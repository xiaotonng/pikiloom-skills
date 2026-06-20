---
name: video-use
description: Record a web app and cut it into a narrated promo/demo video — screen-record (Playwright) → speed-up/cut filler → zoom-in on key moments → burn subtitles → optional voiceover. Zero-key for subtitles; voiceover uses OpenRouter gpt-audio (or macOS `say`). Self-contained skill (own venv + system Chrome). Use when the user says "record a demo / 录个产品导览 / make a promo / 剪个视频 / add subtitles / 配旁白 / turn these into a launch video".
argument-hint: "[what to record / 素材目录] [一句话剪辑意图]"
allowed-tools: Bash, Read, Write, Edit
---

# /video-use — record & cut a web demo into a narrated promo

Self-contained. Installs to `~/.claude/skills/video-use/` and builds **its own venv**
(`.venv` — playwright + pillow + requests). Uses **system Chrome** (no browser download) and
**ffmpeg** (must be on PATH). For demo/marketing material — not a product feature.

## First run (one-time setup)

```bash
bash ~/.claude/skills/video-use/scripts/setup.sh   # builds .venv, ensures Chrome, checks ffmpeg
```

`PY=~/.claude/skills/video-use/.venv/bin/python` in the commands below.

## Pipeline (zero-key subtitle path)

1. **Record** — `scripts/record_web.py` drives Chrome and records a 1080p webm +
   `nav_manifest.json` (per-page enter/settle/leave timestamps). For a *scripted
   interaction* (not a page tour), write a small Playwright script that opens a
   context with `record_video_dir=...` and logs your own millisecond timestamps.
2. **Compose** — `scripts/compose_narrated.py` cuts the source into segments,
   speeds up / freezes filler, **zooms into key regions**, burns subtitles, and
   (optionally) lays a TTS voiceover. Subtitles come straight from the narration
   text — **no transcription key needed**.

```bash
PY=~/.claude/skills/video-use/.venv/bin/python

# 1) generic page-tour recorder (optional; skip if you scripted your own flow)
$PY ~/.claude/skills/video-use/scripts/record_web.py \
  --base http://127.0.0.1:3000 --page 'Home=/' --page 'Agents=/agents' --out-dir /tmp/demo

# 2) compose from an explicit spec (subtitles only = zero key)
$PY ~/.claude/skills/video-use/scripts/compose_narrated.py --spec /tmp/demo/spec.json

# 2b) with voiceover — key comes from env or ~/.pikiloom/skills.env automatically:
$PY ~/.claude/skills/video-use/scripts/compose_narrated.py --spec /tmp/demo/spec.json
#    macOS zero-key fallback: add `--engine say --voice Samantha` (English) for voiceover
```

## spec.json schema (explicit segments — the precise path)

```jsonc
{
  "source": "/abs/raw.webm",
  "out_dir": "/abs/edit",
  "fps": 30,
  "tts": { "engine": "openrouter", "model": "openai/gpt-audio", "voice": "marin" },
  "segments": [
    {
      "name": "pick-model",
      "narration": "Pick any model for Codex — cloud or local.",   // → subtitle (+ voiceover if key set)
      "parts": [
        { "window": [a, b], "speed": 1 },                          // real-time
        { "window": [b, c], "speed": 6 },                          // speed up filler / waits
        { "window": [c, d], "speed": 1, "zoom": [x, y, w, h] }     // ZOOM into a region (source px)
      ],
      "extend_part": 0   // freeze THIS part to fit narration length (freeze on a STATIC frame)
    }
  ]
}
```

- **speed** `>1` timelapses a window (loads, waits, scrolls) — keeps filler short.
- **zoom** `[x,y,w,h]` (source px): crop to that region and scale back to a full
  frame so a small UI detail is legible ("放大核心能力"). Match the source aspect
  ratio (e.g. 16:10) to avoid stretch.
- **narration** drives the burned subtitle (and voiceover if an engine/key is
  set); the segment auto-extends (freeze on `extend_part`) to fit it. Omit it for
  a silent segment (a muted track is padded so the `-c copy` concat stays valid).

## Hard-won ffmpeg notes (read before editing the scripts)

- Homebrew ffmpeg has **no libass/drawtext** → subtitles render as PIL transparent
  PNGs `overlay`-ed on time windows. Fonts: PingFang → Hiragino Sans GB → STHeiti
  (renders Latin fine too). On non-macOS, install a CJK-capable TTF and adjust the
  `FONT_CANDIDATES` list at the top of `compose_narrated.py`.
- Multi-segment `-c copy` concat drifts ~60ms/seg → the subtitle cursor accumulates
  by ffprobe **actual** segment length, not nominal.
- Static pages: `tpad` freeze-extends a part to fill narration — freeze on a settled
  frame, never on a route-transition white flash.
- SPA recording: `networkidle` fires instantly on route changes ≠ data painted; the
  real skeleton window is ≈1.2s after enter. Assert readiness on a post-load
  element's text, not a URL prefix.

## Secrets

- Voiceover key resolves from `$OPENROUTER_API_KEY` → `~/.pikiloom/skills.env`
  (`OPENROUTER_API_KEY=...`). Never echo or commit keys. The subtitle path needs
  **no key**; `--engine say` is a macOS zero-key voiceover fallback.
- `ELEVENLABS_API_KEY` is optional and only used for *word-level transcription
  editing of spoken-source footage* via the upstream `browser-use/video-use` tool —
  not needed for the screen-record → narrate pipeline above.
