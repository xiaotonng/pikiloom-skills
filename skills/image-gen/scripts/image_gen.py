#!/usr/bin/env python3
"""
image-gen — atomic image generation / editing (stdlib only).

Two providers, auto-selected by which key you have (override with --provider):
  • openai      OpenAI native Images API — gpt-image-2
                  text-to-image   POST /v1/images/generations
                  image-to-image  POST /v1/images/edits        (--ref, multipart)
  • openrouter  OpenRouter chat-completions image output (POST /v1/chat/completions,
                  modalities:["image","text"]). With the default model it prefers the best
                  and falls back on failure: openai/gpt-5.4-image-2 (GPT Image 2 — best
                  text/wordmarks; needs the OpenRouter data policy to allow OpenAI image
                  models, else 404) → google/gemini-3-pro-image → google/gemini-2.5-flash-image.
                  --ref images are inlined as base64 data URLs. Pin one model (no fallback)
                  by passing an explicit slug, e.g. --model google/gemini-2.5-flash-image.

No third-party deps: pure Python stdlib (urllib multipart / JSON hand-rolled).

Key + provider resolution (first hit wins):
  --api-key  (+ --provider, else inferred: sk-or-… → openrouter, else openai)
  → OPENAI_API_KEY      → openai      (native; preferred when present)
  → OPENROUTER_API_KEY  → openrouter
  each key is read from: env → --env-file → $IMAGE_GEN_ENV_FILE → ~/.pikiloom/skills.env
"""
import argparse, base64, json, mimetypes, os, pathlib, sys, urllib.request, urllib.error, uuid

# Shared local secrets file for all pikiloom skills (gitignored, machine-local).
FALLBACK_ENV_FILES = [os.path.expanduser("~/.pikiloom/skills.env")]
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

# Bare OpenAI model name → OpenRouter slug. The GPT Image 2 backend lives behind gpt-5.4-image-2.
OPENROUTER_MODEL_ALIASES = {
    "gpt-image-2": "openai/gpt-5.4-image-2",
    "gpt-image-2-2026-04-21": "openai/gpt-5.4-image-2",
    "gpt-image-1.5": "openai/gpt-5-image",
    "gpt-image-1": "openai/gpt-5-image",
    "gpt-image-1-mini": "openai/gpt-5-image-mini",
}
# Quality-ordered fallback chain used by --provider openrouter when no explicit model is given.
# gpt-image-2 is the top priority (best text rendering, esp. wordmarks/logos); the backups are
# reachable non-OpenAI models (no data-policy opt-in needed) in descending quality. Override with
# IMAGE_GEN_OPENROUTER_FALLBACK="slug1,slug2,…".
OPENROUTER_FALLBACK = [m.strip() for m in os.environ.get("IMAGE_GEN_OPENROUTER_FALLBACK", "").split(",") if m.strip()] or [
    "openai/gpt-5.4-image-2",         # GPT Image 2 — best (needs data-policy opt-in on OpenRouter)
    "google/gemini-3-pro-image",      # Nano Banana Pro — strongest reachable non-OpenAI
    "google/gemini-2.5-flash-image",  # cheap last resort
]
# --size → OpenRouter image_config.aspect_ratio (chat-completions has no WxH field).
SIZE_TO_ASPECT = {"1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3"}


def _read_env_var(path, name):
    try:
        with open(path) as f:
            for line in f:
                s = line.strip()
                if s.startswith(f"{name}=") and not s.startswith("#"):
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _find_key(args, name):
    if os.environ.get(name):
        return os.environ[name]
    cands = []
    if args.env_file:
        cands.append(args.env_file)
    if os.environ.get("IMAGE_GEN_ENV_FILE"):
        cands.append(os.environ["IMAGE_GEN_ENV_FILE"])
    for p in cands + FALLBACK_ENV_FILES:
        k = _read_env_var(p, name)
        if k:
            return k
    return None


def resolve(args):
    """Return (api_key, provider, base_url)."""
    if args.api_key:
        prov = args.provider if args.provider != "auto" else \
            ("openrouter" if args.api_key.startswith("sk-or-") else "openai")
        return args.api_key, prov, (OPENROUTER_BASE if prov == "openrouter" else OPENAI_BASE)

    oa = _find_key(args, "OPENAI_API_KEY")
    orr = _find_key(args, "OPENROUTER_API_KEY")
    prov = args.provider
    if prov == "auto":  # native preferred for quality when present, else fall back to router key
        prov = "openai" if oa else ("openrouter" if orr else None)
    key = oa if prov == "openai" else orr
    if not key:
        want = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(prov, "OPENAI_API_KEY/OPENROUTER_API_KEY")
        sys.exit(f"No {want} found. Set it in env, pass --api-key, --env-file <dotenv>, "
                 "or add it to ~/.pikiloom/skills.env.")
    return key, prov, (OPENROUTER_BASE if prov == "openrouter" else OPENAI_BASE)


class ApiError(Exception):
    """An HTTP/parse error from a provider — raised (not exited) so callers can fall back."""

    def __init__(self, provider, code, body):
        self.provider, self.code, self.body = provider, code, body
        super().__init__(f"{provider} API error HTTP {code}: {body}")

    @property
    def is_data_policy(self):
        return self.provider == "openrouter" and self.code == 404 and "data policy" in self.body


def _send(req, provider):
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(provider, e.code, e.read().decode(errors="replace")[:1200])
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e}")


def _exit_api(e):
    hint = ""
    if e.is_data_policy:
        hint = ("\nHINT: this OpenAI image model is blocked by your OpenRouter data policy. "
                "Allow it at https://openrouter.ai/settings/privacy, or use --provider openai.")
    sys.exit(f"{e}{hint}")


def _post_json(url, key, payload, provider, extra_headers=None):
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers=headers)
    return _send(req, provider)


def _post_multipart(url, key, fields, files, provider):
    boundary = "----imagegen" + uuid.uuid4().hex
    buf = bytearray()
    for name, val in fields.items():
        if val is None:
            continue
        buf += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode()
    for name, path in files:
        fn = os.path.basename(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            content = f.read()
        buf += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n").encode()
        buf += content + b"\r\n"
    buf += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=bytes(buf), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _send(req, provider)


def _out_path(out, i, total):
    if total <= 1:
        return out
    stem, ext = os.path.splitext(out)
    return f"{stem}_{i + 1}{ext or '.png'}"


def _save_b64(b64, path):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))


def save_images(resp, out):
    """Save an OpenAI Images API response (data[].b64_json) to PNG file(s)."""
    items = [d.get("b64_json") for d in (resp.get("data") or []) if d.get("b64_json")]
    if not items:
        sys.exit(f"No image in response: {json.dumps(resp)[:600]}")
    paths = []
    for i, b64 in enumerate(items):
        p = _out_path(out, i, len(items))
        _save_b64(b64, p)
        paths.append(p)
    for p in paths:
        print("saved", p)
    if resp.get("usage"):
        print("usage:", json.dumps(resp["usage"]))
    return paths


def run_openai(args, key, base):
    try:
        if args.ref:
            fields = {"model": args.model, "prompt": args.prompt, "n": str(args.n),
                      "size": args.size, "quality": args.quality, "background": args.background}
            files = [("image[]", p) for p in args.ref]
            resp = _post_multipart(f"{base}/images/edits", key, fields, files, "openai")
        else:
            payload = {"model": args.model, "prompt": args.prompt, "n": args.n,
                       "size": args.size, "quality": args.quality, "background": args.background}
            resp = _post_json(f"{base}/images/generations", key, payload, "openai")
    except ApiError as e:
        _exit_api(e)
    return save_images(resp, args.out)


def _data_url(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def or_model(name):
    """Map a bare OpenAI model name to an OpenRouter slug; pass any explicit slug through."""
    return name if "/" in name else OPENROUTER_MODEL_ALIASES.get(name, "openai/gpt-5.4-image-2")


def or_chain(name):
    """Models to try for --provider openrouter. The default (gpt-image-2, i.e. the top of the
    quality chain) walks the whole fallback chain; any other explicit model is used alone."""
    return list(OPENROUTER_FALLBACK) if or_model(name) == OPENROUTER_FALLBACK[0] else [or_model(name)]


def _or_one(base, key, model, body, headers):
    """One chat-completions image call → (b64, cost). Raises ApiError on HTTP error or no image."""
    resp = _post_json(f"{base}/chat/completions", key, dict(body, model=model), "openrouter", headers)
    msg = (resp.get("choices") or [{}])[0].get("message", {}) or {}
    imgs = msg.get("images") or []
    if not imgs:
        raise ApiError("openrouter", 502, f"no image returned (message keys={list(msg.keys())})")
    url = imgs[0].get("image_url", {}).get("url", "")
    b64 = url.split("base64,", 1)[1] if "base64," in url else url
    return b64, float((resp.get("usage") or {}).get("cost") or 0)


def run_openrouter(args, key, base):
    chain = or_chain(args.model)
    if "/" not in args.model:
        print(f"[openrouter] model {args.model!r} → {or_model(args.model)!r}"
              + (f"  (+{len(chain) - 1} fallback{'s' if len(chain) > 2 else ''})" if len(chain) > 1 else ""),
              file=sys.stderr)
    for opt, val, default in (("--quality", args.quality, "high"), ("--background", args.background, "auto")):
        if val != default:
            print(f"[openrouter] {opt}={val} ignored (no equivalent in chat-completions image output)", file=sys.stderr)

    if args.ref:
        content = [{"type": "text", "text": args.prompt}] + \
                  [{"type": "image_url", "image_url": {"url": _data_url(p)}} for p in args.ref]
    else:
        content = args.prompt
    body = {"modalities": ["image", "text"], "messages": [{"role": "user", "content": content}]}
    ar = SIZE_TO_ASPECT.get(args.size)
    if ar:
        body["image_config"] = {"aspect_ratio": ar}
    headers = {"HTTP-Referer": "https://github.com/xiaotonng/pikiloom-skills", "X-Title": "pikiloom image-gen"}

    # First image: walk the quality-ordered chain until a model answers.
    paths, cost, working, last_err = [], 0.0, None, None
    for j, m in enumerate(chain):
        try:
            b64, c = _or_one(base, key, m, body, headers)
        except ApiError as e:
            last_err = e
            if j + 1 < len(chain):
                why = "blocked by data policy" if e.is_data_policy else f"HTTP {e.code}"
                print(f"[openrouter] {m} unavailable ({why}) → falling back to {chain[j + 1]}", file=sys.stderr)
            continue
        working, cost = m, cost + c
        p = _out_path(args.out, 0, args.n)
        _save_b64(b64, p)
        paths.append(p)
        break
    if working is None:
        _exit_api(last_err)
    if working != chain[0]:
        print(f"[openrouter] NOTE: used backup {working!r}; preferred {chain[0]!r} was unavailable "
              "— enable OpenAI image models at https://openrouter.ai/settings/privacy for best quality.",
              file=sys.stderr)

    # Remaining images reuse the working model (no second fallback walk).
    for i in range(1, max(1, args.n)):
        try:
            b64, c = _or_one(base, key, working, body, headers)
        except ApiError as e:
            _exit_api(e)
        cost += c
        p = _out_path(args.out, i, args.n)
        _save_b64(b64, p)
        paths.append(p)

    for p in paths:
        print("saved", p)
    if cost:
        print("usage:", json.dumps({"model": working, "cost": round(cost, 6), "images": len(paths)}))
    return paths


def main():
    ap = argparse.ArgumentParser(description="Generate / edit images via OpenAI gpt-image-2 (direct) or OpenRouter.")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, help="output PNG path; with --n>1, _1.._N suffixes are added")
    ap.add_argument("--ref", action="append", default=[],
                    help="reference image path (repeatable); any --ref switches to image-to-image / edit mode")
    ap.add_argument("--model", default="gpt-image-2",
                    help="openai: gpt-image-2 (default) | gpt-image-2-2026-04-21 | gpt-image-1.5 | gpt-image-1 | "
                         "gpt-image-1-mini.  openrouter: the default walks a quality chain "
                         "(openai/gpt-5.4-image-2 → google/gemini-3-pro-image → google/gemini-2.5-flash-image); "
                         "pass an explicit slug to pin one model (no fallback)")
    ap.add_argument("--provider", default="auto", choices=["auto", "openai", "openrouter"],
                    help="auto (default): openai if OPENAI_API_KEY is present, else openrouter; or force one")
    ap.add_argument("--size", default="1024x1024", help="1024x1024 | 1536x1024 (wide) | 1024x1536 (tall) | auto")
    ap.add_argument("--quality", default="high", help="low | medium | high (default) | auto   [openai only]")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--background", default="auto", help="transparent | opaque | auto   [openai only]")
    ap.add_argument("--api-key")
    ap.add_argument("--env-file")
    args = ap.parse_args()

    for p in args.ref:
        if not os.path.exists(p):
            sys.exit(f"--ref not found: {p}")

    key, provider, base = resolve(args)
    (run_openrouter if provider == "openrouter" else run_openai)(args, key, base)


if __name__ == "__main__":
    main()
