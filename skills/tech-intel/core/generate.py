"""Draft step — render the prompt, make ONE LLM call (with a JSON-retry), parse
the structured result into Output rows, and build the report.

Adapted from an internal signal pipeline's merge/report stage. The host-specific
style normalizers (number verification, de-personalization, etc.) are NOT here —
they belong in a project's drafter extension. The generic, reusable parts are the
prompt templating, the tolerant JSON parse + one retry, and the report builder.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .schemas import Item, Output, build_output

STRICT_JSON_ADDENDUM = (
    "\n\n## OUTPUT FORMAT (reiterated — must obey)\n"
    "1. Output a raw JSON object ONLY.\n"
    "2. No ``` or ```json code fences.\n"
    "3. No prose prefix ('Here is the JSON:') or suffix.\n"
    "4. The first character MUST be '{' and the last MUST be '}'."
)


def _fill(text: str, mapping: dict[str, str]) -> str:
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text


def render_items_block(items: list[Item]) -> str:
    parts: list[str] = []
    for row in items:
        metrics = row.get("metrics") or {}
        entry = (
            f"- source_id: {row.get('source_id', '')}\n"
            f"  author: {row.get('author', '')}\n"
            f"  url: {row.get('url', '')}\n"
            f"  created_at: {row.get('created_at', '')}\n"
            f"  summary: {row.get('one_liner', '')}\n"
            f"  score: {row.get('score', 0)}\n"
            f"  metrics: {json.dumps(metrics, ensure_ascii=False)}"
        )
        refs = row.get("reference_urls") or []
        if refs:
            entry += f"\n  reference_urls: {json.dumps(refs, ensure_ascii=False)}"
        text = str(row.get("text", "") or "").strip()
        if text:
            entry += f"\n  text: {text[:1200]}"
        ctx = str(row.get("context_text", "") or "").strip()
        if ctx and ctx != text:
            entry += f"\n  context_text: {ctx[:1200]}"
        parts.append(entry)
    return "\n\n".join(parts)


def render_prompt(template: str, items: list[Item], persona, config) -> str:
    mins = dict(config.min_per_type or {})
    target = config.total_target()
    mapping = {
        "{{ITEMS_BLOCK}}": render_items_block(items),
        "{{TOP_N}}": str(len(items)),
        "{{TARGET_TOTAL}}": str(target),
        "{{HARD_MIN_TOTAL}}": str(config.hard_min_total),
    }
    for ct in persona.content_types:
        mapping["{{MIN_" + ct.upper() + "}}"] = str(int(mins.get(ct, 0) or 0))
    focus = (persona.focus_topics or "").strip()
    mapping["{{FOCUS_DIRECTIVE}}"] = (
        f"## Focus for this run\nPrioritise items related to: **{focus}**. "
        f"Prefer fewer items over padding with unrelated ones.\n" if focus else ""
    )
    return _fill(template, mapping)


def parse_json_object(text: str) -> dict | None:
    """Tolerant parse: strip code fences, then take the outermost {...}."""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _to_outputs(result: dict, items: list[Item], persona, run_id: str) -> list[Output]:
    lookup = {str(i.get("source_id", "")).strip(): i for i in items}
    now = datetime.now().isoformat(timespec="seconds")
    outs: list[Output] = []
    seq = 0
    for ct in persona.content_types:
        rows = result.get(ct, [])
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict):
                continue
            text = str(r.get("text", "") or "").strip()
            if not text:
                continue
            sid = str(r.get("source_id", "") or "").strip()
            src = lookup.get(sid, {})
            seq += 1
            outs.append(
                build_output(
                    item_id=f"{run_id}_{ct}_{seq}",
                    source_id=sid,
                    content_type=ct,
                    text=text,
                    url=str(src.get("url", "") or ""),
                    author=str(src.get("author", "") or ""),
                    source_text=" ".join(
                        [str(src.get("text", "") or ""), str(src.get("context_text", "") or "")]
                    ).strip(),
                    run_id=run_id,
                    generated_at=now,
                )
            )
    return outs


def draft(*, llm, persona, items: list[Item], config, store=None, run_id: str) -> list[Output]:
    system = persona.system
    prompt = render_prompt(persona.generate_template, items, persona, config)
    if store is not None:
        topics = _topics_from_items(items)
        ctx = store.writing_context(topics=topics) or ""
        if ctx:
            prompt = ctx.strip() + "\n\n---\n\n" + prompt

    content = llm.complete(
        system, prompt, model=config.model, temperature=config.temperature, reasoning=config.reasoning
    )
    result = parse_json_object(content)
    if result is None:
        content = llm.complete(
            system + STRICT_JSON_ADDENDUM,
            prompt,
            model=config.model,
            temperature=config.temperature,
            reasoning=config.reasoning,
        )
        result = parse_json_object(content)
        if result is None:
            raise RuntimeError("Draft LLM output did not parse as a JSON object after one retry.")
    return _to_outputs(result, items, persona, run_id)


def _topics_from_items(items: list[Item]) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for row in items:
        cat = str(row.get("category", "") or "").strip()
        if cat and cat not in seen:
            seen.add(cat)
            topics.append(cat)
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{2,}\b", str(row.get("text", "") or "")):
            t = token.lower()
            if t in {"the", "and", "for", "with", "that", "this", "from", "have", "are"} or t in seen:
                continue
            seen.add(t)
            topics.append(t)
    return topics[:30]


def build_report(outputs: list[Output], content_types: tuple[str, ...]) -> str:
    lines = ["# Tech-Intel Report", ""]
    for ct in content_types:
        bucket = [o for o in outputs if str(o.get("content_type", "")) == ct]
        if not bucket:
            continue
        lines.append(f"## {ct} ({len(bucket)})")
        lines.append("")
        for o in bucket:
            lines.append(str(o.get("text", "") or "").strip())
            url = str(o.get("url", "") or "").strip()
            if url and url not in str(o.get("text", "")):
                lines.append(url)
            lines.append("")
    return "\n".join(lines).strip() + "\n"
