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

from common import DATA_DIR, fetch_json, fetch_text, now_iso, today_str, write_json
from status import record_source


ATOM = "{http://www.w3.org/2005/Atom}"
RSS10 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"


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


def is_boilerplate_text(value: str | None) -> bool:
    normalized = " ".join((value or "").split()).casefold()
    boilerplates = [
        "founded in 1920, the nber is a private",
        "the federal reserve board of governors in washington dc",
    ]
    return any(fragment in normalized for fragment in boilerplates)


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
    wanted = {name.split("}")[-1].split(":")[-1] for name in names}
    for child in list(node):
        local_name = child.tag.split("}")[-1]
        if local_name in wanted and child.text:
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
    if source.get("id") == "world-bank-prwp":
        return enrich_world_bank_from_detail(record, source, timeout=timeout) or record

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

    source_id = str(source.get("id") or "")
    detail_abstract_patterns = [
        r'<div[^>]+class=["\'][^"\']*page-header__intro[^"\']*["\'][^>]*>\s*<div[^>]*>\s*<p[^>]*>(.*?)</p>',
        r'<h2[^>]*>\s*Abstract\s*</h2>\s*<p[^>]*>(.*?)</p>',
        r'<div[^>]+class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</div>',
        r'<section[^>]+class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</section>',
    ]
    generic_description = None if source_id == "nber" else (meta_values(html_text, ["description", "og:description"]) or [None])[0]
    abstract = (
        (meta_values(html_text, ["citation_abstract", "dc.description"]) or [None])[0]
        or first_match(detail_abstract_patterns, html_text)
        or generic_description
        or json_ld_value(html_text, ["description", "abstract"])
    )
    if abstract and not is_boilerplate_text(abstract):
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
    elif "ideas.repec.org/" in str(url or ""):
        year_value = (
            first_match([r'\b(20\d{2})\b'], str(date_value or ""), flags=re.I)
            or first_match([r'"datePublished"\s*:\s*"(20\d{2})"'], html_text, flags=re.I)
            or (meta_values(html_text, ["citation_publication_date"]) or [None])[0]
        )
        year_match = re.search(r"\b(20\d{2})\b", str(year_value or ""))
        if year_match:
            record["published_online"] = f"{year_match.group(1)}-01-01"
            record["available_online"] = f"{year_match.group(1)}-01-01"
            record["date_source"] = "repec_detail_year"
            record["date_confidence"] = "C"

    doi = (meta_values(html_text, ["citation_doi", "dc.identifier"]) or [None])[0]
    if doi and "10." in doi:
        doi_match = re.search(r"(10\.\d{4,9}/\S+)", doi)
        record["doi"] = doi_match.group(1).rstrip(".") if doi_match else doi

    pdf = (meta_values(html_text, ["citation_pdf_url"]) or [None])[0]
    if pdf:
        record["pdf_url"] = urljoin(str(url), pdf)
    record["paper_number"] = record.get("paper_number") or detect_paper_number(source, str(record.get("title") or ""), str(record.get("url") or ""))
    return record


def world_bank_uuid(record: dict[str, Any]) -> str | None:
    for value in (record.get("paper_number"), record.get("url")):
        if not isinstance(value, str):
            continue
        match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", value, flags=re.I)
        if match:
            return match.group(1)
    return None


def first_metadata_value(item: dict[str, Any], keys: list[str]) -> str | None:
    values = metadata_values(item, keys)
    return values[0] if values else None


def world_bank_pdf_url(detail: dict[str, Any]) -> str | None:
    for value in nested_values(detail):
        if not isinstance(value, dict):
            continue
        href = value.get("href")
        if isinstance(href, str) and "/bitstreams/" in href:
            return href if href.startswith("http") else urljoin("https://openknowledge.worldbank.org", href)
        uuid = value.get("uuid")
        if isinstance(uuid, str) and value.get("bundleName") != "LICENSE":
            name = str(value.get("name") or value.get("uuid") or "")
            if name.lower().endswith(".pdf") or value.get("format") == "Adobe PDF":
                return f"https://openknowledge.worldbank.org/bitstreams/{uuid}/download"
    return None


def enrich_world_bank_from_detail(record: dict[str, Any], source: dict[str, Any], *, timeout: int) -> dict[str, Any] | None:
    uuid = world_bank_uuid(record)
    if not uuid:
        return None
    detail_url = f"https://openknowledge.worldbank.org/server/api/core/items/{uuid}"
    try:
        detail = fetch_json(detail_url, timeout=timeout)
    except Exception:
        return None
    if not isinstance(detail, dict):
        return None

    title = first_metadata_value(detail, ["dc.title", "title"])
    if title and plausible_title(title):
        record["title"] = title

    authors = list(dict.fromkeys(metadata_values(detail, ["dc.contributor.author", "contributor.author", "author"])))
    if authors:
        record["authors"] = authors[:12]

    abstract = first_metadata_value(detail, ["dc.description.abstract", "description.abstract"])
    if abstract and not is_boilerplate_text(abstract):
        record["abstract"] = abstract
        record["abstract_source"] = "world_bank_detail_api"

    date_value = first_metadata_value(detail, ["dc.date.issued", "date.issued", "issued"])
    parsed_date = parse_date(date_value)
    if parsed_date:
        record["published_online"] = parsed_date
        record["available_online"] = parsed_date
        record["date_source"] = "world_bank_detail_api"
        record["date_confidence"] = "B"

    doi = first_metadata_value(detail, ["dc.identifier.doi", "identifier.doi", "doi"])
    if doi:
        record["doi"] = doi

    handle = first_metadata_value(detail, ["dc.identifier.uri", "identifier.uri"])
    if handle and handle.startswith("http"):
        record["source_url"] = handle

    pdf = world_bank_pdf_url(detail)
    if pdf:
        record["pdf_url"] = pdf

    record["paper_number"] = uuid
    return record


def parse_feed(xml_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    if root.tag.endswith("RDF"):
        for item in root.findall(f".//{RSS10}item") or [node for node in root.iter() if node.tag.endswith("item")]:
            title = clean_text(child_text(item, ["title"]))
            link = child_text(item, ["link"])
            if not title or not allowed_url(source, link):
                continue
            published = parse_date(child_text(item, [f"{DC}date", "date", "dc:date"]))
            abstract = child_text(item, ["description", "summary"])
            records.append(source_record(source, title=title, url=link, published=published, abstract=abstract))
        return records
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
        if not plausible_title(title):
            window = html_text[max(0, match.start() - 900) : min(len(html_text), match.end() + 900)]
            title = (
                first_match([r'<h[23][^>]*>(.*?)</h[23]>', r'class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)<'], window)
                or title
            )
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
        if not plausible_title(title):
            window = html_text[max(0, match.start() - 700) : min(len(html_text), match.end() + 1200)]
            title = (
                first_match(
                    [
                        r'<span[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</span>',
                        r'<td[^>]*>\s*<a[^>]+/publ/work\d+[^>]*>.*?</a>\s*</td>\s*<td[^>]*>(.*?)</td>',
                        r'<a[^>]+/publ/work\d+[^>]*>.*?</a>\s*</[^>]+>\s*<[^>]+>(.*?)</[^>]+>',
                    ],
                    window,
                )
                or title
            )
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


def parse_repec_cesifo_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = (
        r'<LI[^>]*class=["\'][^"\']*list-group-item[^"\']*["\'][^>]*>\s*'
        r'<B>\s*(?P<number>\d+)\s*<A\s+HREF=["\'](?P<href>/p/ces/ceswps/[^"\']+)["\']>(?P<title>.*?)</A></B>'
        r'(?P<tail>.*?)</LI>'
    )
    for match in re.finditer(pattern, html_text, flags=re.I | re.S):
        url = normalize_url(urljoin(str(source.get("homepage")), html.unescape(match.group("href"))))
        title = clean_text(match.group("title"))
        if not url or url in seen or not plausible_title(title):
            continue
        record = source_record(source, title=title, url=url)
        record["paper_number"] = match.group("number")
        tail = match.group("tail")
        authors = first_match([r'<I>\s*by\s*</I>\s*(.*?)(?:<BR|</LI|<span|$)'], tail)
        if authors:
            record["authors"] = [clean_text(part) for part in re.split(r"\s*&\s*|\s+and\s+|;", authors) if clean_text(part)][:12]
        year = first_match([r'\b(20\d{2})\b'], tail, flags=re.I)
        if year:
            record["published_online"] = f"{year}-01-01"
            record["available_online"] = f"{year}-01-01"
            record["date_source"] = "repec_series_year"
            record["date_confidence"] = "C"
        seen.add(url)
        records.append(record)
        if len(records) >= limit:
            break
    return records


def parse_repec_series_list(html_text: str, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = (
        r'<LI[^>]*class=["\'][^"\']*list-group-item[^"\']*["\'][^>]*>\s*'
        r'(?:<B>\s*)?(?P<number>[^<\s]{1,40})?\s*'
        r'<A\s+HREF=["\'](?P<href>/p/[^"\']+)["\']>(?P<title>.*?)</A>'
        r'(?P<tail>.*?)</LI>'
    )
    for match in re.finditer(pattern, html_text, flags=re.I | re.S):
        url = normalize_url(urljoin(str(source.get("homepage")), html.unescape(match.group("href"))))
        title = clean_text(match.group("title"))
        if not url or url in seen or not plausible_title(title):
            continue
        record = source_record(source, title=title, url=url)
        number = clean_text(match.group("number") or "")
        if number and not number.startswith("<"):
            record["paper_number"] = number
        tail = match.group("tail")
        authors = first_match([r'<I>\s*by\s*</I>\s*(.*?)(?:<BR|</LI|<span|$)'], tail)
        if authors:
            record["authors"] = [clean_text(part) for part in re.split(r"\s*&\s*|\s+and\s+|;", authors) if clean_text(part)][:12]
        year = first_match([r'\b(20\d{2})\b'], tail, flags=re.I)
        if year:
            record["published_online"] = f"{year}-01-01"
            record["available_online"] = f"{year}-01-01"
            record["date_source"] = "repec_series_year"
            record["date_confidence"] = "C"
        seen.add(url)
        records.append(record)
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
    if source_id == "cesifo-working-papers":
        return parse_repec_cesifo_list(html_text, source, limit)
    if "ideas.repec.org/s/" in str(source.get("homepage") or ""):
        return parse_repec_series_list(html_text, source, limit)
    return []


def nested_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(nested_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(nested_values(child))
    return values


def first_key_text(item: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return clean_text(value)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return clean_text(first)
            if isinstance(first, dict):
                for nested_key in ("value", "name", "title"):
                    if isinstance(first.get(nested_key), str):
                        return clean_text(first[nested_key])
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        for key in keys:
            variants = [key, key.replace("_", "."), f"dc.{key}", f"dc.{key}.none"]
            for variant in variants:
                raw = metadata.get(variant)
                if isinstance(raw, list) and raw:
                    first = raw[0]
                    if isinstance(first, dict) and first.get("value"):
                        return clean_text(str(first["value"]))
    return None


def metadata_values(item: dict[str, Any], keys: list[str]) -> list[str]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return []
    values: list[str] = []
    for key in keys:
        variants = [key, key.replace("_", "."), f"dc.{key}", f"dc.{key}.none"]
        for variant in variants:
            raw = metadata.get(variant)
            if isinstance(raw, list):
                for entry in raw:
                    if isinstance(entry, dict) and entry.get("value"):
                        values.append(clean_text(str(entry["value"])))
                    elif isinstance(entry, str):
                        values.append(clean_text(entry))
    return [value for value in values if value]


def first_url_text(item: dict[str, Any], source: dict[str, Any]) -> str | None:
    for key in ("url", "href", "link", "path", "canonical_url"):
        value = item.get(key)
        if isinstance(value, str):
            absolute = normalize_url(urljoin(str(source.get("homepage") or ""), value))
            if allowed_url(source, absolute):
                return absolute
    links = item.get("_links") or item.get("links")
    if isinstance(links, dict):
        for child in links.values():
            if isinstance(child, dict) and isinstance(child.get("href"), str):
                absolute = normalize_url(child["href"])
                if allowed_url(source, absolute):
                    return absolute
            if isinstance(child, list):
                for entry in child:
                    if isinstance(entry, dict) and isinstance(entry.get("href"), str):
                        absolute = normalize_url(entry["href"])
                        if allowed_url(source, absolute):
                            return absolute
    return None


def parse_world_bank_json_records(payload: Any, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for value in nested_values(payload):
        if isinstance(value, dict) and isinstance(value.get("metadata"), dict):
            candidates.append(value)
    for item in candidates:
        title = (metadata_values(item, ["dc.title", "title"]) or [None])[0]
        if not title or not plausible_title(title):
            continue
        uuid = item.get("uuid") or item.get("id")
        url = f"https://openknowledge.worldbank.org/entities/publication/{uuid}" if isinstance(uuid, str) else first_url_text(item, source)
        if not url or url in seen or not allowed_url(source, url):
            continue
        # World Bank discover metadata sometimes carries repeated or mismatched
        # abstract values across search objects. Keep the source reliable by
        # using title/date/DOI here; detail-level abstract validation can be
        # added later.
        abstract = None
        date_value = (metadata_values(item, ["dc.date.issued", "date.issued", "issued"]) or [None])[0]
        record = source_record(source, title=title, url=url, published=parse_date(date_value), abstract=abstract)
        authors = list(dict.fromkeys(metadata_values(item, ["dc.contributor.author", "contributor.author", "author"])))
        if authors:
            record["authors"] = authors[:12]
        doi = (metadata_values(item, ["dc.identifier.doi", "identifier.doi", "doi"]) or [None])[0]
        if doi:
            record["doi"] = doi
        uri = (metadata_values(item, ["dc.identifier.uri", "identifier.uri"]) or [None])[0]
        if uri and uri.startswith("http"):
            record["source_url"] = uri
        bitstreams = item.get("bundles")
        if isinstance(bitstreams, list):
            for bundle in bitstreams:
                if not isinstance(bundle, dict):
                    continue
                for candidate in nested_values(bundle):
                    if isinstance(candidate, dict) and isinstance(candidate.get("uuid"), str):
                        record["pdf_url"] = f"https://openknowledge.worldbank.org/bitstreams/{candidate['uuid']}/download"
                        break
                if record.get("pdf_url"):
                    break
        record["paper_number"] = str(uuid) if uuid else record.get("paper_number")
        seen.add(url)
        records.append(record)
        if len(records) >= limit:
            break
    return records


def parse_json_records(payload: Any, source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    if source.get("id") == "world-bank-prwp":
        return parse_world_bank_json_records(payload, source, limit)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in nested_values(payload):
        if not isinstance(value, dict):
            continue
        title = first_key_text(value, ["title", "name", "label", "dc.title"])
        if not title or not plausible_title(title):
            continue
        url = first_url_text(value, source)
        if not url:
            # DSpace item UUID pages can be reconstructed from uuid.
            uuid = value.get("uuid") or value.get("id")
            if isinstance(uuid, str) and source.get("id") == "world-bank-prwp":
                url = f"https://openknowledge.worldbank.org/entities/publication/{uuid}"
        if not url or url in seen or not allowed_url(source, url):
            continue
        seen.add(url)
        date_value = first_key_text(value, ["date", "issued", "dateIssued", "publication_date", "dc.date.issued"])
        abstract = first_key_text(value, ["abstract", "description", "dc.description.abstract"])
        records.append(source_record(source, title=title, url=url, published=parse_date(date_value), abstract=abstract))
        if len(records) >= limit:
            break
    return records


def specialized_api_urls(source: dict[str, Any]) -> list[str]:
    source_id = str(source.get("id") or "")
    if source_id == "nber":
        return [
            "https://www.nber.org/api/v1/working_page_listing/contentType/working_paper/_/_/search?page=1&perPage=50",
            "https://www.nber.org/api/v1/working_paper/working_paper_listing/_/_/search?page=1&perPage=50",
        ]
    if source_id == "world-bank-prwp":
        collection_id = str(source.get("homepage") or "").rstrip("/").split("/")[-1]
        return [
            "https://openknowledge.worldbank.org/server/api/discover/search/objects?query=%22Policy%20Research%20Working%20Paper%22&size=50&sort=dc.date.issued,DESC",
            f"https://openknowledge.worldbank.org/server/api/discover/search/objects?scope={collection_id}&size=50&sort=dc.date.issued,DESC",
            f"https://openknowledge.worldbank.org/server/api/core/collections/{collection_id}/items?size=50",
        ]
    return []


def fetch_specialized_api(source: dict[str, Any], *, timeout: int, limit: int) -> tuple[list[dict[str, Any]], str] | None:
    for url in specialized_api_urls(source):
        try:
            payload = fetch_json(url, timeout=timeout)
            records = parse_json_records(payload, source, limit)
            if records:
                return records, "specialized-api"
        except Exception:
            continue
    return None


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
    api_result = fetch_specialized_api(source, timeout=timeout, limit=limit)
    if api_result:
        return api_result
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
                    if index < args.detail_limit or source_id == "nber":
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
    summary = "; ".join(messages)
    if failures:
        summary = f"partial_success failures={failures}; {summary}"
    record_source(
        "working-papers",
        ok=len(all_records) > 0,
        count=len(all_records),
        message=summary,
    )
    print(f"wrote {len(all_records)} working-paper records to {output}; failures={failures}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
