"""Move source-dated backfill out of the current-day archive.

Official publisher RSS feeds often contain a long back catalog. The first
monitor run after enabling a feed can therefore discover hundreds of old items.
Those are useful for enrichment, but they should not appear as today's papers.

RePEc NEP is also source-dated by issue. Newly discovered records should live
under the NEP issue date rather than the day our system first saw them.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, stable_id, today_str, write_json
from dedupe import merge_daily
from status import record_source


def valid_iso_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        return text
    return None


def source_archive_date(record: dict[str, Any]) -> str | None:
    source = str(record.get("source") or "")
    source_id = str(record.get("source_id") or "")
    if source != "rss" and not source_id.startswith("repec-nep-"):
        return None
    return valid_iso_date(record.get("available_online")) or valid_iso_date(record.get("published_online"))


def clean_date(daily_dir: Path, date_value: str) -> tuple[int, int, int]:
    path = daily_dir / f"{date_value}.json"
    records = read_json(path, [])
    kept: list[dict[str, Any]] = []
    moved_by_date: dict[str, list[dict[str, Any]]] = {}
    suppressed = 0

    for record in records:
        target_date = source_archive_date(record)
        if not target_date:
            if str(record.get("source") or "") == "rss":
                suppressed += 1
                continue
            kept.append(record)
            continue
        if target_date == date_value:
            kept.append(record)
        else:
            moved_by_date.setdefault(target_date, []).append(record)

    touched = 0
    moved = 0
    if len(kept) != len(records):
        write_json(path, kept)
        touched += 1

    for target_date, moved_records in sorted(moved_by_date.items()):
        target_path = daily_dir / f"{target_date}.json"
        existing = read_json(target_path, [])
        for record in moved_records:
            record["id"] = record.get("id") or stable_id(record)
        write_json(target_path, merge_daily(existing, moved_records))
        touched += 1
        moved += len(moved_records)

    return moved, suppressed, touched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    args = parser.parse_args()

    moved, suppressed, touched = clean_date(args.daily_dir, args.date)
    record_source(
        "clean-rss-backfill",
        ok=True,
        count=moved + suppressed,
        message=f"date={args.date} moved={moved} suppressed={suppressed} files={touched}",
    )
    print(f"rss backfill cleaned date={args.date} moved={moved} suppressed={suppressed} files={touched}")


if __name__ == "__main__":
    main()
