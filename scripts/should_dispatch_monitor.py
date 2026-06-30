"""Decide which monitor mode the watchdog should dispatch.

GitHub scheduled workflows can be delayed or occasionally skipped. This script
keeps the public monitor fresh by letting the watchdog backfill the daily full
run after the Beijing 08:30 window, then falling back to the hourly light run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, time, timedelta, timezone

from status import load_status


BEIJING = timezone(timedelta(hours=8))


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_today_beijing(value: datetime | None, now_bj: datetime) -> bool:
    if value is None:
        return False
    return value.astimezone(BEIJING).date() == now_bj.date()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--light-min-minutes", type=int, default=50)
    parser.add_argument("--full-after-hour", type=int, default=8)
    parser.add_argument("--full-after-minute", type=int, default=30)
    args = parser.parse_args()

    status = load_status()
    workflow = status.get("workflow", {})
    now_utc = datetime.now(UTC)
    now_bj = now_utc.astimezone(BEIJING)

    last_full = parse_dt(str(workflow.get("last_full_finished_at", "")))
    full_window = time(args.full_after_hour, args.full_after_minute)
    if now_bj.time() >= full_window and not is_today_beijing(last_full, now_bj):
        print("full")
        return

    last_light = parse_dt(str(workflow.get("last_light_finished_at", "")))
    if last_light is None:
        print("light")
        return

    age = now_utc - last_light.astimezone(UTC)
    if age >= timedelta(minutes=args.light_min_minutes):
        print("light")
    else:
        print(f"skip:{int(age.total_seconds() // 60)}")


if __name__ == "__main__":
    main()
