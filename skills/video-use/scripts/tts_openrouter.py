"""旁白 TTS:OpenRouter 语音模型(默认 openai/gpt-audio)→ 24kHz mono wav。

- key 解析顺序:`$OPENROUTER_API_KEY` → `~/.pikiloom/skills.env` 里的 OPENROUTER_API_KEY。
  脚本自身不写任何配置;缺 key 时报错并提示用 `--engine say` 本地兜底。
- chat 模型当 TTS 的坑:会自作主张加「好的,我来朗读」之类开场白。
  对策 = 录音棚系统提示词 + 转写逐字校验,不一致自动重试(≤2),仍失败则警告放行。
- `--engine say` 走 macOS 本地兜底(零 key,音质差,仅断网/无 key 应急)。

CLI:
    tts_openrouter.py --text "文案" --id intro --out-dir narration/
    tts_openrouter.py --json lines.json --out-dir narration/   # [{"id","text"},…]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-audio"  # 效果优先;省钱换 openai/gpt-audio-mini
DEFAULT_VOICE = "marin"
SAMPLE_RATE = 24000

SYSTEM_PROMPT = (
    "你是录音棚里的旁白配音引擎。用户消息就是待录文案。"
    "直接开始朗读文案本身,逐字、不增不减:不要任何开场白、确认语、结尾语,"
    "不要说『好的』『以下是』之类的话。语气自然克制,产品介绍旁白节奏。"
)

_PUNCT = re.compile(r"[\s,。:;、,.:;!?!?·…『』「」“”\"'()()\-—]")


def _norm(s: str) -> str:
    return _PUNCT.sub("", s).lower()


def _read_env_file_key(path: str, name: str) -> str:
    """Read NAME=value from a dotenv-style file; '' if missing/unreadable."""
    try:
        for line in open(path):
            s = line.strip()
            if s.startswith(f"{name}=") and not s.startswith("#"):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def resolve_openrouter_key() -> str:
    return (
        os.getenv("OPENROUTER_API_KEY", "")
        or _read_env_file_key(os.path.expanduser("~/.pikiloom/skills.env"), "OPENROUTER_API_KEY")
    )


def _stream_once(
    text: str, model: str, voice: str, api_key: str, system: str = SYSTEM_PROMPT
) -> tuple[bytes, str]:
    import requests

    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "modalities": ["text", "audio"],
            "audio": {"voice": voice, "format": "pcm16"},
            "stream": True,  # OpenRouter: audio output requires stream
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        },
        timeout=300,
        stream=True,
    )
    resp.raise_for_status()
    pcm = bytearray()
    transcript: list[str] = []
    for line in resp.iter_lines():
        if not line or not line.startswith(b"data: "):
            continue
        payload = line[6:]
        if payload == b"[DONE]":
            break
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for ch in ev.get("choices", []):
            au = (ch.get("delta") or {}).get("audio") or {}
            if au.get("data"):
                pcm += base64.b64decode(au["data"])
            if au.get("transcript"):
                transcript.append(au["transcript"])
    return bytes(pcm), "".join(transcript)


RETRY_ADDENDUM = (
    "注意:上一次你没有逐字朗读,这是错误的。文案是给你『读』的,不是给你『回应/扩写』的。"
    "重来:只朗读文案本身的每一个字,一个字都不要加,读完最后一个字立即停止。"
)
MIN_SIMILARITY = 0.85  # 逐字闸:低于此相似度宁可失败也不出错音(字幕=文案,音文必须一致)


def _similarity(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def synth_openrouter(
    text: str, dest: Path, model: str = DEFAULT_MODEL, voice: str = DEFAULT_VOICE,
    retries: int = 2,
) -> None:
    api_key = resolve_openrouter_key()
    if not api_key:
        sys.exit(
            "OPENROUTER_API_KEY not found — set it in your shell env or add it to "
            "~/.pikiloom/skills.env, or use --engine say for the macOS zero-key fallback."
        )
    best: tuple[float, bytes, str] | None = None  # (相似度, pcm, transcript)
    system = SYSTEM_PROMPT
    for attempt in range(retries + 1):
        pcm, transcript = _stream_once(text, model, voice, api_key, system)
        if not pcm:
            raise RuntimeError(f"no audio returned (transcript={transcript[:80]!r})")
        sim = _similarity(transcript, text)
        if best is None or sim > best[0]:
            best = (sim, pcm, transcript)
        if _norm(transcript) == _norm(text):
            break
        print(f"  ! 非逐字(attempt {attempt + 1}, sim={sim:.2f}): "
              f"{transcript[:60]!r} → 升级重试", file=sys.stderr)
        system = SYSTEM_PROMPT + RETRY_ADDENDUM  # 重试用更硬的指令
    sim, pcm, transcript = best
    if sim < MIN_SIMILARITY:
        raise RuntimeError(
            f"TTS 始终不逐字(最优相似度 {sim:.2f} < {MIN_SIMILARITY}),拒绝出错音。"
            f"换个说法重写这句文案(过短的句子最易触发自由发挥):{text!r} → {transcript[:80]!r}"
        )
    if sim < 1.0 and _norm(transcript) != _norm(text):
        print(f"  ! 取最优尝试(sim={sim:.2f}),人工抽听: {transcript[:80]!r}", file=sys.stderr)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


def synth_say(text: str, dest: Path, voice: str = "Tingting") -> None:
    aiff = dest.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(aiff),
         "-ac", "1", "-ar", str(SAMPLE_RATE), str(dest)],
        check=True,
    )
    aiff.unlink(missing_ok=True)


def synth_line(
    text: str, dest: Path, engine: str = "openrouter",
    model: str = DEFAULT_MODEL, voice: str | None = None,
) -> float:
    """合成一句 → dest(wav),返回时长秒。供 compose_narrated.py import。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if engine == "say":
        synth_say(text, dest, voice or "Tingting")
    else:
        synth_openrouter(text, dest, model, voice or DEFAULT_VOICE)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(dest)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenRouter TTS → wav")
    ap.add_argument("--text")
    ap.add_argument("--id", default="line")
    ap.add_argument("--json", dest="json_path", help='[{"id","text"},…] 或 {"lines":[…]}')
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--engine", choices=["openrouter", "say"], default="openrouter")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--voice", default=None)
    args = ap.parse_args()

    if bool(args.text) == bool(args.json_path):
        ap.error("--text 与 --json 二选一")
    lines = (
        [{"id": args.id, "text": args.text}]
        if args.text
        else (lambda d: d.get("lines", d))(json.loads(Path(args.json_path).read_text()))
    )
    out_dir = Path(args.out_dir)
    for item in lines:
        dest = out_dir / f"{item['id']}.wav"
        dur = synth_line(item["text"], dest, args.engine, args.model, args.voice)
        print(f"{item['id']:24s} {dur:6.2f}s  {dest}")


if __name__ == "__main__":
    main()
