"""Source registry and RSS feed discovery."""

from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from common import DATA_DIR, fetch_text, read_json, write_json


REGISTRY_PATH = DATA_DIR / "source_registry.json"


class FeedLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "link":
            rel = attr.get("rel", "").lower()
            typ = attr.get("type", "").lower()
            href = attr.get("href", "")
            if href and "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
                self.links.append({"url": self._join(href), "label": typ or "alternate"})
        if tag.lower() == "a":
            self._href = attr.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        text = re.sub(r"\s+", " ", "".join(self._text)).strip()
        if text and re.search(r"rss|atom|feed|online first|advance|latest|current issue", text, re.I):
            self.links.append({"url": self._join(self._href), "label": text})
        self._href = None
        self._text = []

    def _join(self, href: str) -> str:
        return urllib.parse.urljoin(self.base_url, href).split("#", 1)[0]


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return read_json(path, {"journals": {}})


def save_registry(registry: dict[str, Any], path: Path = REGISTRY_PATH) -> None:
    write_json(path, registry)


def configured_rss_urls(journal: dict[str, Any]) -> list[dict[str, str]]:
    feeds: list[dict[str, str]] = []
    for source in journal.get("sources", []):
        if source.get("type") == "rss" and source.get("url"):
            feeds.append({"url": source["url"], "label": "configured"})
    return feeds


def candidate_pages(journal: dict[str, Any]) -> list[str]:
    pages = []
    for key in ("homepage_url", "rss_page_url"):
        if journal.get(key):
            pages.append(journal[key])
    for source in journal.get("sources", []):
        if source.get("type") in {"homepage", "rss_page"} and source.get("url"):
            pages.append(source["url"])
    return list(dict.fromkeys(pages))


def discover_feeds_from_page(url: str, timeout: int = 20) -> list[dict[str, str]]:
    html = fetch_text(url, timeout=timeout)
    parser = FeedLinkParser(url)
    parser.feed(html)
    seen: dict[str, dict[str, str]] = {}
    for item in parser.links:
        if item["url"].startswith(("http://", "https://")):
            seen[item["url"]] = item
    return list(seen.values())


def feeds_for_journal(journal: dict[str, Any], *, discover: bool = False) -> tuple[list[dict[str, str]], str]:
    registry = load_registry()
    journal_entry = registry.setdefault("journals", {}).setdefault(journal["id"], {})
    feeds = configured_rss_urls(journal)
    feeds.extend(journal_entry.get("rss", []))

    if discover and not feeds:
        discovered: list[dict[str, str]] = []
        for page in candidate_pages(journal):
            try:
                discovered.extend(discover_feeds_from_page(page))
            except Exception:
                continue
        if discovered:
            journal_entry["rss"] = discovered
            journal_entry["rss_status"] = "discovered"
            save_registry(registry)
            feeds.extend(discovered)

    deduped = list({feed["url"]: feed for feed in feeds if feed.get("url")}.values())
    status = "configured" if configured_rss_urls(journal) else journal_entry.get("rss_status", "none")
    return deduped, status
