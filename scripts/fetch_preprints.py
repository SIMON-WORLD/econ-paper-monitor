"""Fetch working paper and policy paper metadata sources.

The first implementation is intentionally conservative: collect public
metadata from feeds or list pages, never bulk-download PDFs, and keep failed
sources non-fatal for scheduled runs.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from common import DATA_DIR, fetch_text, now_iso, today_str, write_json
from status import record_source


ATOM = "{http://www.w3.org/2005/Atom}"


def load_sources(path: Path) -> list[dict[str, Any]]:
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(loaded.get("sources") or [])
    except Exception:
        # Narrow fallback for the checked-in YAML shape.
        sources: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        list_key: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped == "sources:":
                continue
            if line.startswith("  - id:"):
                if current:
                    sources.append(current)
                current = {"id": stripped.removeprefix("- id:").strip(), "fields": []}
                list_key = None
                continue
            if current is None:
                continue
            if line.startswith("    ") and not line.startswith("      "):
                key, _, value = stripped.partition(":")
                if value == "":
                    list_key = key
                    continue
                value = value.strip().strip('"')
                current[key] = int(value) if key == "stage" and value.isdigit() else value
                list_key = None
                continue
            if list_key and line.startswith("      - "):
                current.setdefault(list_key, []).append(stripped.removeprefix("- ").strip().strip('"'))
        if current:
            sources.append(current)
        return sources


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    value = fix_mojibake(value)
    return value.strip()


def fix_mojibake(value: str) -> str:
    replacements = {
        "鈥檚": "'s",
        "鈥檛": "n't",
        "鈥?": "-",
        "鈥�": "-",
        "鈥�": "-",
        "鈥淪": '"S',
        "鈥漵": '"',
        "鈥": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€\x9d": '"',
        "â€“": "-",
        "â€”": "-",
        "Â ": " ",
        "Â": "",
    }
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = clean_text(value)
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except Exception:
        pass
    match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", value)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return None


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    clean = parsed._replace(query="", fragment="")
    return clean.geturl().rstrip("/")


def first_match(patterns: list[str], text: str, flags: int = re.I | re.S) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=flags)
        if match:
            return clean_text(match.group(1))
    return None


def meta_values(html_text: str, names: list[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        pattern = (
            r'<meta[^>]+(?:name|property)=["\']'
            + re.escape(name)
            + r'["\'][^>]+content=["\']([^"\']+)["\'][^>]*>'
        )
        values.extend(clean_text(match) for match in re.findall(pattern, html_text, flags=re.I | re.S))
        pattern = (
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']'
            + re.escape(name)
            + r'["\'][^>]*>'
        )
        values.extend(clean_text(match) for match in re.findall(pattern, html_text, flags=re.I | re.S))
    return [value for value in values if value]


def json_ld_objects(html_text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, flags=re.I | re.S):
        payload = clean_text(match.group(1))
        try:
            parsed = json.loads(payload)
        except Exception:
            continue
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for item in candidates:
            if isinstance(item, dict):
                objects.append(item)
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                objects.extend(node for node in item["@graph"] if isinstance(node, dict))
    return objects


def json_ld_value(html_text: str, keys: list[str]) -> str | None:
    for item in json_ld_objects(html_text):
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return clean_text(value)
            if isinstance(value, list) and value:
                pieces = []
                for part in value:
                    if isinstance(part, str):
                        pieces.append(part)
                    elif isinstance(part, dict) and part.get("name"):
                        pieces.append(str(part["name"]))
                if pieces:
                    return clean_text(", ".join(pieces))
    return None


def detect_paper_number(source: dict[str, Any], title: str, url: str | None) -> str | None:
    source_id = str(source.get("id") or "")
    text = f"{title} {url or ''}"
    patterns = {
        "nber": [r"/papers/(w\d+)", r"\b(w\d{4,})\b"],
        "iza": [r"/dp/(\d+)/", r"\bDP\s*No\.?\s*(\d+)\b"],
        "cepr-dp": [r"/publications/(dp\d+)", r"\bDP\s*(\d{4,})\b"],
        "fed-feds": [r"/econres/feds/([^/.]+)", r"\bFEDS\s*(\d{4}-\d+)\b"],
        "bis-working-papers": [r"/publ/(work\d+)", r"\bWorking Paper[s]?\s*No\.?\s*(\d+)\b"],
        "imf-working-papers": [r"\bWP/(\d+/\d+)\b", r"/Issues/.+?/([^/]+)$"],
        "world-bank-prwp": [r"/entities/publication/([^/?#]+)"],
        "cesifo-working-papers": [r"\bWorking Paper\s*No\.?\s*(\d+)\b"],
    }
    for pattern in patterns.get(source_id, []):
        match = re.search(pattern, text, flags=re.I)
        if match:
            return clean_text(match.group(1))
    return None


def child_text(node: ElementTree.Element, names: list[str]) -> str | None:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return None


def source_record(
    source: dict[str, Any],
    *,
    title: str,
    url: str | None,
    published: str | None = None,
    abstract: str | None = None,
) -> dict[str, Any]:
    source_type = str(source.get("type") or "working_paper")
    source_title = str(source.get("title") or source.get("id") or "Working Paper")
    clean_url = normalize_url(url)
    clean_title = clean_text(title)
    return {
        "title": clean_title,
        "authors": [],
        "journal": source_title,
        "journal_id": f"source-{source.get('id')}",
        "publisher": source_title,
        "fields": source.get("fields") or ["general"],
        "source": "working_papers",
        "source_type": source_type,
        "source_id": source.get("id"),
        "source_name": source_title,
        "series": source_title,
        "paper_number": detect_paper_number(source, clean_title, clean_url),
        "source_url": source.get("feed") or source.get("homepage"),
        "url": clean_url,
        "doi": None,
        "abstract": clean_text(abstract) or None,
        "published_online": published,
        "available_online": published,
        "date_source": "rss_published" if published and source.get("feed") else ("source_list_date" if published else None),
        "date_confidence": "B" if published else "F",
        "detected_at": now_iso(),
    }


def enrich_record_from_detail(record: dict[str, Any], source: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    url = record.get("url")
    if not url:
        return record
    try:
        html_text = fetch_text(str(url), timeout=timeout)
    except Exception:
        return record

    title = (
        first_match([r'<h1[^>]*>(.*?)</h1>'], html_text)
        or (meta_values(html_text, ["citation_title", "dc.title", "og:title"]) or [None])[0]
        or json_ld_value(html_text, ["headline", "name"])
    )
    if title and plausible_title(title):
        record["title"] = title

    authors = meta_values(html_text, ["citation_author", "dc.creator", "author"])
    if authors:
        record["authors"] = list(dict.fromkeys(authors))[:12]
    elif json_authors := json_ld_value(html_text, ["author", "creator"]):
        record["authors"] = [item.strip() for item in json_authors.split(",") if item.strip()][:12]

    abstract = (
        (meta_values(html_text, ["citation_abstract", "dc.description", "description", "og:description"]) or [None])[0]
        or json_ld_value(html_text, ["description", "abstract"])
        or first_match(
            [
                r'<h2[^>]*>\s*Abstract\s*</h2>\s*<p[^>]*>(.*?)</p>',
                r'<div[^>]+class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</div>',
                r'<section[^>]+class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</section>',
            ],
            html_text,
        )
    )
    if abstract:
        record["abstract"] = clean_text(abstract)

    date_value = (
        (meta_values(html_text, ["citation_publication_date", "citation_online_date", "article:published_time", "dc.date"]) or [None])[0]
        or json_ld_value(html_text, ["datePublished", "dateCreated", "dateModified"])
        or first_match(
            [
                r'(?:Published|Posted|Date)\s*:?\s*</?[^>]*>\s*([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})',
                r'(?:Published|Posted|Date)\s*:?\s*(20\d{2}-\d{1,2}-\d{1,2})',
            ],
            html_text,
        )
    )
    parsed_date = parse_date(date_value)
    if parsed_date:
        record["published_online"] = parsed_date
        record["available_online"] = parsed_date
        record["date_source"] = "publisher_detail"
        record["date_confidence"] = "B"

    doi = (meta_values(html_text, ["citation_doi", "dc.identifier"]) or [None])[0]
    if doi and "10." in doi:
        doi_match = re.search(r"(10\.\d{4,9}/\S+)", doi)
        record["doi"] = doi_match.group(1).rstrip(".") if doi_match else doi

    pdf = (meta_values(html_text, ["citation_pdf_url"]) or [None])[0]
    if pdf:
        record["pdf_url"] = urljoin(str(url), pdf)
    record["paper_number"] = record.get("paper_number") or detect_paper_number(source, str(record.get("title") or ""), str(record.get("url") or ""))
    return record


def parse_feed(xml_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    if root.tag.endswith("rss") or root.find("channel") is not None:
        for item in root.findall("./channel/item"):
            title = clean_text(child_text(item, ["title"]))
            if not title:
                continue
            link = child_text(item, ["link", "guid"])
            if not allowed_url(source, link):
                continue
            published = parse_date(child_text(item, ["pubDate", "date", "dc:date"]))
            abstract = child_text(item, ["description", "summary"])
            records.append(source_record(source, title=title, url=link, published=published, abstract=abstract))
        return records

    for entry in root.findall(f".//{ATOM}entry"):
        title = clean_text(child_text(entry, [f"{ATOM}title"]))
        if not title:
            continue
        link = None
        link_node = entry.find(f"{ATOM}link")
        if link_node is not None:
            link = link_node.attrib.get("href")
        if not allowed_url(source, link):
            continue
        published = parse_date(child_text(entry, [f"{ATOM}published", f"{ATOM}updated"]))
        abstract = child_text(entry, [f"{ATOM}summary", f"{ATOM}content"])
        records.append(source_record(source, title=title, url=link, published=published, abstract=abstract))
    return records


def parse_html_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base_url = str(source.get("homepage") or "")
    records: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    title_patterns = [
        r'<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<title>[^<]{20,240})</a>',
        r'<h[23][^>]*>\s*<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<title>.*?)</a>\s*</h[23]>',
    ]
    for pattern in title_patterns:
        for match in re.finditer(pattern, html_text, flags=re.I | re.S):
            title = clean_text(match.group("title"))
            if not plausible_title(title) or title.lower() in seen_titles:
                continue
            href = html.unescape(match.group("href"))
            if href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            absolute_url = urljoin(base_url, href)
            if not allowed_url(source, absolute_url):
                continue
            seen_titles.add(title.lower())
            records.append(source_record(source, title=title, url=absolute_url))
            if len(records) >= limit:
                return records
    return records


def parse_nber_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href=["\'](?P<href>/papers/w\d+)["\'][^>]*>(?P<title>.*?)</a>', html_text, flags=re.I | re.S):
        url = urljoin(str(source.get("homepage")), match.group("href"))
        title = clean_text(match.group("title"))
        if not plausible_title(title) or url in seen:
            continue
        seen.add(url)
        records.append(source_record(source, title=title, url=url))
        if len(records) >= limit:
            break
    return records


def parse_imf_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = r'<a[^>]+href=["\'](?P<href>[^"\']*/en/Publications/WP/Issues/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>'
    for match in re.finditer(pattern, html_text, flags=re.I | re.S):
        url = normalize_url(urljoin("https://www.imf.org", html.unescape(match.group("href"))))
        title = clean_text(match.group("title"))
        if not url or url in seen or not plausible_title(title):
            continue
        seen.add(url)
        records.append(source_record(source, title=title, url=url))
        if len(records) >= limit:
            break
    return records


def parse_bis_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = r'<a[^>]+href=["\'](?P<href>[^"\']*/publ/work\d+[^"\']*)["\'][^>]*>(?P<title>.*?)</a>'
    for match in re.finditer(pattern, html_text, flags=re.I | re.S):
        url = normalize_url(urljoin("https://www.bis.org", html.unescape(match.group("href"))))
        title = clean_text(match.group("title"))
        if not url or url in seen or not plausible_title(title):
            continue
        seen.add(url)
        records.append(source_record(source, title=title, url=url))
        if len(records) >= limit:
            break
    return records


def parse_world_bank_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = r'<a[^>]+href=["\'](?P<href>[^"\']*/entities/publication/[^"\']+)["\'][^>]*>(?P<title>.*?)</a>'
    for match in re.finditer(pattern, html_text, flags=re.I | re.S):
        url = normalize_url(urljoin(str(source.get("homepage")), html.unescape(match.group("href"))))
        title = clean_text(match.group("title"))
        if not url or url in seen or not plausible_title(title):
            continue
        seen.add(url)
        records.append(source_record(source, title=title, url=url))
        if len(records) >= limit:
            break
    return records


def parse_specialized_html(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    source_id = str(source.get("id") or "")
    if source_id == "nber":
        return parse_nber_list(html_text, source, limit)
    if source_id == "imf-working-papers":
        return parse_imf_list(html_text, source, limit)
    if source_id == "bis-working-papers":
        return parse_bis_list(html_text, source, limit)
    if source_id == "world-bank-prwp":
        return parse_world_bank_list(html_text, source, limit)
    return []


def plausible_title(title: str) -> bool:
    bad_fragments = [
        "subscribe",
        "sign in",
        "login",
        "privacy",
        "cookie",
        "download",
        "publications",
        "working papers",
        "discussion papers",
    ]
    if len(title) < 20 or len(title.split()) < 4:
        return False
    lowered = title.lower()
    return not any(fragment in lowered for fragment in bad_fragments)


def allowed_url(source: dict[str, Any], url: str | None) -> bool:
    if not url:
        return not source.get("url_pattern") and not source.get("url_contains")
    homepage = str(source.get("homepage") or "").rstrip("/")
    if homepage and url.rstrip("/") == homepage:
        return False
    for fragment in source.get("url_contains") or []:
        if str(fragment).lower() in url.lower():
            return True
    pattern = source.get("url_pattern")
    if not pattern:
        return True
    return re.search(str(pattern), url, flags=re.I) is not None


def fetch_source(source: dict[str, Any], *, timeout: int, limit: int) -> tuple[list[dict[str, Any]], str]:
    if source.get("feed"):
        xml_text = fetch_text(str(source["feed"]), timeout=timeout)
        records = parse_feed(xml_text, source)
        return records[:limit], "feed"
    html_text = fetch_text(str(source["homepage"]), timeout=timeout)
    specialized = parse_specialized_html(html_text, source, limit)
    if specialized:
        return specialized[:limit], "specialized-html"
    discovered_feed = discover_feed(html_text, str(source.get("homepage") or ""))
    if discovered_feed:
        try:
            xml_text = fetch_text(discovered_feed, timeout=timeout)
            records = parse_feed(xml_text, {**source, "feed": discovered_feed})
            return records[:limit], "discovered-feed"
        except Exception:
            pass
    records = parse_html_list(html_text, source, limit)
    return records, "html"


def discover_feed(html_text: str, base_url: str) -> str | None:
    for match in re.finditer(r'<link[^>]+rel=["\'][^"\']*alternate[^"\']*["\'][^>]*>', html_text, flags=re.I):
        tag = match.group(0)
        type_match = re.search(r'type=["\']([^"\']+)["\']', tag, flags=re.I)
        if type_match and "rss" not in type_match.group(1).lower() and "atom" not in type_match.group(1).lower():
            continue
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag, flags=re.I)
        if href_match:
            return urljoin(base_url, html.unescape(href_match.group(1)))
    for href in re.findall(r'href=["\']([^"\']*(?:rss|feed|atom)[^"\']*)["\']', html_text, flags=re.I):
        if href.lower().startswith("javascript:"):
            continue
        return urljoin(base_url, html.unescape(href))
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=DATA_DIR / "working_paper_sources.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--stage", type=int, default=2, help="Fetch sources with stage <= this value.")
    parser.add_argument("--limit-per-source", type=int, default=20)
    parser.add_argument("--detail-limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "working_papers" / f"{today_str()}.json"
    sources = [source for source in load_sources(args.sources) if int(source.get("stage") or 99) <= args.stage]
    all_records: list[dict[str, Any]] = []
    messages: list[str] = []
    failures = 0
    for source in sources:
        source_id = str(source.get("id") or "unknown")
        try:
            records, method = fetch_source(source, timeout=args.timeout, limit=args.limit_per_source)
            if args.detail_limit:
                enriched: list[dict[str, Any]] = []
                for index, record in enumerate(records):
                    if index < args.detail_limit:
                        record = enrich_record_from_detail(record, source, timeout=args.timeout)
                    enriched.append(record)
                records = enriched
            all_records.extend(records)
            messages.append(f"{source_id}: {len(records)} via {method}")
            record_source(f"working-paper:{source_id}", ok=True, count=len(records), message=method)
        except Exception as exc:  # noqa: BLE001 - source failures should not block the monitor.
            failures += 1
            message = f"{type(exc).__name__}: {exc}"
            messages.append(f"{source_id}: {message}")
            record_source(f"working-paper:{source_id}", ok=False, count=0, message=message)

    write_json(output, all_records)
    record_source(
        "working-papers",
        ok=failures == 0,
        count=len(all_records),
        message="; ".join(messages),
    )
    print(f"wrote {len(all_records)} working-paper records to {output}; failures={failures}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
