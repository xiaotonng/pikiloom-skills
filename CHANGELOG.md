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
- **Test suite** — 47 stdlib `unittest` tests across the three skills (`tests/`),
  runnable with no dependencies, no API key, and no network. See
  [TESTING.md](./TESTING.md). The tech-intel lint guardrail is pinned both in
  isolation and inside a full pipeline run.
- **CI** — a GitHub Actions workflow that byte-compiles every skill, runs the test
  suite, and runs the zero-key `tech-intel --demo` smoke on Python 3.10–3.13.
- **Project docs & templates** — `CONTRIBUTING.md`, `TESTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, issue forms, and a pull-request template.

### Fixed
- `.gitignore` now ignores the machine-local `.claude/` and `.agents/` install
  symlinks created by the skills CLI, so they no longer show up as untracked.

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
