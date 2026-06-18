"""Fetch working paper and policy paper metadata sources.

The first implementation is intentionally conservative: collect public
metadata from feeds or list pages, never bulk-download PDFs, and keep failed
sources non-fatal for scheduled runs.
"""

from __future__ import annotations

import argparse
import html
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
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
    return value.strip()


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
    return {
        "title": clean_text(title),
        "authors": [],
        "journal": source_title,
        "journal_id": f"source-{source.get('id')}",
        "publisher": source_title,
        "fields": source.get("fields") or ["general"],
        "source": "working_papers",
        "source_type": source_type,
        "source_url": source.get("feed") or source.get("homepage"),
        "url": url,
        "doi": None,
        "abstract": clean_text(abstract) or None,
        "published_online": published,
        "available_online": published,
        "date_source": "rss_published" if published and source.get("feed") else ("source_list_date" if published else None),
        "date_confidence": "B" if published else "F",
        "detected_at": now_iso(),
    }


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
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "working_papers" / f"{today_str()}.json"
    sources = [source for source in load_sources(args.sources) if int(source.get("stage") or 99) <= args.stage]
    all_records: list[dict[str, Any]] = []
    messages: list[str] = []
    failures = 0
    for source in sources:
        try:
            records, method = fetch_source(source, timeout=args.timeout, limit=args.limit_per_source)
            all_records.extend(records)
            messages.append(f"{source.get('id')}: {len(records)} via {method}")
        except Exception as exc:  # noqa: BLE001 - source failures should not block the monitor.
            failures += 1
            messages.append(f"{source.get('id')}: {type(exc).__name__}: {exc}")

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
