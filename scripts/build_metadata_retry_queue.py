"""Build a durable queue for metadata that needs an honest retry."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json
from dedupe import is_source_navigation_noise


WEAK_DATE_CONFIDENCE = {"", "C", "D", "F", "unknown"}


def record_identity(record: dict[str, Any]) -> str:
    doi = str(record.get("doi") or "").strip().casefold()
    if doi:
        return f"doi:{doi}"
    url = str(record.get("url") or record.get("source_url") or "").strip().casefold()
    if url:
        return f"url:{url}"
    return "title:{}:{}".format(
        str(record.get("journal") or "").strip().casefold(),
        str(record.get("title") or "").strip().casefold(),
    )


def parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def load_records(seen_path: Path) -> list[dict[str, Any]]:
    payload = read_json(seen_path, {"papers": {}})
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if isinstance(papers, dict):
        return [record for record in papers.values() if isinstance(record, dict)]
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    return []


def queue_item(record: dict[str, Any], anchor: date, recent_start: date) -> dict[str, Any] | None:
    first_seen = parse_date(record.get("first_seen") or record.get("detected_at"))
    official_date = parse_date(
        record.get("official_date")
        or record.get("available_online")
        or record.get("published_online")
        or record.get("issue_date")
    )
    reference_date = official_date or first_seen
    recent = bool(reference_date and reference_date >= recent_start)
    missing_abstract = not str(record.get("abstract") or "").strip()
    missing_authors = not record.get("authors")
    weak_date = str(record.get("date_confidence") or "unknown") in WEAK_DATE_CONFIDENCE
    if is_source_navigation_noise(record) or not (missing_abstract or missing_authors or weak_date):
        return None

    reasons = []
    if missing_abstract:
        reasons.append("missing_abstract")
    if missing_authors:
        reasons.append("missing_authors")
    if weak_date:
        reasons.append("weak_date_evidence")

    # Lower values are processed first: fresh records and missing abstracts
    # affect the public detail experience most directly.
    age_days = (anchor - (official_date or first_seen or anchor)).days
    priority = (0 if recent else 1, 0 if missing_abstract else 1, 0 if missing_authors else 1, max(age_days, 0))
    return {
        "identity": record_identity(record),
        "priority": list(priority),
        "reasons": reasons,
        "journal": record.get("journal"),
        "source_type": record.get("source_type"),
        "source_id": record.get("source_id"),
        "title": record.get("title"),
        "doi": record.get("doi"),
        "url": record.get("url") or record.get("source_url"),
        "first_seen": record.get("first_seen") or record.get("detected_at"),
        "official_date": (
            record.get("official_date")
            or record.get("available_online")
            or record.get("published_online")
            or record.get("issue_date")
        ),
        "recency_basis": "official_date" if official_date else ("first_seen" if first_seen else "unknown"),
        "historical_backfill": bool(
            record.get("historical_backfill")
            or record.get("historical_backfill_status")
            or record.get("public_flow_excluded")
        ),
        "date_confidence": record.get("date_confidence"),
    }


def build_queue(
    seen_path: Path,
    *,
    anchor: date,
    recent_days: int,
    limit: int,
) -> dict[str, Any]:
    recent_start = anchor - timedelta(days=max(1, recent_days) - 1)
    all_items = [
        item
        for record in load_records(seen_path)
        if (item := queue_item(record, anchor, recent_start))
    ]
    all_items.sort(key=lambda item: (tuple(item["priority"]), item["identity"]))
    items = all_items[: max(0, limit)]
    reason_counts = Counter(reason for item in items for reason in item["reasons"])
    recent_count = sum(1 for item in items if tuple(item["priority"])[0] == 0)
    return {
        "generated_for": anchor.isoformat(),
        "recent_window_start": recent_start.isoformat(),
        "total_candidates": len(items),
        "total_candidates_before_limit": len(all_items),
        "truncated": len(items) < len(all_items),
        "recent_candidates": recent_count,
        "recent_candidates_before_limit": sum(tuple(item["priority"])[0] == 0 for item in all_items),
        "historical_backfill_candidates": sum(bool(item["historical_backfill"]) for item in items),
        "reason_counts": dict(sorted(reason_counts.items())),
        "records": items,
        "note": "Retry queue only. Missing fields remain unmodified until an authoritative source supplies evidence.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "metadata_retry_queue.json")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    anchor = parse_date(args.date) or date.today()
    report = build_queue(
        args.seen,
        anchor=anchor,
        recent_days=args.recent_days,
        limit=args.limit,
    )
    write_json(args.output, report)
    print(
        f"metadata retry queue candidates={report['total_candidates']} "
        f"recent={report['recent_candidates']} total={report['total_candidates_before_limit']}"
    )


if __name__ == "__main__":
    main()
