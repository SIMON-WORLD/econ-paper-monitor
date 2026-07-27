"""Audit acquisition-path health for the formal journal registry.

This is an operational report, not a public-facing error page.  A journal is
usable when at least one configured acquisition path was checked successfully;
publisher blocks on one path are therefore reported as degraded rather than
as a false complete outage.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import DATA_DIR, load_journals, read_json, today_str, write_json
from status import record_source


GOOD_RSS = {"official-generated", "configured", "feed", "html", "specialized-api", "specialized-html", "nep-issue"}


def age_days(value: str | None, today: date) -> int | None:
    if not value:
        return None
    try:
        return (today - date.fromisoformat(str(value)[:10])).days
    except ValueError:
        return None


def status_age_days(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, (now - stamp.astimezone(timezone.utc)).total_seconds() / 86400)
    except ValueError:
        return None


def inspect_journal(journal: dict[str, Any], registry: dict[str, Any], today: date, now: datetime, max_age: int) -> dict[str, Any]:
    journal_id = str(journal.get("id") or "")
    entry = ((registry.get("journals") or {}).get(journal_id) or {})
    rss_status = str(entry.get("last_rss_status") or "")
    crossref_status = str(entry.get("last_crossref_status") or "")
    rss_ok = rss_status in GOOD_RSS
    crossref_ok = crossref_status == "ok"
    paths = [name for name, ok in (("rss", rss_ok), ("crossref", crossref_ok)) if ok]
    checked = entry.get("updated_at") or entry.get("last_checked_at")
    checked_age = status_age_days(checked, now)
    stale = checked_age is None or checked_age > max_age
    if not paths:
        level = "unavailable"
    elif stale:
        level = "stale"
    elif len(paths) == 1:
        level = "degraded"
    else:
        level = "healthy"
    return {
        "journal_id": journal_id,
        "journal": journal.get("title"),
        "publisher": journal.get("publisher"),
        "level": level,
        "usable_paths": paths,
        "rss_status": rss_status,
        "rss_count": entry.get("last_rss_count"),
        "crossref_status": crossref_status,
        "crossref_count": entry.get("last_crossref_count"),
        "last_checked_at": checked,
        "checked_age_days": checked_age,
        "registry_age_days": age_days(entry.get("last_checked_at"), today),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--registry", type=Path, default=DATA_DIR / "source_registry.json")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "source_health.json")
    parser.add_argument("--max-age-hours", type=float, default=36)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    today = date.fromisoformat(today_str())
    max_age = args.max_age_hours / 24
    registry = read_json(args.registry, {})
    rows = [inspect_journal(journal, registry, today, now, max_age) for journal in load_journals(args.journals)]
    counts = {level: sum(row["level"] == level for row in rows) for level in ("healthy", "degraded", "stale", "unavailable")}
    report = {
        "checked_at": now.replace(microsecond=0).isoformat(),
        "max_age_hours": args.max_age_hours,
        "formal_journals": len(rows),
        "counts": counts,
        "unavailable": [row for row in rows if row["level"] == "unavailable"],
        "stale": [row for row in rows if row["level"] == "stale"],
        "degraded": [row for row in rows if row["level"] == "degraded"],
        "journals": rows,
    }
    write_json(args.output, report)
    ok = counts["unavailable"] == 0
    message = "healthy={healthy} degraded={degraded} stale={stale} unavailable={unavailable}".format(**counts)
    record_source("source-health", ok=ok, count=len(rows), message=message)
    print(f"source health formal={len(rows)} {message}")
    if not ok:
        for row in report["unavailable"][:20]:
            print(f"UNAVAILABLE {row['journal']}: rss={row['rss_status']} crossref={row['crossref_status']}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
