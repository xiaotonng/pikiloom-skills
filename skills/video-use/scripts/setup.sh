#!/usr/bin/env bash
# video-use setup — build the skill's self-contained venv + check system deps.
#
# Idempotent. Project deps (playwright / pillow / requests) auto-install into a
# local .venv next to the skill; system deps (ffmpeg, Chrome) are reported if
# missing, never auto-installed. The voiceover key (OPENROUTER_API_KEY) is
# OPTIONAL — the subtitle path needs zero keys.
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$SKILL_DIR/.venv"
REQ="$SKILL_DIR/requirements.txt"
NEED=""
say() { printf '%s\n' "$*"; }

# 1) venv + python deps (prefer uv; fall back to python3 -m venv + pip)
if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV" >/dev/null 2>&1 || true
  if uv pip install --python "$VENV/bin/python" -q -r "$REQ"; then
    say "✓ python deps installed (uv) → $VENV"
  else
    NEED=1; say "✗ uv pip install failed — run: uv pip install --python $VENV/bin/python -r $REQ"
  fi
elif command -v python3 >/dev/null 2>&1; then
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  if "$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1 \
     && "$VENV/bin/python" -m pip install -q -r "$REQ"; then
    say "✓ python deps installed (pip) → $VENV"
  else
    NEED=1; say "✗ pip install failed — run: $VENV/bin/python -m pip install -r $REQ"
  fi
else
  NEED=1; say "✗ no python3 / uv found — install Python 3.10+ or uv"
fi

# 2) Playwright Chrome (record_web.py prefers the system 'chrome' channel)
if [ -x "$VENV/bin/python" ]; then
  if "$VENV/bin/python" -m playwright install chrome >/dev/null 2>&1; then
    say "✓ Playwright Chrome ready"
  else
    say "• Playwright couldn't ensure Chrome — system Chrome is used if present"
  fi
fi

# 3) system tools (report only — don't auto-install system packages)
for bin in ffmpeg ffprobe; do
  if command -v "$bin" >/dev/null 2>&1; then
    say "✓ $bin: $(command -v "$bin")"
  else
    NEED=1; say "✗ missing $bin"
  fi
done
[ -n "$NEED" ] && say "  install ffmpeg (incl. ffprobe): macOS 'brew install ffmpeg' / Debian 'sudo apt install ffmpeg' / Arch 'sudo pacman -S ffmpeg'"

# 4) voiceover key (OPTIONAL) — env first, then the shared skills env file
KEY="${OPENROUTER_API_KEY:-}"
if [ -z "$KEY" ] && [ -f "$HOME/.pikiloom/skills.env" ]; then
  KEY="$(grep -sh '^OPENROUTER_API_KEY=.\+' "$HOME/.pikiloom/skills.env" 2>/dev/null | head -1)"
fi
if [ -n "$KEY" ]; then
  say "✓ OPENROUTER_API_KEY present (voiceover available)"
else
  say "• no OPENROUTER_API_KEY — OpenRouter voiceover unavailable; subtitles still work, or use --engine say (macOS)"
fi

say "---"
say "VENV=$VENV"
say "PY=$VENV/bin/python"
if [ -z "$NEED" ]; then
  say "VERDICT: READY — see SKILL.md for the record → compose pipeline"
else
  say "VERDICT: NEEDS_SETUP — fix the ✗ items above and re-run this script"
fi
