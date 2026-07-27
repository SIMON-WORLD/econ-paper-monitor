"""Move clearly historical working-paper catalogue items out of public pages."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, stable_id, today_str, write_json


CEPR_NUMBER = re.compile(r"/dp(\d+)(?:\D|$)", flags=re.I)


def is_historical_cepr(record: dict[str, Any]) -> bool:
    if str(record.get("source_id") or "") != "cepr-dp":
        return False
    match = CEPR_NUMBER.search(str(record.get("url") or ""))
    return bool(match and int(match.group(1)) < 10000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--pending", type=Path, default=DATA_DIR / "pending_date_records.json")
    args = parser.parse_args()

    pending = read_json(args.pending, [])
    pending = pending if isinstance(pending, list) else []
    pending_keys = {str(item.get("id") or stable_id(item)) for item in pending if isinstance(item, dict)}
    moved = 0
    changed_files = 0
    for path in sorted(args.daily_dir.glob("*.json")):
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        kept: list[dict[str, Any]] = []
        file_changed = False
        for record in payload:
            if isinstance(record, dict) and is_historical_cepr(record):
                record = dict(record)
                record["id"] = record.get("id") or stable_id(record)
                record["pending_reason"] = "historical CEPR catalogue item without a current online date"
                if record["id"] not in pending_keys:
                    pending.append(record)
                    pending_keys.add(record["id"])
                moved += 1
                file_changed = True
            else:
                kept.append(record)
        if file_changed:
            write_json(path, kept)
            changed_files += 1
    write_json(args.pending, pending)
    print(f"historical working-paper cleanup: moved={moved} files={changed_files} pending={len(pending)} date={today_str()}")


if __name__ == "__main__":
    main()
