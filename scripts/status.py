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


def record_workflow_run(summary: dict[str, Any], path: Path = STATUS_PATH) -> None:
    """Store the latest end-to-end workflow context for dashboards."""
    status = load_status(path)
    workflow = status.setdefault("workflow", {})
    workflow.update(summary)
    workflow.setdefault("updated_at", now())
    mode = summary.get("mode")
    finished_at = summary.get("finished_at") or workflow["updated_at"]
    if mode == "full":
        workflow["last_full_finished_at"] = finished_at
    elif mode == "light":
        workflow["last_light_finished_at"] = finished_at
    elif mode == "single":
        workflow["last_single_finished_at"] = finished_at
    save_status(status, path)
