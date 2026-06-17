"""Aggregate per-journal Chinese source outputs into one status entry."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import DATA_DIR, load_journals, read_json, today_str
from status import load_status, now, record_source, save_status


CN_JOURNAL_IDS = [
    "journal-f69300dae2",
    "journal-679eaa2a0c",
    "journal-ba9f46c919",
    "journal-379b4022ce",
    "journal-bf2aa9381f",
    "journal-edcb877d78",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw" / "cn")
    args = parser.parse_args()

    journals = {journal["id"]: journal for journal in load_journals()}
    rows: list[dict[str, Any]] = []
    total = 0
    found_outputs = 0
    for journal_id in CN_JOURNAL_IDS:
        journal = journals.get(journal_id, {})
        path = args.raw_dir / f"{args.date}-{journal_id}.json"
        payload = read_json(path, None)
        exists = isinstance(payload, list)
        if exists:
            found_outputs += 1
        count = len(payload) if exists else 0
        total += count
        rows.append(
            {
                "journal_id": journal_id,
                "journal": journal.get("title") or journal_id,
                "ok": exists,
                "count": count,
                "mode": "official-source",
                "message": "ok" if exists else "missing output",
            }
        )

    if found_outputs == 0:
        print("cn journal aggregate skipped: no per-journal raw outputs found")
        return

    ok = any(row["ok"] for row in rows)
    message = "; ".join(f"{row['journal']}: {row['count']}" for row in rows)
    record_source("cn-journals", ok=ok, count=total, message=message)
    status = load_status()
    status.setdefault("source_groups", {})["cn-journals"] = {
        "ok": ok,
        "count": total,
        "updated_at": now(),
        "journals": rows,
    }
    save_status(status)
    print(f"cn journal aggregate: {total} records")
    print(message)


if __name__ == "__main__":
    main()
