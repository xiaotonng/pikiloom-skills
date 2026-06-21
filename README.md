# pikiloom-skills

[![CI](https://github.com/xiaotonng/pikiloom-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaotonng/pikiloom-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

High-value, **non-official** agent skills, packaged for [skills.sh](https://skills.sh)
and Claude Code / Codex / any agent that reads `SKILL.md`. Curated from real use in
the pikiloom workflow — atomic, scriptable, and honest about their dependencies and
secrets.

| Skill | What it does | Keys (optional unless noted) |
|-------|--------------|------------------------------|
| **image-gen** | Generate / edit images with OpenAI `gpt-image-2` (text-to-image + reference/edit). Pure stdlib, no installs. | `OPENAI_API_KEY` (**required**, *direct OpenAI — not OpenRouter*) |
| **video-use** | Record a web app (Playwright) → cut filler → zoom → burn subtitles → optional voiceover. Self-contained venv. | `OPENROUTER_API_KEY` (voiceover only; subtitles need none) |
| **tech-intel** | Signal pipeline: collect → score → draft (1 LLM call) → **lint guardrail** → publish. Ships a **Chinese AI-news 仿写 default** (宝玉/歸藏-style faithful localized rewrite of high-engagement EN tweets). File-in/file-out, or collect fresh from an X List (Playwright) → Feishu. | `OPENROUTER_API_KEY` (draft; default model `deepseek/deepseek-chat`); `FEISHU_*` (sink); `playwright` (X-List source) |

**Contents:** [Install](#install) · [Keys](#keys) · [Per-skill setup](#per-skill-setup) · [Repo layout](#repo-layout) · [Tests](#tests) · [Contributing](#contributing)

## Install

```bash
# all skills, global (~/.claude/skills/), via the skills CLI
npx skills add xiaotonng/pikiloom-skills --skill '*' --agent claude-code -g -y

# or just one
npx skills add xiaotonng/pikiloom-skills --skill tech-intel --agent claude-code -g -y
```

Each skill lives under `skills/<name>/` with its own `SKILL.md`. After install,
your agent picks them up on the next session.

## Keys

Every skill resolves a key in this order (first hit wins) — so the simplest setup is
one gitignored file:

```
CLI flag  →  process env  →  skill-specific *_ENV_FILE  →  ~/.pikiloom/skills.env
```

```bash
cp .env.example ~/.pikiloom/skills.env
chmod 600 ~/.pikiloom/skills.env
# then fill in only the keys you need (see comments in the file)
```

- **image-gen** needs a **direct** OpenAI key (`sk-…` / `sk-svcacct-…`): it calls OpenAI's
  native Images API (`/v1/images/*`), which OpenRouter doesn't expose (OpenRouter does image
  generation through `/chat/completions` image output) — so a router key won't work here.
- **video-use** voiceover uses an OpenRouter `gpt-audio` key; the subtitle path needs
  no key at all (and `--engine say` is a macOS zero-key voiceover fallback).
- **tech-intel** uses an OpenRouter key for the draft step. To publish to Feishu (a doc +
  a card) pass `--feishu` and set `FEISHU_APP_ID/SECRET/RECEIVE_ID` (the app needs the
  `docx:document` and `im:message:send_as_bot` scopes). These resolve **`skills.env`-first**,
  not env-first like other keys: a pikiloom host injects its *own* bot's `FEISHU_*` into the
  process env, so the content-publishing app in your `skills.env` must take precedence
  (override per-run with `TECH_INTEL_FEISHU_*`). Other sinks: see `skills/tech-intel/EMBEDDING.md`.

Secrets are never committed: `.gitignore` drops `*.env`, and each skill reads keys at
runtime — none are baked into the scripts. See [SECURITY.md](./SECURITY.md).

## Per-skill setup

```bash
# video-use builds its own venv + ensures Chrome; needs ffmpeg on PATH
bash ~/.claude/skills/video-use/scripts/setup.sh

# tech-intel: core is stdlib-only; the runner/adapters want pyyaml + requests
pip install -r ~/.claude/skills/tech-intel/requirements.txt
python3 ~/.claude/skills/tech-intel/run.py --demo   # zero-key end-to-end smoke test
```

`image-gen` needs nothing installed — it is pure Python stdlib.

## Repo layout

```text
skills/
  image-gen/   SKILL.md + scripts/image_gen.py            (stdlib only)
  video-use/   SKILL.md + scripts/ + requirements.txt     (own venv; ffmpeg + Chrome)
  tech-intel/  SKILL.md + core/ + adapters/ + prompts/    (embeddable pipeline)
tests/         stdlib unittest suite, mirrors skills/
.github/       CI workflow + issue / PR templates
.env.example   every env var, documented
```

## Tests

The suite is stdlib `unittest` — no dependencies, no API key, no network:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

73 tests cover all three skills, including the tech-intel lint guardrail (run both in
isolation and end-to-end). CI runs them plus the zero-key demo on Python 3.10–3.13.
Details and the per-file coverage table: [TESTING.md](./TESTING.md).

## Contributing

New skills and fixes are welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md) for the
`SKILL.md` contract, the shared key-resolution convention, and the secrets policy.
Changes are logged in [CHANGELOG.md](./CHANGELOG.md). These are non-official,
best-effort skills: no support guarantee, but issues and PRs are read.

## License

MIT — see [LICENSE](./LICENSE).
