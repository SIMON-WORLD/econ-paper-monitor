"""Check that source registry types agree with stored records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from normalize_records import WORKING_SOURCE_TYPES, infer_registered_source_id


def records_from_daily(daily_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(daily_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            for record in payload:
                if isinstance(record, dict):
                    item = dict(record)
                    item["_daily_date"] = path.stem
                    records.append(item)
    return records


def records_from_seen(daily_dir: Path) -> list[dict[str, Any]]:
    path = daily_dir.parent / "seen.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, dict):
        return []
    return [dict(record, _daily_date="seen") for record in papers.values() if isinstance(record, dict)]


def source_id(record: dict[str, Any]) -> str:
    value = str(record.get("source_id") or "").casefold().removeprefix("source-")
    if value:
        return value
    return str(record.get("journal_id") or "").casefold().removeprefix("source-")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "daily")
    args = parser.parse_args()

    records = records_from_daily(args.daily_dir) + records_from_seen(args.daily_dir)
    mismatches: list[dict[str, Any]] = []
    for record in records:
        sid = source_id(record) or infer_registered_source_id(record)
        registered = WORKING_SOURCE_TYPES.get(sid)
        source = str(record.get("source") or "")
        source_type = str(record.get("source_type") or "")
        if source != "working_papers" and registered is None:
            continue
        expected = registered or "working_paper"
        if source != "working_papers" or source_type != expected:
            mismatches.append(
                {
                    "date": record.get("_daily_date"),
                    "title": record.get("title"),
                    "source_id": sid,
                    "source": source,
                    "source_type": source_type,
                    "expected_source_type": expected,
                    "url": record.get("url"),
                }
            )

    print(f"source type audit records={len(records)} mismatches={len(mismatches)}")
    for item in mismatches[:20]:
        print(json.dumps(item, ensure_ascii=False))
    raise SystemExit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
