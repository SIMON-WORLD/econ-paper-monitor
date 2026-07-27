"""Block a public release when discovery correctness is not proven.

Metadata gaps such as a missing abstract are reported for later enrichment;
they do not block the site.  Discovery-integrity failures do block publishing
because they can make the public "today" view misleading.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, [])
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("papers"), dict):
        return [dict(item) for item in payload["papers"].values() if isinstance(item, dict)]
    return []


def record_key(record: dict[str, Any]) -> str:
    return str(record.get("doi") or record.get("url") or record.get("id") or "").strip().casefold()


def is_working(record: dict[str, Any]) -> bool:
    return str(record.get("source") or "") == "working_papers" or str(record.get("source_type") or "") in {
        "working_paper", "policy_paper", "aggregator"
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    today = args.date or today_str()
    daily = load_records(args.daily_dir / f"{today}.json")
    quality = read_json(args.quality_report, {})
    ingestion = read_json(args.ingestion_audit, {})
    formal = read_json(args.formal_audit, {})
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    keys = [record_key(record) for record in daily]
    duplicates = sorted({key for key in keys if key and keys.count(key) > 1})
    if duplicates:
        failures.append({"code": "duplicate_public_records", "count": len(duplicates), "examples": duplicates[:10]})

    missing = int(ingestion.get("new_today_missing_candidates") or 0)
    if missing:
        failures.append({"code": "ingestion_missing_candidates", "count": missing})

    formal_missed = int(formal.get("suspected_missed_journals") or 0)
    if formal_missed:
        failures.append({"code": "formal_journal_candidates_not_archived", "count": formal_missed})

    source_type_errors = []
    malformed_dates = []
    for record in daily:
        working = is_working(record)
        source_type = str(record.get("source_type") or "")
        if working and source_type in {"journal_article", "article"}:
            source_type_errors.append(record.get("title"))
        if not working and source_type in {"working_paper", "policy_paper", "aggregator"}:
            source_type_errors.append(record.get("title"))
        for field in ("accepted_date", "available_online", "published_online", "issue_date"):
            value = str(record.get(field) or "").strip()
            if value:
                try:
                    if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                        malformed_dates.append({"title": record.get("title"), "field": field, "value": value})
                except ValueError:
                    malformed_dates.append({"title": record.get("title"), "field": field, "value": value})
    if source_type_errors:
        failures.append({"code": "source_type_mismatch", "count": len(source_type_errors), "examples": source_type_errors[:10]})
    if malformed_dates:
        failures.append({"code": "malformed_public_dates", "count": len(malformed_dates), "examples": malformed_dates[:10]})

    today_date = date.fromisoformat(today)
    historical = []
    for record in daily:
        official = str(record.get("available_online") or record.get("published_online") or "")[:10]
        if not official:
            continue
        try:
            age = (today_date - date.fromisoformat(official)).days
        except ValueError:
            continue
        if age > args.max_historical_days and str(record.get("date_confidence") or "") not in {"F", "unknown"}:
            historical.append({"title": record.get("title"), "official_date": official, "age_days": age})
    if historical:
        failures.append({"code": "historical_records_in_today", "count": len(historical), "examples": historical[:10]})

    missing_abstract = int((quality.get("totals") or {}).get("missing_abstract_today") or 0)
    if missing_abstract:
        warnings.append({"code": "missing_abstract_today", "count": missing_abstract})
    missing_authors = int((quality.get("totals") or {}).get("missing_authors_today_journals") or 0)
    if missing_authors:
        warnings.append({"code": "missing_authors_today_journals", "count": missing_authors})

    return {"date": today, "ok": not failures, "failures": failures, "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--quality-report", type=Path, default=DATA_DIR / "quality_report.json")
    parser.add_argument("--ingestion-audit", type=Path, default=DATA_DIR / "ingestion_audit.json")
    parser.add_argument("--formal-audit", type=Path, default=DATA_DIR / "formal_journal_audit.json")
    parser.add_argument("--max-historical-days", type=int, default=14)
    args = parser.parse_args()
    report = run(args)
    print(f"release gate date={report['date']} ok={report['ok']} failures={len(report['failures'])} warnings={len(report['warnings'])}")
    for item in report["failures"]:
        print(f"FAIL {item}")
    for item in report["warnings"]:
        print(f"WARN {item}")
    if not report["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
