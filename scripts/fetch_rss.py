"""Fetch publisher RSS/Atom feeds configured in journals.yml."""

from __future__ import annotations

import argparse
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from common import DATA_DIR, fetch_text, first_text, load_journals, now_iso, today_str, write_json


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
        "title": title or "",
        "title_zh": None,
        "abstract": None,
        "abstract_zh": None,
        "authors": [],
        "journal": journal["title"],
        "journal_short": journal.get("short_name"),
        "journal_id": journal["id"],
        "source_type": "journal",
        "source": "rss",
        "source_url": feed_url,
        "publisher": journal.get("publisher"),
        "published_online": published,
        "detected_at": now_iso(),
        "doi": None,
        "url": link,
        "pdf_url": None,
        "fields": journal.get("fields", []),
        "ai_tags": [],
        "translation_status": "missing_abstract",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "rss" / f"{today_str()}.json"
    journals = load_journals(args.journals)
    selected = journals[: args.limit] if args.limit else journals
    records: list[dict[str, Any]] = []

    for journal in selected:
        for source in journal.get("sources", []):
            if source.get("type") != "rss" or not source.get("url"):
                continue
            try:
                records.extend(parse_feed(fetch_text(source["url"]), journal, source["url"]))
            except Exception as exc:  # noqa: BLE001 - keep the scheduled job moving.
                print(f"rss error for {journal.get('title')}: {exc}")

    write_json(output, records)
    print(f"wrote {len(records)} RSS records to {output}")


if __name__ == "__main__":
    main()
