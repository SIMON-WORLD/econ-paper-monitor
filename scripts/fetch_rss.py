"""Fetch publisher RSS/Atom feeds configured in journals.yml."""

from __future__ import annotations

import argparse
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from common import DATA_DIR, fetch_text, load_journals, today_str, write_json
from sources.record import article_record
from sources.registry import feeds_for_journal
from status import record_source


ATOM = "{http://www.w3.org/2005/Atom}"


def child_text(node: ElementTree.Element, names: list[str]) -> str | None:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return value[:10] if len(value) >= 10 else None


def parse_feed(xml_text: str, journal: dict[str, Any], feed_url: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    records: list[dict[str, Any]] = []

    if root.tag.endswith("rss") or root.find("channel") is not None:
        items = root.findall("./channel/item")
        for item in items:
            title = child_text(item, ["title"])
            link = child_text(item, ["link", "guid"])
            published = parse_date(child_text(item, ["pubDate", "date"]))
            records.append(make_record(title, link, published, journal, feed_url))
        return [record for record in records if record["title"]]

    entries = root.findall(f".//{ATOM}entry")
    for entry in entries:
        title = child_text(entry, [f"{ATOM}title"])
        link = None
        link_node = entry.find(f"{ATOM}link")
        if link_node is not None:
            link = link_node.attrib.get("href")
        published = parse_date(child_text(entry, [f"{ATOM}published", f"{ATOM}updated"]))
        records.append(make_record(title, link, published, journal, feed_url))
    return [record for record in records if record["title"]]


def make_record(
    title: str | None,
    link: str | None,
    published: str | None,
    journal: dict[str, Any],
    feed_url: str,
) -> dict[str, Any]:
    return {
        **article_record(
            journal,
            title=title or "",
            url=link,
            source="rss",
            source_url=feed_url,
            published_online=published,
            available_online=published,
            date_source="rss_published" if published else None,
            date_confidence="B" if published else "F",
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "rss" / f"{today_str()}.json"
    journals = load_journals(args.journals)
    selected = journals[: args.limit] if args.limit else journals
    records: list[dict[str, Any]] = []
    messages: list[str] = []

    for journal in selected:
        feeds, feed_status = feeds_for_journal(journal, discover=args.discover)
        if not feeds:
            continue
        journal_count = 0
        for source in feeds:
            try:
                fetched = parse_feed(fetch_text(source["url"]), journal, source["url"])
                records.extend(fetched)
                journal_count += len(fetched)
            except Exception as exc:  # noqa: BLE001 - keep the scheduled job moving.
                messages.append(f"{journal.get('title')}: {type(exc).__name__}: {exc}")
        messages.append(f"{journal.get('title')}: {journal_count} via {feed_status}")

    write_json(output, records)
    record_source("rss", ok=True, count=len(records), message="; ".join(messages[-20:]) or str(output))
    print(f"wrote {len(records)} RSS records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
