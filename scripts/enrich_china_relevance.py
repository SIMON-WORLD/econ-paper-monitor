"""Add China-relevance signals to daily records.

The public red tag is conservative:
- manual override
- Chinese journals
- explicit China keywords in title/abstract/metadata
- high-confidence AI decisions from ai_china_relevance.py

Weak signals remain candidates for the local review server.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str, write_json
from status import record_source


EXPLICIT_ENGLISH_PATTERNS = [
    r"\bchina\b",
    r"\bchinese\b",
    r"\bprc\b",
    r"\bmainland china\b",
    r"\bhong kong\b",
    r"\btaiwan\b",
    r"\bbeijing\b",
    r"\bshanghai\b",
    r"\bguangdong\b",
    r"\brural china\b",
    r"\bchina shock\b",
    r"\bhukou\b",
]

EXPLICIT_CHINESE_KEYWORDS = [
    "中国企业",
    "中国农村",
    "中国市场",
    "中国经济",
    "中国",
    "香港",
    "台湾",
]

CHINESE_FALSE_POSITIVE_PHRASES = [
    "发展中国家",
    "发展中经济体",
    "最不发达国家",
]

WEAK_TOPIC_HINTS = [
    "air pollution",
    "pollution",
    "app security",
    "digital era",
    "electric vehicle",
    "ev ",
    "tariff",
    "tariffs",
    "trade war",
    "geoeconomic",
    "great powers",
    "climate risk",
    "green transformation",
    "corporate green",
    "green innovation",
    "export",
    "cross-border",
    "overseas investment",
    "multinational enterprises",
    "industrial",
    "supply chain",
    "household registration",
    "hukou",
    "rural",
    "urban",
]

COMMON_CHINESE_SURNAMES = {
    "bai",
    "cai",
    "cao",
    "chang",
    "chen",
    "cheng",
    "cui",
    "deng",
    "ding",
    "dong",
    "du",
    "fan",
    "fang",
    "feng",
    "fu",
    "gao",
    "gu",
    "guan",
    "guo",
    "han",
    "he",
    "hong",
    "hou",
    "hu",
    "huang",
    "jiang",
    "jin",
    "lei",
    "li",
    "lian",
    "liang",
    "lin",
    "liu",
    "lu",
    "luo",
    "ma",
    "pan",
    "peng",
    "qian",
    "qin",
    "ren",
    "shen",
    "shi",
    "song",
    "sun",
    "tan",
    "tang",
    "tao",
    "wang",
    "wei",
    "wu",
    "xia",
    "xiao",
    "xie",
    "xin",
    "xu",
    "xue",
    "yan",
    "yang",
    "yao",
    "ye",
    "yu",
    "yuan",
    "zhang",
    "zhao",
    "zheng",
    "zhou",
    "zhu",
}

CN_JOURNAL_IDS = {
    "journal-379b4022ce",  # 管理世界
    "journal-edcb877d78",  # 数量经济技术经济研究
    "journal-bf2aa9381f",  # 中国工业经济
    "journal-f69300dae2",  # 中国农村经济
    "journal-679eaa2a0c",  # 世界经济
    "journal-ba9f46c919",  # 经济研究
}

CHINA_SCOPE_JOURNAL_IDS = {
    "china-economic-review",
}


def haystack(record: dict[str, Any]) -> str:
    values = [
        record.get("title"),
        record.get("title_zh"),
        record.get("abstract"),
        record.get("abstract_zh"),
        record.get("source_issue"),
        " ".join(record.get("authors") or []),
    ]
    return " ".join(str(value or "") for value in values).casefold()


def chinese_text(record: dict[str, Any]) -> str:
    values = [record.get("title_zh"), record.get("abstract_zh"), record.get("title"), record.get("abstract")]
    text = " ".join(str(value or "") for value in values)
    for phrase in CHINESE_FALSE_POSITIVE_PHRASES:
        text = text.replace(phrase, "")
    return text


def has_explicit_china_signal(record: dict[str, Any]) -> bool:
    text = haystack(record)
    if any(re.search(pattern, text, flags=re.I) for pattern in EXPLICIT_ENGLISH_PATTERNS):
        return True
    cn_text = chinese_text(record)
    return any(keyword in cn_text for keyword in EXPLICIT_CHINESE_KEYWORDS)


def surname(name: str) -> str:
    parts = re.findall(r"[A-Za-z]+", name.casefold())
    return parts[-1] if parts else ""


def chinese_author_count(record: dict[str, Any]) -> int:
    return sum(1 for name in record.get("authors") or [] if surname(str(name)) in COMMON_CHINESE_SURNAMES)


def is_chinese_journal(record: dict[str, Any]) -> bool:
    fields = set(record.get("fields") or [])
    source = str(record.get("source") or "")
    journal_id = str(record.get("journal_id") or "")
    return "chinese" in fields or source == "cn-official" or journal_id in CN_JOURNAL_IDS


def is_china_scope_journal(record: dict[str, Any]) -> bool:
    return str(record.get("journal_id") or "") in CHINA_SCOPE_JOURNAL_IDS


def has_china_topic(record: dict[str, Any]) -> bool:
    return "china" in {str(field) for field in (record.get("fields") or [])}


def classify(record: dict[str, Any]) -> tuple[str, str, str]:
    """Return status, reason, source."""
    manual_reason = str(record.get("china_reason") or "")
    source = str(record.get("china_related_source") or "")
    if record.get("china_related") is True and (source == "manual" or (manual_reason and source != "ai")):
        return "confirmed", str(record.get("china_reason") or record.get("china_relevance_reason") or "人工确认：中国相关"), "manual"
    if record.get("china_related") is False and (source == "manual" or (manual_reason and source != "ai")):
        return "none", str(record.get("china_reason") or record.get("china_relevance_reason") or "人工确认：排除中国相关"), "manual"
    if is_chinese_journal(record):
        return "confirmed", "中文期刊默认与中国相关", "rule"
    if is_china_scope_journal(record) or has_china_topic(record):
        return "confirmed", "journal or topic scope is China economy", "rule"

    text = haystack(record)
    if record.get("china_related") is True and source == "ai" and not has_explicit_china_signal(record):
        return "none", "AI 曾判定为中国相关，但题名/摘要/元数据缺少直接中国证据，已按保守规则排除", "rule"
    if record.get("china_related") is True and source == "ai":
        return "confirmed", str(record.get("china_relevance_reason") or "AI 确认且存在直接中国证据"), "ai"
    if record.get("china_related") is False and source == "ai":
        return "none", str(record.get("china_relevance_reason") or "AI 排除中国相关"), "ai"

    if has_explicit_china_signal(record):
        return "confirmed", "标题、摘要或元数据包含中国相关关键词", "rule"

    author_count = chinese_author_count(record)
    has_abstract = bool(record.get("abstract") or record.get("abstract_zh"))
    has_weak_topic = any(hint in text for hint in WEAK_TOPIC_HINTS)
    if author_count >= 2 and has_weak_topic:
        evidence = "摘要/题名" if has_abstract else "题名或元数据"
        return "candidate", f"{author_count} 位疑似中文姓名作者，且{evidence}包含中国研究常见主题词，需要 AI 确认", "rule"
    if str(record.get("source") or "") == "working_papers" and has_weak_topic and has_abstract:
        return "candidate", "工作论文摘要包含中国研究常见主题词，需要 AI 确认", "rule"
    return "none", "", "rule"


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"))


def classification_updates(record: dict[str, Any]) -> tuple[dict[str, Any | None], str]:
    status, reason, source = classify(record)
    if status == "confirmed":
        return (
            {
                "china_related": True,
                "china_related_source": record.get("china_related_source") or source,
                "china_relevance_status": "confirmed",
                "china_relevance_reason": reason,
            },
            status,
        )
    if status == "candidate":
        return (
            {
                "china_related": None,
                "china_related_source": None,
                "china_relevance_status": "candidate",
                "china_relevance_reason": reason,
            },
            status,
        )
    return (
        {
            "china_related": None,
            "china_related_source": None,
            "china_relevance_status": "none",
            "china_relevance_reason": reason or None,
        },
        status,
    )


def apply_updates(record: dict[str, Any], updates: dict[str, Any | None]) -> int:
    changed = 0
    for key, value in updates.items():
        if value is None:
            if key in record:
                record.pop(key, None)
                changed += 1
            continue
        if record.get(key) != value:
            record[key] = value
            changed += 1
    return changed


def process_seen(path: Path) -> tuple[int, int, int]:
    payload = read_json(path, {"papers": {}})
    papers = payload.get("papers") if isinstance(payload, dict) else {}
    if not isinstance(papers, dict):
        return 0, 0, 0
    changed = confirmed = candidates = 0
    for record in papers.values():
        if not isinstance(record, dict):
            continue
        updates, status = classification_updates(record)
        changed += apply_updates(record, updates)
        if status == "confirmed":
            confirmed += 1
        elif status == "candidate":
            candidates += 1
    if changed:
        write_json(path, payload)
    return changed, confirmed, candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--all", action="store_true", help="Process all daily archives.")
    args = parser.parse_args()

    changed = confirmed = candidates = 0
    date_filter = None if args.all else args.date
    for path in daily_paths(args.daily_dir, date_filter):
        records = read_json(path, [])
        path_changed = False
        for record in records:
            updates, status = classification_updates(record)
            record_changed = apply_updates(record, updates)
            if record_changed:
                path_changed = True
                changed += record_changed
            if status == "confirmed":
                confirmed += 1
            elif status == "candidate":
                candidates += 1
        if path_changed:
            write_json(path, records)
    seen_changed, seen_confirmed, seen_candidates = process_seen(args.seen)
    changed += seen_changed
    confirmed += seen_confirmed
    candidates += seen_candidates
    record_source("china-relevance", ok=True, count=confirmed, message=f"candidates={candidates} changed={changed}")
    print(f"china relevance confirmed={confirmed} candidates={candidates} changed={changed}")


if __name__ == "__main__":
    main()
