"""Remove known navigation/editorial boilerplate from public archives."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import DATA_DIR, read_json, write_json
from dedupe import is_source_navigation_noise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    args = parser.parse_args()

    removed_daily = 0
    for path in args.daily_dir.glob("*.json"):
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        kept = [record for record in payload if not (isinstance(record, dict) and is_source_navigation_noise(record))]
        removed_daily += len(payload) - len(kept)
        if len(kept) != len(payload):
            write_json(path, kept)

    seen = read_json(args.seen, {})
    removed_seen = 0
    if isinstance(seen, dict) and isinstance(seen.get("papers"), dict):
        papers = seen["papers"]
        kept_papers = {
            record_id: record
            for record_id, record in papers.items()
            if not (isinstance(record, dict) and is_source_navigation_noise(record))
        }
        removed_seen = len(papers) - len(kept_papers)
        if removed_seen:
            seen["papers"] = kept_papers
            write_json(args.seen, seen)
    elif isinstance(seen, list):
        kept_seen = [record for record in seen if not (isinstance(record, dict) and is_source_navigation_noise(record))]
        removed_seen = len(seen) - len(kept_seen)
        if removed_seen:
            write_json(args.seen, kept_seen)

    print(f"non-paper cleanup: daily={removed_daily} seen={removed_seen}")


if __name__ == "__main__":
    main()
