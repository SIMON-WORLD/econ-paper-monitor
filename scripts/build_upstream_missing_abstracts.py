"""Build a closed list of upstream records that will never carry an abstract.

Records with a DOI stay in the metadata retry/recovery pipeline.  Records
without a DOI (CNKI uploads, NEP aggregates, book reviews, working-paper
indexes, etc.) often have no abstract upstream; repeatedly hammering them is
noise.  This script writes ``data/upstream_missing_abstracts.json`` so the
missing-abstract debt is explicit and bounded.

It also fixes the known ``abstract_as_title`` case (AJARE book review): when a
title is duplicated verbatim as the abstract, the abstract is cleared and the
record is included in the upstream list with ``book_review`` as the reason.

Data line only: reads/writes ``data/**``.  Idempotent.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, now_iso, write_json


def norm_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def missing_abstract(record: dict[str, Any]) -> bool:
    return not str(record.get("abstract") or "").strip()


def looks_like_book_review(record: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(record.get(key) or "")
        for key in ("title", "source_issue", "journal", "url")
    )
    return "isbn" in haystack.casefold() or "book review" in haystack.casefold()


def title_as_abstract(record: dict[str, Any]) -> bool:
    title = norm_text(record.get("title"))
    abstract = norm_text(record.get("abstract"))
    if not title or not abstract:
        return False
    return abstract == title or abstract.startswith(title)


def fix_book_review_title(record: dict[str, Any]) -> bool:
    """Shorten a book-review title that embeds the full citation (>260 chars)."""
    if not looks_like_book_review(record):
        return False
    text = str(record.get("title") or "").strip()
    if len(text) <= 260:
        return False
    short = re.split(r"\s+By\s+", text, maxsplit=1)[0].strip()
    if not short or len(short) >= len(text):
        return False
    raw = record.get("raw_data")
    if not isinstance(raw, dict):
        raw = {}
        record["raw_data"] = raw
    raw.setdefault("book_review_full_title", text)
    record["title"] = short
    return True


def upstream_reason(record: dict[str, Any]) -> str:
    source_type = str(record.get("source_type") or "")
    source = str(record.get("source") or "")
    if looks_like_book_review(record) or title_as_abstract(record):
        return "book_review"
    if source == "working_papers" or source_type in {
        "working_paper",
        "policy_paper",
        "policy_commentary",
        "aggregator",
    }:
        return "working_paper_no_abstract"
    if source in {"cn-official", "cnki-rss"} or source_type in {"cn_journal", "cnki"}:
        return "cn_upstream_no_abstract"
    return "upstream_no_abstract"


def upstream_entry(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "journal": record.get("journal") or record.get("journal_id"),
        "title": record.get("title"),
        "url": record.get("url"),
        "doi": record.get("doi"),
        "source": record.get("source"),
        "source_type": record.get("source_type"),
        "source_issue": record.get("source_issue"),
        "date": record.get("first_seen") or record.get("detected_at") or record.get("available_online"),
        "detail_key": record.get("detail_key"),
        "reason": upstream_reason(record),
    }


def process_batch(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    upstream: list[dict[str, Any]] = []
    fixed = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        if fix_book_review_title(record):
            fixed += 1
        if missing_abstract(record):
            if record.get("doi"):
                continue
            upstream.append(upstream_entry(record))
            continue
        if looks_like_book_review(record) and title_as_abstract(record):
            record["abstract"] = None
            record["abstract_source"] = None
            record["abstract_status_code"] = "book_review_title_as_abstract"
            fixed += 1
        if looks_like_book_review(record) and (
            not str(record.get("abstract") or "").strip() or str(record.get("abstract_status_code") or "") == "book_review_title_as_abstract"
        ):
            upstream.append(upstream_entry(record))
    return upstream, fixed


def build_list(data_dir: Path, *, write: bool = True) -> dict[str, Any]:
    upstream: list[dict[str, Any]] = []
    with_doi_retryable = 0
    daily_fixed = 0
    seen_fixed = 0
    daily_dir = data_dir / "daily"
    for path in sorted(daily_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        batch_upstream, batch_fixed = process_batch(payload)
        upstream.extend(batch_upstream)
        with_doi_retryable += sum(
            1
            for record in payload
            if isinstance(record, dict) and missing_abstract(record) and record.get("doi")
        )
        daily_fixed += batch_fixed
        if batch_fixed and write:
            write_json(path, payload)

    seen_path = data_dir / "seen.json"
    seen_payload = json.loads(seen_path.read_text(encoding="utf-8"))
    papers = seen_payload.get("papers") if isinstance(seen_payload, dict) else {}
    seen_records = [papers[key] for key in papers if isinstance(papers.get(key), dict)]
    _seen_upstream, batch_fixed = process_batch(seen_records)
    seen_fixed = batch_fixed
    if batch_fixed and write:
        write_json(seen_path, seen_payload)

    report = {
        "generated_at": now_iso(),
        "with_doi_retryable": with_doi_retryable,
        "without_doi_upstream": len(upstream),
        "daily_abstract_as_title_fixed": daily_fixed,
        "seen_abstract_as_title_fixed": seen_fixed,
        "records": upstream,
    }
    if write:
        write_json(data_dir / "upstream_missing_abstracts.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = build_list(args.data_dir, write=not args.dry_run)
    print(
        "without_doi_upstream="
        f"{report['without_doi_upstream']} "
        f"abstract_as_title_fixed={report['daily_abstract_as_title_fixed'] + report['seen_abstract_as_title_fixed']}"
    )


if __name__ == "__main__":
    main()
