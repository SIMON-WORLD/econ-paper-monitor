"""Aggregate Semantic Scholar API key usage into a daily report.

Reads ``data/metadata_provider_health.json`` (per-run provider health) and
``data/semantic_scholar_keepalive.json`` (daily keep-alive state) and writes
``data/semantic_scholar_usage.json`` with per-day and cumulative request
counts for the ``semantic-scholar`` provider.

The report powers a self-hosted usage page; Semantic Scholar itself does not
expose a usage dashboard.  No credentials are read or printed.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, now_iso, read_json, write_json


def _beijing_date(value: Any) -> str | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(BEIJING_TZ).date().isoformat()


def build_usage(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    health = read_json(data_dir / "metadata_provider_health.json", {})
    keepalive = read_json(data_dir / "semantic_scholar_keepalive.json", {})
    if not isinstance(health, dict):
        health = {}
    if not isinstance(keepalive, dict):
        keepalive = {}

    runs = health.get("runs") if isinstance(health.get("runs"), list) else []
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "attempts": 0,
            "available": 0,
            "not_found": 0,
            "rate_limited": 0,
            "skipped": 0,
            "http_error": 0,
            "runs": 0,
        }
    )
    totals = {
        "attempts": 0,
        "available": 0,
        "not_found": 0,
        "rate_limited": 0,
        "skipped": 0,
        "http_error": 0,
        "runs": 0,
    }
    last_used_at: str | None = None
    key_configured: bool | None = None

    def absorb(run: dict[str, Any]) -> None:
        nonlocal last_used_at, key_configured
        providers = run.get("providers") if isinstance(run, dict) else {}
        ss = providers.get("semantic-scholar") if isinstance(providers, dict) else {}
        if not isinstance(ss, dict) or not ss:
            return
        checked = run.get("checked_at")
        attempts = int(ss.get("attempts") or 0)
        if attempts > 0 and checked:
            if last_used_at is None or str(checked) > last_used_at:
                last_used_at = str(checked)
        if "api_key_configured" in ss:
            key_configured = bool(ss["api_key_configured"])
        statuses = ss.get("statuses") if isinstance(ss.get("statuses"), dict) else {}
        not_found = int(statuses.get("not_found") or 0)
        rate_limited = int(statuses.get("rate_limited") or 0)
        skipped = int(statuses.get("skipped_rate_limited") or 0)
        available = int(ss.get("available") or 0)
        http_error = int(statuses.get("http_error") or 0)
        day = _beijing_date(checked)
        row = by_day[day] if day else None
        if row is not None:
            row["attempts"] += attempts
            row["available"] += available
            row["not_found"] += not_found
            row["rate_limited"] += rate_limited
            row["skipped"] += skipped
            row["http_error"] += http_error
            row["runs"] += 1
        totals["attempts"] += attempts
        totals["available"] += available
        totals["not_found"] += not_found
        totals["rate_limited"] += rate_limited
        totals["skipped"] += skipped
        totals["http_error"] += http_error
        totals["runs"] += 1

    for run in runs:
        absorb(run)
    latest = health.get("latest") if isinstance(health.get("latest"), dict) else {}
    absorb(latest)

    by_day_list = [
        {
            "date": day,
            **by_day[day],
        }
        for day in sorted(day for day in by_day if day)
    ]

    last_keepalive_at = keepalive.get("checked_at")
    keepalive_ok = keepalive.get("ok")
    keepalive_reason = str(keepalive.get("reason") or "missing")

    days_since_last_use: int | None = None
    if last_used_at:
        used = _beijing_date(last_used_at)
        if used:
            today = datetime.now(BEIJING_TZ).date()
            days_since_last_use = max(0, (today - datetime.fromisoformat(used).date()).days)

    return {
        "updated_at": now_iso(),
        "key_configured": bool(key_configured),
        "last_used_at": last_used_at,
        "last_keepalive_at": last_keepalive_at,
        "last_keepalive_ok": keepalive_ok,
        "last_keepalive_reason": keepalive_reason,
        "days_since_last_use": days_since_last_use,
        "total": totals,
        "by_day": by_day_list,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    usage = build_usage(args.data_dir)
    write_json(args.data_dir / "semantic_scholar_usage.json", usage)
    print(
        f"semantic_scholar_usage updated_at={usage['updated_at']} "
        f"key_configured={usage['key_configured']} "
        f"attempts={usage['total']['attempts']} days={len(usage['by_day'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())