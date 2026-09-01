"""Audit ingestion coverage against the formal journal list.

This report is deliberately journal-scoped. It distinguishes a source that
returned no records from a journal that returned candidates which failed to
reach the public daily archive.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import DATA_DIR, load_journals, read_json, today_str, write_json
from dedupe import archive_date_for_new_record, covered_by_derived_doi, is_source_navigation_noise, record_match_keys
from status import record_source


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, [])
    if isinstance(payload, dict):
        papers = payload.get("papers")
        if isinstance(papers, dict):
            return [dict(item) for item in papers.values() if isinstance(item, dict)]
    return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def record_matches_journal(record: dict[str, Any], journal: dict[str, Any]) -> bool:
    journal_id = str(journal.get("id") or "")
    title = str(journal.get("title") or "").strip().casefold()
    aliases = {title, *(str(value).strip().casefold() for value in journal.get("aliases") or [])}
    return str(record.get("journal_id") or "") == journal_id or str(record.get("journal") or "").strip().casefold() in aliases


def source_status(source_registry: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    entry = (source_registry.get("journals") or {}).get(str(journal.get("id") or ""), {})
    return {
        "status": entry.get("status"),
        "rss_status": entry.get("last_rss_status"),
        "rss_count": entry.get("last_rss_count"),
        "crossref_status": entry.get("last_crossref_status"),
        "crossref_count": entry.get("last_crossref_count"),
        "checked_at": entry.get("last_checked_at"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "formal_journal_audit.json")
    args = parser.parse_args()

    target = date.fromisoformat(args.date)
    dates = [(target - timedelta(days=offset)).isoformat() for offset in range(3)]
    raw_by_date = {day: [record for path in sorted(args.raw_dir.rglob(f"{day}*.json")) if not path.name.endswith(".status.json") for record in load_records(path)] for day in dates}
    daily_by_date = {day: load_records(args.daily_dir / f"{day}.json") for day in dates}
    seen = load_records(DATA_DIR / "seen.json")
    seen_keys = set().union(*(record_match_keys(record) for record in seen))
    registry = read_json(DATA_DIR / "source_registry.json", {})
    rows: list[dict[str, Any]] = []
    suspected: list[dict[str, Any]] = []

    for journal in load_journals(DATA_DIR / "journals.yml"):
        raw_recent = [record for day in dates for record in raw_by_date[day] if record_matches_journal(record, journal)]
        raw_today = [record for record in raw_by_date[args.date] if record_matches_journal(record, journal)]
        daily_recent = [record for day in dates for record in daily_by_date[day] if record_matches_journal(record, journal)]
        daily_today = [record for record in daily_by_date[args.date] if record_matches_journal(record, journal)]
        daily_keys = set().union(*(record_match_keys(record) for record in daily_today))
        missing: list[dict[str, Any]] = []
        for record in raw_today:
            if is_source_navigation_noise(record) or set(record_match_keys(record)) & seen_keys:
                continue
            if (
                archive_date_for_new_record(record, args.date) == args.date
                and not set(record_match_keys(record)) & daily_keys
                and not covered_by_derived_doi(record, daily_today)
            ):
                missing.append({"title": record.get("title"), "doi": record.get("doi"), "url": record.get("url")})

        row = {
            "journal_id": journal.get("id"),
            "journal": journal.get("title"),
            "priority": journal.get("priority_private"),
            "raw_today": len(raw_today),
            "raw_recent72": len(raw_recent),
            "daily_today": len(daily_today),
            "daily_recent72": len(daily_recent),
            "missing_today": len(missing),
            "missing_examples": missing[:5],
            "source": source_status(registry, journal),
        }
        rows.append(row)
        if missing:
            suspected.append(row)

    report = {
        "date": args.date,
        "window_days": 3,
        "formal_journals": len(rows),
        "journals_with_raw_today": sum(row["raw_today"] > 0 for row in rows),
        "journals_with_daily_today": sum(row["daily_today"] > 0 for row in rows),
        "suspected_missed_journals": len(suspected),
        "suspected_missed": suspected,
        "journals": rows,
    }
    write_json(args.output, report)
    message = f"formal={len(rows)} raw_today={report['journals_with_raw_today']} daily_today={report['journals_with_daily_today']} missed={len(suspected)}"
    record_source("formal-journal-audit", ok=not suspected, count=len(rows), message=message)
    print(message)


if __name__ == "__main__":
    main()
