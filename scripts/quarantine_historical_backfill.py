"""Keep verified historical backfill out of today's public discovery flow."""

from __future__ import annotations

import argparse
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, stable_id, today_str, write_json
from dedupe import merge_daily
from status import record_source


def valid_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text) else None


def verified_official_date(record: dict[str, Any]) -> str | None:
    if str(record.get("date_confidence") or "").upper() not in {"A", "B"}:
        return None
    return valid_date(record.get("available_online")) or valid_date(record.get("published_online"))


def should_quarantine(record: dict[str, Any], run_date: str, max_age_days: int) -> bool:
    official = verified_official_date(record)
    if not official:
        return False
    try:
        return date.fromisoformat(official) < date.fromisoformat(run_date) - timedelta(days=max_age_days)
    except ValueError:
        return False


def cepr_number(record: dict[str, Any]) -> int | None:
    if str(record.get("source_id") or "") != "cepr-dp":
        return None
    match = re.search(r"\bDP\s*(\d+)\b", str(record.get("paper_number") or record.get("url") or ""), flags=re.I)
    return int(match.group(1)) if match else None


def quarantine_date(daily_dir: Path, run_date: str, max_age_days: int = 30) -> tuple[int, int]:
    source_path = daily_dir / f"{run_date}.json"
    payload = read_json(source_path, [])
    if not isinstance(payload, list):
        return 0, 0
    kept: list[dict[str, Any]] = []
    moved_by_date: dict[str, list[dict[str, Any]]] = {}
    pending: list[dict[str, Any]] = []
    cepr_numbers = [number for record in payload if isinstance(record, dict) if (number := cepr_number(record))]
    newest_cepr_number = max(cepr_numbers, default=0)
    for record in payload:
        if not isinstance(record, dict):
            kept.append(record)
            continue
        number = cepr_number(record)
        stale_cepr_catalogue_item = bool(
            number
            and newest_cepr_number
            and number < newest_cepr_number - 200
            and not verified_official_date(record)
        )
        if stale_cepr_catalogue_item:
            record["id"] = record.get("id") or stable_id(record)
            record["historical_backfill"] = True
            record["historical_backfill_detected_on"] = run_date
            record["public_flow_excluded"] = True
            record["historical_backfill_status"] = "pending_official_date"
            pending.append(record)
            continue
        if not should_quarantine(record, run_date, max_age_days):
            kept.append(record)
            continue
        official = verified_official_date(record)
        if not official:
            kept.append(record)
            continue
        record["id"] = record.get("id") or stable_id(record)
        record["historical_backfill"] = True
        record["historical_backfill_detected_on"] = run_date
        record["public_flow_excluded"] = True
        moved_by_date.setdefault(official, []).append(record)

    if not moved_by_date and not pending:
        return 0, 0
    write_json(source_path, kept)
    for target_date, records in moved_by_date.items():
        target_path = daily_dir / f"{target_date}.json"
        existing = read_json(target_path, [])
        write_json(target_path, merge_daily(existing if isinstance(existing, list) else [], records))
    if pending:
        pending_path = daily_dir.parent / "historical_backfill_pending.json"
        existing_pending = read_json(pending_path, [])
        write_json(pending_path, merge_daily(existing_pending if isinstance(existing_pending, list) else [], pending))
    moved = sum(len(records) for records in moved_by_date.values()) + len(pending)
    touched = len(moved_by_date) + 1 + int(bool(pending))
    return moved, touched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--latest-days", type=int, default=3)
    args = parser.parse_args()
    anchor = date.fromisoformat(args.date)
    moved = touched = 0
    for offset in range(max(1, args.latest_days)):
        run_date = (anchor - timedelta(days=offset)).isoformat()
        date_moved, date_touched = quarantine_date(args.daily_dir, run_date, args.max_age_days)
        moved += date_moved
        touched += date_touched
    record_source(
        "historical-backfill-quarantine",
        ok=True,
        count=moved,
        message=(
            f"date={args.date}; latest_days={max(1, args.latest_days)}; "
            f"moved={moved}; files={touched}; max_age_days={args.max_age_days}"
        ),
    )
    print(f"historical backfill quarantine: moved={moved} files={touched}")


if __name__ == "__main__":
    main()
