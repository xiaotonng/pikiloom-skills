---
name: image-gen
description: Generate or edit images with OpenAI gpt-image-2 — text-to-image and reference-image (image-to-image / edit / restyle / combine) modes. Use when the user wants to create or modify images such as logos, icons, illustrations, mockups, product shots, transparent-background assets, and social/marketing graphics, or edit/extend/restyle an existing image. Atomic, scriptable, stdlib-only (no pip installs).
---

# image-gen — gpt-image-2 image generation (atomic capability)

A self-contained wrapper around OpenAI's `gpt-image-2` Images API. Pure Python stdlib — no
`pip install`, no venv. Two modes, auto-selected by whether you pass `--ref`:

- **text-to-image** — prompt only → `/v1/images/generations`.
- **image-to-image / edit** — one or more `--ref` images → `/v1/images/edits`. Use a reference to
  lock a visual style, edit/extend an existing image, or combine multiple inputs. gpt-image-2 keeps
  the look of the reference(s) and applies the prompt.

## Run

```bash
python3 ~/.claude/skills/image-gen/scripts/image_gen.py \
  --prompt "your prompt" \
  --out /abs/path/out.png \
  [--ref /path/style-or-base.png]   # repeatable; presence switches to edit mode
  [--n 4]                            # variations → out_1.png .. out_4.png
  [--size 1536x1024]                 # 1024x1024 (default) | 1536x1024 (wide) | 1024x1536 (tall) | auto
  [--quality high]                   # low | medium | high (default) | auto
  [--background transparent]         # transparent | opaque | auto  (PNG)
  [--model gpt-image-2]              # see Models
```

Always saves PNG file(s). With `--n>1`, files get `_1.._N` suffixes. To show the result to a user,
`Read` the PNG (and/or `open` it on macOS). The caller decides where `--out` lives — for throwaway
exploration use a gitignored scratch dir.

## API key

Resolved in order: `--api-key` → `$OPENAI_API_KEY` → `--env-file <dotenv>` → `$IMAGE_GEN_ENV_FILE`
→ `~/.pikiloom/skills.env`. The simplest setup is one line in `~/.pikiloom/skills.env`:

```bash
echo 'OPENAI_API_KEY=sk-...' >> ~/.pikiloom/skills.env
```

> Use a **DIRECT** OpenAI key (`sk-...` / `sk-svcacct-...`), **not** an OpenRouter key: this wrapper
> calls OpenAI's native Images API (`/v1/images/*`), which OpenRouter doesn't expose (it does image
> generation via `/chat/completions` image output). gpt-image-2 needs the direct key.

## Prompting tips (these matter a lot)

- **Keep prompts light.** State only the essentials (subject, any must-have text spelled exactly,
  the vibe) and let the model diverge — over-specifying motif/colors/composition kills the spark.
  Generate several with `--n` and pick the best.
- **Lock a style with `--ref`** instead of describing it in words: pass an existing image and say
  only what to change.
- **Exact text**: put the literal string in quotes and spell short brand words letter-by-letter
  (e.g. `the word "pikiloom", spelled p-i-k-i-l-o-o-m`). gpt-image-2 renders text well but verify it.
- **Transparent assets**: `--background transparent` for icons/logos to drop on any surface.
- **Aspect**: wide logos → `--size 1536x1024`; icons/avatars/square → `1024x1024`; posters → `1024x1536`.

## Models

`gpt-image-2` (default, best) · `gpt-image-2-2026-04-21` (pinned snapshot) · `gpt-image-1.5` ·
`gpt-image-1` · `gpt-image-1-mini` (cheapest/fastest, good for drafts). Override with `--model`.

## Cost / time

`--quality high` is the slowest (~tens of seconds, up to ~80s/image) and priciest; use `low`/`medium`
for drafts. Each image is a separate billed generation, so batch with `--n` thoughtfully.

## Examples

```bash
# Logo, wide, several light-prompt variations
python3 .../image_gen.py --prompt "minimal premium logo wordmark 'acme', off-white on dark, one green accent mark" \
  --out ./acme.png --size 1536x1024 --n 4

# Restyle / edit using a reference image
python3 .../image_gen.py --prompt "same style, but the word is 'acme2' and the accent is blue" \
  --ref ./acme.png --out ./acme2.png

# Transparent app icon
python3 .../image_gen.py --prompt "rounded app icon, single abstract green knot mark, no text" \
  --out ./icon.png --size 1024x1024 --background transparent
```
