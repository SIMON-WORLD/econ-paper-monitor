"""Decide whether the scheduled lightweight monitor should run."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from status import load_status


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-minutes", type=int, default=50)
    args = parser.parse_args()

    status = load_status()
    workflow = status.get("workflow", {})
    last_light = parse_dt(str(workflow.get("last_light_finished_at", "")))
    if last_light is None:
        print("run")
        return

    age = datetime.now(UTC) - last_light.astimezone(UTC)
    if age >= timedelta(minutes=args.min_minutes):
        print("run")
    else:
        print(f"skip:{int(age.total_seconds() // 60)}")


if __name__ == "__main__":
    main()
