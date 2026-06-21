# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Renamed the embeddable-pipeline skill `discover` → **`tech-intel`** throughout:
  the skill `name`, the directory, `DiscoverPipeline` → `TechIntelPipeline`,
  `DISCOVER_DATA_DIR` → `TECH_INTEL_DATA_DIR`, the report title, and the default
  memory directory. The install command is now
  `npx skills add xiaotonng/pikiloom-skills --skill tech-intel …`.

### Added
- **image-gen: optional OpenRouter provider with a gpt-image-2-first fallback chain (one key can
  cover every skill).** New `--provider {auto,openai,openrouter}`. With an `OPENROUTER_API_KEY` (or an
  `sk-or-…` `--api-key`) the skill routes image generation through OpenRouter's `/chat/completions`
  image output: `--ref` images are inlined as base64 data URLs, `--size` → `image_config.aspect_ratio`,
  `--n` loops one call per image. The **default model walks a quality-ordered chain, best first**:
  `gpt-image-2` (`openai/gpt-5.4-image-2`, the **same GPT Image 2 backend** — top for text/logos) →
  `google/gemini-3-pro-image` → `google/gemini-2.5-flash-image`; on any failure (e.g. the data-policy
  404) it falls back to the next and prints a `NOTE`. Override the chain with
  `IMAGE_GEN_OPENROUTER_FALLBACK="slug,…"`, or pin a single model (no fallback) with an explicit
  `--model <slug>`. `auto` still prefers a **direct** `OPENAI_API_KEY` (native Images API — best text
  fidelity, plus `--quality` / transparent / native `--n`) when present, so existing behaviour is
  unchanged. NOTE: OpenAI image models return **404** on OpenRouter unless allowed in your data policy
  (`openrouter.ai/settings/privacy`); the non-OpenAI backups need no opt-in. Adds 15 offline tests
  (provider/key selection, model-alias mapping, size→aspect, fallback-chain ordering).
- **tech-intel: Chinese AI-news 仿写 digest is the default.** The shipped `config.example.yaml` +
  `prompts/*.example.md` produce a top Chinese AI-news blogger voice (宝玉 / 歸藏 style): each
  already-high-engagement English tweet/thread is **faithfully 仿写'd (localized rewrite, not literal
  translation)** into natural Chinese — source structure / hook / stance / numbers / English terms kept,
  **no decomposition, no editorializing, no added takes**. Selects **concrete technical news only**
  (models / tools / papers / benchmarks / releases) and **skips opinion / ranking / "landscape"
  hot-takes**, hardware-vendor strategy, finance, people-moves, geopolitics, non-AI crypto. Default
  model **`deepseek/deepseek-chat`** (Chinese-native; A/B-beat Gemini, whose unit-localization tripped
  the number-trace). `require_source_trace: false` so faithful number localization (10B→100亿) isn't
  flagged — banned-phrase + scrub still run. Headed report under `今日 AI 资讯`, temperature 0.4.
  **Length follows the source** (one-liners short; rich threads/lists expand to full multi-paragraph /
  bulleted items — a 10-project list becomes all 10), long/short mix. **Obvious duplicates are aggregated**
  into one comprehensive item (a hot model's reviews + cost + deploy + caveats fused with sub-bullets).
  `dedup: false` by default (once-a-day feed). **Full-content capture**: `TwitterListSource` now scrolls
  each tweet's detail page and pulls the complete tweet + entire thread (incl. clicking "show more"),
  and enriches **every** shortlisted item (`max_threads` = `shortlist_size`) so nothing is summarized
  from a truncated head; `render_items_block` context cap raised to 8000. Default model
  `google/gemini-3.1-pro-preview` (best at group→merge→list-all; deepseek/deepseek-chat is a natural-but-
  non-aggregating alternative). `run.py --demo` + file source work zero-setup. Overridable via flags.
- **tech-intel: TwitterListSource (fresh collection)** — a config-driven `SourceCollector`
  that collects fresh from X List(s) + search queries via Playwright on a logged-in,
  isolated Chrome profile (headless by default), with a read-only DOM extractor, an
  engagement `min_score` floor, canonical-URL dedup, and a cap. `run.py` selects it via
  `source.type: twitter-list` (else the default file source). Turns the pipeline into a
  one-command collect → score → draft → lint → report → publish flow. Playwright is an
  optional dep (only this source needs it).
- **tech-intel: tone scrub** — `LintPolicy.scrub_replacements` ({bad: good}) runs a
  deterministic substring rewrite *before* the lint, so cheap cringe / 江湖气 / 老登
  wording (e.g. `死磕→攻坚`, `撒币→大额补贴`, variants included, longer keys first) is
  fixed in place instead of dropping an otherwise-good piece. Scrub for tone; keep
  `banned_phrases` for the unsalvageable.
- **tech-intel: thread enrichment + synthesis support** — `TwitterListSource` can pull each
  top item's full **thread** (`enrich_threads` / `max_threads`) into `context_text`, giving
  the drafter the author's complete reasoning instead of one tweet. `LintPolicy.trace_scope:
  corpus` traces facts against ALL collected items (not just the output's own source), so a
  persona can fuse related items into one synthesized, opinionated piece while fabrication
  (a fact in no collected item) is still dropped. Negation-preservation stays scoped to the
  item's own source (an unrelated item's "not" never forces a negation into every draft).
- **tech-intel: shipped Feishu sink** — `adapters/feishu.FeishuPublisher` and a
  `run.py --feishu` flag publish the report as a Feishu **doc + an interactive card**
  (token → create docx → markdown-to-blocks → DM a card with an "open doc" button).
  Credentials resolve **`skills.env`-first** via `resolve_feishu_cred` (a pikiloom host
  injects its own bot's `FEISHU_*` into the process env; the content-publishing app must
  win) — override per-run with `TECH_INTEL_FEISHU_*`.
- **tech-intel: report styles** — `build_report` now supports `report_style: headed`
  (one `# <section title>` per content type, each item under `### N. @author — url`)
  alongside the default `buckets`, with a config-driven `section_titles` map so
  project-specific headings stay in config, not the engine. Lets the generic pipeline
  reproduce a per-source briefing layout.
- **Test suite** — 73 stdlib `unittest` tests across the three skills (`tests/`),
  runnable with no dependencies, no API key, and no network. See
  [TESTING.md](./TESTING.md). The tech-intel lint guardrail is pinned both in
  isolation and inside a full pipeline run; the Feishu sink is covered against a
  fake `requests` (call sequence, block conversion, cred precedence); both report
  styles are covered.
- **CI** — a GitHub Actions workflow that byte-compiles every skill, runs the test
  suite, and runs the zero-key `tech-intel --demo` smoke on Python 3.10–3.13.
- **Project docs & templates** — `CONTRIBUTING.md`, `TESTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, issue forms, and a pull-request template.

### Fixed
- `.gitignore` now ignores the machine-local `.claude/` and `.agents/` install
  symlinks created by the skills CLI, so they no longer show up as untracked.
- `adapters.defaults.resolve_key` no longer leaks a file handle when reading
  `skills.env` (now uses a `with` block).

## [0.1.0] - 2026-06-20

### Added
- Initial release with three skills:
  - **image-gen** — text-to-image and reference-image editing via OpenAI
    `gpt-image-2`, pure Python stdlib (no installs).
  - **video-use** — record a web app, cut filler, zoom, burn subtitles, and add an
    optional voiceover; self-contained venv.
  - **embeddable signal pipeline** (shipped as `discover`, renamed to `tech-intel`
    in *Unreleased*) — collect → score → draft (one LLM call) → lint guardrail →
    publish, with pluggable source/voice/sink adapters.
