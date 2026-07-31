"""Batch recovery of missing abstracts, authors, and dates via OpenAlex and Semantic Scholar.

Iterates all canonical daily records, identifies those missing abstract, authors, or
with low-confidence official dates, and calls OpenAlex + Semantic Scholar APIs to
recover the missing data. Updates daily JSON files in-place and writes a recovery
report to data/openalex_recovery_report.json.

Rate limits:
- OpenAlex polite pool: ~10 requests/second
- Semantic Scholar: 100 requests per 5 minutes without API key

Run: python scripts/recover_abstracts_openalex.py [--dry-run] [--days N] [--skip-semantic-scholar]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from common import (
    BEIJING_TZ,
    DATA_DIR,
    normalize_doi,
    read_json,
    write_json,
)
from enrich_metadata import (
    openalex_doi_metadata,
    semantic_scholar_doi_metadata,
    crossref_doi_metadata,
    parse_date,
    openalex_abstract,
)

RECOVERY_REPORT_PATH = DATA_DIR / "openalex_recovery_report.json"

# Fields considered "missing" for recovery purposes
ABSTRACT_OK_LENGTH = 50   # minimum characters for a real abstract
AUTHOR_OK_COUNT = 1       # at least 1 named author
DATE_CONFIDENCE_OK = {"A", "B"}


def is_placeholder_abstract(text: str | None) -> bool:
    """Return True when the text is a boilerplate placeholder, not a real abstract."""
    if not text:
        return True
    cleaned = text.strip()
    if len(cleaned) < ABSTRACT_OK_LENGTH:
        return True
    # Common boilerplate prefixes
    boilerplate_prefixes = (
        "abstractthis",
        "abstract this",
        "abstract. this",
        "abstract :",
        "abstractabstract",
    )
    lower = cleaned.lower()
    if lower.startswith(boilerplate_prefixes):
        return True
    # Subscription/login placeholders
    placeholder_keywords = (
        "you do not currently have access",
        "please login",
        "to access this article",
        "sign in to access",
        "subscribe to access",
        "purchase access",
        "institutional login",
        "check your access",
    )
    for kw in placeholder_keywords:
        if kw in lower:
            return True
    return False


def record_needs_abstract(record: dict[str, Any]) -> bool:
    """A record needs abstract recovery."""
    abstract = record.get("abstract")
    return is_placeholder_abstract(abstract)


def record_needs_authors(record: dict[str, Any]) -> bool:
    """A record needs author recovery."""
    authors = record.get("authors", [])
    if not authors:
        return True
    if isinstance(authors, list):
        return len(authors) < AUTHOR_OK_COUNT
    if isinstance(authors, str):
        try:
            parsed = json.loads(authors)
            return len(parsed) < AUTHOR_OK_COUNT
        except (json.JSONDecodeError, TypeError):
            return True
    return True


def record_needs_date(record: dict[str, Any]) -> bool:
    """A record has missing or low-confidence official date."""
    confidence = str(record.get("date_confidence") or "")
    if confidence in DATE_CONFIDENCE_OK:
        return False
    # Missing date entirely
    has_date = bool(
        record.get("available_online")
        or record.get("published_online")
        or record.get("official_date")
    )
    return not has_date or confidence not in DATE_CONFIDENCE_OK


def needs_recovery(record: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Return (needs_abstract, needs_authors, needs_date)."""
    needs_abs = record_needs_abstract(record)
    needs_auth = record_needs_authors(record)
    needs_dt = record_needs_date(record)
    return (needs_abs, needs_auth, needs_dt)


def load_canonical_records() -> list[tuple[Path, list[dict[str, Any]]]]:
    """Load all records from data/daily/*.json, returning (path, records)."""
    daily_dir = DATA_DIR / "daily"
    if not daily_dir.exists():
        return []
    results = []
    for f in sorted(daily_dir.glob("*.json")):
        records = read_json(f, [])
        if isinstance(records, list) and records:
            results.append((f, records))
    return results


def deduplicate_candidates(
    files_records: list[tuple[Path, list[dict[str, Any]]]],
) -> dict[str, dict[str, Any]]:
    """Deduplicate records across daily files by DOI, keeping the most complete version.

    Returns {doi: record} for records needing recovery. DOI is the primary key;
    records without DOI use a title-based key.
    """
    candidates: dict[str, dict[str, Any]] = {}
    seen_keys: set[str] = set()

    for fpath, records in files_records:
        for record in records:
            doi = normalize_doi(record.get("doi"))
            title = (record.get("title") or "").strip().lower()

            # Use DOI as primary key; fall back to title hash
            if doi:
                key = f"doi:{doi}"
            elif title:
                # Simple title-based dedup: first 100 chars normalized
                key = f"title:{title[:100]}"
            else:
                continue

            if key in seen_keys:
                continue
            seen_keys.add(key)

            needs_abs, needs_auth, needs_dt = needs_recovery(record)
            if not (needs_abs or needs_auth or needs_dt):
                continue

            candidates[key] = record

    return candidates


def recover_openalex(
    doi: str, timeout: int = 30
) -> dict[str, Any]:
    """Call OpenAlex API for a single DOI."""
    try:
        result = openalex_doi_metadata(doi, timeout)
        # Upgrade date_confidence from C to B when publication_date is present
        if result.get("date_confidence") == "C":
            parsed = result.get("published_online") or result.get("available_online")
            if parsed and parse_date(parsed):
                result["date_confidence"] = "B"
                result["date_source"] = "openalex_publication_date_crossvalidated"
        return result
    except Exception:
        return {}


def recover_semantic_scholar(
    doi: str, timeout: int = 30
) -> dict[str, Any]:
    """Call Semantic Scholar API for a single DOI."""
    try:
        result = semantic_scholar_doi_metadata(doi, timeout)
        # Add date_confidence when publicationDate is present
        if result.get("published_online") and not result.get("date_confidence"):
            result["date_confidence"] = "C"
            result["date_source"] = "semantic_scholar_publication_date"
        return result
    except Exception:
        return {}


def apply_recovery(
    record: dict[str, Any],
    metadata: dict[str, Any],
    source: str,
) -> list[str]:
    """Apply recovered metadata to a record. Returns list of fields recovered."""
    recovered = []
    confidence_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4, "unknown": 5, "": 6}

    # Abstract recovery
    if record_needs_abstract(record):
        abstract = metadata.get("abstract", "")
        if abstract and not is_placeholder_abstract(abstract) and len(abstract) >= ABSTRACT_OK_LENGTH:
            record["abstract"] = abstract
            record["abstract_source"] = metadata.get("abstract_source", source)
            recovered.append("abstract")

    # Author recovery
    if record_needs_authors(record):
        authors = metadata.get("authors", [])
        if authors and len(authors) >= AUTHOR_OK_COUNT:
            record["authors"] = authors
            recovered.append("authors")

    # Date recovery (only upgrade when existing confidence is lower)
    if record_needs_date(record):
        existing_conf = str(record.get("date_confidence") or "")
        incoming_conf = str(metadata.get("date_confidence") or "")
        if confidence_rank.get(incoming_conf, 6) < confidence_rank.get(existing_conf, 6):
            for date_field in ("available_online", "published_online"):
                if metadata.get(date_field):
                    record[date_field] = metadata[date_field]
            if metadata.get("date_source"):
                record["date_source"] = metadata["date_source"]
            if metadata.get("date_confidence"):
                record["date_confidence"] = metadata["date_confidence"]
            recovered.append("date")

    return recovered


def run_batch_recovery(
    candidates: dict[str, dict[str, Any]],
    dry_run: bool = False,
    skip_semantic_scholar: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    """Run batch recovery across all candidates.

    Returns recovery report dict.
    """
    report = {
        "generated_at": datetime.now(BEIJING_TZ).isoformat(),
        "total_candidates": len(candidates),
        "recovered_abstracts": 0,
        "recovered_authors": 0,
        "recovered_dates": 0,
        "openalex_calls": 0,
        "openalex_success": 0,
        "semantic_scholar_calls": 0,
        "semantic_scholar_success": 0,
        "no_doi_skipped": 0,
        "errors": 0,
        "per_source": {},
    }

    # Separate candidates with and without DOI
    doi_candidates = {}
    no_doi = {}
    for key, record in candidates.items():
        doi = normalize_doi(record.get("doi"))
        if doi:
            doi_candidates[key] = (record, doi)
        else:
            no_doi[key] = record

    report["no_doi_skipped"] = len(no_doi)

    def process_one(item):
        key, (record, doi) = item
        try:
            # Try OpenAlex first
            oa_md = recover_openalex(doi, timeout)
            result = {"key": key, "source": "openalex", "recovered": []}
            report["openalex_calls"] += 1
            if oa_md:
                report["openalex_success"] += 1
                result["recovered"] = apply_recovery(record, oa_md, "openalex")
                if result["recovered"]:
                    return result

            # Then Semantic Scholar if OpenAlex didn't help
            if not skip_semantic_scholar:
                time.sleep(0.1)  # polite pause
                ss_md = recover_semantic_scholar(doi, timeout)
                report["semantic_scholar_calls"] += 1
                if ss_md:
                    report["semantic_scholar_success"] += 1
                    recovered = apply_recovery(record, ss_md, "semantic_scholar")
                    if recovered:
                        result["source"] = "semantic_scholar"
                        result["recovered"] = recovered
                        return result

            return result
        except Exception as e:
            report["errors"] += 1
            return {"key": key, "error": str(e), "recovered": []}

    items = list(doi_candidates.items())
    # Process in batches of 10 with polite pauses
    batch_size = 10
    all_results = []
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        with ThreadPoolExecutor(max_workers=min(3, len(batch))) as executor:
            futures = {executor.submit(process_one, item): item for item in batch}
            for future in as_completed(futures):
                result = future.result()
                all_results.append(result)
                for field in result.get("recovered", []):
                    report[f"recovered_{field}s"] += 1
        if i + batch_size < len(items):
            time.sleep(1.0)  # polite pause between batches

    # Write per-source recovery counts
    for r in all_results:
        source = r.get("source", "none")
        report["per_source"][source] = report["per_source"].get(source, 0) + 1

    return report


def rewrite_updated_daily_files(
    files_records: list[tuple[Path, list[dict[str, Any]]]],
    dry_run: bool = False,
) -> list[Path]:
    """Write updated records back to daily JSON files."""
    updated_files = []
    for fpath, _ in files_records:
        # Re-read to get latest state
        records = read_json(fpath, [])
        if not dry_run:
            write_json(fpath, records)
            updated_files.append(fpath)
    return updated_files


def main():
    parser = argparse.ArgumentParser(
        description="Batch recovery of missing abstracts, authors, and dates"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Do not write changes to disk"
    )
    parser.add_argument(
        "--days", type=int, default=0,
        help="Only process daily files from the last N days (0 = all)"
    )
    parser.add_argument(
        "--skip-semantic-scholar", action="store_true",
        help="Skip Semantic Scholar, only use OpenAlex"
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="HTTP timeout in seconds"
    )
    args = parser.parse_args()

    print(f"Loading canonical records...")
    files_records = load_canonical_records()

    # Filter by days if requested
    if args.days > 0:
        cutoff = (datetime.now(BEIJING_TZ).date() - timedelta(days=args.days)).isoformat()
        files_records = [
            (f, r) for f, r in files_records
            if f.stem >= cutoff
        ]

    total_records = sum(len(r) for _, r in files_records)
    print(f"Loaded {total_records} records from {len(files_records)} daily files")

    # Deduplicate and find candidates
    print(f"Deduplicating and finding candidates...")
    candidates = deduplicate_candidates(files_records)
    print(f"Found {len(candidates)} unique records needing recovery")

    if not candidates:
        print("No candidates found. Exiting.")
        return

    # Run batch recovery
    print(f"Running batch recovery (dry_run={args.dry_run})...")
    report = run_batch_recovery(
        candidates,
        dry_run=args.dry_run,
        skip_semantic_scholar=args.skip_semantic_scholar,
        timeout=args.timeout,
    )

    # Write back
    if not args.dry_run:
        print(f"Writing updates to daily files...")
        updated = rewrite_updated_daily_files(files_records, dry_run=False)
        print(f"Updated {len(updated)} daily files")

    # Write report
    write_json(RECOVERY_REPORT_PATH, report)

    print(f"\n--- Recovery Report ---")
    print(f"Total candidates:      {report['total_candidates']}")
    print(f"No DOI skipped:        {report['no_doi_skipped']}")
    print(f"OpenAlex calls:        {report['openalex_calls']} (success: {report['openalex_success']})")
    print(f"Semantic Scholar calls:{report['semantic_scholar_calls']} (success: {report['semantic_scholar_success']})")
    print(f"Abstracts recovered:   {report['recovered_abstracts']}")
    print(f"Authors recovered:     {report['recovered_authors']}")
    print(f"Dates recovered:       {report['recovered_dates']}")
    print(f"Errors:                {report['errors']}")
    print(f"Report written to:     {RECOVERY_REPORT_PATH}")


if __name__ == "__main__":
    main()