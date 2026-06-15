"""Fetch Chinese journal article detail pages.

This parser is intentionally conservative:
- only article-detail URLs are kept
- news/navigation/platform pages are dropped
- available_online is extracted from the article page when possible
"""

from __future__ import annotations

import argparse
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from common import DATA_DIR, fetch_text, load_journals, now_iso, today_str, write_json
from fetch_rss import parse_feed
from status import record_source


CN_HOME_URLS = {
    "journal-f69300dae2": "https://zgncjj.ajcass.com/#/",
    "journal-679eaa2a0c": "https://sjjj.magtech.com.cn/CN/home",
    "journal-ba9f46c919": "https://erj.ajcass.com/#/index?title=%E6%9C%AC%E7%AB%99%E9%A6%96%E9%A1%B5",
    "journal-379b4022ce": "https://glsj.chinajournal.net.cn/WKB/WebPublication/index.aspx?mid=glsj",
    "journal-bf2aa9381f": "https://ciejournal.ajcass.com/?jumpnotice=201606280001",
    "journal-edcb877d78": "https://www.jqte.net/sljjjsjjyj/ch/index.aspx",
}

ARTICLE_URL_PATTERNS = (
    "view_abstract.aspx",
    "reader/view_abstract.aspx",
    "article/abstract",
    "CN/abstract/abstract",
    "/CN/Y",
)
NOISE_TEXT = (
    "平台",
    "数据库",
    "征文",
    "会议",
    "新闻",
    "规范",
    "说明",
    "投稿",
    "采编",
    "影响因子",
    "获评",
    "复现包",
    "补充材料",
    "期刊征文",
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        self._href = attrs_dict.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            if text:
                self.links.append((self._href, text))
            self._href = None
            self._text = []


def normalize_url(url: str, base_url: str) -> str:
    url = urllib.parse.urljoin(base_url, url)
    return url.split("#", 1)[0]


def is_article_url(url: str) -> bool:
    return any(pattern.lower() in url.lower() for pattern in ARTICLE_URL_PATTERNS)


def is_noise_text(text: str) -> bool:
    return any(noise in text for noise in NOISE_TEXT)


def discover_feeds(html: str, base_url: str) -> list[str]:
    feeds = []
    for match in re.finditer(r'<link[^>]+(?:rss|atom|application/(?:rss|atom)\+xml)[^>]+>', html, flags=re.I):
        href_match = re.search(r'href=["\']([^"\']+)["\']', match.group(0), flags=re.I)
        if href_match:
            feeds.append(urllib.parse.urljoin(base_url, href_match.group(1)))
    return list(dict.fromkeys(feeds))


def parse_meta(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key, value in re.findall(r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I):
        meta[key.lower()] = value.strip()
    return meta


def extract_date(text: str) -> str | None:
    patterns = [
        r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})",
        r"(20\d{2}年\d{1,2}月\d{1,2}日)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = match.group(1)
            value = value.replace("年", "-").replace("月", "-").replace("日", "")
            value = value.replace(".", "-").replace("/", "-")
            parts = value.split("-")
            if len(parts) == 3:
                try:
                    year, month, day = (int(parts[0]), int(parts[1]), int(parts[2]))
                    return f"{year:04d}-{month:02d}-{day:02d}"
                except ValueError:
                    return None
    return None


def first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def parse_detail_page(html: str, url: str, journal: dict[str, Any], source_url: str) -> dict[str, Any] | None:
    meta = parse_meta(html)
    title = first_nonempty(
        meta.get("citation_title"),
        meta.get("og:title"),
        re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S).group(1) if re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S) else None,
    )
    if not title or is_noise_text(title):
        return None

    doi = first_nonempty(meta.get("citation_doi"), meta.get("dc.identifier"), meta.get("doi"))
    if doi and doi.lower().startswith("10.") is False:
        doi = None
    if doi:
        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()

    published = first_nonempty(
        meta.get("citation_online_date"),
        meta.get("citation_publication_date"),
        meta.get("article:published_time"),
        meta.get("og:updated_time"),
    )
    available_online = extract_date(html) or (published[:10] if published else None)

    abstract = first_nonempty(
        meta.get("citation_abstract"),
        meta.get("description"),
    )
    authors = [value.strip() for key, value in meta.items() if key.startswith("citation_author") and value.strip()]

    return {
        "title": title,
        "title_zh": title if any("\u4e00" <= ch <= "\u9fff" for ch in title) else None,
        "abstract": abstract,
        "abstract_zh": abstract if abstract and any("\u4e00" <= ch <= "\u9fff" for ch in abstract) else None,
        "authors": authors,
        "journal": journal["title"],
        "journal_short": journal.get("short_name"),
        "journal_id": journal["id"],
        "source_type": "journal",
        "source": "cn-html",
        "source_url": source_url,
        "publisher": first_nonempty(meta.get("citation_publisher"), journal.get("publisher")),
        "published_online": published[:10] if published else None,
        "available_online": available_online,
        "detected_at": now_iso(),
        "doi": doi,
        "url": url,
        "pdf_url": None,
        "fields": journal.get("fields", []),
        "ai_tags": [],
        "translation_status": "native_chinese" if any("\u4e00" <= ch <= "\u9fff" for ch in title) else "missing_abstract",
    }


def html_records(html: str, base_url: str, journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    parser = LinkParser()
    parser.feed(html)
    records = []
    seen = set()
    for href, text in parser.links:
        if len(records) >= limit:
            break
        url = normalize_url(href, base_url)
        if url in seen or len(text) < 6:
            continue
        if not is_article_url(url):
            continue
        if is_noise_text(text):
            continue
        seen.add(url)
        try:
            detail_html = fetch_text(url, timeout=8)
        except Exception:
            continue
        record = parse_detail_page(detail_html, url, journal, base_url)
        if record:
            records.append(record)
    return records


def fetch_journal(journal: dict[str, Any], url: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    html = fetch_text(url, timeout=10)
    for feed_url in discover_feeds(html, url):
        try:
            records = parse_feed(fetch_text(feed_url, timeout=8), journal, feed_url)
            if records:
                for record in records:
                    record["source"] = "cn-rss"
                return records[:limit], f"rss:{feed_url}"
        except Exception:
            continue
    records = html_records(html, url, journal, limit)
    return records, "html-detail"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit-per-journal", type=int, default=20)
    args = parser.parse_args()

    journals_by_id = {journal["id"]: journal for journal in load_journals(args.journals)}
    output = args.output or DATA_DIR / "raw" / "cn" / f"{today_str()}.json"
    records: list[dict[str, Any]] = []
    messages = []

    for journal_id, url in CN_HOME_URLS.items():
        journal = journals_by_id.get(journal_id)
        if not journal:
            messages.append(f"{journal_id}: missing journal config")
            continue
        try:
            fetched, mode = fetch_journal(journal, url, args.limit_per_journal)
            records.extend(fetched)
            messages.append(f"{journal_id}: {len(fetched)} via {mode}")
        except Exception as exc:  # noqa: BLE001
            messages.append(f"{journal_id}: error {exc}")

    if records or not output.exists():
        write_json(output, records)
    record_source("cn-journals", ok=bool(records), count=len(records), message="; ".join(messages))
    print(f"wrote {len(records)} Chinese journal records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
