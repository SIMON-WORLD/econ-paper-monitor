"""Triage degraded formal sources into a machine-readable action table.

Reads ``data/source_health.json`` and emits ``data/source_health_triage.json``
with one row per degraded journal.  The table distinguishes true acquisition
path failures from the single-reliable-path marking convention so maintainers
can decide between adding an official source and keeping the degraded marker.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, write_json


GOOD_RSS = {"official-generated", "configured", "feed", "html", "specialized-api", "specialized-html", "nep-issue"}
SUPPLEMENTAL_SOURCE_IDS = {"openalex-recall"}


# Journals verified to have no usable official feed (checked 2026-08-05).
# They keep the degraded/single-path marker with an explicit supplemental
# source policy instead of an open-ended search for an official feed.
NO_OFFICIAL_FEED_NOTES = {
    "journal-of-the-association-of-environmental-and-resource-economists": (
        "UChicago 平台未提供 JAERE 的 etoc RSS（jc=jaere 404）；按补充源口径封口：Crossref + OpenAlex recall 兜底。"
    ),
    "journal-of-agricultural-and-resource-economics": (
        "官方站 jareonline.org 的 WordPress feed 为空；按补充源口径封口：Crossref + OpenAlex recall 兜底。"
    ),
}


def classify_failure(row: dict[str, Any]) -> dict[str, str]:
    failed = row.get("failed_paths") or []
    failed_groups = [str(item.get("path") or "?") for item in failed]
    reason = str(row.get("degradation_reason") or "")
    crossref_status = str(row.get("crossref_status") or "")
    rss_status = str(row.get("rss_status") or "")
    usable = [str(path) for path in (row.get("usable_paths") or []) if path not in SUPPLEMENTAL_SOURCE_IDS]

    if "priority-toc" in failed_groups:
        return {
            "group": "priority-toc-blocked",
            "summary": "priority-toc 出版社页面结构性失败（HTTPError/URLError/0），Crossref fallback 已兜底",
            "action": "复测确认仍被拦；接入官方 RSS（OUP/MIT/Springer）或保持降级标记并依赖 Crossref fallback",
        }
    if "cn-journals" in failed_groups:
        return {
            "group": "cn-endpoint",
            "summary": "CN 期刊端点失败（如 502），cnki-rss/crossref 已兜底",
            "action": "等待出版社恢复并复测；保持显式降级标记",
        }
    if failed_groups:
        return {
            "group": "failed-path",
            "summary": f"配置路径失败: {', '.join(failed_groups)}",
            "action": "复测源；若结构性问题则接入官方 RSS 或保持降级标记",
        }
    if reason == "single_path":
        if "rss" in usable and crossref_status != "ok":
            return {
                "group": "marking-single-path",
                "summary": "官方 RSS 正常，仅 Crossref 报错导致单路径降级标记",
                "action": "标记口径而非真实中断；恢复 Crossref 或增加第二路径后可转 healthy",
            }
        if "crossref" in usable and len(usable) == 1:
            return {
                "group": "true-single-path",
                "summary": "仅 Crossref 单路径可用",
                "action": "接入官方 RSS/TOC/advance 源以建立独立兜底",
            }
        return {
            "group": "true-single-path",
            "summary": f"单条可靠路径可用: {', '.join(usable) or 'none'}",
            "action": "增加独立兜底路径或保持降级标记",
        }
    if reason == "no_reliable_path":
        return {
            "group": "supplemental-only",
            "summary": "无可靠抓取路径，仅 openalex-recall 兜底",
            "action": "接入官方 RSS/TOC/advance 源；未接入前保持 degraded 标记",
        }
    return {
        "group": "other",
        "summary": f"降级原因: {reason or 'unknown'}",
        "action": "核对 source_health 判定口径后处理",
    }


def build_triage(source_health: dict[str, Any]) -> dict[str, Any]:
    degraded = source_health.get("degraded") or []
    rows = []
    for row in degraded:
        cls = classify_failure(row)
        note = NO_OFFICIAL_FEED_NOTES.get(str(row.get("journal_id") or ""))
        group = "supplemental-closed" if note else cls["group"]
        failed = row.get("failed_paths") or []
        rows.append(
            {
                "journal": row.get("journal"),
                "journal_id": row.get("journal_id"),
                "publisher": row.get("publisher"),
                "current_paths": row.get("usable_paths") or [],
                "degradation_reason": row.get("degradation_reason"),
                "failed_paths": [
                    {"path": item.get("path"), "message": str(item.get("message") or "")[:160]}
                    for item in failed
                ],
                "crossref_status": row.get("crossref_status"),
                "rss_status": row.get("rss_status"),
                "group": group,
                "failure_summary": note or cls["summary"],
                "suggested_action": note or cls["action"],
            }
        )
    groups: dict[str, int] = {}
    for row in rows:
        groups[row["group"]] = groups.get(row["group"], 0) + 1
    table = [
        "| 期刊 | 当前路径 | 失败原因 | 建议动作 |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        paths = ", ".join(row["current_paths"] or ["none"])
        failed = ", ".join(f"{item['path']}" for item in row["failed_paths"]) or row["degradation_reason"] or "none"
        action = row["suggested_action"].replace("|", "/")
        table.append(f"| {row['journal'] or row['journal_id']} | {paths} | {failed} | {action} |")
    return {
        "checked_at": source_health.get("checked_at"),
        "degraded_count": len(rows),
        "group_counts": groups,
        "rows": rows,
        "markdown_table": "\n".join(table),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=DATA_DIR / "source_health_triage.json")
    args = parser.parse_args()
    source_health = read_json(args.data_dir / "source_health.json", {})
    report = build_triage(source_health)
    write_json(args.output, report)
    print(f"triage degraded={report['degraded_count']} groups={report['group_counts']}")
    print(report["markdown_table"])


if __name__ == "__main__":
    main()