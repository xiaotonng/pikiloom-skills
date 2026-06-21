"""Twitter/X List + search `SourceCollector` — fresh collection via Playwright.

Drives a DEDICATED Chrome on an isolated *persistent profile* (a logged-in
``--user-data-dir``), headless by default, never touching your main browser. It
navigates one or more X Lists (and optional search queries), scrolls the
virtualized timeline, and extracts visible tweets with a read-only DOM script.

Everything is config: the profile dir (where the login/permissions live), the
lists, the search queries, scroll rounds, a min-engagement floor, and a cap. This
is the worked example of a real `SourceCollector`; map its output straight into
the pipeline.

Requires ``playwright`` (imported lazily) and a Chrome channel:
    pip install playwright    # the persistent profile must already be logged in
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Any

from core.schemas import Item, build_item

_LIST_ID_RE = re.compile(r"/lists/(\d+)")
_STATUS_RE = re.compile(r"https?://(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)", re.I)


def to_int(raw: Any) -> int:
    """Lenient count parse: 1.2K / 3M / 1.5万 / plain digits → int."""
    if raw is None or isinstance(raw, bool):
        return int(raw or 0)
    if isinstance(raw, (int, float)):
        return int(raw)
    if not isinstance(raw, str):
        return 0
    text = raw.strip().replace(",", "").replace(" ", "").upper()
    if not text:
        return 0
    mult = 1
    if text.endswith("K"):
        mult, text = 1_000, text[:-1]
    elif text.endswith("M"):
        mult, text = 1_000_000, text[:-1]
    elif text.endswith("B"):
        mult, text = 1_000_000_000, text[:-1]
    elif text.endswith("W") or text.endswith("万"):
        mult, text = 10_000, text[:-1]
    if not re.match(r"^\d+(\.\d+)?$", text):
        nums = re.findall(r"\d+(?:\.\d+)?", text)
        if not nums:
            return 0
        text = nums[0]
    try:
        return int(float(text) * mult)
    except ValueError:
        return 0


def normalize_list_url(value: str) -> str:
    """A bare id / list URL → canonical ``https://x.com/i/lists/<id>``."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        return f"https://x.com/i/lists/{raw}"
    m = _LIST_ID_RE.search(raw)
    if m:
        return f"https://x.com/i/lists/{m.group(1)}"
    return raw if raw.startswith("http") else ""


def canonical_status_url(url: str) -> str:
    m = _STATUS_RE.search(url or "")
    return f"https://x.com/{m.group(1)}/status/{m.group(2)}" if m else (url or "")


# Read-only DOM extractor — lifted verbatim from the proven cyber-chou collector so
# the extracted fields (handle/text/metrics/links) match. Returns JSON.stringify(list).
_EXTRACT_JS = r"""
(() => {
  const toNum = (v) => { if (!v) return "0"; const t = String(v).trim(); return t || "0"; };
  const canonicalStatusUrl = (raw) => {
    const href = String(raw || "").trim(); if (!href) return "";
    const abs = href.startsWith("http") ? href : (window.location.origin + href);
    const m = abs.match(/https?:\/\/(?:x|twitter)\.com\/([A-Za-z0-9_]+)\/status\/(\d+)/i);
    return m ? `https://x.com/${m[1]}/status/${m[2]}` : "";
  };
  const looksLikeUrl = (v) => /^(?:https?:\/\/|www\.)/i.test(String(v || "").trim());
  const looksTruncatedUrl = (v) => /…/.test(String(v || "").trim());
  const toAbsoluteUrl = (raw) => {
    const href = String(raw || "").trim(); if (!href) return "";
    if (href.startsWith("http")) return href;
    if (href.startsWith("/")) return window.location.origin + href;
    if (looksLikeUrl(href)) return href.startsWith("www.") ? ("https://" + href) : href;
    return "";
  };
  const dedupKeepOrder = (arr) => {
    const seen = new Set(); const out = [];
    for (const item of arr) { const v = String(item || "").trim(); if (!v || seen.has(v)) continue; seen.add(v); out.push(v); }
    return out;
  };
  const list = [];
  const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
  for (const a of articles) {
    const textEl = a.querySelector('[data-testid="tweetText"]');
    const text = textEl ? textEl.innerText.trim() : "";
    if (!text) continue;
    const timeEl = a.querySelector('time[datetime]');
    let statusLink = timeEl ? timeEl.closest('a[href*="/status/"]') : null;
    if (!statusLink) {
      const statusLinks = Array.from(a.querySelectorAll('a[href*="/status/"]'));
      statusLink = statusLinks.find(Boolean) || null;
    }
    const href = statusLink ? statusLink.getAttribute("href") : "";
    const url = href ? (href.startsWith("http") ? href : (window.location.origin + href)) : "";
    const canonicalUrl = canonicalStatusUrl(url);
    let handle = "";
    const handleHref = canonicalUrl || url || href;
    if (handleHref) { const m = handleHref.match(/\/([A-Za-z0-9_]+)\/status\/\d+/); if (m) handle = "@" + m[1]; }
    const likeEl = a.querySelector('[data-testid="like"] span');
    const retweetEl = a.querySelector('[data-testid="retweet"] span, [data-testid="unretweet"] span');
    const replyEl = a.querySelector('[data-testid="reply"] span');
    const viewEl = a.querySelector('a[href*="/analytics"] span');
    const created_at = timeEl ? timeEl.getAttribute('datetime') : "";
    const quotedUrls = []; const externalLinks = [];
    for (const link of Array.from(a.querySelectorAll('a[href]'))) {
      const hrefRaw = link.getAttribute("href") || "";
      const statusUrl = canonicalStatusUrl(hrefRaw);
      if (statusUrl) { if (statusUrl !== canonicalUrl) quotedUrls.push(statusUrl); continue; }
      const title = (link.getAttribute("title") || "").trim();
      const aria = (link.getAttribute("aria-label") || "").trim();
      const textHint = (link.innerText || "").trim();
      const hrefAbs = toAbsoluteUrl(hrefRaw);
      let picked = "";
      for (const cand of [title, textHint, aria]) {
        const abs = toAbsoluteUrl(cand);
        if (!abs || looksTruncatedUrl(abs) || /^https?:\/\/(?:x|twitter)\.com\//i.test(abs)) continue;
        picked = abs; break;
      }
      if (!picked && hrefAbs && !/^https?:\/\/(?:x|twitter)\.com\//i.test(hrefAbs)) picked = hrefAbs;
      if (picked) externalLinks.push(picked);
    }
    list.push({
      handle, text,
      likes: toNum(likeEl ? likeEl.innerText : "0"),
      retweets: toNum(retweetEl ? retweetEl.innerText : "0"),
      replies: toNum(replyEl ? replyEl.innerText : "0"),
      views: toNum(viewEl ? viewEl.innerText : "0"),
      created_at, url,
      external_links: dedupKeepOrder(externalLinks),
      quoted_urls: dedupKeepOrder(quotedUrls),
    });
  }
  return JSON.stringify(list);
})()
"""


class TwitterListSource:
    """Collect fresh tweets from X List(s) + optional search queries via Playwright."""

    def __init__(
        self,
        *,
        profile: str | None = None,
        headless: bool = True,
        lists: list[str] | None = None,
        list_rounds: int = 36,
        search_queries: list[str] | None = None,
        search_count_per_query: int = 15,
        search_sort: str = "latest",
        min_score: float = 0.0,
        max_items: int = 180,
        scroll_delay: float = 0.45,
        nav_settle: float = 2.0,
        enrich_threads: bool = True,
        max_threads: int = 12,
        thread_scroll_rounds: int = 8,
    ) -> None:
        self.profile = os.path.abspath(os.path.expanduser(profile)) if profile else None
        self.headless = headless
        self.lists = [u for u in (normalize_list_url(v) for v in (lists or [])) if u]
        self.list_rounds = int(list_rounds or 0)
        self.search_queries = list(search_queries or [])
        self.search_count = int(search_count_per_query or 15)
        self.search_sort = search_sort
        self.min_score = float(min_score or 0.0)
        self.max_items = int(max_items or 0)
        self.scroll_delay = float(scroll_delay or 0.45)
        self.nav_settle = float(nav_settle or 2.0)
        self.enrich_threads = bool(enrich_threads)
        self.max_threads = int(max_threads or 0)
        self.thread_scroll_rounds = int(thread_scroll_rounds or 8)

    # ── browser primitives ──
    def _extract(self, page) -> list[dict]:
        try:
            raw = page.evaluate(_EXTRACT_JS)
        except Exception:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return []
        return data if isinstance(data, list) else []

    def _scroll(self, page) -> None:
        try:
            page.mouse.wheel(0, 2600)
        except Exception:
            pass
        time.sleep(max(0.0, self.scroll_delay + random.uniform(-0.2, 0.2)))

    def _scan(self, page, *, rounds: int, want: int | None = None) -> list[dict]:
        """Scroll `rounds` times, extracting + deduping by text[:80]."""
        rows: list[dict] = []
        seen: set[str] = set()
        empty = 0
        for idx in range(1, max(1, rounds) + 1):
            chunk = self._extract(page)
            for d in chunk:
                key = (d.get("text", "") or "")[:80]
                if key and key not in seen:
                    seen.add(key)
                    rows.append(d)
            empty = empty + 1 if not chunk else 0
            if empty >= (3 if rows else 10):
                break
            if want and len(rows) >= want:
                break
            if idx < rounds:
                self._scroll(page)
        return rows

    def _open(self, page, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        time.sleep(self.nav_settle)
        try:
            page.wait_for_selector('article[data-testid="tweet"]', timeout=12000)
        except Exception:
            pass

    def _full_detail(self, page, url: str, handle: str) -> str:
        """Open a tweet's detail page, SCROLL it, and collect the SAME author's
        complete content — the focal tweet's full (un-truncated) text plus every
        tweet in their thread. The List/search card only shows a truncated head;
        a long tweet ("Show more") or a multi-tweet thread must be read off the
        detail page, scrolling until no new same-author tweets load. Returns the
        joined full text even for a single (long) tweet — that's the whole point
        (the card text was truncated)."""
        h = (handle or "").lstrip("@").lower().replace("'", "\\'")
        if not url or not h:
            return ""
        self._open(page, url)
        time.sleep(0.8)
        # click any "Show more" to expand truncated tweets, then read same-author texts
        js = (
            "(() => { const A='" + h + "'; const out=[];"
            "for (const b of Array.from(document.querySelectorAll('[data-testid=\"tweet-text-show-more-link\"]'))) { try{b.click();}catch(e){} }"
            "for (const a of Array.from(document.querySelectorAll('article[data-testid=\"tweet\"]'))) {"
            "  const l=a.querySelector('a[href*=\"/status/\"]'); if(!l) continue;"
            "  const m=(l.getAttribute('href')||'').match(/\\/([A-Za-z0-9_]+)\\/status\\/\\d+/); if(!m) continue;"
            "  if(m[1].toLowerCase()!==A) continue;"
            "  const t=a.querySelector('[data-testid=\"tweetText\"]');"
            "  if(t && t.innerText.trim()) out.push(t.innerText.trim());"
            "} return JSON.stringify(out); })()"
        )
        seen: set[str] = set()
        parts: list[str] = []
        empty = 0
        for _ in range(max(1, self.thread_scroll_rounds)):
            try:
                raw = page.evaluate(js)
                chunk = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                chunk = []
            new = 0
            for p in chunk or []:
                if p and p not in seen:
                    seen.add(p)
                    parts.append(p)
                    new += 1
            empty = empty + 1 if new == 0 else 0
            if empty >= 2 and parts:  # thread fully loaded
                break
            self._scroll(page)
        return "\n---\n".join(parts)

    def _enrich(self, page, items: list[Item]) -> int:
        """Pull each top item's COMPLETE content (full tweet + thread) into
        context_text, so the drafter has everything — not just the card's head."""
        enriched = 0
        for it in items[: self.max_threads]:
            full = self._full_detail(page, str(it.get("url", "")), str(it.get("author", "")))
            if full and len(full) > len(str(it.get("text", "") or "")):
                prov = str(it.get("context_text", "") or "")
                it["context_text"] = (full + "\n\n" + prov).strip()
                enriched += 1
        return enriched

    # ── SourceCollector protocol ──
    def collect(self, *, run_id: str, spec: dict[str, Any]) -> tuple[list[Item], dict[str, Any]]:
        # per-run overrides
        lists = [u for u in (normalize_list_url(v) for v in spec.get("lists", [])) if u] or self.lists
        queries = list(spec.get("search_queries", []) or self.search_queries)
        if not lists and not queries:
            raise RuntimeError("TwitterListSource: no lists or search_queries configured.")

        from playwright.sync_api import sync_playwright  # lazy — heavy optional dep
        import urllib.parse

        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=self.profile or os.path.abspath(os.path.expanduser("~/.pikiloom/browser/sim-mock-profile")),
            channel="chrome",
            headless=self.headless,
            viewport={"width": 1400, "height": 1000},
            ignore_default_args=["--disable-blink-features=AutomationControlled"],
            args=["--no-first-run", "--no-default-browser-check"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        raw_rows: list[dict] = []
        items: list[Item] = []
        meta: dict[str, Any] = {"source": "twitter-list", "lists": lists, "queries": len(queries), "per_source": []}
        try:
            for url in lists:
                self._open(page, url)
                rows = self._scan(page, rounds=self.list_rounds)
                meta["per_source"].append({"list": url, "rows": len(rows)})
                raw_rows.extend(rows)
            f = "live" if self.search_sort == "latest" else "top"
            for q in queries:
                self._open(page, f"https://x.com/search?q={urllib.parse.quote(q)}&src=typed_query&f={f}")
                rounds = max(3, (self.search_count // 5) + 3)
                rows = self._scan(page, rounds=rounds, want=self.search_count)[: self.search_count]
                meta["per_source"].append({"query": q, "rows": len(rows)})
                raw_rows.extend(rows)
            items = self._to_items(raw_rows)
            # depth pass: pull threads for the top items while the browser is still open
            meta["threads_enriched"] = self._enrich(page, items) if (self.enrich_threads and self.max_threads) else 0
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

        meta.update({"raw": len(raw_rows), "count": len(items)})
        return items, meta

    def _score(self, likes: int, retweets: int, replies: int, views: int) -> float:
        # cyber-chou intel_sources.min_score formula
        return likes * 2 + retweets * 3 + replies + views / 100.0

    def _to_items(self, raw_rows: list[dict]) -> list[Item]:
        items: list[Item] = []
        seen: set[str] = set()
        for d in raw_rows:
            text = (d.get("text", "") or "").strip()
            canon = canonical_status_url(d.get("url", "") or "")
            if not text or not canon or canon in seen:
                continue
            likes, rts = to_int(d.get("likes")), to_int(d.get("retweets"))
            replies, views = to_int(d.get("replies")), to_int(d.get("views"))
            score = self._score(likes, rts, replies, views)
            if score < self.min_score:
                continue
            seen.add(canon)
            handle = (d.get("handle", "") or "").lstrip("@")
            refs = [u for u in ((d.get("external_links") or []) + (d.get("quoted_urls") or [])) if u != canon]
            # provenance line: keeps @handle / url traceable for the lint guardrail
            prov = f"[source] @{handle} {canon}" + (f" refs: {' '.join(refs[:3])}" if refs else "")
            items.append(build_item(
                canon, text,
                source="twitter-list",
                author=handle,
                url=canon,
                created_at=d.get("created_at", "") or "",
                context_text=prov,
                metrics={"likes": likes, "retweets": rts, "replies": replies, "views": views},
                reference_urls=refs[:5],
                score=round(score, 2),
            ))
        items.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)
        return items[: self.max_items] if self.max_items else items
