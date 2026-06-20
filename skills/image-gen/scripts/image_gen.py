#!/usr/bin/env python3
"""
image-gen — atomic image generation / editing via OpenAI gpt-image-2 (stdlib only).

Two modes (auto-selected):
  text-to-image    no --ref      -> POST /v1/images/generations
  image-to-image   one+ --ref    -> POST /v1/images/edits   (style ref / edit / combine)

No third-party deps: pure Python stdlib (urllib multipart hand-rolled).

Key resolution, first hit wins:
  --api-key  >  $OPENAI_API_KEY  >  --env-file's OPENAI_API_KEY
            >  $IMAGE_GEN_ENV_FILE's OPENAI_API_KEY  >  ~/.pikiloom/skills.env
Use a DIRECT OpenAI key (sk-... / sk-svcacct-...), NOT an OpenRouter key:
OpenRouter may block OpenAI image models by data policy.
"""
import argparse, base64, json, mimetypes, os, pathlib, sys, urllib.request, urllib.error, uuid

# Shared local secrets file for all pikiloom skills (gitignored, machine-local).
FALLBACK_ENV_FILES = [
    os.path.expanduser("~/.pikiloom/skills.env"),
]
API_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _read_env_key(path):
    try:
        for line in open(path):
            s = line.strip()
            if s.startswith("OPENAI_API_KEY=") and not s.startswith("#"):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def resolve_key(args):
    if args.api_key:
        return args.api_key
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    cands = []
    if args.env_file:
        cands.append(args.env_file)
    if os.environ.get("IMAGE_GEN_ENV_FILE"):
        cands.append(os.environ["IMAGE_GEN_ENV_FILE"])
    cands += FALLBACK_ENV_FILES
    for p in cands:
        k = _read_env_key(p)
        if k:
            return k
    sys.exit("No OpenAI API key found. Set $OPENAI_API_KEY, pass --api-key, --env-file <dotenv>, "
             "or add OPENAI_API_KEY to ~/.pikiloom/skills.env.")


def _send(req):
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"OpenAI API error HTTP {e.code}: {e.read().decode(errors='replace')[:1200]}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e}")


def _post_json(url, key, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return _send(req)


def _post_multipart(url, key, fields, files):
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
    req = urllib.request.Request(
        url, data=bytes(buf), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _send(req)


def save_images(resp, out):
    data = resp.get("data") or []
    if not data:
        sys.exit(f"No image in response: {json.dumps(resp)[:600]}")
    stem, ext = os.path.splitext(out)
    ext = ext or ".png"
    paths = []
    for i, d in enumerate(data):
        b64 = d.get("b64_json")
        if not b64:
            continue
        p = out if len(data) == 1 else f"{stem}_{i + 1}{ext}"
        pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            f.write(base64.b64decode(b64))
        paths.append(p)
    for p in paths:
        print("saved", p)
    if resp.get("usage"):
        print("usage:", json.dumps(resp["usage"]))
    return paths


def main():
    ap = argparse.ArgumentParser(description="Generate / edit images with OpenAI gpt-image-2.")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, help="output PNG path; with --n>1, _1.._N suffixes are added")
    ap.add_argument("--ref", action="append", default=[],
                    help="reference image path (repeatable); any --ref switches to image-to-image / edit mode")
    ap.add_argument("--model", default="gpt-image-2",
                    help="gpt-image-2 (default) | gpt-image-2-2026-04-21 | gpt-image-1.5 | gpt-image-1 | gpt-image-1-mini")
    ap.add_argument("--size", default="1024x1024", help="1024x1024 | 1536x1024 (wide) | 1024x1536 (tall) | auto")
    ap.add_argument("--quality", default="high", help="low | medium | high (default) | auto")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--background", default="auto", help="transparent | opaque | auto (transparent needs PNG/WebP)")
    ap.add_argument("--api-key")
    ap.add_argument("--env-file")
    args = ap.parse_args()

    key = resolve_key(args)
    if args.ref:
        for p in args.ref:
            if not os.path.exists(p):
                sys.exit(f"--ref not found: {p}")
        fields = {"model": args.model, "prompt": args.prompt, "n": str(args.n),
                  "size": args.size, "quality": args.quality, "background": args.background}
        files = [("image[]", p) for p in args.ref]
        resp = _post_multipart(f"{API_BASE}/images/edits", key, fields, files)
    else:
        payload = {"model": args.model, "prompt": args.prompt, "n": args.n,
                   "size": args.size, "quality": args.quality, "background": args.background}
        resp = _post_json(f"{API_BASE}/images/generations", key, payload)
    save_images(resp, args.out)


if __name__ == "__main__":
    main()
