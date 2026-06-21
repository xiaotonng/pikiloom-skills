"""Guardrail — the drafter's anti-fabrication / anti-fluff pass.

Adapted from an internal signal pipeline's lint stage. The valuable, reusable part is
the set of *structural* checks that keep generated content honest:

  - unsourced entities: numbers / @handles in the draft must appear in the source
  - negation preservation: if the source says "never/not/不要", the draft must too
  - thin content: reject empty / too-short / no-concrete-signal drafts
  - broken line breaks: a single numeric/path fact split across two lines
  - link position (soft): the main link should be the last line
  - long lines (soft): paragraph-cramming several facts onto one line

The lexical pieces (banned marketing phrases, first-person brand-voice markers)
are project-specific and come in via LintPolicy — keep your real voice's banned
list private; the public defaults are a small neutral illustration.
"""

from __future__ import annotations

import re

from .adapters import LintPolicy

_NEGATION_EN = ("never", "no ", "not ", "don't", "doesn't", "isn't", "won't", "can't", "cannot")
_NEGATION_ZH = ("严禁", "不要", "不能", "禁止", "不会", "没有", "不准", "切勿", "绝不")
_LINK_RE = re.compile(r"https?://\S+")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def scrub_text(text: str, replacements: dict[str, str] | None) -> str:
    """Deterministic pre-lint rewrite: swap cheap cringe / 江湖气 / 老登 vocabulary
    for plain wording (e.g. 死磕→攻坚, 撒币→大额补贴). Substring replace, so it
    catches variants (死磕题, 死磕良率). Longer keys are applied first so a
    compound (降维打击) wins over its stem. Rewriting beats dropping — it keeps an
    otherwise-good synthesized piece while removing the tonal noise."""
    out = text or ""
    if not out or not replacements:
        return out
    for src in sorted(replacements, key=len, reverse=True):
        if src:
            out = out.replace(src, str(replacements[src]))
    return out


def extract_numbers(text: str) -> list[str]:
    """Fact-bearing numeric tokens (%, 倍, $, units, versions). Ignores numbers
    inside URLs / @handles (usually status ids)."""
    if not text:
        return []
    cleaned = re.sub(r"https?://\S+", " ", text)
    cleaned = re.sub(r"@\w+", " ", cleaned)
    out: list[str] = []
    number = r"(?:\d+\s*[-–]\s*\d+|\d{1,3}(?:,\d{3})+|\d+\.?\d*)"
    for m in re.finditer(
        rf"(?:{number}\s*(?:%|倍|万|亿|千|百万|M|B|K|GB|MB|TB|TFLOPS|FLOPS|tokens|token|词|个|条|张|台|家|x|ms|s|min|h|hours|days)|"
        r"[¥$€]\s*\d+\.?\d*|\d+\.?\d*\s*[¥$€]|"
        r"(?:v|V)\d+(?:\.\d+){0,3}|"
        r"\d+\s*x\s*\d+|"
        r"\b\d{3,}\b)",
        cleaned,
    ):
        token = m.group(0).strip()
        if token.lower() == "0x":
            continue
        out.append(token)
    return out


def extract_handles(text: str) -> list[str]:
    return re.findall(r"@[\w_]+", text or "")


def _number_forms(n: str) -> list[str]:
    """Equivalent forms so '8 倍' matches '8x' in the source."""
    n = n.strip()
    compact = n.replace(" ", "")
    forms = {n, n.lower(), compact, compact.replace(",", "")}
    rng = re.match(r"(\d+)\s*[-–]\s*(\d+)", n)
    if rng:
        lo, hi = rng.groups()
        forms.update({f"{lo}-{hi}", f"{lo}–{hi}", f"{lo} to {hi}"})
    if "倍" in n:
        d = re.match(r"(\d+\.?\d*)", n)
        if d:
            forms.update({f"{d.group(1)}x", f"{d.group(1)} x"})
    if re.search(r"\dx\b", n.lower()):
        d = re.match(r"(\d+\.?\d*)", n)
        if d:
            forms.update({f"{d.group(1)}倍", f"{d.group(1)} 倍"})
    return list(forms)


def detect_unsourced_entities(draft: str, source_blob: str) -> list[str]:
    """Numbers / @handles present in the draft but absent from the source."""
    if not draft or not source_blob:
        return []
    src_lower = _normalize(source_blob)
    out: list[str] = []
    for n in extract_numbers(draft):
        if any(f.lower() in src_lower or f in source_blob for f in _number_forms(n)):
            continue
        if re.match(r"^\d{1,2}(?:行|条|句|个|分|秒|步)$", n):  # harmless descriptive count
            continue
        out.append(f"number:{n}")
    for h in extract_handles(draft):
        if h.lower() not in src_lower:
            out.append(f"handle:{h}")
    return out


def detect_negation_drop(draft: str, source: str) -> list[str]:
    """If the source negates, the draft must keep a negation."""
    src = _normalize(source)
    has_neg = any(t in src for t in _NEGATION_EN) or any(t in source for t in _NEGATION_ZH)
    if not has_neg:
        return []
    draft_neg = (
        any(t in draft for t in _NEGATION_ZH)
        or "不" in draft
        or any(t in _normalize(draft) for t in _NEGATION_EN)
    )
    return [] if draft_neg else ["missing_negation"]


def detect_thin_content(text: str, *, content_type: str, policy: LintPolicy) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    non_link = [ln for ln in lines if not _LINK_RE.fullmatch(ln)]
    if not non_link:
        return ["no_content"]
    total = sum(len(_LINK_RE.sub("", ln)) for ln in non_link)
    issues: list[str] = []
    if content_type == "post" and len(non_link) < 2:
        issues.append("too_few_lines")
    if content_type == "post" and total < policy.min_post_chars:
        issues.append("too_short")
    if content_type == "quote" and total < policy.min_quote_chars:
        issues.append("too_short")
    has_signal = bool(
        re.search(r"\d", text) or re.search(r"@\w+", text) or re.search(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text)
    )
    if not has_signal:
        issues.append("no_concrete_signal")
    return issues


def detect_broken_line_breaks(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    bad: list[str] = []
    dangling = ("压到了", "达到了", "提升到", "降到了", "降到", "达到", "从", "到", "用了", "加了", "基于")
    for idx, line in enumerate(lines[:-1]):
        if not line or _LINK_RE.match(line):
            continue
        nxt = lines[idx + 1].strip()
        if not nxt or _LINK_RE.match(nxt):
            continue
        if line.endswith(dangling) or (re.search(r"从\s*\d", line) and re.match(r"^\d", nxt)):
            bad.append(line[:25])
    return bad


def detect_long_lines(text: str, *, max_chars: int) -> list[str]:
    bad: list[str] = []
    for line in text.splitlines():
        content = _LINK_RE.sub("", line.strip()).strip()
        if content and len(content) > max_chars:
            bad.append(content[:25] + "...")
    return bad


def detect_link_position(text: str, *, content_type: str) -> list[str]:
    if content_type == "quote":
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    link_lines = [(i, ln) for i, ln in enumerate(lines) if _LINK_RE.search(ln)]
    if not link_lines:
        return []
    issues: list[str] = []
    for idx, ln in link_lines:
        if not re.fullmatch(r"https?://\S+", ln):
            issues.append(f"inline_link:{ln[:30]}")
        elif idx != len(lines) - 1:
            issues.append(f"link_not_last:{ln[:30]}")
    return issues


def lint_item(
    item: dict, source_blob: str, policy: LintPolicy, *, trace_blob: str | None = None
) -> tuple[bool, list[str], list[str]]:
    """Return (passed, hard_errors, soft_warnings). Hard → drop; soft → log only.

    ``source_blob`` is the output's OWN source (used for negation-preservation —
    stance must match the item it's keyed to). ``trace_blob`` is what the
    unsourced-number/handle check traces against; under corpus scope it's the
    whole collected corpus (so a synthesized piece may pull a fact across items),
    defaulting to ``source_blob``. Keeping negation per-item avoids a corpus full
    of unrelated "not"s forcing a negation into every draft."""
    text = str(item.get("text", "") or "").strip()
    if not text:
        return False, ["empty"], []
    content_type = str(item.get("content_type", "post") or "post").lower()
    hard: list[str] = []
    soft: list[str] = []

    for phrase in policy.banned_phrases:
        if phrase and phrase in text:
            hard.append(f"banned:{phrase}")
    for marker in policy.first_person_markers:
        if marker and marker in text:
            hard.append(f"first_person:{marker}")
    if policy.require_source_trace:
        unsourced = detect_unsourced_entities(text, trace_blob if trace_blob is not None else source_blob)
        if unsourced:
            hard.append("unsourced:" + ",".join(unsourced))
        neg = detect_negation_drop(text, source_blob)  # negation: vs the item's OWN source only
        if neg:
            hard.append("negation:" + ",".join(neg))
    thin = detect_thin_content(text, content_type=content_type, policy=policy)
    if thin:
        hard.append("thin:" + ",".join(thin))
    broken = detect_broken_line_breaks(text)
    if broken:
        hard.append("line_break:" + ",".join(broken[:2]))

    long_lines = detect_long_lines(text, max_chars=policy.max_line_chars)
    if long_lines:
        soft.append("long_lines:" + ",".join(long_lines[:2]))
    if policy.enforce_link_last:
        link_issues = detect_link_position(text, content_type=content_type)
        if link_issues:
            soft.append("link_pos:" + ",".join(link_issues[:2]))

    return (len(hard) == 0), hard, soft


def lint_outputs(outputs: list[dict], source_lookup: dict[str, dict], policy: LintPolicy) -> list[dict]:
    """Enrich each output with lint_passed / lint_errors / lint_warnings (in place).

    With ``policy.trace_scope == "corpus"`` the anti-fabrication trace runs against
    the union of ALL collected items (not just the output's own source), so a
    synthesized piece may legitimately pull a number/handle from a related item it
    fused in — a fact present in NO collected item is still dropped."""
    corpus = ""
    if str(getattr(policy, "trace_scope", "item")) == "corpus":
        corpus = " ".join(
            f"{src.get('text', '') or ''} {src.get('context_text', '') or ''}"
            for src in source_lookup.values()
        )
    for o in outputs:
        sid = str(o.get("source_id", "")).strip()
        src = source_lookup.get(sid, {})
        # item's OWN source — negation stance is checked against this
        item_blob = " ".join(
            [str(src.get("text", "") or ""), str(src.get("context_text", "") or ""), str(o.get("source_text", "") or "")]
        )
        # trace blob for unsourced numbers/handles — adds the corpus under corpus scope
        trace_blob = f"{item_blob} {corpus}" if corpus else item_blob
        passed, hard, soft = lint_item(o, item_blob, policy, trace_blob=trace_blob)
        o["lint_passed"] = passed
        o["lint_errors"] = hard
        o["lint_warnings"] = soft
    return outputs
