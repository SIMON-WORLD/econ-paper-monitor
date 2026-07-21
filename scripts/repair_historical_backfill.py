"""Resolve quarantined historical records and file them by official date."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, stable_id, write_json
from dedupe import merge_daily
from fetch_preprints import enrich_record_from_detail, load_sources
from normalize_records import normalize_record
from quarantine_historical_backfill import verified_official_date
from status import record_source


def repair_pending(
    pending_path: Path,
    daily_dir: Path,
    source: dict[str, Any],
    *,
    limit: int = 20,
    workers: int = 4,
    timeout: int = 15,
) -> tuple[int, int]:
    payload = read_json(pending_path, [])
    if not isinstance(payload, list):
        return 0, 0
    selected = [record for record in payload if isinstance(record, dict) and record.get("source_id") == "cepr-dp"][: max(0, limit)]
    selected_ids = {id(record) for record in selected}

    def enrich(record: dict[str, Any]) -> dict[str, Any]:
        enrich_record_from_detail(record, source, timeout=timeout)
        normalize_record(record)
        return record

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        list(executor.map(enrich, selected))

    moved_by_date: dict[str, list[dict[str, Any]]] = {}
    kept: list[dict[str, Any]] = [
        record for record in payload if not isinstance(record, dict) or id(record) not in selected_ids
    ]
    unresolved: list[dict[str, Any]] = []
    for record in payload:
        if not isinstance(record, dict) or id(record) not in selected_ids:
            continue
        official = verified_official_date(record)
        if not official:
            record["historical_backfill_attempts"] = int(record.get("historical_backfill_attempts") or 0) + 1
            unresolved.append(record)
            continue
        record["id"] = record.get("id") or stable_id(record)
        record["historical_backfill_status"] = "archived_by_official_date"
        moved_by_date.setdefault(official, []).append(record)

    # Failed records rotate behind untouched records so one blocked publisher
    # page cannot starve the rest of the repair queue.
    write_json(pending_path, kept + unresolved)
    for official, records in moved_by_date.items():
        target = daily_dir / f"{official}.json"
        existing = read_json(target, [])
        write_json(target, merge_daily(existing if isinstance(existing, list) else [], records))
    return sum(len(records) for records in moved_by_date.values()), len(selected)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", type=Path, default=DATA_DIR / "historical_backfill_pending.json")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--sources", type=Path, default=DATA_DIR / "working_paper_sources.yml")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()
    source = next((item for item in load_sources(args.sources) if item.get("id") == "cepr-dp"), None)
    if not source:
        raise SystemExit("CEPR source configuration not found")
    moved, attempted = repair_pending(
        args.pending,
        args.daily_dir,
        source,
        limit=args.limit,
        workers=args.workers,
        timeout=args.timeout,
    )
    remaining_payload = read_json(args.pending, [])
    remaining = len(remaining_payload) if isinstance(remaining_payload, list) else 0
    record_source(
        "historical-backfill-repair",
        ok=True,
        count=moved,
        message=f"attempted={attempted}; archived={moved}; remaining={remaining}",
    )
    print(f"historical backfill repair: attempted={attempted} archived={moved} remaining={remaining}")


if __name__ == "__main__":
    main()
