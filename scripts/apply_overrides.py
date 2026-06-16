"""Apply manual metadata corrections to daily archives and seen.json."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import DATA_DIR, normalize_doi, parse_scalar, read_json, stable_id, write_json
from status import record_source


def record_key(record: dict[str, Any]) -> str | None:
    doi = normalize_doi(record.get("doi"))
    if doi:
        return doi
    return record.get("id") or stable_id(record)


def apply_to_record(record: dict[str, Any], override: dict[str, Any]) -> bool:
    changed = False
    field_map = {
        "title_zh": "title_zh",
        "china_related": "china_related",
        "china_reason": "china_reason",
        "date_confidence": "date_confidence",
        "accepted_date": "accepted_date",
        "available_online": "available_online",
        "published_online": "published_online",
    }
    for source_key, target_key in field_map.items():
        if source_key not in override:
            continue
        value = override[source_key]
        if source_key == "china_related" and isinstance(value, str):
            value = value.strip().casefold() == "true"
        if record.get(target_key) != value:
            record[target_key] = value
            changed = True
    if override.get("title_zh") and record.get("translation_status") != "manual_title":
        record["translation_status"] = "manual_title"
        changed = True
    if override.get("china_related") is True and record.get("china_related_source") != "manual":
        record["china_related_source"] = "manual"
        changed = True
    return changed


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"))


def load_overrides(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    current_key: str | None = None
    in_records = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "records:":
            in_records = True
            continue
        if not in_records:
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key = stripped.rstrip(":").strip('"')
            records[key] = {}
            current_key = key
            continue
        if current_key and line.startswith("    "):
            field, _, value = stripped.partition(":")
            records[current_key][field.strip()] = parse_scalar(value.strip())
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overrides", type=Path, default=DATA_DIR / "manual_overrides.yml")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    overrides = load_overrides(args.overrides)
    changed = 0
    touched = 0
    for path in daily_paths(args.daily_dir, args.date):
        records = read_json(path, [])
        path_changed = False
        for record in records:
            key = record_key(record)
            override = overrides.get(key or "")
            if isinstance(override, dict) and apply_to_record(record, override):
                changed += 1
                path_changed = True
        if path_changed:
            write_json(path, records)
            touched += 1

    seen = read_json(args.seen, {"papers": {}})
    for key, override in overrides.items():
        if not isinstance(override, dict):
            continue
        seen_key = f"doi:{normalize_doi(key)}" if normalize_doi(key) else key
        entry = seen.get("papers", {}).get(seen_key)
        if isinstance(entry, dict) and apply_to_record(entry, override):
            changed += 1
    write_json(args.seen, seen)
    record_source("manual-overrides", ok=True, count=changed, message=f"files={touched}")
    print(f"manual overrides changed={changed} files={touched}")


if __name__ == "__main__":
    main()
