"""Fetch Chinese journal latest-article pages with low-cost parsers.

This first version avoids browser automation. It tries configured RSS feeds,
RSS auto-discovery, and simple HTML article-link extraction. Failures are
recorded in data/status.json for follow-up parser work.
"""

from __future__ import annotations

import argparse
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

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

ARTICLE_HINTS = ("Article", "article", "abstract", "CN/abstract", "ch/reader", "期", "摘要", "目录")


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


def discover_feeds(html: str, base_url: str) -> list[str]:
    feeds = []
    for match in re.finditer(r'<link[^>]+(?:rss|atom|application/(?:rss|atom)\+xml)[^>]+>', html, flags=re.I):
        href_match = re.search(r'href=["\']([^"\']+)["\']', match.group(0), flags=re.I)
        if href_match:
            feeds.append(urllib.parse.urljoin(base_url, href_match.group(1)))
    return list(dict.fromkeys(feeds))


def html_records(html: str, base_url: str, journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    parser = LinkParser()
    parser.feed(html)
    records = []
    seen = set()
    for href, text in parser.links:
        if len(records) >= limit:
            break
        url = urllib.parse.urljoin(base_url, href)
        if url in seen or len(text) < 8:
            continue
        if not any(hint in url or hint in text for hint in ARTICLE_HINTS):
            continue
        seen.add(url)
        records.append(
            {
                "title": text,
                "title_zh": text if any("\u4e00" <= ch <= "\u9fff" for ch in text) else None,
                "abstract": None,
                "abstract_zh": None,
                "authors": [],
                "journal": journal["title"],
                "journal_short": journal.get("short_name"),
                "journal_id": journal["id"],
                "source_type": "journal",
                "source": "cn-html",
                "source_url": base_url,
                "publisher": journal.get("publisher"),
                "published_online": None,
                "available_online": None,
                "detected_at": now_iso(),
                "doi": None,
                "url": url,
                "pdf_url": None,
                "fields": journal.get("fields", []),
                "ai_tags": [],
                "translation_status": "native_chinese" if any("\u4e00" <= ch <= "\u9fff" for ch in text) else "missing_abstract",
            }
        )
    return records


def fetch_journal(journal: dict[str, Any], url: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    html = fetch_text(url, timeout=20)
    for feed_url in discover_feeds(html, url):
        try:
            records = parse_feed(fetch_text(feed_url, timeout=20), journal, feed_url)
            if records:
                for record in records:
                    record["source"] = "cn-rss"
                return records[:limit], f"rss:{feed_url}"
        except Exception:
            continue
    records = html_records(html, url, journal, limit)
    return records, "html"


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

    write_json(output, records)
    record_source("cn-journals", ok=True, count=len(records), message="; ".join(messages))
    print(f"wrote {len(records)} Chinese journal records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
