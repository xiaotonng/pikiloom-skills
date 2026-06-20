# pikiloom-skills

High-value, **non-official** agent skills, packaged for [skills.sh](https://skills.sh)
and Claude Code / Codex / any agent that reads `SKILL.md`. Curated from real use in
the pikiloom workflow — atomic, scriptable, and honest about their dependencies and
secrets.

| Skill | What it does | Keys (optional unless noted) |
|-------|--------------|------------------------------|
| **image-gen** | Generate / edit images with OpenAI `gpt-image-2` (text-to-image + reference/edit). Pure stdlib, no installs. | `OPENAI_API_KEY` (**required**, *direct OpenAI — not OpenRouter*) |
| **video-use** | Record a web app (Playwright) → cut filler → zoom → burn subtitles → optional voiceover. Self-contained venv. | `OPENROUTER_API_KEY` (voiceover only; subtitles need none) |
| **discover** | Embeddable signal pipeline: collect → score → draft (1 LLM call) → **lint guardrail** → publish. Runs file-in/file-out; plug in your own source/voice/sink. | `OPENROUTER_API_KEY` (LLM draft) |

## Install

```bash
# all skills, global (~/.claude/skills/), via the skills CLI
npx skills add xiaotonng/pikiloom-skills --skill '*' --agent claude-code -g -y

# or just one
npx skills add xiaotonng/pikiloom-skills --skill video-use --agent claude-code -g -y
```

Each skill lives under `skills/<name>/` with its own `SKILL.md`. After install,
your agent picks them up on the next session.

## Keys — one shared local file

Every skill resolves a key in this order (first hit wins):

```
CLI flag  →  process env  →  skill-specific *_ENV_FILE  →  ~/.pikiloom/skills.env
```

So the simplest setup is one gitignored file:

```bash
cp .env.example ~/.pikiloom/skills.env
chmod 600 ~/.pikiloom/skills.env
# then fill in only the keys you need (see comments in the file)
```

- **image-gen** needs a **direct** OpenAI key (`sk-…` / `sk-svcacct-…`). OpenRouter
  blocks OpenAI image models by data policy — a router key returns `404 … data policy`.
- **video-use** voiceover uses an OpenRouter `gpt-audio` key; the subtitle path needs
  no key at all (and `--engine say` is a macOS zero-key voiceover fallback).
- **discover** uses an OpenRouter key for the draft step; its Feishu/Slack-style sink
  credentials are only needed if you wire that publisher (see `skills/discover/EMBEDDING.md`).

Secrets are never committed: `.gitignore` drops `*.env`, and each skill reads keys at
runtime — none are baked into the scripts.

## Per-skill setup

```bash
# video-use builds its own venv + ensures Chrome; needs ffmpeg on PATH
bash ~/.claude/skills/video-use/scripts/setup.sh

# discover: core is stdlib-only; the runner/adapters want pyyaml + requests
pip install -r ~/.claude/skills/discover/requirements.txt
python3 ~/.claude/skills/discover/run.py --demo   # zero-key end-to-end smoke test
```

## Layout

```text
skills/
  image-gen/   SKILL.md + scripts/image_gen.py            (stdlib only)
  video-use/   SKILL.md + scripts/ + requirements.txt     (own venv; ffmpeg + Chrome)
  discover/    SKILL.md + core/ + adapters/ + prompts/    (embeddable pipeline)
.env.example   every env var, documented
```

## License

MIT — see [LICENSE](./LICENSE).
