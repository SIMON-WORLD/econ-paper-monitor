"""Fetch priority publisher TOC pages that are faster than Crossref.

This adapter is intentionally narrow.  It covers sources that matter for the
project's economics-journal scope and that external sentinels often see before
Crossref catches up: REStud advance articles and REStat current/advance pages.
"""

from __future__ import annotations

import argparse
import html
import re
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from common import DATA_DIR, load_journals, today_str, write_json
from sources.record import article_record
from status import record_source


TARGETS = {
    "review-of-economic-studies": [
        {
            "kind": "restud_advance",
            "url": "https://academic.oup.com/restud/advance-articles",
            "date_source": "oup_advance_articles",
            "date_confidence": "B",
        }
    ],
    "review-of-economics-and-statistics": [
        {
            "kind": "restat_current",
            "url": "https://direct.mit.edu/rest/issue/current",
            "date_source": "mitpress_current_issue",
            "date_confidence": "C",
        },
        {
            "kind": "restat_advance",
            "url": "https://direct.mit.edu/rest/advance-articles",
            "date_source": "mitpress_advance_articles",
            "date_confidence": "B",
        },
    ],
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def fetch_toc_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except Exception:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    for encoding in dict.fromkeys([charset, "utf-8", "latin-1"]):
        try:
            return payload.decode(encoding)
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def doi_from_text(value: str | None) -> str | None:
    match = re.search(r"(10\.\d{4,9}/[^\s\"'<>]+)", value or "", flags=re.I)
    if not match:
        return None
    return match.group(1).rstrip(").,;").lower()


def parse_date(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})", text)
    if match and match.group(1).casefold() in months:
        return f"{int(match.group(3)):04d}-{months[match.group(1).casefold()]:02d}-{int(match.group(2)):02d}"
    match = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})", text)
    if match and match.group(2).casefold() in months:
        return f"{int(match.group(3)):04d}-{months[match.group(2).casefold()]:02d}-{int(match.group(1)):02d}"
    return None


def meta_values(html_text: str, name: str) -> list[str]:
    values: list[str] = []
    patterns = [
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']',
    ]
    for pattern in patterns:
        values.extend(clean_text(match) for match in re.findall(pattern, html_text, flags=re.I | re.S))
    return [value for value in values if value]


def article_links(html_text: str, base_url: str) -> list[tuple[str, str]]:
    """Return article links from OUP/MIT pages with broad but safe patterns."""
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<title>.*?)</a>', html_text, flags=re.I | re.S):
        href = html.unescape(match.group("href")).strip()
        title = clean_text(match.group("title"))
        if not title or len(title) < 8:
            continue
        if not (
            "/restud/" in href
            or "/rest/" in href
            or "doi/10." in href
            or "10.1093/restud/" in href
            or "10.1162/rest" in href.lower()
        ):
            continue
        if any(skip in title.casefold() for skip in ("pdf", "permissions", "supplementary", "view metrics")):
            continue
        url = urljoin(base_url, href)
        key = url.split("?", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        links.append((url, title))
    return links


def enrich_detail(url: str, fallback_title: str, timeout: int) -> dict[str, object]:
    try:
        html_text = fetch_toc_text(url, timeout=timeout)
    except Exception:
        return {"title": fallback_title, "authors": [], "doi": doi_from_text(url)}
    title = (meta_values(html_text, "citation_title") or [fallback_title])[0]
    authors = meta_values(html_text, "citation_author")[:12]
    doi = (meta_values(html_text, "citation_doi") or [doi_from_text(url)])[0]
    published = (
        parse_date((meta_values(html_text, "citation_online_date") or [None])[0])
        or parse_date((meta_values(html_text, "citation_publication_date") or [None])[0])
        or parse_date((meta_values(html_text, "dc.Date") or [None])[0])
    )
    abstract = (meta_values(html_text, "citation_abstract") or [None])[0]
    return {
        "title": title,
        "authors": authors,
        "doi": doi,
        "published_online": published,
        "abstract": abstract,
    }


def fetch_target(journal: dict, target: dict[str, str], *, timeout: int, detail_limit: int, max_items: int) -> list[dict]:
    page_url = target["url"]
    html_text = fetch_toc_text(page_url, timeout=timeout)
    records: list[dict] = []
    for url, title in article_links(html_text, page_url):
        detail = enrich_detail(url, title, timeout) if len(records) < detail_limit else {"title": title, "doi": doi_from_text(url)}
        records.append(
            article_record(
                journal,
                title=str(detail.get("title") or title),
                url=url,
                source="priority_toc",
                source_url=page_url,
                doi=detail.get("doi") if isinstance(detail.get("doi"), str) else None,
                authors=detail.get("authors") if isinstance(detail.get("authors"), list) else [],
                abstract=detail.get("abstract") if isinstance(detail.get("abstract"), str) else None,
                published_online=detail.get("published_online") if isinstance(detail.get("published_online"), str) else None,
                available_online=detail.get("published_online") if isinstance(detail.get("published_online"), str) else None,
                date_source=target["date_source"],
                date_confidence=target["date_confidence"],
                raw_data={"priority_toc_kind": target["kind"]},
            )
        )
        if len(records) >= max_items:
            break
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--detail-limit", type=int, default=12)
    parser.add_argument("--max-items-per-source", type=int, default=40)
    args = parser.parse_args()

    journals = {str(journal.get("id")): journal for journal in load_journals(args.journals)}
    output = args.output or DATA_DIR / "raw" / "priority-toc" / f"{today_str()}.json"
    records: list[dict] = []
    messages: list[str] = []
    failures = 0
    for journal_id, targets in TARGETS.items():
        journal = journals.get(journal_id)
        if not journal:
            continue
        journal_count = 0
        for target in targets:
            try:
                fetched = fetch_target(
                    journal,
                    target,
                    timeout=args.timeout,
                    detail_limit=args.detail_limit,
                    max_items=args.max_items_per_source,
                )
                records.extend(fetched)
                journal_count += len(fetched)
                messages.append(f"{journal_id}/{target['kind']}: {len(fetched)}")
            except Exception as exc:  # noqa: BLE001 - source health is reported below.
                failures += 1
                messages.append(f"{journal_id}/{target['kind']}: {type(exc).__name__}: {exc}")
        if journal_count == 0:
            messages.append(f"{journal_id}: 0")

    write_json(output, records)
    record_source(
        "priority-toc",
        ok=bool(records) or failures == 0,
        count=len(records),
        message="; ".join(messages[-20:]) or str(output),
    )
    print(f"wrote {len(records)} priority TOC records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
