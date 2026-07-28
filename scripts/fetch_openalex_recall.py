"""Fetch an independent OpenAlex recall pass for formal journals.

OpenAlex is deliberately a recall source, not proof of first online. Records
from this adapter carry low-confidence publication dates and therefore cannot
drive the public "today" stream by themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import DATA_DIR, load_journals, today_str, write_json
from sources.record import article_record
from status import record_source


# These are the formal journals currently relying on Crossref as their only
# usable path. Keep the list explicit so adding a recall source does not
# silently broaden the formal journal scope.
RECALL_JOURNALS = {
    "journal-of-political-economy",
    "quarterly-journal-of-economics",
    "economic-journal",
    "journal-of-the-european-economic-association",
    "international-journal-of-game-theory",
    "theoretical-economics",
    "economic-theory",
    "review-of-economic-design",
    "journal-of-law-economics-and-organization",
    "social-choice-and-welfare",
    "public-choice",
    "international-tax-and-public-finance",
    "review-of-financial-studies",
    "economic-development-and-cultural-change",
    "quantitative-economics",
    "applied-economics",
    "journal-of-economic-growth",
    "journal-of-population-economics",
    "journal-of-labor-economics",
    "journal-of-law-and-economics",
    "journal-of-the-association-of-environmental-and-resource-economists",
    "european-review-of-agricultural-economics",
    "environmental-and-resource-economics",
    "journal-of-agricultural-and-resource-economics",
}

USER_AGENT = "AcademicDoorPaperMonitor/1.0 (mailto:academic-door@users.noreply.github.com)"


def compact_issn(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch.upper() == "X").upper()


def openalex_issn(value: str | None) -> str:
    compact = compact_issn(value)
    return f"{compact[:4]}-{compact[4:]}" if len(compact) == 8 else compact


def abstract_from_inverted_index(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    words: list[tuple[int, str]] = []
    for token, positions in value.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words.append((position, str(token)))
    if not words:
        return None
    return " ".join(token for _, token in sorted(words))


def openalex_get(params: dict[str, str], timeout: int) -> dict[str, Any]:
    params = dict(params)
    params.setdefault("mailto", os.environ.get("OPENALEX_MAILTO", "academic-door@users.noreply.github.com"))
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def author_names(work: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = str((author or {}).get("display_name") or "").strip() if isinstance(author, dict) else ""
        if name and name not in values:
            values.append(name)
    return values[:12]


def fetch_journal(journal: dict[str, Any], *, days: int, rows: int, timeout: int) -> list[dict[str, Any]]:
    issn = compact_issn(journal.get("issn"))
    if len(issn) != 8:
        return []
    start = (date.today() - timedelta(days=days)).isoformat()
    payload = openalex_get(
        {
            "filter": f"primary_location.source.issn:{openalex_issn(issn)},from_publication_date:{start}",
            "sort": "publication_date:desc",
            "per-page": str(rows),
            "select": "id,doi,title,publication_date,authorships,abstract_inverted_index,primary_location,type",
        },
        timeout,
    )
    records: list[dict[str, Any]] = []
    for work in payload.get("results") or []:
        if str(work.get("type") or "").casefold() not in {"article", "journal-article", ""}:
            continue
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        source_issn = compact_issn(source.get("issn_l") or source.get("issn"))
        if source_issn and source_issn != issn:
            continue
        title = str(work.get("title") or "").strip()
        if not title:
            continue
        doi = str(work.get("doi") or "").strip()
        url = doi or str(location.get("landing_page_url") or work.get("id") or "")
        published = str(work.get("publication_date") or "")[:10] or None
        records.append(
            article_record(
                journal,
                title=title,
                url=url,
                source="openalex_recall",
                source_url="https://api.openalex.org/works",
                doi=doi.removeprefix("https://doi.org/") or None,
                authors=author_names(work),
                abstract=abstract_from_inverted_index(work.get("abstract_inverted_index")),
                published_online=published,
                available_online=published,
                issue_date=published,
                date_source="openalex_publication_date",
                date_confidence="C",
                raw_data={"openalex_id": work.get("id"), "recall_only": True},
            )
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--rows", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    journals = {str(j.get("id")): j for j in load_journals()}
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for journal_id in sorted(RECALL_JOURNALS):
        journal = journals.get(journal_id)
        if not journal:
            failures.append(f"{journal_id}: missing from journals.yml")
            continue
        try:
            fetched = fetch_journal(journal, days=args.days, rows=args.rows, timeout=args.timeout)
            records.extend(fetched)
            print(f"{journal_id}: {len(fetched)}")
        except Exception as exc:  # noqa: BLE001 - one source must not stop recall.
            failures.append(f"{journal_id}: {type(exc).__name__}: {exc}")
            print(f"{journal_id}: failed: {type(exc).__name__}: {exc}")
        time.sleep(max(0.0, args.sleep))

    output = args.output or DATA_DIR / "raw" / "openalex-recall" / f"{today_str()}.json"
    write_json(output, records)
    record_source(
        "openalex-recall",
        ok=bool(records),
        count=len(records),
        message="; ".join(failures[-8:]) or str(output),
        details={"journals": len(RECALL_JOURNALS), "failed_journals": len(failures), "recall_only": True},
    )
    print(f"wrote {len(records)} OpenAlex recall records to {output}; failures={len(failures)}")


if __name__ == "__main__":
    main()
