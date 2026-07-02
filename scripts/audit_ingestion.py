"""Summarize raw candidates versus public daily records for troubleshooting."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json
from status import load_status, record_source


def load_json_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def raw_records_for_date(raw_dir: Path, date_value: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not raw_dir.exists():
        return records
    for path in sorted(raw_dir.rglob(f"{date_value}*.json")):
        if path.name.endswith(".status.json"):
            continue
        for record in load_json_records(path):
            record = dict(record)
            record["_raw_file"] = str(path)
            records.append(record)
    return records


def source_key(record: dict[str, Any]) -> str:
    source = str(record.get("source") or "")
    source_id = str(record.get("source_id") or "")
    if source == "working_papers" or source_id.startswith("source-") or source_id.startswith("repec-nep-"):
        return "working_papers"
    if source in {"rss", "crossref", "cnki-rss"}:
        return source
    if source == "cn-official" or str(record.get("journal_id") or "").startswith("journal-"):
        return "cn_journals"
    return source or "unknown"


def has_precise_date(record: dict[str, Any]) -> bool:
    return bool(record.get("available_online") or record.get("published_online") or record.get("accepted_date"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "ingestion_audit.json")
    args = parser.parse_args()

    raw_records = raw_records_for_date(args.raw_dir, args.date)
    daily_records = load_json_records(args.daily_dir / f"{args.date}.json")
    raw_by_source = Counter(source_key(record) for record in raw_records)
    daily_by_source = Counter(source_key(record) for record in daily_records)
    raw_by_journal = Counter(str(record.get("journal") or record.get("source_id") or "unknown") for record in raw_records)
    daily_by_journal = Counter(str(record.get("journal") or record.get("source_id") or "unknown") for record in daily_records)
    rss_no_precise_date = [record for record in raw_records if source_key(record) == "rss" and not has_precise_date(record)]
    daily_no_precise_date = [record for record in daily_records if source_key(record) == "rss" and not has_precise_date(record)]
    suspected_missed = []
    for name, raw_count in raw_by_journal.most_common():
        if raw_count > 0 and daily_by_journal.get(name, 0) == 0:
            suspected_missed.append(
                {
                    "source": name,
                    "raw_count": raw_count,
                    "daily_count": 0,
                    "reason": "raw candidates present but no same-source record reached today's public archive",
                }
            )
        if len(suspected_missed) >= 20:
            break
    status = load_status()
    backflow_status = ((status.get("sources") or {}).get("remove-seen-backflow") or {}) if isinstance(status, dict) else {}

    report = {
        "date": args.date,
        "raw_candidates": len(raw_records),
        "daily_records": len(daily_records),
        "raw_by_source": dict(raw_by_source.most_common()),
        "daily_by_source": dict(daily_by_source.most_common()),
        "raw_by_journal_top": dict(raw_by_journal.most_common(30)),
        "daily_by_journal_top": dict(daily_by_journal.most_common(30)),
        "rss_without_precise_date_candidates": len(rss_no_precise_date),
        "rss_without_precise_date_daily": len(daily_no_precise_date),
        "suspected_missed_sources": suspected_missed,
        "seen_backflow_removed": int(backflow_status.get("count") or 0),
        "seen_backflow_message": backflow_status.get("message") or "",
    }
    write_json(args.output, report)
    message = (
        f"raw={len(raw_records)} daily={len(daily_records)} "
        f"rss_no_precise_date={len(rss_no_precise_date)}"
    )
    record_source("ingestion-audit", ok=True, count=len(raw_records), message=message)
    print(message)


if __name__ == "__main__":
    main()
