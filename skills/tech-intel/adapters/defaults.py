"""Runnable reference adapters.

These make ``tech-intel`` work standalone (file in → file/stdout out) and double as
copy-paste templates for real adapters. Nothing here is project-specific.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from core.schemas import Item, Output, build_item


# ── key resolution (shared convention with the other pikiloom skills) ─────────

def resolve_key(name: str) -> str:
    """env var → ~/.pikiloom/skills.env. Returns '' if absent."""
    val = os.getenv(name, "")
    if val:
        return val
    path = os.path.expanduser("~/.pikiloom/skills.env")
    try:
        for line in open(path):
            s = line.strip()
            if s.startswith(f"{name}=") and not s.startswith("#"):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# ── LLM clients ───────────────────────────────────────────────────────────────

class OpenRouterLLM:
    """OpenAI-compatible chat completion via OpenRouter. One call, no streaming."""

    def __init__(
        self,
        *,
        model: str = "google/gemini-2.5-pro",
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 300,
    ) -> None:
        self.model = model
        self.api_key = api_key or resolve_key("OPENROUTER_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(
        self,
        system: str,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        reasoning: str | None = None,
    ) -> str:
        import requests

        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set — add it to your env or ~/.pikiloom/skills.env."
            )
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if temperature is not None:
            body["temperature"] = temperature
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class CannedLLM:
    """Zero-key test double: returns a fixed response string. Used by `run.py --demo`
    and unit tests so the full pipeline runs without any API key."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system: str, prompt: str, **_: Any) -> str:
        return self._response


# ── source collectors ─────────────────────────────────────────────────────────

class FileSource:
    """Read items from a JSONL file. Path comes from spec['items_path'] or the
    constructor. Each line is an Item dict (source_id + text minimum)."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser() if path else None

    def collect(self, *, run_id: str, spec: dict[str, Any]) -> tuple[list[Item], dict[str, Any]]:
        p = Path(spec["items_path"]).expanduser() if spec.get("items_path") else self.path
        if not p or not p.exists():
            raise RuntimeError(f"FileSource: items file not found ({p}). Pass --items or spec['items_path'].")
        items: list[Item] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            items.append(build_item(str(row.get("source_id") or row.get("url") or ""), str(row.get("text", "")), **{k: v for k, v in row.items() if k not in ("source_id", "text")}))
        return items, {"source": "file", "path": str(p), "count": len(items)}


# ── scorer ──────────────────────────────────────────────────────────────────--

class HeuristicScorer:
    """Engagement-weighted score + blacklist/posted filtering. No LLM. Good enough
    to shortlist; swap for an LLM scorer when ranking quality matters."""

    def shortlist(
        self, items: list[Item], *, store=None, spec: dict[str, Any] | None = None
    ) -> tuple[list[Item], dict[str, Any]]:
        bl = store.blacklist() if store is not None else set()
        kept: list[Item] = []
        drops = {"blacklist": 0, "already_posted": 0}
        for it in items:
            author = str(it.get("author", "") or "").lstrip("@").lower()
            if author and author in bl:
                drops["blacklist"] += 1
                continue
            key = str(it.get("source_id", "") or it.get("url", "")).strip().lower()
            if store is not None and key and store.is_posted(key):
                drops["already_posted"] += 1
                continue
            it["score"] = self._score(it)
            if not it.get("one_liner"):
                it["one_liner"] = self._one_liner(it)
            kept.append(it)
        kept.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)
        return kept, {"kept": len(kept), "drops": drops}

    @staticmethod
    def _score(it: Item) -> float:
        m = it.get("metrics") or {}
        eng = sum(float(m.get(k, 0) or 0) for k in ("likes", "upvotes", "stars", "reactions", "retweets"))
        views = float(m.get("views", 0) or 0)
        return round(eng + views / 100.0, 2)

    @staticmethod
    def _one_liner(it: Item) -> str:
        t = str(it.get("text", "") or "").strip()
        first = re.split(r"[。！？!?\n]+", t, maxsplit=1)[0].strip()
        return (first[:48] + "…") if len(first) > 50 else first


# ── publishers ────────────────────────────────────────────────────────────────

class StdoutPublisher:
    def publish(self, *, report_md: str, outputs: list[Output], run_id: str) -> dict[str, Any]:
        print("\n" + "=" * 60 + f"\nTECH-INTEL REPORT · {run_id}\n" + "=" * 60)
        print(report_md)
        return {"ok": True, "sink": "stdout"}


class FilePublisher:
    """Write the report to a directory (defaults to ./out)."""

    def __init__(self, out_dir: str | os.PathLike[str] = "out") -> None:
        self.out_dir = Path(out_dir).expanduser()

    def publish(self, *, report_md: str, outputs: list[Output], run_id: str) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        dest = self.out_dir / f"{run_id}.md"
        dest.write_text(report_md, encoding="utf-8")
        return {"ok": True, "sink": "file", "path": str(dest)}


# ── knowledge stores ──────────────────────────────────────────────────────────

class NullStore:
    """No memory. Every run is independent; nothing is blacklisted or deduped."""

    def blacklist(self) -> set[str]:
        return set()

    def is_posted(self, key: str) -> bool:
        return False

    def mark_posted(self, run_id: str, outputs: list[Output]) -> int:
        return 0

    def writing_context(self, *, topics: list[str]) -> str:
        return ""

    def record_run(self, run_id: str, refs: dict[str, Any]) -> None:
        return None


class JsonKnowledgeStore:
    """File-backed memory: a posted-keys set + a blacklist + a lessons log, under
    a directory (default ~/.pikiloom/tech-intel-memory). Enough for cross-run dedup
    standalone; replace with your own KB (wiki/db) when embedding."""

    def __init__(self, root: str | os.PathLike[str] = "~/.pikiloom/tech-intel-memory") -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._posted = self.root / "posted.json"
        self._blacklist = self.root / "blacklist.json"
        self._lessons = self.root / "lessons.jsonl"

    def _load(self, path: Path) -> list[str]:
        try:
            return list(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return []

    def blacklist(self) -> set[str]:
        return {str(h).lstrip("@").lower() for h in self._load(self._blacklist)}

    def is_posted(self, key: str) -> bool:
        return key.strip().lower() in set(self._load(self._posted))

    def mark_posted(self, run_id: str, outputs: list[Output]) -> int:
        posted = set(self._load(self._posted))
        added = 0
        for o in outputs:
            key = str(o.get("source_id", "") or o.get("url", "")).strip().lower()
            if key and key not in posted:
                posted.add(key)
                added += 1
        self._posted.write_text(json.dumps(sorted(posted), ensure_ascii=False, indent=2), encoding="utf-8")
        return added

    def writing_context(self, *, topics: list[str]) -> str:
        return ""

    def record_run(self, run_id: str, refs: dict[str, Any]) -> None:
        with open(self._lessons, "a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": run_id, **refs}, ensure_ascii=False) + "\n")
