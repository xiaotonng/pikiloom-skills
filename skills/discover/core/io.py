"""Run-scoped artifact IO — atomic writes, JSONL helpers, run discovery.

Adapted from an internal discover pipeline's run IO and generalized: the data root is
configurable (``DISCOVER_DATA_DIR`` env, else ``./data/discover``) instead of
hard-wired to a project tree.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .schemas import RunPaths


def data_dir() -> Path:
    return Path(os.environ.get("DISCOVER_DATA_DIR", "data/discover")).expanduser()


def build_run_id(prefix: str = "discover") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def build_run_paths(run_id: str, *, base: Path | None = None) -> RunPaths:
    run_dir = (base or data_dir()) / run_id
    return RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        items_raw=run_dir / "items_raw.jsonl",
        scored=run_dir / "scored.jsonl",
        outputs=run_dir / "outputs.jsonl",
        report=run_dir / "report.md",
        meta=run_dir / "meta.json",
        usage=run_dir / "usage.json",
    )


def ensure_run_dir(paths: RunPaths) -> None:
    paths.run_dir.mkdir(parents=True, exist_ok=True)


def write_json_atomic(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_jsonl_atomic(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def list_runs(*, base: Path | None = None) -> list[Path]:
    root = base or data_dir()
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir()])


def find_latest_run(*, base: Path | None = None) -> Path | None:
    runs = list_runs(base=base)
    return runs[-1] if runs else None
