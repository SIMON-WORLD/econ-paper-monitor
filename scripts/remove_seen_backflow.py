"""Remove already-seen records that leaked back into today's discovery page."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json
from dedupe import build_seen_index, find_matching_seen_id, merge_daily
from status import record_source


def first_seen_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) >= 10 and text[:4].isdigit():
        return text[:10]
    return None


def detected_date(record: dict[str, Any], fallback: str) -> str:
    text = str(record.get("detected_at") or "")
    if len(text) >= 10 and text[:4].isdigit():
        return text[:10]
    return fallback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    args = parser.parse_args()

    daily_path = args.daily_dir / f"{args.date}.json"
    records = read_json(daily_path, [])
    if not isinstance(records, list):
        records = []

    seen = read_json(args.seen, {"papers": {}})
    seen_papers = seen.get("papers") if isinstance(seen, dict) else {}
    if not isinstance(seen_papers, dict):
        seen_papers = {}
    seen_index = build_seen_index(seen_papers)

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    restore_by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        seen_id = find_matching_seen_id(seen_index, record)
        seen_entry = seen_papers.get(seen_id) if seen_id else None
        first_date = first_seen_date((seen_entry or {}).get("first_seen"))
        # Only remove records whose canonical seen entry predates the current
        # daily page. This preserves true first discoveries and prevents RSS
        # re-publishes or TOC reshuffles from polluting "today".
        if first_date and first_date < args.date:
            restored = dict(record)
            if isinstance(seen_entry, dict):
                for key, value in seen_entry.items():
                    if key not in restored or restored.get(key) in (None, "", []):
                        restored[key] = value
            restored["_restored_from_backflow"] = args.date
            restore_by_date.setdefault(first_date, []).append(restored)
            removed.append(record)
            continue
        # Some historical records were inserted into seen without first_seen;
        # fall back to the record's own detected_at if it clearly predates today.
        fallback_date = detected_date(record, args.date)
        if fallback_date < args.date:
            restored = dict(record)
            restored["_restored_from_backflow"] = args.date
            restore_by_date.setdefault(fallback_date, []).append(restored)
            removed.append(record)
            continue
        kept.append(record)

    if removed:
        write_json(daily_path, kept)
    restored_count = 0
    for restore_date, restore_records in sorted(restore_by_date.items()):
        restore_path = args.daily_dir / f"{restore_date}.json"
        existing = read_json(restore_path, [])
        if not isinstance(existing, list):
            existing = []
        write_json(restore_path, merge_daily(existing, restore_records))
        restored_count += len(restore_records)
    record_source(
        "remove-seen-backflow",
        ok=True,
        count=len(removed),
        message=f"date={args.date} kept={len(kept)} removed={len(removed)} restored={restored_count}",
    )
    print(f"seen backflow cleaned date={args.date} kept={len(kept)} removed={len(removed)} restored={restored_count}")


if __name__ == "__main__":
    main()
