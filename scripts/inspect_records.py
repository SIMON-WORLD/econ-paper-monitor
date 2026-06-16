"""Small local helper to inspect selected records by DOI substring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import DATA_DIR, read_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("needles", nargs="+")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    paths = [DATA_DIR / "daily" / f"{args.date}.json"] if args.date else sorted((DATA_DIR / "daily").glob("*.json"), reverse=True)
    keys = [
        "title",
        "title_zh",
        "authors",
        "abstract",
        "journal",
        "doi",
        "fields",
        "accepted_date",
        "available_online",
        "published_online",
        "issue_date",
        "date_source",
        "date_confidence",
        "translation_status",
        "china_related",
        "china_relevance_status",
    ]
    for path in paths:
        for record in read_json(path, []):
            blob = json.dumps(record, ensure_ascii=False)
            if any(needle in blob for needle in args.needles):
                print(path)
                print(json.dumps({key: record.get(key) for key in keys}, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
