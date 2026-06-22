"""Product-quality audit for monitored paper records.

The audit is intentionally data-facing: it reports issues that affect what a
reader sees on the public site, not crawler implementation details.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json


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


def is_working_paper(record: dict[str, Any]) -> bool:
    source_type = str(record.get("source_type") or "")
    return str(record.get("source") or "") == "working_papers" or source_type in {"working_paper", "policy_paper", "aggregator"}


def is_cn_journal(record: dict[str, Any]) -> bool:
    return str(record.get("journal_id") or "") in CN_JOURNAL_IDS or str(record.get("source") or "") == "cn-official"


def official_date(record: dict[str, Any]) -> str:
    return str(
        record.get("available_online")
        or record.get("published_online")
        or record.get("accepted_date")
        or record.get("issue_date")
        or ""
    )


def looks_like_abstract(value: str | None) -> bool:
    text = " ".join(str(value or "").split())
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


def daily_paths(daily_dir: Path) -> list[Path]:
    return sorted(daily_dir.glob("*.json"), reverse=True)


def load_records(daily_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in daily_paths(daily_dir):
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        for record in payload:
            record = dict(record)
            record["_daily_date"] = path.stem
            records.append(record)
    return records


def record_label(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": record.get("_daily_date"),
        "title": record.get("title"),
        "journal": record.get("journal"),
        "url": record.get("url") or (f"https://doi.org/{record.get('doi')}" if record.get("doi") else None),
        "date_confidence": record.get("date_confidence"),
        "date_source": record.get("date_source"),
        "official_date": official_date(record),
        "source_issue": record.get("source_issue"),
    }


def audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    today = today_str()
    today_records = [record for record in records if record.get("_daily_date") == today]
    journal_today = [record for record in today_records if not is_working_paper(record)]
    working_today = [record for record in today_records if is_working_paper(record)]
    confidence = Counter(str(record.get("date_confidence") or "unknown") for record in records)
    date_source = Counter(str(record.get("date_source") or "unknown") for record in records)
    by_source = Counter(str(record.get("source") or record.get("source_id") or "unknown") for record in records)

    duplicate_keys: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = str(record.get("doi") or record.get("url") or "").casefold()
        if key:
            duplicate_keys[key].append(record)
    duplicates = [items for items in duplicate_keys.values() if len(items) > 1]

    low_conf_today = [
        record
        for record in today_records
        if str(record.get("date_confidence") or "F") in {"D", "F", "unknown"}
    ]
    cn_issue_only_today = [
        record
        for record in journal_today
        if is_cn_journal(record)
        and str(record.get("date_source") or "") == "issue_only"
        and not official_date(record)
    ]
    abstract_titles = [record for record in records if looks_like_abstract(record.get("title"))]
    untranslated_recent = [
        record
        for record in records[:500]
        if record.get("title") and not has_chinese(str(record.get("title"))) and not record.get("title_zh")
    ]
    china_candidates = [record for record in records if record.get("china_relevance_status") == "candidate"]
    china_public = [record for record in records if record.get("china_related") is True or record.get("china_relevance_status") == "confirmed"]

    return {
        "generated_for": today,
        "totals": {
            "records": len(records),
            "today_records": len(today_records),
            "today_journal_records": len(journal_today),
            "today_working_papers": len(working_today),
            "china_related_public": len(china_public),
            "china_candidates": len(china_candidates),
            "duplicates_by_url_or_doi": len(duplicates),
        },
        "date_confidence": dict(confidence),
        "date_source_top": dict(date_source.most_common(20)),
        "source_top": dict(by_source.most_common(20)),
        "issues": {
            "today_low_confidence": [record_label(record) for record in low_conf_today[:50]],
            "today_cn_issue_only": [record_label(record) for record in cn_issue_only_today[:50]],
            "abstract_as_title": [record_label(record) for record in abstract_titles[:50]],
            "untranslated_recent": [record_label(record) for record in untranslated_recent[:50]],
            "duplicate_examples": [[record_label(record) for record in group[:5]] for group in duplicates[:20]],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "quality_report.json")
    args = parser.parse_args()
    records = load_records(args.daily_dir)
    report = audit(records)
    write_json(args.output, report)
    totals = report["totals"]
    print(
        "quality audit "
        f"records={totals['records']} today={totals['today_records']} "
        f"today_journals={totals['today_journal_records']} today_wp={totals['today_working_papers']} "
        f"duplicates={totals['duplicates_by_url_or_doi']}"
    )


if __name__ == "__main__":
    main()
