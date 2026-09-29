"""On-disk cache / archive helpers shared by the alternative-data gateways
(sec_ftd, hiring_lab, app_charts). Everything lives under
<MARKETMIND_DATA_DIR>/altdata/<source>/ and is written atomically (temp file +
os.replace, retried while a reader holds the target open on Windows).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def altdata_dir(source: str, data_dir: Path | str | None = None) -> Path:
    root = Path(data_dir) if data_dir is not None else Path(os.getenv("MARKETMIND_DATA_DIR", "data"))
    return root / "altdata" / source


def _replace(tmp: Path, target: Path) -> None:
    for attempt in range(10):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    _replace(tmp, path)


def write_json_atomic(path: Path, doc) -> None:
    write_bytes_atomic(path, json.dumps(doc, ensure_ascii=False, indent=1, default=str)
                       .encode("utf-8"))


def is_fresh(path: Path, max_age_s: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime < max_age_s
    except OSError:
        return False
