"""Fetch American Economic Association journal TOC pages.

AEA does not expose the simple RSS endpoints used by ScienceDirect/Wiley.
Their current-issue and forthcoming pages are stable enough to serve as a
fast-path source for AER, AEJ journals, JEP, JEL, and P&P.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from urllib.parse import urljoin

from common import DATA_DIR, fetch_text, filter_journals_by_tier, load_journals, today_str, write_json
from sources.record import article_record
from status import record_source


BASE = "https://www.aeaweb.org"

AEA_CODES = {
    "american-economic-review": "aer",
    "american-economic-review-insights": "aeri",
    "journal-of-economic-literature": "jel",
    "journal-of-economic-perspectives": "jep",
    "american-economic-journal-applied-economics": "app",
    "american-economic-journal-economic-policy": "pol",
    "american-economic-journal-macroeconomics": "mac",
    "american-economic-journal-microeconomics": "mic",
    "american-economic-review-papers-and-proceedings": "pandp",
}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def meta_values(html_text: str, name: str) -> list[str]:
    values: list[str] = []
    patterns = [
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']',
    ]
    for pattern in patterns:
        values.extend(clean_text(match) for match in re.findall(pattern, html_text, flags=re.I | re.S))
    return [value for value in values if value]


def parse_year_month(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})[/-](\d{1,2})(?:[/-](\d{1,2}))?", value)
    if not match:
        return None
    day = int(match.group(3) or 1)
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{day:02d}"


def article_links(html_text: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    pattern = r'<a[^>]+href=["\'](?P<href>/articles\?id=10\.1257/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>'
    for match in re.finditer(pattern, html_text, flags=re.I | re.S):
        href = html.unescape(match.group("href")).replace("&amp;", "&")
        href = href.split("&&", 1)[0]
        title = clean_text(match.group("title"))
        if not title or title.casefold() == "front matter":
            continue
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        links.append((url, title))
    return links


def enrich_article(url: str, fallback_title: str, timeout: int) -> dict[str, object]:
    try:
        html_text = fetch_text(url, timeout=timeout)
    except Exception:
        return {
            "title": fallback_title,
            "authors": [],
            "doi": None,
            "issue_date": None,
            "source_issue": None,
        }
    title = (meta_values(html_text, "citation_title") or [fallback_title])[0]
    authors = meta_values(html_text, "citation_author")[:12]
    doi = (meta_values(html_text, "citation_doi") or [None])[0]
    pub_date = parse_year_month((meta_values(html_text, "citation_publication_date") or [None])[0])
    abstract = (meta_values(html_text, "citation_abstract") or [None])[0]
    return {
        "title": title,
        "authors": authors,
        "doi": doi,
        "issue_date": pub_date,
        "source_issue": (meta_values(html_text, "citation_journal_title") or [None])[0],
        "abstract": abstract,
    }


def fetch_journal(journal: dict, code: str, *, timeout: int, detail_limit: int, max_items: int) -> list[dict]:
    records: list[dict] = []
    pages = [
        ("current-issue", f"{BASE}/journals/{code}/current-issue"),
        ("forthcoming", f"{BASE}/journals/{code}/forthcoming"),
    ]
    for page_kind, page_url in pages:
        try:
            html_text = fetch_text(page_url, timeout=timeout)
        except Exception:
            continue
        for url, title in article_links(html_text):
            detail = enrich_article(url, title, timeout) if len(records) < detail_limit else {"title": title}
            records.append(
                article_record(
                    journal,
                    title=str(detail.get("title") or title),
                    url=url,
                    source="aea_toc",
                    source_url=page_url,
                    doi=detail.get("doi") if isinstance(detail.get("doi"), str) else None,
                    authors=detail.get("authors") if isinstance(detail.get("authors"), list) else [],
                    abstract=detail.get("abstract") if isinstance(detail.get("abstract"), str) else None,
                    issue_date=detail.get("issue_date") if isinstance(detail.get("issue_date"), str) else None,
                    source_issue=detail.get("source_issue") if isinstance(detail.get("source_issue"), str) else None,
                    date_source="aea_forthcoming" if page_kind == "forthcoming" else "aea_current_issue",
                    date_confidence="C",
                    raw_data={"aea_code": code, "aea_page": page_kind},
                )
            )
            if len(records) >= max_items:
                return records
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--tier", default=None)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--detail-limit", type=int, default=8)
    parser.add_argument("--max-items-per-journal", type=int, default=30)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "aea" / f"{today_str()}.json"
    records: list[dict] = []
    messages: list[str] = []
    journals = filter_journals_by_tier(load_journals(args.journals), args.tier)
    for journal in journals:
        code = AEA_CODES.get(str(journal.get("id") or ""))
        if not code:
            continue
        fetched = fetch_journal(
            journal,
            code,
            timeout=args.timeout,
            detail_limit=args.detail_limit,
            max_items=args.max_items_per_journal,
        )
        records.extend(fetched)
        messages.append(f"{journal.get('id')}: {len(fetched)}")

    write_json(output, records)
    record_source("aea-toc", ok=True, count=len(records), message="; ".join(messages) or str(output))
    print(f"wrote {len(records)} AEA records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
