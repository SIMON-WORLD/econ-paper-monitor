"""Render a local CNKI RSS supplement status page."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, ROOT, html_escape, read_json, write_text
from status import load_status


def beijing_stamp(value: str | None) -> str:
    if not value:
        return "暂无"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M 北京时间")


def load_daily_cnki_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True):
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        for record in payload:
            if record.get("source") == "cnki-rss" or str(record.get("date_source") or "").startswith("cnki_rss"):
                record["_daily_date"] = path.stem
                records.append(record)
    return records


def row(cells: list[Any], *, warn: bool = False) -> str:
    class_attr = " class='warn'" if warn else ""
    return f"<tr{class_attr}>" + "".join(f"<td>{html_escape(cell)}</td>" for cell in cells) + "</tr>"


def table(rows: list[str], headers: list[str]) -> str:
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}'>暂无</td></tr>"
    head = "".join(f"<th>{html_escape(header)}</th>" for header in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def main() -> None:
    status = load_status()
    source = (status.get("sources") or {}).get("cnki-rss") or {}
    local_run = (status.get("sources") or {}).get("local-cnki-run") or {}
    group = (status.get("source_groups") or {}).get("cnki-rss") or {}
    records = load_daily_cnki_records()
    by_journal = Counter(record.get("journal") or "未知期刊" for record in records)

    journal_rows = [
        row(
            [
                item.get("journal"),
                "OK" if item.get("ok") else "FAIL",
                item.get("count"),
                item.get("latest_research_date") or item.get("latest_item_date") or "",
                item.get("mode"),
                item.get("message"),
            ],
            warn=(not item.get("ok") or int(item.get("count") or 0) == 0),
        )
        for item in group.get("journals", [])
    ]
    archive_rows = [
        row([journal, count])
        for journal, count in sorted(by_journal.items(), key=lambda item: (-item[1], item[0]))
    ]

    latest_rows = [
        row(
            [
                record.get("_daily_date"),
                record.get("journal"),
                record.get("title"),
                record.get("published_online") or record.get("available_online") or "",
                record.get("url") or "",
            ]
        )
        for record in sorted(records, key=lambda item: (item.get("_daily_date") or "", item.get("title") or ""), reverse=True)[:80]
    ]

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>CNKI RSS 本地补充状态</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:32px;color:#1f2328;line-height:1.55}}
    h1{{margin-bottom:4px}}.muted{{color:#656d76}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(160px,1fr));gap:12px;margin:18px 0}}
    .card{{border:1px solid #d0d7de;border-radius:8px;padding:14px;background:#fff}}.card strong{{display:block;font-size:26px}}
    table{{border-collapse:collapse;width:100%;margin:14px 0 28px;font-size:14px}}th,td{{border:1px solid #d0d7de;padding:8px;text-align:left;vertical-align:top}}th{{background:#f6f8fa}}
    .warn td{{background:#fff8c5}}a{{color:#0969da;text-decoration:none}}
  </style>
</head>
<body>
  <h1>CNKI RSS 本地补充状态</h1>
  <p class="muted">这个页面只在本地后台使用，用来检查 CNKI RSS 是否通过本机成功补充中文期刊数据。</p>
  <div class="grid">
    <div class="card"><strong>{html_escape(source.get('count', 0))}</strong><span>本轮 RSS 原始记录</span></div>
    <div class="card"><strong>{html_escape(len(records))}</strong><span>已进入归档的 CNKI RSS 记录</span></div>
    <div class="card"><strong>{html_escape('OK' if source.get('ok') else 'FAIL')}</strong><span>CNKI RSS 状态</span></div>
    <div class="card"><strong>{html_escape(beijing_stamp(local_run.get('updated_at') or source.get('updated_at')))}</strong><span>最近本地运行</span></div>
  </div>
  <h2>本轮各期刊 RSS 结果</h2>
  {table(journal_rows, ["期刊", "状态", "RSS 条数", "最新来源日期", "模式", "信息"])}
  <h2>已进入归档的 CNKI RSS 记录分布</h2>
  {table(archive_rows, ["期刊", "归档记录数"])}
  <h2>最近 CNKI RSS 归档记录</h2>
  {table(latest_rows, ["归档日期", "期刊", "标题", "来源日期", "链接"])}
</body>
</html>
"""
    output = ROOT / "local_admin" / "cnki_status.html"
    write_text(output, html)
    print(output)


if __name__ == "__main__":
    main()
