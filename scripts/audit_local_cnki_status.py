"""Validate the durable status published by the local CNKI supplement."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "data" / "local_cnki_status.json"


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def inspect_status(path: Path, *, now: datetime | None = None, max_age_hours: float = 30.0) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "code": "missing_or_invalid", "message": str(exc)}

    if not isinstance(payload, dict):
        return {"ok": False, "code": "invalid_shape", "message": "status must be an object"}
    if payload.get("state") != "published" or payload.get("ok") is not True:
        return {
            "ok": False,
            "code": "not_published",
            "state": payload.get("state"),
            "message": payload.get("message", "local CNKI status is not published"),
        }

    source_health = {
        key: payload.get(key)
        for key in ("selected_sources", "successful_sources", "failed_sources")
        if key in payload
    }
    if source_health:
        selected = int(source_health.get("selected_sources") or 0)
        successful = int(source_health.get("successful_sources") or 0)
        failed = int(source_health.get("failed_sources") or 0)
        if selected <= 0 or failed != 0 or successful != selected:
            return {
                "ok": False,
                "code": "incomplete_source_health",
                "source_health": source_health,
            }

    timestamp = parse_timestamp(payload.get("last_success_at"))
    if timestamp is None:
        return {"ok": False, "code": "missing_success_timestamp", "message": "last_success_at is invalid"}

    age_hours = (now - timestamp).total_seconds() / 3600
    if age_hours < -1:
        return {"ok": False, "code": "future_timestamp", "age_hours": round(age_hours, 2)}
    if age_hours > max_age_hours:
        return {
            "ok": False,
            "code": "stale",
            "age_hours": round(age_hours, 2),
            "last_success_at": timestamp.isoformat(),
        }
    return {
        "ok": True,
        "code": "fresh",
        "age_hours": round(max(age_hours, 0), 2),
        "last_success_at": timestamp.isoformat(),
        "count": payload.get("count"),
        "source_health": source_health or None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local CNKI durable status freshness")
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--max-age-hours", type=float, default=30.0)
    args = parser.parse_args()
    result = inspect_status(args.status, max_age_hours=args.max_age_hours)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
