"""Summarize raw candidates versus public daily records for troubleshooting."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json
from dedupe import archive_date_for_new_record, record_match_keys
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


def record_label(record: dict[str, Any]) -> str:
    title = str(record.get("title") or record.get("paper_title") or "untitled").strip()
    source = str(record.get("journal") or record.get("source_id") or record.get("source") or "").strip()
    return f"{source}: {title}" if source else title


def load_seen_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, {"papers": {}})
    if isinstance(payload, dict):
        papers = payload.get("papers")
        if isinstance(papers, dict):
            return [item for item in papers.values() if isinstance(item, dict)]
        return [item for item in payload.values() if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def key_set(records: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for record in records:
        keys.update(record_match_keys(record))
    return keys


def intersects(keys: set[str], universe: set[str]) -> bool:
    return bool(keys and keys.intersection(universe))


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
    seen_records = load_seen_records(DATA_DIR / "seen.json")
    seen_keys = key_set(seen_records)
    daily_keys = key_set(daily_records)
    already_seen = []
    new_today_candidates = []
    new_other_date_candidates = []
    suppressed_candidates = []
    missing_new_today = []
    for record in raw_records:
        keys = record_match_keys(record)
        if intersects(keys, seen_keys):
            already_seen.append(record)
            continue
        archive_date = archive_date_for_new_record(record, args.date)
        if not archive_date:
            suppressed_candidates.append(record)
            continue
        if archive_date != args.date:
            new_other_date_candidates.append(record)
            continue
        new_today_candidates.append(record)
        if not intersects(keys, daily_keys):
            missing_new_today.append(record)

    missed_by_source: dict[str, dict[str, Any]] = {}
    for record in missing_new_today:
        name = str(record.get("journal") or record.get("source_id") or source_key(record) or "unknown")
        item = missed_by_source.setdefault(
            name,
            {
                "source": name,
                "new_candidate_count": 0,
                "daily_count": daily_by_journal.get(name, 0),
                "examples": [],
                "reason": "new DOI/title candidates look eligible for today's archive but were not found in the public daily file",
            },
        )
        item["new_candidate_count"] += 1
        if len(item["examples"]) < 3:
            item["examples"].append(record_label(record))
    suspected_missed = sorted(missed_by_source.values(), key=lambda item: item["new_candidate_count"], reverse=True)[:20]
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
        "already_seen_candidates": len(already_seen),
        "new_candidates": len(raw_records) - len(already_seen),
        "new_today_candidates": len(new_today_candidates),
        "new_other_date_candidates": len(new_other_date_candidates),
        "suppressed_candidates": len(suppressed_candidates),
        "new_today_missing_candidates": len(missing_new_today),
        "suspected_missed_sources": suspected_missed,
        "seen_backflow_removed": int(backflow_status.get("count") or 0),
        "seen_backflow_message": backflow_status.get("message") or "",
    }
    write_json(args.output, report)
    message = (
        f"raw={len(raw_records)} daily={len(daily_records)} "
        f"new_today={len(new_today_candidates)} missed={len(missing_new_today)} "
        f"seen={len(already_seen)} suppressed={len(suppressed_candidates)}"
    )
    record_source("ingestion-audit", ok=True, count=len(raw_records), message=message)
    print(message)


if __name__ == "__main__":
    main()
