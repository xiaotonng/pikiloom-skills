# Testing

The whole suite is **stdlib `unittest`** — no `pip install`, no API key, no network,
no `ffmpeg`/Chrome. It runs anywhere Python 3.10+ runs, which is why CI needs no
setup step beyond `setup-python`.

```bash
# from the repo root
python3 -m unittest discover -s tests -p 'test_*.py' -v

# a single file / case
python3 -m unittest tests.test_tech_intel_lint -v
python3 -m unittest tests.test_tech_intel_lint.UnsourcedEntityTests
```

## What is covered — 88 tests across 7 files

| File | Tests | Covers |
|------|------:|--------|
| `tests/test_tech_intel_lint.py` | 25 | The lint guardrail: fact-bearing number/handle extraction, unit-equivalence (`8倍`≡`8x`), unsourced-entity drop, negation preservation (and that it stays **item-scoped** even under corpus trace), thin-content, full `lint_item` / `lint_outputs` verdicts, `trace_scope` (item vs **corpus**), and `scrub_text` tone rewrite (variants + longer-key precedence). |
| `tests/test_tech_intel_adapters.py` | 15 | `parse_json_object` (fences/prose/garbage), `HeuristicScorer` ranking + blacklist/posted dedup, `FileSource` JSONL parsing, `JsonKnowledgeStore` round-trip, `resolve_key` precedence, and `build_report` styles (`buckets` + `headed` with config-driven `section_titles`). |
| `tests/test_tech_intel_feishu.py` | 10 | The `FeishuPublisher` sink against a fake `requests`: `md_to_feishu_blocks` conversion (headings/divider/bullets/inline), the token→create-doc→write-blocks→send-card call sequence, `folder_token` passthrough, missing-creds skip, error → raise (non-fatal), and `resolve_feishu_cred` precedence (**skills.env beats the ambient process env**). |
| `tests/test_tech_intel_twitter.py` | 7 | The `TwitterListSource` pure parts (no browser/network): `to_int` count parsing, `normalize_list_url` / `canonical_status_url`, and the raw-row → `Item` mapping (fields/metrics, canonical-url dedup, `min_score` filter + sort, `max_items` cap). `collect()` itself needs Playwright + a logged-in profile (live only). |
| `tests/test_tech_intel_pipeline.py` | 4 | End-to-end runs with the zero-key `CannedLLM`: a clean run persists artifacts; a fabricated number is **dropped by lint mid-run**; an all-fabrication run aborts; and `run.py --demo` (the README's smoke command) is run as a subprocess. |
| `tests/test_image_gen.py` | 21 | `save_images` (single + `_1.._N` suffixes, empty-response exit); `resolve` provider+key selection (flag wins, `sk-or-` prefix → openrouter, env, env-file, OpenAI-preferred when both present, `--provider` override, missing-key exit); `or_model` alias mapping; the `--size` → `image_config.aspect_ratio` table; and the OpenRouter `or_chain` fallback (gpt-image-2 is tier-0, default walks the full chain, explicit slug pins one model, backups are non-OpenAI). |
| `tests/test_video_use.py` | 6 | The deterministic helpers: `srt_ts` formatting, `split_cues` proportional subtitle timing, `derive_spec_from_manifest` segment building. |

The highest-value tests are the lint ones: generated content is only as trustworthy
as its guardrail, so the anti-fabrication checks are pinned both in isolation and
inside a full pipeline run (`PipelineGuardrail.test_fabricated_number_is_dropped_end_to_end`).

## What is intentionally **not** unit-tested

These paths need a live key or a system binary, so they are exercised by the manual
examples in each `SKILL.md` rather than offline tests — calling them out so the
coverage table above stays honest:

- **image-gen** — the live HTTP calls: the OpenAI `POST /v1/images/*` path (needs a real
  OpenAI key) and the OpenRouter `POST /v1/chat/completions` image path (needs
  `OPENROUTER_API_KEY` plus OpenAI image models allowed in your data policy).
- **video-use** — `ffmpeg` encode/concat, Playwright recording, and PIL subtitle
  rendering (need `ffmpeg`, system Chrome, and `pillow`).
- **tech-intel** — the real `OpenRouterLLM` HTTP call (needs `OPENROUTER_API_KEY`),
  the real `FeishuPublisher` HTTP calls (need the Feishu app creds + network), and
  the `TwitterListSource.collect()` browser drive (needs Playwright + a logged-in
  Chrome profile). Everything *around* them — wiring, drafting parse, lint, report,
  artifacts, the Feishu call sequence / block conversion / cred precedence, and the
  Twitter row → Item mapping — is covered via `CannedLLM` and fakes.

## Adding tests

Keep new tests stdlib-only and offline. If a feature can only be verified against a
live service, add it to the "not unit-tested" list above and cover the surrounding
logic with a `CannedLLM`-style double instead. When you change a skill, update both
the test and the count/row in this table — the table is meant to match the suite
exactly, with no phantom entries.
