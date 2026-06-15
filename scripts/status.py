"""Lightweight run status helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, write_json


STATUS_PATH = DATA_DIR / "status.json"


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_status(path: Path = STATUS_PATH) -> dict[str, Any]:
    return read_json(path, {"runs": [], "sources": {}})


def save_status(status: dict[str, Any], path: Path = STATUS_PATH) -> None:
    write_json(path, status)


def record_source(
    source_id: str,
    *,
    ok: bool,
    count: int = 0,
    message: str = "",
    path: Path = STATUS_PATH,
) -> None:
    status = load_status(path)
    status.setdefault("sources", {})[source_id] = {
        "ok": ok,
        "count": count,
        "message": message,
        "updated_at": now(),
    }
    save_status(status, path)


def record_run(summary: dict[str, Any], path: Path = STATUS_PATH) -> None:
    status = load_status(path)
    runs = status.setdefault("runs", [])
    runs.insert(0, {"updated_at": now(), **summary})
    del runs[20:]
    save_status(status, path)
