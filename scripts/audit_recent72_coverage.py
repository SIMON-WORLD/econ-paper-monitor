"""Audit raw candidates against public records for the recent 72-hour view."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from audit_ingestion import key_set, load_json_records, load_seen_records, raw_records_for_date, record_label, source_key
from common import BEIJING_TZ, DATA_DIR, read_json, today_str, write_json
from dedupe import archive_date_for_new_record, record_match_keys
from status import record_source


def recent_dates(days: int) -> list[str]:
    from datetime import datetime

    today = datetime.strptime(today_str(), "%Y-%m-%d").replace(tzinfo=BEIJING_TZ)
    return [(today - timedelta(days=offset)).date().isoformat() for offset in range(days)]


def daily_records_for_dates(daily_dir: Path, dates: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for date_value in dates:
        for record in load_json_records(daily_dir / f"{date_value}.json"):
            item = dict(record)
            item["_daily_date"] = date_value
            records.append(item)
    return records


def count_by_source(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(source_key(record) for record in records).most_common())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "recent72_coverage_audit.json")
    args = parser.parse_args()

    dates = recent_dates(args.days)
    raw_records: list[dict[str, Any]] = []
    for date_value in dates:
        for record in raw_records_for_date(args.raw_dir, date_value):
            record["_raw_date"] = date_value
            raw_records.append(record)
    daily_records = daily_records_for_dates(args.daily_dir, dates)
    daily_keys = key_set(daily_records)
    seen_keys = key_set(load_seen_records(DATA_DIR / "seen.json"))

    already_seen: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []
    eligible_missing: list[dict[str, Any]] = []
    other_archive_date: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []

    for record in raw_records:
        keys = record_match_keys(record)
        if keys and keys.intersection(daily_keys):
            covered.append(record)
            continue
        if keys and keys.intersection(seen_keys):
            already_seen.append(record)
            continue
        raw_date = str(record.get("_raw_date") or dates[0])
        archive_date = archive_date_for_new_record(record, raw_date)
        if not archive_date:
            suppressed.append(record)
            continue
        if archive_date not in dates:
            other_archive_date.append(record)
            continue
        eligible_missing.append(record)

    missing_by_source: dict[str, dict[str, Any]] = {}
    for record in eligible_missing:
        name = str(record.get("journal") or record.get("source_id") or source_key(record) or "unknown")
        row = missing_by_source.setdefault(
            name,
            {
                "source": name,
                "count": 0,
                "examples": [],
                "reason": "raw candidate was not seen before and should belong to the recent 72-hour window, but is absent from public daily files",
            },
        )
        row["count"] += 1
        if len(row["examples"]) < 5:
            row["examples"].append(record_label(record))

    report = {
        "dates": dates,
        "raw_candidates": len(raw_records),
        "daily_records": len(daily_records),
        "covered_candidates": len(covered),
        "already_seen_candidates": len(already_seen),
        "other_archive_date_candidates": len(other_archive_date),
        "suppressed_candidates": len(suppressed),
        "eligible_missing_candidates": len(eligible_missing),
        "raw_by_source": count_by_source(raw_records),
        "daily_by_source": count_by_source(daily_records),
        "missing_by_source": sorted(missing_by_source.values(), key=lambda item: item["count"], reverse=True)[:20],
    }
    write_json(args.output, report)
    message = (
        f"dates={','.join(dates)} raw={len(raw_records)} daily={len(daily_records)} "
        f"covered={len(covered)} seen={len(already_seen)} missing={len(eligible_missing)}"
    )
    record_source("recent72-coverage-audit", ok=not eligible_missing, count=len(eligible_missing), message=message)
    print(message)


if __name__ == "__main__":
    main()
