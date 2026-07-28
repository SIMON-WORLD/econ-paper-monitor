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
SUPPLEMENTAL_SOURCE_IDS = {"openalex-recall"}

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
    "theoretical-economics",
    "quantitative-economics",
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
        per_journal = (entry.get("journals") or {}).get(journal_id)
        if journal_id in targets and (
            status_entry_is_fresh(entry, now, max_age)
            or (
                isinstance(per_journal, dict)
                and per_journal.get("ok")
                and status_age_days(entry.get("updated_at"), now) is not None
                and status_age_days(entry.get("updated_at"), now) <= max_age
            )
        ):
            paths.append(path_name)
            if entry.get("updated_at"):
                checked_at.append(str(entry["updated_at"]))

    for group_id, path_name in (("cn-journals", "cn-journals"), ("cnki-rss", "cnki-rss")):
        group = groups.get(group_id) or {}
        if not status_entry_is_fresh(group, now, max_age):
            continue
        rows = group.get("journals") or []
        row = next((item for item in rows if str(item.get("journal_id") or "") == journal_id), None)
        # A source may have one failed child endpoint while another child
        # endpoint already returned valid records. Treat that as usable with
        # partial-failure evidence, rather than downgrading the whole journal
        # to Crossref-only.
        if row and (row.get("ok") or int(row.get("count") or 0) > 0):
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
    rss_ok = rss_status in GOOD_RSS and not entry.get("last_rss_error")
    crossref_ok = crossref_status == "ok"
    paths = [name for name, ok in (("rss", rss_ok), ("crossref", crossref_ok)) if ok]
    specialized, specialized_checked = specialized_paths(journal_id, status or {}, now, max_age)
    paths.extend(path for path in specialized if path not in paths)
    supplemental: list[str] = []
    supplemental_entry = (status.get("sources") or {}).get("openalex-recall") if status else None
    if isinstance(supplemental_entry, dict) and status_entry_is_fresh(supplemental_entry, now, max_age):
        details = supplemental_entry.get("details") if isinstance(supplemental_entry.get("details"), dict) else {}
        per_journal = details.get("per_journal") if isinstance(details.get("per_journal"), dict) else None
        journal_entry = per_journal.get(journal_id) if per_journal is not None else None
        # Older status files had only a global OpenAlex result. Keep them
        # readable, but use the per-journal ledger whenever it is available so
        # one successful query cannot masquerade as full-journal coverage.
        eligible = journal_entry is None if per_journal is None else bool(journal_entry.get("ok"))
        if eligible:
            supplemental.append("openalex-recall")
            paths.append("openalex-recall")
    checked_candidates = [str(value) for value in (entry.get("updated_at"), entry.get("last_checked_at"), *specialized_checked) if value]
    checked = max(checked_candidates) if checked_candidates else None
    checked_age = status_age_days(checked, now)
    stale = checked_age is None or checked_age > max_age
    reliable_paths = [path for path in paths if path not in SUPPLEMENTAL_SOURCE_IDS]
    if not reliable_paths:
        level = "unavailable" if not paths else "degraded"
    elif stale:
        level = "stale"
    elif len(reliable_paths) == 1:
        level = "degraded"
    else:
        level = "healthy"
    if not reliable_paths and not supplemental:
        coverage = "unavailable"
    elif "crossref" in reliable_paths and len(reliable_paths) == 1 and supplemental:
        coverage = "supplemental"
    elif "crossref" in reliable_paths and len(reliable_paths) == 1:
        coverage = "crossref_only"
    elif any(path in reliable_paths for path in ("rss", "aea-toc", "priority-toc", "cn-journals", "cnki-rss")):
        coverage = "official_or_specialized"
    else:
        coverage = "supplemental"
    return {
        "journal_id": journal_id,
        "journal": journal.get("title"),
        "publisher": journal.get("publisher"),
        "level": level,
        "coverage": coverage,
        "usable_paths": paths,
        "rss_status": rss_status,
        "rss_count": entry.get("last_rss_count"),
        "crossref_status": crossref_status,
        "crossref_count": entry.get("last_crossref_count"),
        "specialized_paths": specialized,
        "supplemental_paths": supplemental,
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
    coverage_counts = {
        coverage: sum(row["coverage"] == coverage for row in rows)
        for coverage in ("official_or_specialized", "supplemental", "crossref_only", "unavailable")
    }
    report = {
        "checked_at": now.replace(microsecond=0).isoformat(),
        "max_age_hours": args.max_age_hours,
        "formal_journals": len(rows),
        "counts": counts,
        "coverage_counts": coverage_counts,
        "unavailable": [row for row in rows if row["level"] == "unavailable"],
        "stale": [row for row in rows if row["level"] == "stale"],
        "degraded": [row for row in rows if row["level"] == "degraded"],
        "journals": rows,
    }
    report["coverage_debt"] = {
        "crossref_only": [
            {
                "journal_id": row["journal_id"],
                "journal": row["journal"],
                "publisher": row["publisher"],
                "usable_paths": row["usable_paths"],
                "next_action": "verify an official RSS, TOC, advance, or latest-article source",
            }
            for row in rows
            if row["coverage"] == "crossref_only"
        ],
        "supplemental_only": [
            {
                "journal_id": row["journal_id"],
                "journal": row["journal"],
                "publisher": row["publisher"],
                "usable_paths": row["usable_paths"],
                "next_action": "replace or complement the recall source with an official RSS, TOC, advance, or latest-article source",
            }
            for row in rows
            if row["coverage"] == "supplemental"
        ],
        "single_path_degraded": [
            {
                "journal_id": row["journal_id"],
                "journal": row["journal"],
                "usable_paths": row["usable_paths"],
                "next_action": "add or verify an independent fallback path",
            }
            for row in rows
            if row["level"] == "degraded"
        ],
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
