"""Ensure the Beijing-date daily archive exists, even before new papers arrive."""

from __future__ import annotations

from common import DATA_DIR, read_json, today_str, write_json


def main() -> None:
    path = DATA_DIR / "daily" / f"{today_str()}.json"
    records = read_json(path, [])
    if not isinstance(records, list):
        raise SystemExit(f"{path} is not a daily record list")
    write_json(path, records)
    print(f"ensured {path} with {len(records)} records")


if __name__ == "__main__":
    main()
