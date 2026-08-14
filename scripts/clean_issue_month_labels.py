"""Migrate month-level labels out of online-date fields.

Month labels such as ``March 2026`` (or truncated ``September ``) describe an
issue/volume, not an online date.  This script moves parseable labels into
``issue_date`` as ``YYYY-MM``, clears ``available_online``/``published_online``,
and marks the record as an issue-date record (confidence D).  Truncated labels
that cannot be resolved are removed from online fields and left as explicit
missing dates.

Data line only: reads/writes ``data/**``.  Idempotent.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, write_json


MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_TOKEN = "|".join(sorted(MONTH_NAMES))
MONTH_RE = re.compile(rf"^\s*({_MONTH_TOKEN})(?:\s+(\d{{1,4}}))?\s*$", re.IGNORECASE)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def month_label(value: Any) -> tuple[int, int | None] | None:
    """Return (month, year) for a month label, or None."""
    text = str(value or "").strip()
    match = MONTH_RE.match(text)
    if not match:
        return None
    month = MONTH_NAMES[match.group(1).casefold()]
    year_text = match.group(2)
    year = int(year_text) if year_text and len(year_text) == 4 else None
    return month, year


def normalize_month(value: Any) -> str | None:
    parsed = month_label(value)
    if not parsed:
        return None
    month, year = parsed
    if year is None:
        return None
    return f"{year:04d}-{month:02d}"


def is_month_label(value: Any) -> bool:
    return month_label(value) is not None


def clean_record(record: dict[str, Any]) -> bool:
    changed = False
    moved_to_issue = False
    for field in ("available_online", "published_online"):
        value = record.get(field)
        if not isinstance(value, str) or not is_month_label(value):
            continue
        normalized = normalize_month(value)
        if normalized:
            current_issue = record.get("issue_date")
            if not current_issue or is_month_label(current_issue):
                record["issue_date"] = normalized
                moved_to_issue = True
        record[field] = None
        changed = True

    issue = record.get("issue_date")
    if isinstance(issue, str) and is_month_label(issue):
        normalized = normalize_month(issue)
        if normalized:
            record["issue_date"] = normalized
            moved_to_issue = True
        else:
            record["issue_date"] = None
        changed = True

    if changed:
        has_online = any(record.get(field) for field in ("available_online", "published_online"))
        has_issue = bool(record.get("issue_date"))
        if has_online:
            # A real online date remains authoritative; do not downgrade it.
            pass
        elif moved_to_issue and has_issue:
            record["date_confidence"] = "D"
        elif not has_issue:
            record["date_confidence"] = "F"
    return changed


def clean_records(records: list[dict[str, Any]]) -> int:
    changed = 0
    for record in records:
        if isinstance(record, dict) and clean_record(record):
            changed += 1
    return changed


def clean_daily_and_seen(data_dir: Path, *, write: bool = True) -> dict[str, Any]:
    daily_dir = data_dir / "daily"
    changed_files: list[str] = []
    daily_changed = 0
    for path in sorted(daily_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        changed = clean_records(payload)
        if changed:
            if write:
                write_json(path, payload)
            changed_files.append(path.name)
            daily_changed += changed

    seen_path = data_dir / "seen.json"
    seen_payload = json.loads(seen_path.read_text(encoding="utf-8"))
    papers = seen_payload.get("papers") if isinstance(seen_payload, dict) else {}
    seen_records = [papers[key] for key in papers if isinstance(papers.get(key), dict)]
    seen_changed = clean_records(seen_records)
    if seen_changed and write:
        write_json(seen_path, seen_payload)

    return {
        "daily_files_changed": changed_files,
        "daily_records_changed": daily_changed,
        "seen_records_changed": seen_changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = clean_daily_and_seen(args.data_dir, write=not args.dry_run)
    output = args.data_dir / "issue_month_label_migration.json"
    if not args.dry_run:
        write_json(output, report)
    print(report)


if __name__ == "__main__":
    main()
