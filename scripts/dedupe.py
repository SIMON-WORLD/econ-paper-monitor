"""Deduplicate raw fetched records and write daily new-paper archives."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, stable_id, today_str, write_json
from status import record_run, record_source


ENRICH_FIELDS = [
    "title_zh",
    "abstract",
    "abstract_zh",
    "authors",
    "publisher",
    "published_online",
    "available_online",
    "accepted_date",
    "issue_date",
    "source_issue",
    "date_source",
    "date_confidence",
    "doi",
    "url",
    "pdf_url",
]

DATE_SOURCE_RANK = {
    None: 0,
    "": 0,
    "issue_only": 1,
    "file_upload_date": 2,
    "crossref_published": 2,
    "crossref_created": 2,
    "crossref_issue": 2,
    "crossref_published_online": 3,
    "publisher_meta": 4,
    "publisher_published_online": 4,
    "publisher_available_online": 4,
    "publisher_accepted_date": 4,
    "official_publish_date": 3,
    "rss_published": 4,
}


def iter_raw_records(raw_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not raw_dir.exists():
        return records
    for path in sorted(raw_dir.rglob("*.json")):
        payload = read_json(path, [])
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    item["_raw_file"] = str(path)
                    records.append(item)
    return records


def merge_daily(existing: list[dict[str, Any]], new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in existing + new_records:
        record_id = record.get("id") or stable_id(record)
        record["id"] = record_id
        merged[record_id] = record
    return sorted(
        merged.values(),
        key=lambda item: (item.get("published_online") or "", item.get("detected_at") or ""),
        reverse=True,
    )


def has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def enrich_record(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    changed = False
    incoming_date_source = incoming.get("date_source")
    existing_date_source = existing.get("date_source")
    if has_value(incoming.get("published_online")) and (
        not has_value(existing.get("published_online"))
        or DATE_SOURCE_RANK.get(incoming_date_source, 1) > DATE_SOURCE_RANK.get(existing_date_source, 1)
        or incoming_date_source == existing_date_source
    ):
        if existing.get("published_online") != incoming.get("published_online"):
            existing["published_online"] = incoming["published_online"]
            changed = True
        if incoming_date_source and existing.get("date_source") != incoming_date_source:
            existing["date_source"] = incoming_date_source
            changed = True
    for field in ENRICH_FIELDS:
        if not has_value(existing.get(field)) and has_value(incoming.get(field)):
            existing[field] = incoming[field]
            changed = True
    if existing.get("translation_status") in {None, "missing_abstract"} and incoming.get("translation_status") == "native_chinese":
        existing["translation_status"] = incoming["translation_status"]
        changed = True
    return changed


def enrich_existing_daily(daily_dir: Path, record: dict[str, Any]) -> bool:
    record_id = stable_id(record)
    changed = False
    for path in daily_dir.glob("*.json"):
        records = read_json(path, [])
        path_changed = False
        for existing in records:
            if (existing.get("id") or stable_id(existing)) == record_id:
                if enrich_record(existing, record):
                    path_changed = True
                    changed = True
        if path_changed:
            write_json(path, records)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    args = parser.parse_args()

    seen = read_json(args.seen, {"papers": {}})
    seen_papers = seen.setdefault("papers", {})
    new_records: list[dict[str, Any]] = []
    enriched = 0

    for record in iter_raw_records(args.raw_dir):
        record_id = stable_id(record)
        record["id"] = record_id
        if record_id in seen_papers:
            seen_entry = seen_papers[record_id]
            if enrich_record(seen_entry, record):
                enriched += 1
            if enrich_existing_daily(args.daily_dir, record):
                enriched += 1
            continue
        seen_papers[record_id] = {
            "title": record.get("title"),
            "journal": record.get("journal"),
            "doi": record.get("doi"),
            "url": record.get("url"),
            "first_seen": record.get("detected_at"),
        }
        enrich_record(seen_papers[record_id], record)
        record.pop("_raw_file", None)
        new_records.append(record)

    daily_path = args.daily_dir / f"{args.date}.json"
    existing_daily = read_json(daily_path, [])
    daily_records = merge_daily(existing_daily, new_records)

    write_json(args.seen, seen)
    write_json(daily_path, daily_records)
    record_source("dedupe", ok=True, count=len(new_records), message=f"daily_total={len(daily_records)} seen={len(seen_papers)} enriched={enriched}")
    record_run({"new": len(new_records), "daily_total": len(daily_records), "seen": len(seen_papers), "enriched": enriched})
    print(f"new={len(new_records)} daily_total={len(daily_records)} seen={len(seen_papers)} enriched={enriched}")


if __name__ == "__main__":
    main()
