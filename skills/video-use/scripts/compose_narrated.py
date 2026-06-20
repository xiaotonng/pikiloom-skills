"""旁白合成引擎:无人声素材(录屏/B-roll)→ 分段剪辑 + TTS 旁白 + 烧字幕成片。

零 key 剪辑路径的「执行端」,与上游 video-use 互补(上游吃带人声素材走转写;
这里吃无人声素材,旁白文案即字幕真源,不需要任何转写)。遵守上游硬规则:
逐段裁切 → 统一编码参数 `-c copy` 拼接;段边界 30ms 音频淡入淡出;字幕最后烧;
切点两侧留 pad。三个本机经验也铸在里面:
  - homebrew ffmpeg 无 libass/drawtext → 字幕用 PIL 渲透明 PNG + overlay 时窗烧;
  - 多段拼接帧取整漂移(~60ms/段)→ 字幕游标按 ffprobe 实际段长累计;
  - 静态页面用 tpad 冻帧把画面无感延长到旁白长度。

两种喂法:
  A. --spec spec.json                     # 显式分段(见 SKILL.md schema)
  B. --manifest nav_manifest.json --narration narration.json --source raw.webm
     (record_web.py 两件套 + {"页面名":"旁白文案"} 直接出片;--save-spec 可落
      派生 spec 供微调后走 A)

跑法(key 经 launcher 注入;--engine say 零 key 兜底):
    python -m infra.config -- .venv/bin/python compose_narrated.py --spec spec.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts_openrouter import synth_line  # noqa: E402

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]
BOLD_STYLES = ("Semibold", "Bold", "W6", "Medium")
FONT_SIZE = 42
STROKE = 3
SUB_MARGIN_V = 90  # 1080p 垂直安全区(对齐上游 MarginV=90)


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-4:]
        raise RuntimeError("ffmpeg failed:\n" + "\n".join(tail))


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_cues(text: str, start: float, dur: float) -> list[tuple[float, float, str]]:
    """一句旁白 → 多条字幕(按标点切,时长按字数比例分)。"""
    parts = [p.strip() for p in re.split(r"[,。:;,.;:]", text) if p.strip()]
    if not parts:
        return []
    total = sum(len(p) for p in parts)
    cues, t = [], start
    for p in parts:
        d = dur * len(p) / total
        cues.append((t, t + d, p))
        t += d
    return cues


def render_cue_pngs(cues: list[tuple[float, float, str]], out_dir: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for path in FONT_CANDIDATES:
        for idx in range(12):
            try:
                f = ImageFont.truetype(path, FONT_SIZE, index=idx)
            except OSError:
                break
            if f.getname()[1] in BOLD_STYLES:
                font = f
                break
            font = font or f
        if font is not None and font.getname()[1] in BOLD_STYLES:
            break
    if font is None:
        raise OSError(f"no usable CJK font among {FONT_CANDIDATES}")

    out_dir.mkdir(parents=True, exist_ok=True)
    pad = 8
    for i, (_a, _b, text) in enumerate(cues):
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        l, t, r, b = probe.textbbox((0, 0), text, font=font, stroke_width=STROKE)
        img = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(img).text(
            (pad - l, pad - t), text, font=font, fill=(255, 255, 255, 255),
            stroke_width=STROKE, stroke_fill=(0, 0, 0, 255),
        )
        img.save(out_dir / f"cue_{i:03d}.png")


def derive_spec_from_manifest(args: argparse.Namespace) -> dict:
    manifest = json.loads(Path(args.manifest).read_text())
    narration = json.loads(Path(args.narration).read_text())
    events = {e["page"]: e for e in manifest["events"]}
    ordered = [e for e in manifest["events"] if "settled" in e]

    segments: list[dict] = []
    if "Login" in events and "Login" in narration and ordered:
        lg, first = events["Login"], ordered[0]
        split = lg["submit"] + 0.16  # 提交动效之后进入「等鉴权」段
        segments.append({
            "name": "Login", "narration": narration["Login"],
            "parts": [
                {"window": [args.head_trim, split], "speed": 1},
                {"window": [split, first["enter"] - 0.06], "speed": args.speed},
            ],
            "extend_part": 0,  # 冻帧落在静态表单上,别冻在跳转白屏里
        })
    for e in ordered:
        if e["page"] not in narration:
            continue
        f0 = e["enter"] + 0.08
        f1 = min(f0 + args.load_window, e["leave"] - 0.5)
        segments.append({
            "name": e["page"], "narration": narration[e["page"]],
            "parts": [
                {"window": [f0, f1], "speed": args.speed},
                {"window": [f1, e["leave"] - 0.15], "speed": 1},
            ],
        })
    return {
        "source": str(Path(args.source).expanduser().resolve()),
        "out_dir": args.out_dir or str(Path(args.source).expanduser().resolve().parent / "edit"),
        "segments": segments,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="无人声素材 → 旁白成片")
    ap.add_argument("--spec", help="显式分段 spec.json")
    ap.add_argument("--manifest", help="record_web.py 的 nav_manifest.json")
    ap.add_argument("--narration", help='{"页面名":"旁白文案",…}')
    ap.add_argument("--source", help="manifest 模式的素材路径")
    ap.add_argument("--out-dir")
    ap.add_argument("--engine", choices=["openrouter", "say"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--speed", type=float, default=4.0, help="加载段倍速")
    ap.add_argument("--load-window", type=float, default=1.2)
    ap.add_argument("--head-trim", type=float, default=1.0, help="开场未首绘白屏裁剪")
    ap.add_argument("--narration-delay", type=float, default=0.25)
    ap.add_argument("--tail-pad", type=float, default=0.45)
    ap.add_argument("--no-subtitles", action="store_true")
    ap.add_argument("--save-spec", action="store_true", help="manifest 模式落派生 spec 后退出")
    args = ap.parse_args()

    if args.spec:
        spec = json.loads(Path(args.spec).read_text())
        spec_dir = Path(args.spec).resolve().parent
    elif args.manifest and args.narration and args.source:
        spec = derive_spec_from_manifest(args)
        spec_dir = Path(args.manifest).resolve().parent
    else:
        ap.error("要么 --spec,要么 --manifest + --narration + --source")

    src = Path(spec["source"])
    if not src.is_absolute():
        src = spec_dir / src
    out = Path(args.out_dir or spec.get("out_dir") or src.parent / "edit")
    out.mkdir(parents=True, exist_ok=True)
    if args.save_spec:
        dest = out / "spec_derived.json"
        dest.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
        print(f"spec → {dest}")
        return

    tts_cfg = spec.get("tts") or {}
    engine = args.engine or tts_cfg.get("engine", "openrouter")
    model = args.model or tts_cfg.get("model", "openai/gpt-audio")
    voice = args.voice or tts_cfg.get("voice")
    fps = spec.get("fps", args.fps)
    delay = spec.get("narration_delay", args.narration_delay)
    tail = spec.get("tail_pad", args.tail_pad)

    clips, narr = out / "clips", out / "narration"
    clips.mkdir(exist_ok=True)
    narr.mkdir(exist_ok=True)

    # Source pixel dims — used to scale a zoomed crop back to a full frame so
    # zoomed and non-zoomed segments share one resolution (required for the
    # `-c copy` concat). A part may carry `"zoom": [x, y, w, h]` (source px) to
    # magnify that region for its window — the "放大核心能力 / zoom-in" effect.
    _dims = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(src)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    SRCW, SRCH = (int(x) for x in _dims.split("x"))

    seg_files: list[Path] = []
    cues: list[tuple[float, float, str]] = []
    cursor = 0.0
    print(f"{'segment':20s} {'visual':>7s} {'narr':>6s} {'target':>7s}")
    for i, seg in enumerate(spec["segments"]):
        text = seg.get("narration", "")
        n_dur = 0.0
        a_path = narr / f"{i:02d}.wav"
        if text:
            # TTS 缓存:同文案+引擎+模型+音色直接复用,迭代剪辑不重复计费
            meta = {"text": text, "engine": engine, "model": model, "voice": voice}
            sidecar = a_path.with_suffix(".json")
            if (
                a_path.exists()
                and sidecar.exists()
                and json.loads(sidecar.read_text()) == meta
            ):
                n_dur = probe_duration(a_path)
            else:
                n_dur = synth_line(text, a_path, engine, model, voice)
                sidecar.write_text(json.dumps(meta, ensure_ascii=False))

        parts = seg["parts"]
        visual = sum((p["window"][1] - p["window"][0]) / p.get("speed", 1) for p in parts)
        target = max(visual, delay + n_dur + tail) if text else visual
        extra = max(0.0, target - visual)
        extend_at = seg.get("extend_part", len(parts) - 1)

        labels, chains = [], []
        for j, p in enumerate(parts):
            a, b = p["window"]
            speed = p.get("speed", 1)
            flt = f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed}"
            zoom = p.get("zoom")
            if zoom:
                zx, zy, zw, zh = zoom
                # Smooth eased zoom (smoothstep), not a hard cut. `zoom_mode`:
                #   in    — ease full→zoomed, hold zoomed (pair with freeze-extend,
                #           e.g. to hold on a streaming answer)
                #   out   — start zoomed, ease back to full (a reveal)
                #   inout — ease in, hold, ease out, within the part (default)
                dur = round((b - a) / speed, 3)
                ramp = round(min(0.7, max(0.25, dur / 2.2)), 3)
                mode = p.get("zoom_mode", "inout")
                # Smooth eased zoom via animated crop + scale. Reliable for `in`
                # (crop shrinks) and `hold` (constant). NOTE: a *growing* crop
                # (zoom-out / the grow-back half of `inout`) hits ffmpeg's "Error
                # reinitializing filters" — the link can't resize larger mid-stream
                # — so prefer in/hold; out/inout are best-effort.
                if mode == "in":
                    prog = f"min(t/{ramp},1)"
                elif mode == "out":
                    prog = f"max(0,1-t/{ramp})"
                elif mode == "hold":
                    prog = "1"
                else:
                    prog = f"max(0,min(t/{ramp},({dur}-t)/{ramp},1))"
                s = f"({prog}*{prog}*(3-2*{prog}))"  # smoothstep ease
                flt += (
                    f",crop=w='{SRCW}-({SRCW}-{zw})*{s}':h='{SRCH}-({SRCH}-{zh})*{s}'"
                    f":x='{zx}*{s}':y='{zy}*{s}',scale={SRCW}:{SRCH}"
                )
            # Normalise sample-aspect-ratio on every part: a recorded source can
            # carry a non-1:1 SAR while crop/scale resets it to 1:1, and concat
            # rejects mismatched SAR ("parameters do not match"). Pin all to 1:1.
            flt += ",setsar=1"
            if j == extend_at and extra > 0:
                flt += f",tpad=stop_mode=clone:stop_duration={extra:.3f}"
            chains.append(flt + f"[p{j}]")
            labels.append(f"[p{j}]")
        chains.append(f"{''.join(labels)}concat=n={len(parts)}:v=1:a=0[v]")

        seg_v = clips / f"seg_{i:02d}_v.mp4"
        run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", ";".join(chains),
             "-map", "[v]", "-r", str(fps), "-c:v", "libx264", "-preset", "fast",
             "-crf", "19", "-pix_fmt", "yuv420p", str(seg_v)])

        seg_f = clips / f"seg_{i:02d}.mp4"
        if text:
            af = (
                f"[1:a]aresample=48000,pan=mono|c0=c0,adelay={int(delay * 1000)},apad,"
                f"atrim=0:{target:.3f},afade=t=in:st=0:d=0.03,"
                f"afade=t=out:st={target - 0.03:.3f}:d=0.03[a]"
            )
            run(["ffmpeg", "-y", "-i", str(seg_v), "-i", str(a_path),
                 "-filter_complex", af, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(seg_f)])
        else:  # 无旁白段也垫静音,保证各段流布局一致可 -c copy 拼接
            run(["ffmpeg", "-y", "-i", str(seg_v),
                 "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                 "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", str(seg_f)])
        seg_files.append(seg_f)

        if text:
            cues.extend(split_cues(text, cursor + delay, n_dur))
        actual = probe_duration(seg_f)
        print(f"{seg['name']:20s} {visual:7.2f} {n_dur:6.2f} {target:7.2f} actual={actual:.2f}")
        cursor += actual  # 实际段长累计,防字幕漂移

    listing = out / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_files))
    base = out / "base.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(base)])

    (out / "master.srt").write_text(
        "\n".join(f"{n}\n{srt_ts(a)} --> {srt_ts(b)}\n{t}\n"
                  for n, (a, b, t) in enumerate(cues, 1)),
        encoding="utf-8",
    )

    final = out / "final.mp4"
    if cues and not args.no_subtitles:
        render_cue_pngs(cues, out / "cues")
        inputs, chains, cur = ["-i", str(base)], [], "[0:v]"
        for i, (a, b, _t) in enumerate(cues):
            inputs += ["-i", str(out / "cues" / f"cue_{i:03d}.png")]
            nxt = f"[v{i}]"
            chains.append(
                f"{cur}[{i + 1}:v]overlay=(W-w)/2:H-h-{SUB_MARGIN_V}:"
                f"enable='between(t,{a:.3f},{b:.3f})'{nxt}"
            )
            cur = nxt
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chains),
             "-map", cur, "-map", "0:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)])
    else:
        run(["ffmpeg", "-y", "-i", str(base), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(final)])

    got = probe_duration(final)
    drift = abs(got - cursor)
    print(f"\nfinal: {final} ({got:.2f}s, 预期 {cursor:.2f}s, 偏差 {drift:.2f}s)")
    if drift > 0.5:
        print("! 偏差超 0.5s,检查段编码参数是否一致", file=sys.stderr)


if __name__ == "__main__":
    main()
