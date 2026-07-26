"""Fetch priority publisher TOC pages that are faster than Crossref.

This adapter is intentionally narrow.  It covers sources that matter for the
project's economics-journal scope and that external sentinels often see before
Crossref catches up: REStud advance articles, REStat current/advance pages,
and Econometrica forthcoming papers.
"""

from __future__ import annotations

import argparse
import html
import re
import ssl
import json
from datetime import date, timedelta
from urllib.parse import urlencode
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
            "fallback_urls": [
                "https://r.jina.ai/http://academic.oup.com/restud/advance-articles",
            ],
            "date_source": "oup_advance_articles",
            "date_confidence": "B",
            "fallback_issn": "0034-6527",
        }
    ],
    "review-of-economics-and-statistics": [
        {
            "kind": "restat_current",
            "url": "https://direct.mit.edu/rest/issue/current",
            "fallback_urls": [
                "https://r.jina.ai/http://direct.mit.edu/rest/issue/current",
            ],
            "date_source": "mitpress_current_issue",
            "date_confidence": "C",
            "fallback_issn": "0034-6535",
        },
        {
            "kind": "restat_advance",
            "url": "https://direct.mit.edu/rest/advance-articles",
            "fallback_urls": [
                "https://r.jina.ai/http://direct.mit.edu/rest/advance-articles",
            ],
            "date_source": "mitpress_advance_articles",
            "date_confidence": "B",
            "fallback_issn": "0034-6535",
        },
    ],
    "econometrica": [
        {
            "kind": "econometrica_forthcoming",
            "url": "https://www.econometricsociety.org/publications/econometrica/forthcoming-papers",
            "fallback_urls": [
                "https://r.jina.ai/http://www.econometricsociety.org/publications/econometrica/forthcoming-papers",
            ],
            "date_source": "econometric_society_forthcoming",
            "date_confidence": "B",
            "fallback_issn": "0012-9682",
        }
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


def fetch_toc_text(url: str, timeout: int, fallback_urls: list[str] | None = None) -> str:
    """Fetch a publisher page, then a text-rendering mirror when blocked.

    The mirror is only an acquisition fallback.  Dates and article metadata
    still come from the page content and are labelled with the publisher
    source configured for the target.
    """
    urls = [url, *(fallback_urls or [])]
    last_error: Exception | None = None
    for candidate in dict.fromkeys(urls):
        request = urllib.request.Request(candidate, headers=BROWSER_HEADERS)
        try:
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
                    text = payload.decode(encoding)
                    if text.strip():
                        return text
                except Exception:
                    continue
            raise ValueError("empty or undecodable publisher response")
        except Exception as exc:  # noqa: BLE001 - try the next acquisition path.
            last_error = exc
    raise last_error or RuntimeError("no TOC acquisition URL")


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
    """Return article-detail links and reject publisher navigation links.

    OUP, MIT Press, and the Econometric Society reuse journal paths for
    navigation, policy, and submission pages. A link is an article candidate
    only when it carries the journal DOI pattern or an article-detail path.
    """
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<title>.*?)</a>', html_text, flags=re.I | re.S):
        href = html.unescape(match.group("href")).strip()
        title = clean_text(match.group("title"))
        if not title or len(title) < 8:
            continue
        href_lower = href.lower()
        base_lower = base_url.lower()
        is_doi_article = bool(re.search(r"10\.\d{4,9}/", href_lower))
        is_restud_article = "10.1093/restud/" in href_lower or "/restud/article/" in href_lower
        is_restat_article = "10.1162/rest" in href_lower or "/rest/article/" in href_lower
        is_econometrica_article = "10.3982/ecta" in href_lower
        if "econometricsociety.org/publications/econometrica" in base_lower:
            valid_article = is_econometrica_article
        elif "academic.oup.com/restud" in base_lower:
            valid_article = is_restud_article or (is_doi_article and "restud" in href_lower)
        elif "direct.mit.edu/rest" in base_lower:
            valid_article = is_restat_article
        else:
            valid_article = is_doi_article
        if not valid_article:
            continue
        if any(skip in title.casefold() for skip in ("pdf", "permissions", "supplementary", "view metrics")):
            continue
        url = urljoin(base_url, href)
        key = url.split("?", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        links.append((url, title))
    # r.jina.ai normally returns Markdown rather than HTML.
    for match in re.finditer(r'\[(?P<title>[^\]]{8,240})\]\((?P<href>https?://[^)]+)\)', html_text):
        href = html.unescape(match.group("href")).strip()
        title = clean_text(match.group("title"))
        href_lower = href.lower()
        valid = bool(re.search(r"10\.\d{4,9}/", href_lower))
        if "academic.oup.com/restud" in base_url.lower():
            valid = valid and ("restud" in href_lower)
        elif "direct.mit.edu/rest" in base_url.lower():
            valid = valid and ("10.1162/rest" in href_lower or "/rest/" in href_lower)
        elif "econometricsociety.org/publications/econometrica" in base_url.lower():
            valid = valid and "10.3982/ecta" in href_lower
        if not valid or any(skip in title.casefold() for skip in ("pdf", "permissions", "supplementary")):
            continue
        key = href.split("?", 1)[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            links.append((href, title))
    return links


def enrich_detail(url: str, fallback_title: str, timeout: int) -> dict[str, object]:
    try:
        html_text = fetch_toc_text(url, timeout=timeout, fallback_urls=[f"https://r.jina.ai/http://{url.removeprefix('https://').removeprefix('http://')}"])
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
    html_text = fetch_toc_text(page_url, timeout=timeout, fallback_urls=target.get("fallback_urls"))
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


def fetch_crossref_fallback(journal: dict, target: dict[str, str], *, timeout: int, max_items: int) -> list[dict]:
    """Use Crossref online-publication metadata when a publisher endpoint blocks CI."""
    issn = str(target.get("fallback_issn") or "").strip()
    if not issn:
        return []
    start = (date.today() - timedelta(days=45)).isoformat()
    params = urlencode({
        "filter": f"from-online-pub-date:{start},until-online-pub-date:{date.today().isoformat()}",
        "rows": max_items,
        "select": "DOI,title,author,published-online,published,created,URL,abstract",
    })
    request = urllib.request.Request(
        f"https://api.crossref.org/journals/{issn}/works?{params}",
        headers={**BROWSER_HEADERS, "Accept": "application/json", "User-Agent": "AcademicDoorPaperMonitor/1.0 (mailto:academic-door@users.noreply.github.com)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    records: list[dict] = []
    for item in (payload.get("message", {}).get("items") or []):
        title = str((item.get("title") or [""])[0]).strip()
        doi = str(item.get("DOI") or "").strip().lower()
        if not title or not doi:
            continue
        online = item.get("published-online") or item.get("published") or {}
        parts = online.get("date-parts") or []
        published = None
        if parts and parts[0]:
            values = parts[0]
            published = "-".join(str(value).zfill(2) for value in values[:3])
            if len(values) == 1:
                published += "-01-01"
            elif len(values) == 2:
                published += "-01"
        authors = [
            " ".join(part for part in (author.get("given"), author.get("family")) if part).strip()
            for author in (item.get("author") or [])
        ]
        authors = [author for author in authors if author]
        records.append(article_record(
            journal,
            title=title,
            url=str(item.get("URL") or f"https://doi.org/{doi}"),
            source="priority_crossref_fallback",
            source_url=f"https://api.crossref.org/journals/{issn}/works",
            doi=doi,
            authors=authors,
            abstract=item.get("abstract"),
            published_online=published,
            available_online=published,
            date_source="crossref_published_online",
            date_confidence="B" if item.get("published-online") else "C",
            raw_data={"priority_toc_kind": target["kind"], "fallback": "crossref", "issn": issn},
        ))
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
                if not fetched:
                    fallback = fetch_crossref_fallback(journal, target, timeout=args.timeout, max_items=args.max_items_per_source)
                    records.extend(fallback)
                    journal_count += len(fallback)
                    messages.append(f"{journal_id}/{target['kind']}: crossref fallback {len(fallback)}")
                    if not fallback:
                        failures += 1
            except Exception as exc:  # noqa: BLE001 - source health is reported below.
                try:
                    fallback = fetch_crossref_fallback(journal, target, timeout=args.timeout, max_items=args.max_items_per_source)
                except Exception as fallback_exc:  # noqa: BLE001
                    fallback = []
                    messages.append(f"{journal_id}/{target['kind']}: Crossref fallback {type(fallback_exc).__name__}: {fallback_exc}")
                records.extend(fallback)
                journal_count += len(fallback)
                messages.append(f"{journal_id}/{target['kind']}: {type(exc).__name__}; crossref fallback {len(fallback)}")
                if not fallback:
                    failures += 1
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
