"""Repair historical RePEc NEP records affected by cross-issue p-number collisions."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import DATA_DIR, fetch_text, normalize_text, read_json, write_json
from fetch_preprints import load_sources, parse_nep_issue_list


def issue_key(record: dict[str, Any]) -> tuple[str, str] | None:
    source_id = str(record.get("source_id") or "")
    if not source_id.startswith("repec-nep-"):
        return None
    issue_url = str(record.get("source_url") or str(record.get("url") or "").split("#", 1)[0]).rstrip("/")
    return (source_id, issue_url) if issue_url else None


def candidate_key(record: dict[str, Any]) -> tuple[str, str]:
    return str(record.get("paper_number") or "").casefold(), normalize_text(record.get("title"))


def best_candidates(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = candidate_key(record)
        current = selected.get(key)
        score = (bool(record.get("abstract")), bool(record.get("authors")), "econpapers.repec.org" in str(record.get("url") or ""))
        current_score = (
            bool(current and current.get("abstract")),
            bool(current and current.get("authors")),
            bool(current and "econpapers.repec.org" in str(current.get("url") or "")),
        )
        if current is None or score > current_score:
            selected[key] = record
    return selected


def apply_candidate(record: dict[str, Any], candidate: dict[str, Any]) -> bool:
    changed = False
    abstract = candidate.get("abstract") or None
    if record.get("abstract") != abstract:
        record["abstract"] = abstract
        record.pop("abstract_zh", None)
        record.pop("translation_status", None)
        changed = True
    authors = candidate.get("authors") or []
    if authors and not record.get("authors"):
        record["authors"] = authors
        changed = True
    if abstract and record.get("abstract_source") != "repec_nep_issue":
        record["abstract_source"] = "repec_nep_issue"
        changed = True
    elif not abstract and "abstract_source" in record:
        record.pop("abstract_source", None)
        changed = True
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--sources", type=Path, default=DATA_DIR / "working_paper_sources.yml")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    sources = {str(item.get("id") or ""): item for item in load_sources(args.sources)}
    daily_payloads: dict[Path, list[dict[str, Any]]] = {}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(args.daily_dir.glob("*.json")):
        records = read_json(path, [])
        if not isinstance(records, list):
            continue
        daily_payloads[path] = records
        for record in records:
            key = issue_key(record)
            if key:
                grouped[key].append(record)

    repaired: dict[tuple[str, str], dict[tuple[str, str], dict[str, Any]]] = {}
    failures: list[str] = []
    for (source_id, issue_url), records in grouped.items():
        source = sources.get(source_id)
        if not source:
            failures.append(f"{source_id}: missing source config")
            continue
        try:
            issue_date = issue_url.rstrip("/").rsplit("/", 1)[-1]
            parsed = parse_nep_issue_list(
                fetch_text(issue_url, timeout=args.timeout),
                source,
                max(50, len(records) * 2),
                issue_date=issue_date,
                issue_url=issue_url,
            )
            repaired[(source_id, issue_url)] = best_candidates(parsed)
        except Exception as exc:
            failures.append(f"{issue_url}: {type(exc).__name__}: {exc}")

    changed_records = changed_files = 0
    for path, records in daily_payloads.items():
        path_changed = False
        for record in records:
            key = issue_key(record)
            if not key or key not in repaired:
                continue
            candidate = repaired[key].get(candidate_key(record))
            if candidate and apply_candidate(record, candidate):
                changed_records += 1
                path_changed = True
        if path_changed:
            write_json(path, records)
            changed_files += 1

    seen = read_json(args.seen, {"papers": {}})
    for record in (seen.get("papers") or {}).values():
        if not isinstance(record, dict):
            continue
        key = issue_key(record)
        if not key or key not in repaired:
            continue
        candidate = repaired[key].get(candidate_key(record))
        if candidate and apply_candidate(record, candidate):
            changed_records += 1
    write_json(args.seen, seen)
    print(f"nep metadata repaired={changed_records} files={changed_files} issues={len(repaired)} failures={len(failures)}")
    for failure in failures:
        print(f"warning: {failure}")


if __name__ == "__main__":
    main()
