"""Backfill missing IZA authors from official detail pages."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from common import DATA_DIR, read_json, today_str, write_json
from fetch_preprints import enrich_record_from_detail, load_sources


def target_dates(days: int) -> set[str]:
    today = date.fromisoformat(today_str())
    return {(today - timedelta(days=offset)).isoformat() for offset in range(max(days, 1))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--sources", type=Path, default=DATA_DIR / "working_paper_sources.yml")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    iza = next((source for source in load_sources(args.sources) if str(source.get("id")) == "iza"), None)
    if not iza:
        print("IZA source definition not found")
        return

    wanted = target_dates(args.days)
    changed_files = 0
    checked = 0
    enriched = 0
    for path in sorted(args.daily_dir.glob("*.json"), reverse=True):
        if path.stem not in wanted or checked >= args.limit:
            continue
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        changed = False
        for record in payload:
            if checked >= args.limit:
                break
            if record.get("source_id") != "iza" or record.get("authors") or not record.get("url"):
                continue
            checked += 1
            before = list(record.get("authors") or [])
            updated = enrich_record_from_detail(record, iza, timeout=args.timeout)
            if updated.get("authors") and updated.get("authors") != before:
                enriched += 1
                changed = True
        if changed:
            write_json(path, payload)
            changed_files += 1

    print(f"IZA author backfill: checked={checked} enriched={enriched} files={changed_files}")


if __name__ == "__main__":
    main()
