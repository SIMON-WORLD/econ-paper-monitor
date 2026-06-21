"""Normalize existing daily records after fetch/enrichment steps."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json
from status import record_source


CN_JOURNAL_IDS = {
    "journal-379b4022ce",
    "journal-edcb877d78",
    "journal-bf2aa9381f",
    "journal-f69300dae2",
    "journal-679eaa2a0c",
    "journal-ba9f46c919",
}


def has_chinese(value: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value or "")


def looks_like_abstract(value: str | None) -> bool:
    text = " ".join(str(value or "").split())
    if not text:
        return False
    lowered = text.casefold()
    starts = (
        "this paper ",
        "this study ",
        "we analyze ",
        "we analyse ",
        "we examine ",
        "we investigate ",
        "using data ",
        "based on ",
    )
    return len(text) > 260 or any(lowered.startswith(prefix) for prefix in starts)


def confidence_from_record(record: dict[str, Any]) -> str:
    if record.get("date_confidence"):
        return str(record["date_confidence"])
    source = str(record.get("date_source") or "")
    if record.get("accepted_date") or record.get("available_online"):
        return "A"
    if source.startswith("publisher_") or source in {"official_publish_date", "file_upload_date", "rss_published"}:
        return "B"
    if source.startswith("crossref_"):
        return "C"
    if record.get("source_issue") or record.get("issue_date"):
        return "D"
    return "F"


def is_chinese_journal(record: dict[str, Any]) -> bool:
    fields = set(record.get("fields") or [])
    source = str(record.get("source") or "")
    journal_id = str(record.get("journal_id") or "")
    return "chinese" in fields or source == "cn-official" or journal_id in CN_JOURNAL_IDS


def normalize_record(record: dict[str, Any]) -> bool:
    changed = False
    title = str(record.get("title") or "")
    if str(record.get("source_id") or "").startswith("repec-nep-") and looks_like_abstract(title):
        if not record.get("abstract"):
            record["abstract"] = title
        paper_number = record.get("paper_number") or str(record.get("url") or "").split("#")[-1]
        fallback_title = f"{record.get('journal') or 'RePEc NEP'} item {paper_number} (题名待解析)"
        record["title"] = fallback_title
        title = fallback_title
        if looks_like_abstract(record.get("title_zh")):
            record["abstract_zh"] = record.get("title_zh")
            record["title_zh"] = "题名待解析"
        record["title_parse_status"] = "needs_repec_detail_title"
        record["public_visible"] = False
        changed = True
    if has_chinese(title):
        if record.get("title_zh") != title:
            record["title_zh"] = title
            changed = True
        if record.get("translation_status") != "native_chinese":
            record["translation_status"] = "native_chinese"
            changed = True
    if is_chinese_journal(record):
        updates = {
            "china_related": True,
            "china_related_source": record.get("china_related_source") or "rule",
            "china_relevance_status": "confirmed",
            "china_relevance_reason": record.get("china_relevance_reason") or "中文期刊默认与中国相关",
        }
        for key, value in updates.items():
            if record.get(key) != value:
                record[key] = value
                changed = True
    date_source = str(record.get("date_source") or "")
    crossref_source = str((record.get("raw_data") or {}).get("crossref_date_source") or date_source)
    if crossref_source in {"crossref_published", "crossref_issue", "crossref_created"} and record.get("published_online"):
        if not record.get("issue_date"):
            record["issue_date"] = record.get("published_online")
        record["published_online"] = None
        if date_source == "crossref_published":
            record["date_source"] = "crossref_issue"
        changed = True
    confidence = confidence_from_record(record)
    if record.get("date_confidence") != confidence:
        record["date_confidence"] = confidence
        changed = True
    if not record.get("date_source"):
        record["date_source"] = "unknown"
        changed = True
    return changed


def record_key(record: dict[str, Any]) -> str | None:
    for key in ("doi", "id", "url"):
        value = record.get(key)
        if value:
            return f"{key}:{str(value).casefold()}"
    title = " ".join(str(record.get("title") or "").casefold().split())
    journal = str(record.get("journal_id") or record.get("journal") or "").casefold()
    return f"title:{journal}:{title}" if title else None


def remove_cross_day_duplicates(paths: list[Path]) -> tuple[int, int]:
    seen: set[str] = set()
    removed = touched = 0
    for path in sorted(paths):
        records = read_json(path, [])
        kept = []
        path_removed = 0
        for record in records:
            key = record_key(record)
            if key and key in seen:
                path_removed += 1
                continue
            if key:
                seen.add(key)
            kept.append(record)
        if path_removed:
            write_json(path, kept)
            removed += path_removed
            touched += 1
    return removed, touched


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    paths = daily_paths(args.daily_dir, args.date)
    changed = touched = 0
    for path in paths:
        records = read_json(path, [])
        path_changed = False
        for record in records:
            if normalize_record(record):
                changed += 1
                path_changed = True
        if path_changed:
            write_json(path, records)
            touched += 1
    duplicate_removed = duplicate_files = 0
    if not args.date:
        duplicate_removed, duplicate_files = remove_cross_day_duplicates(paths)
    record_source("normalize-records", ok=True, count=changed + duplicate_removed, message=f"files={touched} duplicates_removed={duplicate_removed} duplicate_files={duplicate_files}")
    print(f"normalize records changed={changed} files={touched} duplicates_removed={duplicate_removed} duplicate_files={duplicate_files}")


if __name__ == "__main__":
    main()
