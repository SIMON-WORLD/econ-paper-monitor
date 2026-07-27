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

# These sources are written to the run-status ledger rather than the generic
# RSS/Crossref registry.  They still represent real acquisition paths and must
# participate in the per-journal health decision.
AEA_JOURNALS = {
    "american-economic-review",
    "american-economic-review-insights",
    "journal-of-economic-literature",
    "journal-of-economic-perspectives",
    "american-economic-journal-applied-economics",
    "american-economic-journal-economic-policy",
    "american-economic-journal-macroeconomics",
    "american-economic-journal-microeconomics",
    "american-economic-review-papers-and-proceedings",
}
PRIORITY_TOC_JOURNALS = {
    "review-of-economic-studies",
    "review-of-economics-and-statistics",
    "econometrica",
}


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


def status_entry_is_fresh(entry: dict[str, Any], now: datetime, max_age: float) -> bool:
    if not entry.get("ok"):
        return False
    updated = status_age_days(entry.get("updated_at"), now)
    return updated is not None and updated <= max_age


def specialized_paths(journal_id: str, status: dict[str, Any], now: datetime, max_age: float) -> tuple[list[str], list[str]]:
    paths: list[str] = []
    checked_at: list[str] = []
    sources = status.get("sources") or {}
    groups = status.get("source_groups") or {}

    for source_id, path_name, targets in (
        ("aea-toc", "aea-toc", AEA_JOURNALS),
        ("priority-toc", "priority-toc", PRIORITY_TOC_JOURNALS),
    ):
        entry = sources.get(source_id) or {}
        if journal_id in targets and status_entry_is_fresh(entry, now, max_age):
            paths.append(path_name)
            if entry.get("updated_at"):
                checked_at.append(str(entry["updated_at"]))

    for group_id, path_name in (("cn-journals", "cn-journals"), ("cnki-rss", "cnki-rss")):
        group = groups.get(group_id) or {}
        if not status_entry_is_fresh(group, now, max_age):
            continue
        rows = group.get("journals") or []
        row = next((item for item in rows if str(item.get("journal_id") or "") == journal_id), None)
        if row and row.get("ok"):
            paths.append(path_name)
            if group.get("updated_at"):
                checked_at.append(str(group["updated_at"]))
    return paths, checked_at


def inspect_journal(
    journal: dict[str, Any],
    registry: dict[str, Any],
    today: date,
    now: datetime,
    max_age: int,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    journal_id = str(journal.get("id") or "")
    entry = ((registry.get("journals") or {}).get(journal_id) or {})
    rss_status = str(entry.get("last_rss_status") or "")
    crossref_status = str(entry.get("last_crossref_status") or "")
    rss_ok = rss_status in GOOD_RSS
    crossref_ok = crossref_status == "ok"
    paths = [name for name, ok in (("rss", rss_ok), ("crossref", crossref_ok)) if ok]
    specialized, specialized_checked = specialized_paths(journal_id, status or {}, now, max_age)
    paths.extend(path for path in specialized if path not in paths)
    checked_candidates = [str(value) for value in (entry.get("updated_at"), entry.get("last_checked_at"), *specialized_checked) if value]
    checked = max(checked_candidates) if checked_candidates else None
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
        "specialized_paths": specialized,
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
    status = read_json(DATA_DIR / "status.json", {})
    rows = [inspect_journal(journal, registry, today, now, max_age, status) for journal in load_journals(args.journals)]
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
    # A stale registry is not evidence that a source is currently usable. A
    # release may continue with one degraded path, but never with an outage
    # or an unrefreshed formal-source audit.
    ok = counts["unavailable"] == 0 and counts["stale"] == 0
    message = "healthy={healthy} degraded={degraded} stale={stale} unavailable={unavailable}".format(**counts)
    record_source("source-health", ok=ok, count=len(rows), message=message)
    print(f"source health formal={len(rows)} {message}")
    if not ok:
        for row in report["unavailable"][:20]:
            print(f"UNAVAILABLE {row['journal']}: rss={row['rss_status']} crossref={row['crossref_status']}")
        for row in report["stale"][:20]:
            print(f"STALE {row['journal']}: last_checked={row['last_checked_at']}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
