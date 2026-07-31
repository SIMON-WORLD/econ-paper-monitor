"""Write a compact audit of canonical metadata debt and retry recovery."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, write_json
from public_integrity import DATE_FIELDS, audit_integrity


WEAK_DATE_CONFIDENCE = {"", "C", "D", "F", "unknown"}


def load_daily_records(daily_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(daily_dir.glob("*.json")):
        payload = read_json(path, [])
        if isinstance(payload, list):
            records.extend(record for record in payload if isinstance(record, dict))
    return records


def audit_metadata_recovery(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    records = load_daily_records(data_dir / "daily")
    missing_abstract = [record for record in records if not str(record.get("abstract") or "").strip()]
    preview_abstract = [
        record
        for record in records
        if str(record.get("abstract_completeness") or "") == "preview" or record.get("abstract_truncated") is True
    ]
    preview_ids = {id(record) for record in preview_abstract}
    missing_authors = [record for record in records if not record.get("authors")]
    missing_dates = [record for record in records if not any(record.get(field) for field in DATE_FIELDS)]
    weak_dates = [
        record
        for record in records
        if str(record.get("date_confidence") or "unknown") in WEAK_DATE_CONFIDENCE
    ]
    metadata_queue = read_json(data_dir / "metadata_retry_queue.json", {"records": []})
    ingestion_queue = read_json(data_dir / "ingestion_retry_queue.json", {"records": []})
    source_health = read_json(data_dir / "source_health.json", {})
    integrity = audit_integrity(data_dir)
    return {
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "canonical_records": len(records),
        "abstracts": {
            "full": sum(
                bool(str(record.get("abstract") or "").strip())
                and id(record) not in preview_ids
                for record in records
            ),
            "preview": len(preview_abstract),
            "missing": len(missing_abstract),
        },
        "authors": {"available": len(records) - len(missing_authors), "missing": len(missing_authors)},
        "official_dates": {
            "available": len(records) - len(missing_dates),
            "missing": len(missing_dates),
            "weak_confidence": len(weak_dates),
            "confidence_counts": dict(
                sorted(Counter(str(record.get("date_confidence") or "unknown") for record in records).items())
            ),
        },
        "retry_queues": {
            "metadata_pending": len(metadata_queue.get("records") or []) if isinstance(metadata_queue, dict) else 0,
            "metadata_total_before_limit": int(metadata_queue.get("total_candidates_before_limit") or 0)
            if isinstance(metadata_queue, dict)
            else 0,
            "ingestion_pending": len(ingestion_queue.get("records") or []) if isinstance(ingestion_queue, dict) else 0,
            "ingestion_resolved": len(ingestion_queue.get("resolved_records") or [])
            if isinstance(ingestion_queue, dict)
            else 0,
        },
        "source_health": {
            "counts": source_health.get("counts") or {},
            "coverage_counts": source_health.get("coverage_counts") or {},
        },
        "integrity": integrity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.data_dir / "metadata_recovery_audit.json"
    report = audit_metadata_recovery(args.data_dir)
    write_json(output, report)
    print(
        f"metadata audit canonical={report['canonical_records']} "
        f"missing_abstract={report['abstracts']['missing']} "
        f"missing_authors={report['authors']['missing']} "
        f"missing_dates={report['official_dates']['missing']}"
    )


if __name__ == "__main__":
    main()
