"""Add China-relevance signals to daily records.

The public red tag remains conservative: explicit keywords, Chinese journals,
or manual overrides. We also write candidate records for local review when
signals are weaker, such as several Chinese romanized author names.
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
    "hong kong",
    "taiwan",
    "beijing",
    "shanghai",
    "guangdong",
    "rural china",
    "china shock",
    "中国",
    "中国企业",
    "中国农村",
    "香港",
    "台湾",
]

TOPIC_HINTS = [
    "air pollution",
    "pollution",
    "app security",
    "digital era",
    "export",
    "cross-border",
    "industrial",
    "household registration",
    "hukou",
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


def haystack(record: dict[str, Any]) -> str:
    values = [
        record.get("title"),
        record.get("title_zh"),
        record.get("abstract"),
        record.get("abstract_zh"),
        record.get("journal"),
        " ".join(record.get("authors") or []),
    ]
    return " ".join(str(value or "") for value in values).casefold()


def surname(name: str) -> str:
    parts = re.findall(r"[A-Za-z]+", name.casefold())
    return parts[-1] if parts else ""


def chinese_author_count(record: dict[str, Any]) -> int:
    return sum(1 for name in record.get("authors") or [] if surname(str(name)) in COMMON_CHINESE_SURNAMES)


def classify(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("china_related") is True:
        return "confirmed", str(record.get("china_reason") or "manual override")
    if record.get("china_related") is False:
        return "none", str(record.get("china_reason") or "manual exclusion")
    if "chinese" in (record.get("fields") or []):
        return "confirmed", "中文期刊默认与中国相关"
    text = haystack(record)
    if any(keyword.casefold() in text for keyword in EXPLICIT_KEYWORDS):
        return "confirmed", "标题/摘要/元数据包含中国相关关键词"
    author_count = chinese_author_count(record)
    if author_count >= 2 and any(hint in text for hint in TOPIC_HINTS):
        return "candidate", f"{author_count} 位疑似中文姓名作者，且题名含中国研究常见主题词"
    if author_count >= 3:
        return "candidate", f"{author_count} 位疑似中文姓名作者，需要人工确认是否研究中国"
    return "none", ""


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    args = parser.parse_args()

    changed = confirmed = candidates = 0
    for path in daily_paths(args.daily_dir, args.date):
        records = read_json(path, [])
        path_changed = False
        for record in records:
            status, reason = classify(record)
            if status == "confirmed":
                confirmed += 1
                updates = {
                    "china_related": True,
                    "china_related_source": record.get("china_related_source") or "rule",
                    "china_relevance_status": "confirmed",
                    "china_relevance_reason": reason,
                }
            elif status == "candidate":
                candidates += 1
                updates = {
                    "china_relevance_status": "candidate",
                    "china_relevance_reason": reason,
                }
            else:
                updates = {"china_relevance_status": "none"}
                if reason:
                    updates["china_relevance_reason"] = reason
            for key, value in updates.items():
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
