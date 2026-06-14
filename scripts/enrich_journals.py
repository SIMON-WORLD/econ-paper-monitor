"""Enrich journals.yml with ISSN and publisher metadata from Crossref."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path
from typing import Any

from common import (
    DATA_DIR,
    fetch_json,
    load_journals,
    normalize_text,
    polite_sleep,
    write_journals,
    yaml_quote,
)


def score_match(query_title: str, candidate: dict[str, Any]) -> float:
    candidate_title = str(candidate.get("title") or "")
    query_norm = normalize_text(query_title)
    candidate_norm = normalize_text(candidate_title)
    if candidate_norm.startswith(query_norm):
        return 0.95
    return difflib.SequenceMatcher(
        None,
        query_norm,
        candidate_norm,
    ).ratio()


def search_crossref_journal(title: str, rows: int, timeout: int) -> list[dict[str, Any]]:
    payload = fetch_json(
        "https://api.crossref.org/journals",
        params={"query": title, "rows": rows},
        timeout=timeout,
    )
    return payload.get("message", {}).get("items", [])


def best_candidate(journal: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    title = str(journal["title"])
    titles = [title]
    if "&" in title:
        titles.append(title.replace("&", "and"))
    if ":" in title:
        titles.append(title.replace(":", ""))
    if args.include_aliases:
        titles.extend(journal.get("aliases", []))
    seen: dict[str, dict[str, Any]] = {}
    for title in titles:
        if not title or any(ord(ch) > 127 for ch in str(title)):
            continue
        for item in search_crossref_journal(str(title), args.rows, args.timeout):
            key = str(item.get("title") or "") + "|" + ",".join(item.get("ISSN", []))
            seen[key] = item
    if not seen:
        return None
    return max(seen.values(), key=lambda item: score_match(str(journal["title"]), item))


def set_crossref_source_issn(journal: dict[str, Any], issn: str | None) -> None:
    sources = journal.setdefault("sources", [])
    for source in sources:
        if source.get("type") == "crossref":
            source["issn"] = issn
            return
    sources.append({"type": "crossref", "issn": issn})


def render_review(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# Low-confidence or skipped journal matches from scripts/enrich_journals.py.",
        "matches:",
    ]
    for entry in entries:
        lines.extend(
            [
                f"  - id: {yaml_quote(str(entry['id']))}",
                f"    title: {yaml_quote(str(entry['title']))}",
                f"    reason: {yaml_quote(str(entry['reason']))}",
                f"    score: {entry.get('score', 0):.3f}",
                f"    candidate_title: {yaml_quote(str(entry.get('candidate_title') or ''))}",
                f"    candidate_issn: {yaml_quote(str(entry.get('candidate_issn') or ''))}",
                f"    candidate_publisher: {yaml_quote(str(entry.get('candidate_publisher') or ''))}",
            ]
        )
    return "\n".join(lines) + "\n"


def enrich(args: argparse.Namespace) -> None:
    journals = load_journals(args.input)
    review: list[dict[str, Any]] = []
    updated = 0

    for index, journal in enumerate(journals):
        if args.limit and index >= args.limit:
            break
        if journal.get("issn") and journal.get("publisher"):
            continue
        title = str(journal.get("title") or "")
        if any(ord(ch) > 127 for ch in title):
            review.append(
                {
                    "id": journal["id"],
                    "title": title,
                    "reason": "non_latin_title_skipped",
                }
            )
            continue
        try:
            candidate = best_candidate(journal, args)
        except Exception as exc:  # noqa: BLE001 - preserve failures for review.
            review.append(
                {
                    "id": journal["id"],
                    "title": title,
                    "reason": f"crossref_error: {exc}",
                }
            )
            continue
        finally:
            polite_sleep(args.sleep)

        if not candidate:
            review.append({"id": journal["id"], "title": title, "reason": "no_candidate"})
            continue

        score = score_match(title, candidate)
        issns = candidate.get("ISSN") or []
        primary_issn = issns[0] if issns else None
        if score >= args.min_score and primary_issn:
            journal["issn"] = primary_issn
            journal["publisher"] = candidate.get("publisher") or journal.get("publisher")
            set_crossref_source_issn(journal, primary_issn)
            updated += 1
        else:
            review.append(
                {
                    "id": journal["id"],
                    "title": title,
                    "reason": "low_confidence",
                    "score": score,
                    "candidate_title": candidate.get("title"),
                    "candidate_issn": ", ".join(issns),
                    "candidate_publisher": candidate.get("publisher"),
                }
            )

    if not args.dry_run:
        write_journals(args.output, journals)
        args.review.write_text(render_review(review), encoding="utf-8")

    print(f"journals={len(journals)} updated={updated} review={len(review)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--review", type=Path, default=DATA_DIR / "journal_match_review.yml")
    parser.add_argument("--rows", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-score", type=float, default=0.88)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--include-aliases", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    enrich(args)


if __name__ == "__main__":
    main()
