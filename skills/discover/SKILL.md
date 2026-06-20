---
name: discover
description: Embeddable signal pipeline — collect items from any source → score/shortlist → draft on-brand content with ONE LLM call → lint guardrail (anti-fabrication, source-traceable) → publish. Ships runnable file-in/file-out reference adapters and plugs into your own source / voice / sink via small adapter shims. Use when the user wants to monitor sources and turn them into reviewed, source-traceable drafts (social posts, digests, briefings) — never auto-posting, only drafts.
---

# discover — an embeddable signal pipeline

`collect → score → draft (one LLM call) → lint → publish`, with a `KnowledgeStore`
for cross-run memory. The pipeline is **source/voice/sink-agnostic**: every
project-specific piece is injected through an adapter Protocol, so you reuse the
orchestration + guardrail and plug in *what* to watch, *how* to write, and *where*
to send. It drafts only — it never publishes to a social account on its own.

## When to use
"汇总一下 X 上 XX 方向 / 收集这几个方向的动态 / monitor these sources and draft posts /
turn this feed into a briefing." Anything shaped like *watch sources → draft
reviewed, traceable content → push a draft somewhere*.

## Quickstart (zero-key demo)

```bash
SKILL=~/.claude/skills/discover
python3 "$SKILL/run.py" --demo          # file in → linted report out, NO api key
```

Real LLM run (needs `OPENROUTER_API_KEY` in env or `~/.pikiloom/skills.env`):

```bash
pip install -r "$SKILL/requirements.txt"   # pyyaml + requests (core itself is stdlib-only)
python3 "$SKILL/run.py" --items my_items.jsonl --config "$SKILL/config.example.yaml"
```

An item is one JSON line: `{"source_id","text","author","url","metrics":{...},"reference_urls":[...]}`
(see `examples/items.sample.jsonl`). Only `source_id` + `text` are required.

## The five steps (and the adapter behind each)

| Step | Adapter (Protocol) | Reference default | What it does |
|------|--------------------|-------------------|--------------|
| collect | `SourceCollector` | `FileSource` (jsonl) | produce candidate items for the run |
| score | `Scorer` | `HeuristicScorer` | rank/filter + shortlist (applies blacklist + posted-dedup via the store) |
| draft | `LLMClient` | `OpenRouterLLM` / `CannedLLM` | ONE LLM call → JSON → `Output`s (with a JSON-retry) |
| lint | *(built in)* | `core.lint` + `LintPolicy` | drop fabrications / fluff; enforce a clean-output floor |
| publish | `Publisher` | `StdoutPublisher` / `FilePublisher` | deliver the report (drafts only) |
| memory | `KnowledgeStore` | `NullStore` / `JsonKnowledgeStore` | blacklist, cross-run dedup, style anchors, sediment |

## The lint guardrail (why this is the valuable part)

Generated content is only as trustworthy as its guardrail. The **structural**
checks are always on and catch the failure modes that make LLM drafts unsafe to
publish:

- **unsourced entities** — every number / `@handle` in the draft must appear in the
  source (verified: a draft claiming `50ms` or `900%` not in the source is dropped).
- **dropped negation** — if the source says "not / never / 不要", the draft must keep it.
- **thin content** — empty / too-short / no-concrete-signal drafts are dropped.
- **broken line breaks**, **link position**, **long lines** — formatting hygiene.

The *lexical* lists (banned marketing phrases, first-person brand-voice markers) are
project-specific and live in `LintPolicy` / your config — **keep your real voice's
banned list private**; the shipped defaults are a small neutral illustration.

## Configuration

- `config.example.yaml` — counts per content type, target/floor, model, lint policy.
- `prompts/persona.example.md` — the voice + output format (a NEUTRAL example).
- `prompts/generate.example.md` — the per-run generation template (`{{ITEMS_BLOCK}}`,
  `{{TARGET_TOTAL}}`, `{{MIN_POST}}`, `{{FOCUS_DIRECTIVE}}` …).

## Environment

| Var | Used by | Notes |
|-----|---------|-------|
| `OPENROUTER_API_KEY` | `OpenRouterLLM` | env or `~/.pikiloom/skills.env`; not needed for `--demo` |
| `DISCOVER_DATA_DIR` | run artifacts | defaults to `./data/discover` |
| publisher creds (e.g. `FEISHU_APP_ID/SECRET/RECEIVE_ID`) | your `Publisher` | only if you wire that sink |

## Embedding it in a real project

The standalone runner is the worked example. To embed (your own Twitter/RSS source,
your brand voice, a Feishu/Slack sink, a wiki-backed memory), implement the adapters
and call `DiscoverPipeline(...).run(...)`. See **EMBEDDING.md** for copy-paste shims.
