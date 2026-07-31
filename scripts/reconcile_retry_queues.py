"""Reconcile durable ingestion retries with canonical and pending catalogues."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common import DATA_DIR, read_json, write_json
from public_integrity import catalogue_identity_keys, iter_ledger_records


def iter_daily(daily_dir: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    for path in sorted(daily_dir.glob("*.json")):
        payload = read_json(path, [])
        for record in payload if isinstance(payload, list) else []:
            if isinstance(record, dict):
                yield f"daily:{path.stem}", record


def iter_seen(seen_path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    payload = read_json(seen_path, {"papers": {}})
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if isinstance(papers, dict):
        for key, record in papers.items():
            if isinstance(record, dict):
                yield f"seen:{key}", record
    elif isinstance(payload, list):
        for index, record in enumerate(payload):
            if isinstance(record, dict):
                yield f"seen:{index}", record


def iter_pending(path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    payload = read_json(path, [])
    records = payload.get("records") if isinstance(payload, dict) else payload
    for index, record in enumerate(records if isinstance(records, list) else []):
        if isinstance(record, dict):
            yield f"pending:{index}", record


def build_catalogue_index(data_dir: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    sources = (
        iter_daily(data_dir / "daily"),
        iter_seen(data_dir / "seen.json"),
        iter_pending(data_dir / "pending_date_records.json"),
    )
    for records in sources:
        for location, record in records:
            for identity in catalogue_identity_keys(record):
                index.setdefault(identity, (location, record))
    return index


def find_resolution(
    record: dict[str, Any],
    index: dict[str, tuple[str, dict[str, Any]]],
) -> tuple[str, str, dict[str, Any]] | None:
    for identity in sorted(catalogue_identity_keys(record)):
        matched = index.get(identity)
        if matched:
            location, owner = matched
            return identity, location, owner
    return None


def reconcile_retry_queue(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    queue_path = data_dir / "ingestion_retry_queue.json"
    queue = read_json(queue_path, {"records": []})
    if not isinstance(queue, dict):
        queue = {"records": []}
    records = queue.get("records") if isinstance(queue.get("records"), list) else []
    index = build_catalogue_index(data_dir)
    resolved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    pending: list[dict[str, Any]] = []
    resolved_now: list[dict[str, Any]] = []
    resolution_by_identity: dict[str, dict[str, Any]] = {}

    for record in records:
        if not isinstance(record, dict):
            continue
        resolution = find_resolution(record, index)
        if resolution is None:
            pending.append(record)
            continue
        identity, location, owner = resolution
        resolved = copy.deepcopy(record)
        resolved.update(
            {
                "retry_status": "resolved",
                "resolved_at": resolved_at,
                "resolution_identity": identity,
                "resolution_location": location,
                "canonical_detail_key": owner.get("detail_key"),
                "matched_seen_key": location.removeprefix("seen:") if location.startswith("seen:") else None,
            }
        )
        resolved_now.append(resolved)
        for key in catalogue_identity_keys(record):
            resolution_by_identity[key] = resolved

    history = queue.get("resolved_records") if isinstance(queue.get("resolved_records"), list) else []
    existing_history = {
        str(record.get("resolution_identity") or record.get("identity") or "").casefold()
        for record in history
        if isinstance(record, dict)
    }
    for record in resolved_now:
        identity = str(record.get("resolution_identity") or "").casefold()
        if identity and identity not in existing_history:
            history.append(record)
            existing_history.add(identity)

    ledger_path = data_dir / "ingestion_exclusion_ledger.json"
    ledger = read_json(ledger_path, {"records": []})
    ledger_changed = 0
    for record in iter_ledger_records(ledger):
        if record.get("retry_status") != "pending" and record.get("stage") != "retry_reingestion":
            continue
        matched = next(
            (resolution_by_identity[key] for key in sorted(catalogue_identity_keys(record)) if key in resolution_by_identity),
            None,
        )
        if not matched:
            continue
        record["retry_status"] = "resolved"
        record["resolved_at"] = matched["resolved_at"]
        record["resolution_identity"] = matched["resolution_identity"]
        record["resolution_location"] = matched["resolution_location"]
        record["canonical_detail_key"] = matched.get("canonical_detail_key")
        if matched.get("matched_seen_key"):
            record["matched_seen_key"] = matched["matched_seen_key"]
        ledger_changed += 1

    changed = bool(resolved_now) or len(pending) != len(records)
    if changed:
        queue["records"] = pending
        queue["resolved_records"] = history
        queue["generated_at"] = resolved_at
        queue["total_candidates"] = len(pending)
        queue["resolved_count"] = len(history)
        queue["note"] = "Pending candidates only; resolved candidates remain in resolved_records for auditability."
        write_json(queue_path, queue)
    if ledger_changed:
        write_json(ledger_path, ledger)

    report = {
        "checked_at": resolved_at,
        "pending_before": len(records),
        "resolved_now": len(resolved_now),
        "pending_after": len(pending),
        "resolved_history": len(history),
        "ledger_records_resolved": ledger_changed,
        "resolution_locations": {
            prefix: sum(str(record.get("resolution_location") or "").startswith(prefix) for record in resolved_now)
            for prefix in ("daily:", "seen:", "pending:")
        },
    }
    write_json(data_dir / "retry_reconciliation_audit.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    report = reconcile_retry_queue(args.data_dir)
    print(
        f"retry reconciliation pending={report['pending_before']} "
        f"resolved={report['resolved_now']} remaining={report['pending_after']}"
    )


if __name__ == "__main__":
    main()
