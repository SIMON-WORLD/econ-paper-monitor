"""Fetch publisher RSS/Atom feeds configured in journals.yml."""

from __future__ import annotations

import argparse
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
import re

from common import DATA_DIR, fetch_text, filter_journals_by_tier, load_journals, today_str, write_json
from sources.record import article_record
from sources.registry import load_registry, save_registry, feeds_for_journal
from status import record_source


ATOM = "{http://www.w3.org/2005/Atom}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def child_text(node: ElementTree.Element, names: list[str]) -> str | None:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return None


def child_text_any(node: ElementTree.Element, names: list[str]) -> str | None:
    wanted = {name.casefold() for name in names}
    for child in list(node):
        if local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return None


def child_link_any(node: ElementTree.Element) -> str | None:
    for child in list(node):
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text:
            return child.text.strip()
    guid = child_text_any(node, ["guid", "identifier"])
    return guid


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        match = re.search(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", value)
        if match:
            parts = re.split(r"[-/.]", match.group(0))
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return value[:10] if len(value) >= 10 else None


def parse_feed(xml_text: str, journal: dict[str, Any], feed_url: str) -> list[dict[str, Any]]:
    if "<html" in xml_text[:500].casefold():
        raise ValueError("feed URL returned HTML, not RSS/Atom")
    root = ElementTree.fromstring(xml_text)
    records: list[dict[str, Any]] = []

    if root.tag.endswith("rss") or root.find("channel") is not None:
        items = root.findall("./channel/item")
        for item in items:
            title = child_text_any(item, ["title"])
            link = child_link_any(item)
            published = parse_date(child_text_any(item, ["pubDate", "date", "dc:date", "updated", "published"]))
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
    if entries:
        return [record for record in records if record["title"]]

    # Taylor & Francis and some CN platforms expose RSS 1.0/RDF feeds where
    # namespaced <item> nodes are not under /channel.
    for item in root.iter():
        if local_name(item.tag) != "item":
            continue
        title = child_text_any(item, ["title"])
        link = child_link_any(item)
        published = parse_date(child_text_any(item, ["date", "pubDate", "updated", "published"]))
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
            raw_data={"rss_feed_url": feed_url},
        )
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-items-per-feed", type=int, default=120)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--tier", default=None)
    args = parser.parse_args()

    output = args.output or DATA_DIR / "raw" / "rss" / f"{today_str()}.json"
    journals = filter_journals_by_tier(load_journals(args.journals), args.tier)
    if args.only:
        selected_ids = set(args.only)
        journals = [journal for journal in journals if journal.get("id") in selected_ids]
    selected = journals[: args.limit] if args.limit else journals
    records: list[dict[str, Any]] = []
    messages: list[str] = []
    registry = load_registry()

    for journal in selected:
        feeds, feed_status = feeds_for_journal(journal, discover=args.discover)
        registry_entry = registry.setdefault("journals", {}).setdefault(journal["id"], {})
        registry_entry["last_rss_status"] = feed_status
        registry_entry["last_checked_at"] = today_str()
        if not feeds:
            registry_entry["last_rss_count"] = 0
            registry_entry.pop("last_rss_error", None)
            continue
        journal_count = 0
        errors: list[str] = []
        for source in feeds:
            try:
                fetched = parse_feed(fetch_text(source["url"]), journal, source["url"])
                if args.max_items_per_feed:
                    fetched = fetched[: args.max_items_per_feed]
                records.extend(fetched)
                journal_count += len(fetched)
            except Exception as exc:  # noqa: BLE001 - keep the scheduled job moving.
                error = f"{type(exc).__name__}: {exc}"
                errors.append(error)
        registry_entry["last_rss_count"] = journal_count
        if errors and not journal_count:
            registry_entry["last_rss_error"] = errors[-1]
            messages.append(f"{journal.get('title')}: {errors[-1]}")
        else:
            registry_entry.pop("last_rss_error", None)
        messages.append(f"{journal.get('title')}: {journal_count} via {feed_status}")

    save_registry(registry)
    write_json(output, records)
    record_source("rss", ok=True, count=len(records), message="; ".join(messages[-20:]) or str(output))
    print(f"wrote {len(records)} RSS records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
