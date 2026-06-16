"""Fetch recent journal article metadata from Crossref by ISSN."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from common import (
    DATA_DIR,
    USER_AGENT,
    date_from_parts,
    first_text,
    load_journals,
    filter_journals_by_tier,
    polite_sleep,
    recent_cutoff,
    today_str,
    write_json,
)
from sources.record import article_record
from sources.registry import load_registry, save_registry
from status import record_source


def author_name(author: dict[str, Any]) -> str:
    parts = [author.get("given"), author.get("family")]
    name = " ".join(str(part) for part in parts if part)
    return name or str(author.get("name") or "")


def parse_item(item: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    published_online = date_from_parts(item.get("published-online"))
    published = date_from_parts(item.get("published"))
    published_print = date_from_parts(item.get("published-print"))
    issued = date_from_parts(item.get("issued"))
    created = date_from_parts(item.get("created"))
    best_date = published_online or published or published_print or issued or created
    if published_online:
        date_source = "crossref_published_online"
        confidence = "C"
    elif published:
        date_source = "crossref_published"
        confidence = "C"
    elif published_print or issued:
        date_source = "crossref_issue"
        confidence = "D"
    elif created:
        date_source = "crossref_created"
        confidence = "D"
    else:
        date_source = None
        confidence = "F"
    record = article_record(
        journal,
        title=first_text(item.get("title")) or "",
        url=item.get("URL"),
        source="crossref",
        source_url="https://api.crossref.org",
        doi=item.get("DOI"),
        authors=[author_name(author) for author in item.get("author", [])],
        abstract=item.get("abstract"),
        published_online=best_date,
        issue_date=published_print or issued,
        date_source=date_source,
        date_confidence=confidence,
        raw_data={"crossref_date_source": date_source},
    )
    record["publisher"] = item.get("publisher") or journal.get("publisher")
    record["translation_status"] = "missing_abstract" if not item.get("abstract") else "skipped"
    return record


def normalize_issn(value: str | None) -> str | None:
    if not value:
        return None
    compact = value.replace("-", "").strip().upper()
    if len(compact) != 8:
        return value.strip()
    return f"{compact[:4]}-{compact[4:]}"


def journal_issns(journal: dict[str, Any]) -> list[str]:
    registry = load_registry()
    registry_entry = registry.get("journals", {}).get(journal["id"], {})
    values = [
        journal.get("issn"),
        journal.get("eissn"),
        journal.get("online_issn"),
        journal.get("print_issn"),
        registry_entry.get("issn"),
        registry_entry.get("online_issn"),
        registry_entry.get("print_issn"),
    ]
    for source in journal.get("sources", []):
        if source.get("type") == "crossref" and source.get("issn"):
            values.append(source.get("issn"))
    return [issn for issn in dict.fromkeys(normalize_issn(str(value)) for value in values if value) if issn]


def crossref_get(url: str, params: dict[str, Any], timeout: int, retries: int, sleep: float) -> Any:
    mailto = os.environ.get("CROSSREF_MAILTO")
    if mailto:
        params["mailto"] = mailto
    query = urllib.parse.urlencode(params)
    request_url = f"{url}?{query}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(request_url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except urllib.error.URLError as exc:
            last_error = exc
        polite_sleep(sleep * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("empty Crossref response")


def fetch_for_journal(journal: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    issns = journal_issns(journal)
    if not issns:
        return []

    records = []
    seen: set[str] = set()
    for issn in issns:
        params = {
            "filter": f"from-pub-date:{recent_cutoff(args.days)}",
            "sort": "published",
            "order": "desc",
            "rows": args.rows,
            "select": "DOI,URL,title,container-title,author,publisher,published,published-online,published-print,issued,created,abstract,type",
        }
        try:
            payload = crossref_get(
                f"https://api.crossref.org/journals/{urllib.parse.quote(issn)}/works",
                params=params,
                timeout=args.timeout,
                retries=args.retries,
                sleep=args.sleep,
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            fallback_params = dict(params)
            fallback_params["filter"] = f"issn:{issn},from-pub-date:{recent_cutoff(args.days)}"
            payload = crossref_get(
                "https://api.crossref.org/works",
                params=fallback_params,
                timeout=args.timeout,
                retries=args.retries,
                sleep=args.sleep,
            )
        for item in payload.get("message", {}).get("items", []):
            if item.get("type") not in {None, "journal-article"}:
                continue
            record = parse_item(item, journal)
            key = (record.get("doi") or record.get("url") or record.get("title") or "").casefold()
            if not key or key in seen:
                continue
            seen.add(key)
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
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--tier", default=None)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "crossref" / f"{today_str()}.json"
    records: list[dict[str, Any]] = []
    messages: list[str] = []
    journals = filter_journals_by_tier(load_journals(args.journals), args.tier)
    if args.only:
        selected_ids = set(args.only)
        journals = [journal for journal in journals if journal.get("id") in selected_ids]
    selected = journals[: args.limit] if args.limit else journals
    registry = load_registry()

    for journal in selected:
        registry_entry = registry.setdefault("journals", {}).setdefault(journal["id"], {})
        try:
            fetched = fetch_for_journal(journal, args)
            records.extend(fetched)
            registry_entry["last_crossref_count"] = len(fetched)
            registry_entry["last_crossref_status"] = "ok"
            registry_entry["last_crossref_error"] = None
            messages.append(f"{journal.get('title')}: {len(fetched)}")
        except Exception as exc:  # noqa: BLE001 - keep the scheduled job moving.
            registry_entry["last_crossref_count"] = 0
            registry_entry["last_crossref_status"] = "error"
            registry_entry["last_crossref_error"] = f"{type(exc).__name__}: {exc}"
            messages.append(f"{journal.get('title')}: error {type(exc).__name__}: {exc}")
            print(f"crossref error for {journal.get('title')}: {exc}")
        polite_sleep(args.sleep)

    save_registry(registry)
    write_json(output, records)
    record_source("crossref", ok=True, count=len(records), message="; ".join(messages[-30:]) or str(output))
    print(f"wrote {len(records)} Crossref records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
