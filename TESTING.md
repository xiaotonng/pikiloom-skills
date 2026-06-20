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

## What is covered — 47 tests across 5 files

| File | Tests | Covers |
|------|------:|--------|
| `tests/test_tech_intel_lint.py` | 19 | The lint guardrail: fact-bearing number/handle extraction, unit-equivalence (`8倍`≡`8x`), unsourced-entity drop, negation preservation, thin-content, and full `lint_item` / `lint_outputs` verdicts. |
| `tests/test_tech_intel_adapters.py` | 12 | `parse_json_object` (fences/prose/garbage), `HeuristicScorer` ranking + blacklist/posted dedup, `FileSource` JSONL parsing, `JsonKnowledgeStore` round-trip, `resolve_key` precedence. |
| `tests/test_tech_intel_pipeline.py` | 4 | End-to-end runs with the zero-key `CannedLLM`: a clean run persists artifacts; a fabricated number is **dropped by lint mid-run**; an all-fabrication run aborts; and `run.py --demo` (the README's smoke command) is run as a subprocess. |
| `tests/test_image_gen.py` | 6 | `save_images` (single + `_1.._N` suffixes, empty-response exit) and `resolve_key` precedence (flag → env → env-file). |
| `tests/test_video_use.py` | 6 | The deterministic helpers: `srt_ts` formatting, `split_cues` proportional subtitle timing, `derive_spec_from_manifest` segment building. |

The highest-value tests are the lint ones: generated content is only as trustworthy
as its guardrail, so the anti-fabrication checks are pinned both in isolation and
inside a full pipeline run (`PipelineGuardrail.test_fabricated_number_is_dropped_end_to_end`).

## What is intentionally **not** unit-tested

These paths need a live key or a system binary, so they are exercised by the manual
examples in each `SKILL.md` rather than offline tests — calling them out so the
coverage table above stays honest:

- **image-gen** — the actual `POST /v1/images/*` HTTP call (needs a real OpenAI key).
- **video-use** — `ffmpeg` encode/concat, Playwright recording, and PIL subtitle
  rendering (need `ffmpeg`, system Chrome, and `pillow`).
- **tech-intel** — the real `OpenRouterLLM` HTTP call (needs `OPENROUTER_API_KEY`).
  Everything *around* it — wiring, drafting parse, lint, report, artifacts — is
  covered via `CannedLLM`.

## Adding tests

Keep new tests stdlib-only and offline. If a feature can only be verified against a
live service, add it to the "not unit-tested" list above and cover the surrounding
logic with a `CannedLLM`-style double instead. When you change a skill, update both
the test and the count/row in this table — the table is meant to match the suite
exactly, with no phantom entries.
