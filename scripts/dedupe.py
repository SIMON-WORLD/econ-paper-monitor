"""Deduplicate raw fetched records and write daily new-paper archives."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import re

from common import DATA_DIR, normalize_doi, read_json, stable_id, today_str, write_json
from status import record_run, record_source


ENRICH_FIELDS = [
    "title_zh",
    "abstract",
    "abstract_zh",
    "authors",
    "publisher",
    "published_online",
    "available_online",
    "accepted_date",
    "issue_date",
    "source_issue",
    "date_precision",
    "date_source",
    "date_confidence",
    "doi",
    "url",
    "pdf_url",
]

DATE_SOURCE_RANK = {
    None: 0,
    "": 0,
    "issue_only": 1,
    "file_upload_date": 2,
    "crossref_published": 2,
    "crossref_created": 2,
    "crossref_issue": 2,
    "crossref_published_online": 3,
    "publisher_meta": 4,
    "publisher_published_online": 4,
    "publisher_available_online": 4,
    "publisher_accepted_date": 4,
    "official_publish_date": 3,
    "rss_published": 4,
    "rss_description_online": 4,
    "cnki_rss_pubdate": 3,
    "world_bank_detail_api": 4,
    "iza_detail_month": 3,
    "repec_series_year": 2,
    "repec_detail_year": 3,
    "nep_issue_date": 3,
    }


def iter_raw_records(raw_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not raw_dir.exists():
        return records
    for path in sorted(raw_dir.rglob("*.json")):
        payload = read_json(path, [])
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    item["_raw_file"] = str(path)
                    records.append(item)
    return records


def merge_daily(existing: list[dict[str, Any]], new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in existing + new_records:
        record_id = record.get("id") or stable_id(record)
        record["id"] = record_id
        match_id = find_matching_record_id(merged, record) or record_id
        if match_id in merged:
            enrich_record(merged[match_id], record)
        else:
            merged[record_id] = record
    return sorted(
        merged.values(),
        key=lambda item: (item.get("published_online") or "", item.get("detected_at") or ""),
        reverse=True,
    )


def valid_iso_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        return text
    return None


def archive_date_for_new_record(record: dict[str, Any], run_date: str) -> str | None:
    """Decide which daily archive should receive a newly seen record.

    RSS feeds often expose a long back catalog. On the first day a feed is
    enabled, those historical items are newly seen by the system but are not
    today's papers. Put dated RSS records under their source date and suppress
    undated RSS records from public daily archives.
    """
    source = str(record.get("source") or "")
    if source == "cnki-rss":
        source_date = valid_iso_date(record.get("available_online")) or valid_iso_date(record.get("published_online"))
        return source_date or None
    if source != "rss":
        source_id = str(record.get("source_id") or "")
        if source_id.startswith("repec-nep-"):
            return valid_iso_date(record.get("available_online")) or valid_iso_date(record.get("published_online")) or run_date
        return run_date
    official = valid_iso_date(record.get("available_online")) or valid_iso_date(record.get("published_online"))
    if not official:
        return None
    return official


def has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def is_bad_abstract(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = " ".join(value.split()).casefold()
    boilerplates = [
        "founded in 1920, the nber is a private",
        "the federal reserve board of governors in washington dc",
    ]
    return any(fragment in normalized for fragment in boilerplates)


def looks_like_abstract_title(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = " ".join(value.split())
    if not text:
        return False
    lowered = text.casefold()
    return len(text) > 260 or lowered.startswith(
        (
            "this paper ",
            "this study ",
            "we analyze ",
            "we analyse ",
            "we examine ",
            "we investigate ",
            "using data ",
            "based on ",
        )
    )


def is_repec_placeholder(value: Any) -> bool:
    text = str(value or "")
    return "RePEc NEP" in text and " item p" in text


def record_match_keys(record: dict[str, Any]) -> set[str]:
    keys: set[str] = {record.get("id") or stable_id(record)}
    source = str(record.get("source") or "").casefold()
    doi = normalize_doi(record.get("doi"))
    if doi:
        keys.add(f"doi:{doi}")
    url = str(record.get("url") or "").strip().rstrip("/")
    if url:
        normalized_url = url.casefold()
        keys.add(f"url:{normalized_url}")
        # CNKI article URLs often share the same path and only differ by query
        # parameters. Dropping the query collapses unrelated papers into one.
        if "kns.cnki.net/kcms2/article/abstract" not in normalized_url:
            keys.add(f"url:{normalized_url.split('?', 1)[0]}")
        for pattern in (
            r"nber\.org/papers/(w\d+)",
            r"iza\.org/publications/dp/(\d+)",
            r"cepr\.org/publications/(dp\d+)",
            r"federalreserve\.gov/econres/feds/([^/.?#]+)",
            r"econpapers\.repec\.org/repec:([^?#]+)",
            r"ideas\.repec\.org/p/([^?#]+)",
        ):
            match = re.search(pattern, normalized_url, flags=re.I)
            if match:
                keys.add(f"urlpaper:{match.group(1).strip('/').casefold()}")
    source_id = str(record.get("source_id") or "")
    paper_number = str(record.get("paper_number") or "")
    if source_id and paper_number:
        keys.add(f"paper:{source_id.casefold()}:{paper_number.casefold()}")
    if source == "cnki-rss":
        title = " ".join(str(record.get("title") or "").casefold().split())
        journal = " ".join(str(record.get("journal") or "").casefold().split())
        if title and journal:
            keys.add(f"cnki-title:{journal}:{title}")
    return keys


def find_matching_record_id(records: dict[str, dict[str, Any]], incoming: dict[str, Any]) -> str | None:
    incoming_keys = record_match_keys(incoming)
    for record_id, existing in records.items():
        if incoming_keys & record_match_keys(existing):
            return record_id
    return None


def build_seen_index(seen_papers: dict[str, dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for record_id, record in seen_papers.items():
        record.setdefault("id", record_id)
        for key in record_match_keys(record):
            index.setdefault(key, record_id)
    return index


def find_matching_seen_id(index: dict[str, str], incoming: dict[str, Any]) -> str | None:
    for key in record_match_keys(incoming):
        if key in index:
            return index[key]
    return None


def add_seen_index(index: dict[str, str], record_id: str, record: dict[str, Any]) -> None:
    record.setdefault("id", record_id)
    for key in record_match_keys(record):
        index.setdefault(key, record_id)


def build_daily_index(daily_dir: Path) -> tuple[dict[Path, list[dict[str, Any]]], dict[str, list[tuple[Path, dict[str, Any]]]]]:
    path_records: dict[Path, list[dict[str, Any]]] = {}
    index: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in daily_dir.glob("*.json"):
        records = read_json(path, [])
        if not isinstance(records, list):
            continue
        path_records[path] = records
        for record in records:
            for key in record_match_keys(record):
                index.setdefault(key, []).append((path, record))
    return path_records, index


def seed_seen_from_daily_match(record: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    seed = {
        "title": existing.get("title") or record.get("title"),
        "journal": existing.get("journal") or record.get("journal"),
        "doi": existing.get("doi") or record.get("doi"),
        "url": existing.get("url") or record.get("url"),
        "first_seen": existing.get("detected_at") or record.get("detected_at"),
    }
    enrich_record(seed, existing)
    enrich_record(seed, record)
    return seed


def matching_daily_records(
    index: dict[str, list[tuple[Path, dict[str, Any]]]],
    record: dict[str, Any],
) -> list[tuple[Path, dict[str, Any]]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    seen: set[tuple[Path, int]] = set()
    for key in record_match_keys(record):
        for path, existing in index.get(key, []):
            marker = (path, id(existing))
            if marker in seen:
                continue
            seen.add(marker)
            matches.append((path, existing))
    return matches


def enrich_record(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    changed = False
    if incoming.get("source_id") == "world-bank-prwp" and has_value(incoming.get("title")) and existing.get("title") != incoming.get("title"):
        existing["title"] = incoming["title"]
        existing.pop("title_zh", None)
        existing.pop("translation_status", None)
        changed = True
    if (
        incoming.get("source_id") == "fed-feds"
        and has_value(incoming.get("title"))
        and str(existing.get("title") or "").strip().casefold() == "board of governors of the federal reserve system"
        and str(incoming.get("title") or "").strip().casefold() != "board of governors of the federal reserve system"
    ):
        existing["title"] = incoming["title"]
        existing.pop("title_zh", None)
        existing.pop("translation_status", None)
        changed = True
    if (
        incoming.get("source_id") == "world-bank-prwp"
        and existing.get("abstract")
        and existing.get("abstract_source") != "world_bank_detail_api"
        and incoming.get("abstract_source") != "world_bank_detail_api"
    ):
        existing["abstract"] = None
        changed = True
    if (
        str(incoming.get("source_id") or "").startswith("repec-nep-")
        and has_value(incoming.get("title"))
        and not looks_like_abstract_title(incoming.get("title"))
        and (is_repec_placeholder(existing.get("title")) or looks_like_abstract_title(existing.get("title")))
    ):
        existing["title"] = incoming["title"]
        existing["url"] = incoming.get("url") or existing.get("url")
        existing.pop("title_zh", None)
        existing.pop("translation_status", None)
        existing.pop("title_parse_status", None)
        existing.pop("public_visible", None)
        changed = True
    if incoming.get("source_id") == "world-bank-prwp" and has_value(incoming.get("authors")) and existing.get("authors") != incoming.get("authors"):
        existing["authors"] = incoming["authors"]
        changed = True
    incoming_date_source = incoming.get("date_source")
    existing_date_source = existing.get("date_source")
    if has_value(incoming.get("published_online")) and (
        not has_value(existing.get("published_online"))
        or DATE_SOURCE_RANK.get(incoming_date_source, 1) > DATE_SOURCE_RANK.get(existing_date_source, 1)
        or incoming_date_source == existing_date_source
    ):
        if existing.get("published_online") != incoming.get("published_online"):
            existing["published_online"] = incoming["published_online"]
            changed = True
        if incoming_date_source and existing.get("date_source") != incoming_date_source:
            existing["date_source"] = incoming_date_source
            changed = True
        if has_value(incoming.get("date_confidence")) and existing.get("date_confidence") != incoming.get("date_confidence"):
            existing["date_confidence"] = incoming["date_confidence"]
            changed = True
    if is_bad_abstract(existing.get("abstract")) and not has_value(incoming.get("abstract")):
        existing["abstract"] = None
        changed = True
    for field in ENRICH_FIELDS:
        if field == "abstract" and is_bad_abstract(existing.get(field)) and has_value(incoming.get(field)) and not is_bad_abstract(incoming.get(field)):
            existing[field] = incoming[field]
            changed = True
            continue
        if not has_value(existing.get(field)) and has_value(incoming.get(field)):
            existing[field] = incoming[field]
            changed = True
    if existing.get("translation_status") in {None, "missing_abstract"} and incoming.get("translation_status") == "native_chinese":
        existing["translation_status"] = incoming["translation_status"]
        changed = True
    return changed


def enrich_existing_daily(daily_dir: Path, record: dict[str, Any]) -> bool:
    record_id = stable_id(record)
    incoming_keys = record_match_keys(record)
    changed = False
    for path in daily_dir.glob("*.json"):
        records = read_json(path, [])
        path_changed = False
        for existing in records:
            existing_keys = record_match_keys(existing)
            if (existing.get("id") or stable_id(existing)) == record_id or incoming_keys & existing_keys:
                if enrich_record(existing, record):
                    path_changed = True
                    changed = True
        if path_changed:
            write_json(path, records)
    return changed


def exists_in_daily(daily_dir: Path, record: dict[str, Any]) -> bool:
    record_id = record.get("id") or stable_id(record)
    incoming_keys = record_match_keys(record)
    for path in daily_dir.glob("*.json"):
        records = read_json(path, [])
        for existing in records:
            existing_keys = record_match_keys(existing)
            if (existing.get("id") or stable_id(existing)) == record_id or incoming_keys & existing_keys:
                return True
    return False


def ensure_daily_archive(daily_dir: Path, record: dict[str, Any], run_date: str) -> bool:
    source = str(record.get("source") or "")
    source_id = str(record.get("source_id") or "")
    if source not in {"rss", "cnki-rss"} and not source_id.startswith("repec-nep-"):
        return False
    archive_date = archive_date_for_new_record(record, run_date)
    if not archive_date or exists_in_daily(daily_dir, record):
        return False
    daily_path = daily_dir / f"{archive_date}.json"
    existing_daily = read_json(daily_path, [])
    write_json(daily_path, merge_daily(existing_daily, [record]))
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    args = parser.parse_args()

    seen = read_json(args.seen, {"papers": {}})
    seen_papers = seen.setdefault("papers", {})
    seen_index = build_seen_index(seen_papers)
    daily_records_by_path, daily_index = build_daily_index(args.daily_dir)
    touched_daily_paths: set[Path] = set()
    new_records_by_date: dict[str, list[dict[str, Any]]] = {}
    enriched = 0
    suppressed = 0

    for record in iter_raw_records(args.raw_dir):
        record_id = stable_id(record)
        record["id"] = record_id
        seen_id = record_id
        if record_id not in seen_papers:
            seen_id = find_matching_seen_id(seen_index, record) or record_id
        daily_matches = matching_daily_records(daily_index, record)
        if seen_id not in seen_papers and daily_matches:
            _, first_existing = daily_matches[0]
            seen_papers[seen_id] = seed_seen_from_daily_match(record, first_existing)
            add_seen_index(seen_index, seen_id, seen_papers[seen_id])
        if seen_id in seen_papers:
            seen_entry = seen_papers[seen_id]
            if enrich_record(seen_entry, record):
                enriched += 1
                add_seen_index(seen_index, seen_id, seen_entry)
            if daily_matches:
                for path, existing in daily_matches:
                    if enrich_record(existing, record):
                        enriched += 1
                        touched_daily_paths.add(path)
            elif ensure_daily_archive(args.daily_dir, record, args.date):
                enriched += 1
                daily_records_by_path, daily_index = build_daily_index(args.daily_dir)
            continue
        seen_papers[record_id] = {
            "title": record.get("title"),
            "journal": record.get("journal"),
            "doi": record.get("doi"),
            "url": record.get("url"),
            "first_seen": record.get("detected_at"),
        }
        enrich_record(seen_papers[record_id], record)
        add_seen_index(seen_index, record_id, seen_papers[record_id])
        record.pop("_raw_file", None)
        archive_date = archive_date_for_new_record(record, args.date)
        if archive_date:
            new_records_by_date.setdefault(archive_date, []).append(record)
        else:
            suppressed += 1

    for path in sorted(touched_daily_paths):
        write_json(path, daily_records_by_path[path])

    daily_total = 0
    for archive_date, dated_records in sorted(new_records_by_date.items()):
        daily_path = args.daily_dir / f"{archive_date}.json"
        existing_daily = read_json(daily_path, [])
        daily_records = merge_daily(existing_daily, dated_records)
        write_json(daily_path, daily_records)
        if archive_date == args.date:
            daily_total = len(daily_records)
    if args.date not in new_records_by_date:
        daily_path = args.daily_dir / f"{args.date}.json"
        daily_total = len(read_json(daily_path, []))

    write_json(args.seen, seen)
    new_total = sum(len(items) for items in new_records_by_date.values())
    record_source("dedupe", ok=True, count=new_total, message=f"daily_total={daily_total} seen={len(seen_papers)} enriched={enriched} suppressed={suppressed}")
    record_run({"new": new_total, "daily_total": daily_total, "seen": len(seen_papers), "enriched": enriched, "suppressed": suppressed})
    print(f"new={new_total} daily_total={daily_total} seen={len(seen_papers)} enriched={enriched} suppressed={suppressed}")


if __name__ == "__main__":
    main()
