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

MONTHS = {
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


def child_texts_any(node: ElementTree.Element, names: list[str]) -> list[str]:
    wanted = {name.casefold() for name in names}
    values: list[str] = []
    for child in list(node):
        if local_name(child.tag) in wanted and child.text:
            cleaned = clean_text(child.text)
            if cleaned:
                values.append(cleaned)
    return values


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
        match = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})", value)
        if match:
            month = MONTHS.get(match.group(2).casefold())
            if month:
                return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(1)):02d}"
        match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})", value)
        if match:
            month = MONTHS.get(match.group(1).casefold())
            if month:
                return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
        return value[:10] if len(value) >= 10 else None


def parse_month_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    match = re.search(r"([A-Za-z]{3,9})\s+(20\d{2})", text)
    if match:
        month = MONTHS.get(match.group(1).casefold())
        if month:
            return f"{int(match.group(2)):04d}-{month:02d}-01"
    match = re.search(r"(20\d{2})\s*[-/年]\s*(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-01"
    return None


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def metadata_from_description(description: str | None) -> dict[str, Any]:
    text = clean_text(description)
    result: dict[str, Any] = {}
    if not text:
        return result
    available_match = re.search(r"(?:Available online|Online available|Article available online)\s*:?\s*(.+?20\d{2})", text, flags=re.I)
    parsed_date = parse_date(available_match.group(1)) if available_match else None
    if parsed_date:
        result["published_online"] = parsed_date
        result["available_online"] = parsed_date
        result["date_source"] = "rss_description_online"
        result["date_confidence"] = "B"
    publication_match = re.search(r"Publication date:\s*(.+?20\d{2})", text, flags=re.I)
    publication_value = publication_match.group(1) if publication_match else None
    issue_date = parse_date(publication_value) or parse_month_date(publication_value)
    if issue_date:
        result["issue_date"] = issue_date
        if issue_date.endswith("-01") and publication_value and not re.search(r"\d{1,2}\s+[A-Za-z]{3,9}|[A-Za-z]{3,9}\s+\d{1,2}", publication_value):
            result["date_precision"] = "month"
    source_match = re.search(r"Source:\s*(.*?)(?:Author\(s\):|$)", text, flags=re.I)
    if source_match:
        result["source_issue"] = clean_text(source_match.group(1))
    authors_match = re.search(r"Author\(s\):\s*(.*)$", text, flags=re.I)
    if authors_match:
        authors = [clean_text(part) for part in re.split(r"\s*,\s*|\s+and\s+", authors_match.group(1)) if clean_text(part)]
        if authors:
            result["authors"] = authors[:12]
    return result


def normalize_authors(values: list[str]) -> list[str]:
    authors: list[str] = []
    for value in values:
        for part in re.split(r"\s*;\s*|\s+ and\s+|\s*,\s*(?=[A-Z][A-Za-z'.-]+(?:\s|$))", value):
            cleaned = clean_text(part)
            if cleaned and cleaned not in authors:
                authors.append(cleaned)
    return authors[:12]


def extract_pii(*values: str | None) -> str | None:
    for value in values:
        text = str(value or "")
        match = re.search(r"/pii/(S[0-9A-Z]+)", text, flags=re.I)
        if match:
            return match.group(1).upper()
        match = re.search(r"\b(S\d{15,}[A-Z0-9]*)\b", text, flags=re.I)
        if match:
            return match.group(1).upper()
    return None


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
            guid = child_text_any(item, ["guid", "identifier"])
            published = parse_date(child_text_any(item, ["pubDate", "date", "dc:date", "updated", "published"]))
            description = child_text_any(item, ["description", "summary", "content"])
            authors = child_texts_any(item, ["creator", "author", "dc:creator"])
            records.append(make_record(title, link, published, journal, feed_url, description=description, guid=guid, authors=authors))
        return [record for record in records if record["title"]]

    entries = root.findall(f".//{ATOM}entry")
    for entry in entries:
        title = child_text(entry, [f"{ATOM}title"])
        link = None
        link_node = entry.find(f"{ATOM}link")
        if link_node is not None:
            link = link_node.attrib.get("href")
        published = parse_date(child_text(entry, [f"{ATOM}published", f"{ATOM}updated"]))
        description = child_text(entry, [f"{ATOM}summary", f"{ATOM}content"])
        authors = [
            clean_text(name.text)
            for author in entry.findall(f"{ATOM}author")
            for name in [author.find(f"{ATOM}name")]
            if name is not None and name.text
        ]
        records.append(make_record(title, link, published, journal, feed_url, description=description, authors=authors))
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
        description = child_text_any(item, ["description", "summary", "content"])
        authors = child_texts_any(item, ["creator", "author", "dc:creator"])
        records.append(make_record(title, link, published, journal, feed_url, description=description, authors=authors))
    return [record for record in records if record["title"]]


def make_record(
    title: str | None,
    link: str | None,
    published: str | None,
    journal: dict[str, Any],
    feed_url: str,
    description: str | None = None,
    guid: str | None = None,
    authors: list[str] | None = None,
) -> dict[str, Any]:
    description_metadata = metadata_from_description(description)
    parsed_authors = normalize_authors(authors or []) or description_metadata.get("authors")
    pii = extract_pii(link, guid, description)
    record = {
        **article_record(
            journal,
            title=clean_text(title),
            url=link,
            source="rss",
            source_url=feed_url,
            authors=parsed_authors,
            published_online=published or description_metadata.get("published_online"),
            available_online=published or description_metadata.get("available_online"),
            issue_date=description_metadata.get("issue_date"),
            source_issue=description_metadata.get("source_issue"),
            date_source="rss_published" if published else description_metadata.get("date_source"),
            date_confidence="B" if published else description_metadata.get("date_confidence", "F"),
            raw_data={"rss_feed_url": feed_url, "rss_guid": guid, "pii": pii},
        )
    }
    if description_metadata.get("date_precision"):
        record["date_precision"] = description_metadata["date_precision"]
    return record


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
