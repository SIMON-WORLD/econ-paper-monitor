"""Backfill missing CEPR Discussion Paper authors from official detail pages."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from common import DATA_DIR, read_json, today_str, write_json
from fetch_preprints import enrich_record_from_detail, load_sources


def target_dates(days: int) -> set[str]:
    today = date.fromisoformat(today_str())
    return {(today - timedelta(days=offset)).isoformat() for offset in range(max(days, 1))}


def normalize_authors(values: list[str]) -> list[str]:
    """Flatten CEPR combined author meta values into a clean name list."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in str(value or "").split(";"):
            name = " ".join(part.split())
            key = name.casefold()
            if name and key not in seen:
                normalized.append(name)
                seen.add(key)
    return normalized[:12]


def apply_author_state(record: dict) -> None:
    if record.get("authors"):
        record["authors"] = normalize_authors(record["authors"])
        record["authors_status"] = None
        record["authors_status_code"] = "available"


def apply_abstract_state(record: dict) -> None:
    if str(record.get("abstract") or "").strip():
        record["abstract_completeness"] = "full"
        record["abstract_status"] = None
        record["abstract_status_code"] = "available"
        record["abstract_source"] = record.get("abstract_source") or "publisher_meta:description"
        record["abstract_enrichment_status"] = "available"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--sources", type=Path, default=DATA_DIR / "working_paper_sources.yml")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    cepr = next((source for source in load_sources(args.sources) if str(source.get("id")) == "cepr-dp"), None)
    if not cepr:
        print("CEPR source definition not found")
        return

    wanted = target_dates(args.days)
    checked = 0
    enriched = 0
    failures: list[tuple[str, str]] = []
    seen_payload = read_json(args.seen, {"papers": {}})
    papers = seen_payload.get("papers") if isinstance(seen_payload, dict) else {}

    for path in sorted(args.daily_dir.glob("*.json"), reverse=True):
        if path.stem not in wanted or checked >= args.limit:
            continue
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        changed = False
        for record in payload:
            if checked >= args.limit:
                break
            if record.get("source_id") != "cepr-dp" or record.get("authors") or not record.get("url"):
                continue
            checked += 1
            before = list(record.get("authors") or [])
            original_title = record.get("title")
            updated = enrich_record_from_detail(record, cepr, timeout=args.timeout)
            if original_title:
                updated["title"] = original_title
            apply_author_state(updated)
            apply_abstract_state(updated)
            if updated.get("authors") and updated.get("authors") != before:
                enriched += 1
                changed = True
                seen_key = str(record.get("id") or "")
                if seen_key and isinstance(papers, dict) and seen_key in papers:
                    papers[seen_key].update(updated)
            else:
                failures.append((str(record.get("url") or record.get("title")), "no authors returned"))
        if changed:
            write_json(path, payload)

    if isinstance(papers, dict) and enriched:
        seen_payload["papers"] = papers
        write_json(args.seen, seen_payload)

    print(f"CEPR author backfill: checked={checked} enriched={enriched} failures={len(failures)}")
    for url, reason in failures[:20]:
        print(f"  - {url}: {reason}")


if __name__ == "__main__":
    main()
