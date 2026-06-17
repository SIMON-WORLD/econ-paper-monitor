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


EXPLICIT_KEYWORDS = [
    "china",
    "chinese",
    "prc",
    "mainland china",
    "hong kong",
    "taiwan",
    "beijing",
    "shanghai",
    "guangdong",
    "rural china",
    "china shock",
    "hukou",
    "中国",
    "中国企业",
    "中国农村",
    "香港",
    "台湾",
]

WEAK_TOPIC_HINTS = [
    "air pollution",
    "pollution",
    "app security",
    "digital era",
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


def haystack(record: dict[str, Any]) -> str:
    values = [
        record.get("title"),
        record.get("title_zh"),
        record.get("abstract"),
        record.get("abstract_zh"),
        record.get("journal"),
        record.get("source_issue"),
        " ".join(record.get("authors") or []),
    ]
    return " ".join(str(value or "") for value in values).casefold()


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


def classify(record: dict[str, Any]) -> tuple[str, str, str]:
    """Return status, reason, source."""
    manual_reason = str(record.get("china_reason") or "")
    source = str(record.get("china_related_source") or "")
    if record.get("china_related") is True and (source in {"manual", "ai"} or manual_reason):
        return "confirmed", str(record.get("china_reason") or record.get("china_relevance_reason") or "人工/上游确认"), "manual"
    if record.get("china_related") is False and (source in {"manual", "ai"} or manual_reason):
        return "none", str(record.get("china_reason") or record.get("china_relevance_reason") or "人工排除"), "manual"
    if is_chinese_journal(record):
        return "confirmed", "中文期刊默认与中国相关", "rule"

    text = haystack(record)
    if any(keyword.casefold() in text for keyword in EXPLICIT_KEYWORDS):
        return "confirmed", "标题、摘要或元数据包含中国相关关键词", "rule"

    author_count = chinese_author_count(record)
    has_abstract = bool(record.get("abstract") or record.get("abstract_zh"))
    has_weak_topic = any(hint in text for hint in WEAK_TOPIC_HINTS)
    if author_count >= 2 and has_weak_topic and has_abstract:
        return "candidate", f"{author_count} 位疑似中文姓名作者，且摘要/题名含常见中国研究主题词，需要 AI 确认", "rule"
    return "none", "", "rule"


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--all", action="store_true", help="Process all daily archives.")
    args = parser.parse_args()

    changed = confirmed = candidates = 0
    date_filter = None if args.all else args.date
    for path in daily_paths(args.daily_dir, date_filter):
        records = read_json(path, [])
        path_changed = False
        for record in records:
            status, reason, source = classify(record)
            if status == "confirmed":
                confirmed += 1
                updates = {
                    "china_related": True,
                    "china_related_source": record.get("china_related_source") or source,
                    "china_relevance_status": "confirmed",
                    "china_relevance_reason": reason,
                }
            elif status == "candidate":
                candidates += 1
                updates = {
                    "china_related": None,
                    "china_related_source": None,
                    "china_relevance_status": "candidate",
                    "china_relevance_reason": reason,
                }
            else:
                updates = {
                    "china_related": None,
                    "china_related_source": None,
                    "china_relevance_status": "none",
                }
                if reason:
                    updates["china_relevance_reason"] = reason
            for key, value in updates.items():
                if value is None:
                    if key in record:
                        record.pop(key, None)
                        path_changed = True
                        changed += 1
                    continue
                if record.get(key) != value:
                    record[key] = value
                    path_changed = True
                    changed += 1
        if path_changed:
            write_json(path, records)
    record_source("china-relevance", ok=True, count=confirmed, message=f"candidates={candidates} changed={changed}")
    print(f"china relevance confirmed={confirmed} candidates={candidates} changed={changed}")


if __name__ == "__main__":
    main()
