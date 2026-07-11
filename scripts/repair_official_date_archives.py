"""Move already-archived publisher records to their official date."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, stable_id, today_str, write_json
from dedupe import merge_daily


def valid_iso_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text) else None


def archive_date(record: dict[str, Any], run_date: str) -> str | None:
    """Use the best known publisher date, never the fetch date by default."""
    official_date = valid_iso_date(record.get("available_online")) or valid_iso_date(record.get("published_online"))
    if official_date:
        return official_date if official_date <= run_date else None
    issue_date = valid_iso_date(record.get("issue_date"))
    if issue_date:
        return issue_date if issue_date <= run_date else None
    return None


def target_date(record: dict[str, Any], run_date: str) -> str | None:
    if str(record.get("source") or "") not in {"crossref", "priority_toc", "aea_toc"}:
        return None
    return archive_date(record, run_date)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--max-files", type=int, default=0)
    args = parser.parse_args()

    files = sorted(args.daily_dir.glob("*.json"))
    if args.max_files:
        files = files[-args.max_files:]
    moved_by_date: dict[str, list[dict[str, Any]]] = {}
    future_records: list[dict[str, Any]] = []
    changed_files: set[Path] = set()
    moved = 0
    run_date = today_str()

    for path in files:
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        kept: list[dict[str, Any]] = []
        for record in payload:
            if isinstance(record, dict):
                destination = archive_date(record, run_date)
                if destination is None and (
                    valid_iso_date(record.get("available_online"))
                    or valid_iso_date(record.get("published_online"))
                    or valid_iso_date(record.get("issue_date"))
                ):
                    future_records.append(record)
                    moved += 1
                    changed_files.add(path)
                    continue
            destination = target_date(record, run_date) if isinstance(record, dict) else None
            if not destination or destination == path.stem:
                kept.append(record)
                continue
            record["id"] = record.get("id") or stable_id(record)
            moved_by_date.setdefault(destination, []).append(record)
            moved += 1
            changed_files.add(path)
        if len(kept) != len(payload):
            write_json(path, kept)

    for destination, records in moved_by_date.items():
        path = args.daily_dir / f"{destination}.json"
        existing = read_json(path, [])
        write_json(path, merge_daily(existing if isinstance(existing, list) else [], records))
        changed_files.add(path)

    if future_records:
        future_path = DATA_DIR / "future_records.json"
        existing_future = read_json(future_path, [])
        existing_future = existing_future if isinstance(existing_future, list) else []
        write_json(future_path, merge_daily(existing_future, future_records))

    print(f"official-date archive repair: moved={moved} files={len(changed_files)}")


if __name__ == "__main__":
    main()
