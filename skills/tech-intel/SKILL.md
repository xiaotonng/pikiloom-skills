---
name: tech-intel
description: Embeddable signal pipeline — collect items from any source → score/shortlist → draft on-brand content with ONE LLM call → lint guardrail (anti-fabrication, source-traceable) → publish. Ships runnable file-in/file-out reference adapters and plugs into your own source / voice / sink via small adapter shims. Use when the user wants to monitor sources and turn them into reviewed, source-traceable drafts (social posts, digests, briefings) — never auto-posting, only drafts.
---

# tech-intel — an embeddable signal pipeline

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
SKILL=~/.claude/skills/tech-intel
python3 "$SKILL/run.py" --demo          # file in → linted report out, NO api key
```

Real LLM run (needs `OPENROUTER_API_KEY` in env or `~/.pikiloom/skills.env`):

```bash
pip install -r "$SKILL/requirements.txt"   # pyyaml + requests (core itself is stdlib-only)
python3 "$SKILL/run.py" --items my_items.jsonl    # uses config.example.yaml + the default prompts
```

**Defaults out of the box** (`config.example.yaml` + `prompts/*.example.md`): a top Chinese AI-news
blogger voice (宝玉 / 歸藏 style). It **faithfully 仿写 (localized rewrite, not literal translation)**
each already-high-engagement English tweet/thread into natural Chinese — keeps the source's structure,
hook, stance, numbers, and English terms; **does not decompose, editorialize, or add takes**. It
selects **concrete technical news only** (new models / tools / papers / benchmarks / official releases)
and **skips opinion / ranking / "landscape" hot-takes**, hardware-vendor strategy, finance, people-moves,
geopolitics, non-AI crypto. **Obvious duplicates are aggregated** — many tweets on the same thing
become one comprehensive item (e.g. a hot model's reviews + cost + deploy + caveats fused, with
sub-bullets). **Length follows the source** — one-liners stay short, rich threads/lists expand into a
full multi-paragraph or bulleted item (a 10-project list becomes all 10; the full thread is read), so
a digest has a long/short mix. The `TwitterListSource` enriches **every** shortlisted item with its
**full tweet + entire thread** (`max_threads` = `shortlist_size`, scrolling the detail page) so
nothing is summarized from a truncated head. Default model is **`google/gemini-3.1-pro-preview`**
(strong at the group→merge→list-all task; `deepseek/deepseek-chat` reads a touch more natural but
won't aggregate — swap if preferred). `require_source_trace` is **off** so faithful number localization (10B→100亿) isn't flagged, and
`dedup: false` (a once-a-day feed shouldn't drop yesterday's still-trending tweets) — banned-phrase +
tone scrub still run. Headed report under `今日 AI 资讯`. Override via `--config`/`--persona`/`--generate`/`--model`.

An item is one JSON line: `{"source_id","text","author","url","metrics":{...},"reference_urls":[...]}`
(see `examples/items.sample.jsonl`). Only `source_id` + `text` are required.

Collect **fresh** from a Twitter/X List + search instead of a file: set `source.type: twitter-list`
in the config (profile dir + lists + search_queries + scroll rounds — see `config.example.yaml`),
`pip install playwright`, point `profile` at a logged-in Chrome profile dir, then run without `--items`.
Add `--no-headless` to watch the browser. With `enrich_threads: true` it also pulls each top item's
full **thread** — depth a single tweet doesn't have, so the drafter can synthesize rather than parrot.
Pair that with `lint.trace_scope: corpus` (trace facts against ALL collected items, not just one) and a
synthesis persona to fuse related items into longer, opinionated analysis instead of one-tweet summaries.

Publish the report as a **Feishu doc + a card** (instead of a local file) with `--feishu`
(needs `FEISHU_APP_ID/SECRET/RECEIVE_ID`; the app needs `docx:document` + `im:message:send_as_bot`):

```bash
python3 "$SKILL/run.py" --items my_items.jsonl --config "$SKILL/config.example.yaml" --feishu
```

## The five steps (and the adapter behind each)

| Step | Adapter (Protocol) | Reference default | What it does |
|------|--------------------|-------------------|--------------|
| collect | `SourceCollector` | `FileSource` (jsonl) / `TwitterListSource` | produce candidate items; `TwitterListSource` collects fresh from X List(s)+search via Playwright |
| score | `Scorer` | `HeuristicScorer` | rank/filter + shortlist (applies blacklist + posted-dedup via the store) |
| draft | `LLMClient` | `OpenRouterLLM` / `CannedLLM` | ONE LLM call → JSON → `Output`s (with a JSON-retry) |
| lint | *(built in)* | `core.lint` + `LintPolicy` | drop fabrications / fluff; enforce a clean-output floor |
| publish | `Publisher` | `StdoutPublisher` / `FilePublisher` / `FeishuPublisher` | deliver the report (drafts only); `FeishuPublisher` creates a doc + DMs a card |
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
project-specific and live in `LintPolicy` / your config. The shipped `config.example.yaml`
carries a working Chinese attitude/marketing banned list — swap in your own voice's list.

Tone is handled separately from facts: `lint.scrub_replacements` is a deterministic
`{bad: good}` rewrite run *before* the lint (e.g. `死磕→攻坚`, `撒币→大额补贴`) — it
fixes cheap cringe / 江湖气 wording in place rather than dropping an otherwise-good
synthesized piece. Use scrub for tone, `banned_phrases` to drop the unsalvageable.

## Configuration

These are the **shipped defaults** (run.py reads them unless you pass your own). Edit
in place or point `--config` / `--persona` / `--generate` at your own copies.

- `config.example.yaml` — the default config: `content_types: [posts, quotes, replies]`,
  per-type counts / target / floor, model, `report_style: headed` + `section_titles`,
  and the full lint policy (`banned_phrases` drop, `scrub_replacements` tone rewrite,
  `trace_scope: corpus`). The `source.type: twitter-list` + `feishu` blocks ship commented.
- `prompts/persona.example.md` — the **default analyst voice**: internalized first-person,
  no in-text attribution (source link only), synthesize related items, Twitter blank-line
  blocks, banned cringe/老登 register. Replace with your own voice (keep a private brand
  voice out of a public repo).
- `prompts/generate.example.md` — the per-run task template (`{{ITEMS_BLOCK}}`,
  `{{TARGET_TOTAL}}`, `{{MIN_POSTS}}`, `{{FOCUS_DIRECTIVE}}` …). `content_types` must match
  the JSON keys the persona emits (the default persona emits the plural `posts/quotes/replies`).

## Environment

| Var | Used by | Notes |
|-----|---------|-------|
| `OPENROUTER_API_KEY` | `OpenRouterLLM` | env or `~/.pikiloom/skills.env`; not needed for `--demo` |
| `TECH_INTEL_DATA_DIR` | run artifacts | defaults to `./data/tech-intel` |
| `FEISHU_APP_ID/SECRET/RECEIVE_ID` | `FeishuPublisher` (`--feishu`) | resolved **skills.env-first** (a pikiloom host injects its own bot's `FEISHU_*` into the env — your content app in `skills.env` must win); override with `TECH_INTEL_FEISHU_*` |

## Embedding it in a real project

The standalone runner is the worked example. To embed (your own Twitter/RSS source,
your brand voice, a Feishu/Slack sink, a wiki-backed memory), implement the adapters
and call `TechIntelPipeline(...).run(...)`. See **EMBEDDING.md** for copy-paste shims.
