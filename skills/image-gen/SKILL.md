---
name: image-gen
description: Generate or edit images with OpenAI gpt-image-2 — text-to-image and reference-image (image-to-image / edit / restyle / combine) modes. Use when the user wants to create or modify images such as logos, icons, illustrations, mockups, product shots, transparent-background assets, and social/marketing graphics, or edit/extend/restyle an existing image. Atomic, scriptable, stdlib-only (no pip installs).
---

# image-gen — gpt-image-2 image generation (atomic capability)

A self-contained wrapper for `gpt-image-2`. Pure Python stdlib — no `pip install`, no venv.
Runs through **either** provider, auto-picked by your key (override with `--provider`): OpenAI's
native Images API directly, or OpenRouter's chat-completions image output (`openai/gpt-5.4-image-2`
is the same GPT Image 2 backend). Two modes, auto-selected by whether you pass `--ref`:

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
  [--provider openrouter]            # auto (default) | openai | openrouter
```

Always saves PNG file(s). With `--n>1`, files get `_1.._N` suffixes. To show the result to a user,
`Read` the PNG (and/or `open` it on macOS). The caller decides where `--out` lives — for throwaway
exploration use a gitignored scratch dir.

## API key & provider

Pick the provider by the key you supply (first hit wins): `--api-key` (+`--provider`) →
`OPENAI_API_KEY` (→ openai) → `OPENROUTER_API_KEY` (→ openrouter), each read from env →
`--env-file <dotenv>` → `$IMAGE_GEN_ENV_FILE` → `~/.pikiloom/skills.env`.

```bash
echo 'OPENAI_API_KEY=sk-...'        >> ~/.pikiloom/skills.env   # direct OpenAI (native Images API)
echo 'OPENROUTER_API_KEY=sk-or-...' >> ~/.pikiloom/skills.env   # via OpenRouter (one key for every skill)
```

- **Direct OpenAI** (`sk-...` / `sk-svcacct-...`) hits the native Images API (`/v1/images/*`): full
  `--quality`, `--background transparent`, native `--n`, and the sharpest text rendering.
- **OpenRouter** (`sk-or-...`, or `--provider openrouter`) routes through `/chat/completions`
  (`modalities:["image"]`); `--size` → `image_config.aspect_ratio`, `--n` loops, `--quality` /
  `--background` don't apply. With the **default** model it tries the best first and **falls back**
  on failure: `gpt-image-2` (`openai/gpt-5.4-image-2`, same backend — best for text/logos) →
  `google/gemini-3-pro-image` → `google/gemini-2.5-flash-image`. **OpenAI image models 404 unless your
  OpenRouter data policy allows them** — toggle <https://openrouter.ai/settings/privacy>; the
  non-OpenAI backups work without it, and the CLI prints a `NOTE` to stderr whenever it fell back.
  Pin one model (no fallback) with an explicit `--model <slug>`; override the chain with
  `IMAGE_GEN_OPENROUTER_FALLBACK="slug1,slug2,…"`.
- With **both** keys set, `--provider auto` prefers the direct OpenAI path (best fidelity); pass
  `--provider openrouter` to force the router.

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
Under `--provider openrouter` the default `gpt-image-2` walks the fallback chain
(`openai/gpt-5.4-image-2` → `google/gemini-3-pro-image` → `google/gemini-2.5-flash-image`); pass an
explicit slug (e.g. `google/gemini-2.5-flash-image`, `black-forest-labs/flux.2-pro`) to pin one model.

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
