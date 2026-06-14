"""Fetch recent journal article metadata from Crossref by ISSN."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import (
    DATA_DIR,
    date_from_parts,
    fetch_json,
    first_text,
    load_journals,
    now_iso,
    polite_sleep,
    recent_cutoff,
    today_str,
    write_json,
)


def author_name(author: dict[str, Any]) -> str:
    parts = [author.get("given"), author.get("family")]
    name = " ".join(str(part) for part in parts if part)
    return name or str(author.get("name") or "")


def parse_item(item: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    published = (
        date_from_parts(item.get("published-online"))
        or date_from_parts(item.get("published-print"))
        or date_from_parts(item.get("issued"))
    )
    return {
        "title": first_text(item.get("title")) or "",
        "title_zh": None,
        "abstract": item.get("abstract"),
        "abstract_zh": None,
        "authors": [author_name(author) for author in item.get("author", [])],
        "journal": journal["title"],
        "journal_short": journal.get("short_name"),
        "journal_id": journal["id"],
        "source_type": "journal",
        "source": "crossref",
        "publisher": item.get("publisher") or journal.get("publisher"),
        "published_online": published,
        "detected_at": now_iso(),
        "doi": item.get("DOI"),
        "url": item.get("URL"),
        "pdf_url": None,
        "fields": journal.get("fields", []),
        "ai_tags": [],
        "translation_status": "missing_abstract" if not item.get("abstract") else "skipped",
    }


def fetch_for_journal(journal: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    issn = journal.get("issn")
    if not issn:
        for source in journal.get("sources", []):
            if source.get("type") == "crossref" and source.get("issn"):
                issn = source["issn"]
                break
    if not issn:
        return []

    payload = fetch_json(
        "https://api.crossref.org/works",
        params={
            "filter": f"issn:{issn},from-pub-date:{recent_cutoff(args.days)}",
            "sort": "published",
            "order": "desc",
            "rows": args.rows,
            "select": "DOI,URL,title,container-title,author,publisher,published-online,published-print,issued,abstract,type",
        },
        timeout=args.timeout,
    )
    records = []
    for item in payload.get("message", {}).get("items", []):
        if item.get("type") not in {None, "journal-article"}:
            continue
        record = parse_item(item, journal)
        if record["title"]:
            records.append(record)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "crossref" / f"{today_str()}.json"
    records: list[dict[str, Any]] = []
    journals = load_journals(args.journals)
    selected = journals[: args.limit] if args.limit else journals

    for journal in selected:
        try:
            records.extend(fetch_for_journal(journal, args))
        except Exception as exc:  # noqa: BLE001 - keep the scheduled job moving.
            print(f"crossref error for {journal.get('title')}: {exc}")
        polite_sleep(args.sleep)

    write_json(output, records)
    print(f"wrote {len(records)} Crossref records to {output}")


if __name__ == "__main__":
    main()
