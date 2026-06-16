"""Render a local-only admin status page.

Output is written to local_admin/status.html, which is ignored by git.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, ROOT, html_escape, read_json, write_text
from status import load_status


def load_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True):
        payload = read_json(path, [])
        if isinstance(payload, list):
            for record in payload:
                record["_daily_date"] = path.stem
                records.append(record)
    return records


def daily_counts() -> list[tuple[str, int]]:
    rows = []
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True)[:10]:
        payload = read_json(path, [])
        rows.append((path.stem, len(payload) if isinstance(payload, list) else 0))
    return rows


def pct(done: int, total: int) -> str:
    return "0%" if total == 0 else f"{done / total:.1%}"


def record_link(record: dict[str, Any]) -> str:
    return record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#")


def title_cell(record: dict[str, Any]) -> str:
    title = html_escape(record.get("title") or "Untitled")
    title_zh = record.get("title_zh")
    zh = f"<div class='muted'>{html_escape(title_zh)}</div>" if title_zh else ""
    return f"<a href='{html_escape(record_link(record))}'>{title}</a>{zh}"


def table(rows: list[str], headers: list[str]) -> str:
    head = "".join(f"<th>{html_escape(header)}</th>" for header in headers)
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}'>暂无</td></tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def latest_records(records: list[dict[str, Any]], predicate, limit: int = 20) -> list[dict[str, Any]]:
    selected = [record for record in records if predicate(record)]
    return sorted(selected, key=lambda item: item.get("detected_at") or item.get("_daily_date") or "", reverse=True)[:limit]


def health_items(status: dict[str, Any]) -> list[str]:
    items = []
    sources = status.get("sources", {})
    cn_message = str(sources.get("cn-journals", {}).get("message") or "")
    if "stale-latest" in cn_message:
        items.append("部分中文期刊官网/API 当前最新期仍早于当前年份，系统已排除旧期，不进入今日论文流。")
    translation = sources.get("translation", {})
    if translation and not translation.get("ok"):
        items.append("标题翻译未成功：请检查本地 .env 或 GitHub Secrets 中的 DEEPSEEK_API_KEY。")
    failures = [key for key, item in sources.items() if not item.get("ok")]
    if failures:
        items.append("存在失败来源：" + ", ".join(failures))
    return items


def main() -> None:
    records = load_records()
    status = load_status()
    translated = sum(1 for record in records if record.get("title_zh"))
    china_confirmed = sum(1 for record in records if record.get("china_related") is True)
    china_candidates = latest_records(records, lambda record: record.get("china_relevance_status") == "candidate")
    untranslated = latest_records(
        records,
        lambda record: not record.get("title_zh") and not any("\u4e00" <= ch <= "\u9fff" for ch in str(record.get("title") or "")),
    )
    low_confidence = latest_records(records, lambda record: (record.get("date_confidence") or "F") in {"D", "F", "unknown"})
    by_source = Counter(record.get("source") or "unknown" for record in records)
    by_confidence = Counter(record.get("date_confidence") or "unknown" for record in records)
    registry = read_json(DATA_DIR / "source_registry.json", {"journals": {}})
    registry_items = registry.get("journals", {})
    registry_rss = sum(1 for item in registry_items.values() if item.get("rss"))
    registry_status = Counter(item.get("status") or "unknown" for item in registry_items.values())
    registry_platform = Counter(item.get("platform") or "unknown" for item in registry_items.values())
    latest_run = (status.get("runs") or [{}])[0]
    health = health_items(status)

    source_rows = []
    for source_id, item in sorted(status.get("sources", {}).items()):
        ok = "OK" if item.get("ok") else "FAIL"
        source_rows.append(
            f"<tr><td>{html_escape(source_id)}</td><td>{ok}</td><td>{html_escape(item.get('count'))}</td>"
            f"<td>{html_escape(item.get('updated_at'))}</td><td>{html_escape(item.get('message'))}</td></tr>"
        )

    candidate_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td><td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('china_relevance_reason'))}</td></tr>"
        for record in china_candidates
    ]
    untranslated_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td><td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('translation_status'))}</td></tr>"
        for record in untranslated
    ]
    low_conf_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td><td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('date_confidence'))}</td></tr>"
        for record in low_confidence
    ]

    counts_html = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(by_source.items()))
    confidence_html = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(by_confidence.items()))
    registry_status_html = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(registry_status.items()))
    registry_platform_html = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(registry_platform.items()))
    daily_rows = "".join(f"<tr><td>{html_escape(day)}</td><td>{count}</td></tr>" for day, count in daily_counts())
    health_rows = "".join(f"<li>{html_escape(item)}</li>" for item in health) or "<li>暂无需要处理的来源异常。</li>"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Econ Papers Daily 本地后台</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:32px;color:#1f2328;line-height:1.5}}
    table{{border-collapse:collapse;width:100%;margin-top:12px;font-size:14px}}td,th{{border:1px solid #d0d7de;padding:8px;text-align:left;vertical-align:top}}
    th{{background:#f6f8fa}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:12px}}.card{{border:1px solid #d0d7de;padding:14px;border-radius:8px}}
    strong{{font-size:24px;display:block}}.muted{{color:#656d76;font-size:13px}}h2{{margin-top:30px}}a{{color:#0969da;text-decoration:none}}
  </style>
</head>
<body>
  <h1>Econ Papers Daily 本地后台</h1>
  <div class="grid">
    <div class="card"><strong>{len(records)}</strong><span>总记录</span></div>
    <div class="card"><strong>{translated}</strong><span>已翻译标题</span></div>
    <div class="card"><strong>{pct(translated, len(records))}</strong><span>标题翻译覆盖率</span></div>
    <div class="card"><strong>{china_confirmed}</strong><span>已确认中国相关</span></div>
    <div class="card"><strong>{html_escape(latest_run.get('new', '暂无'))}</strong><span>最近新增</span></div>
    <div class="card"><strong>{registry_rss}</strong><span>RSS Registry</span></div>
    <div class="card"><strong>{len(china_candidates)}</strong><span>中国相关待确认</span></div>
    <div class="card"><strong>{len(untranslated)}</strong><span>未翻译标题样本</span></div>
    <div class="card"><strong>{len(low_confidence)}</strong><span>低可信日期样本</span></div>
  </div>

  <h2>健康提醒</h2>
  <ul>{health_rows}</ul>

  <h2>中国相关待人工确认</h2>
  {table(candidate_rows, ["日期", "论文", "期刊", "判定原因"])}

  <h2>未翻译英文标题样本</h2>
  {table(untranslated_rows, ["日期", "论文", "期刊", "翻译状态"])}

  <h2>低可信日期样本</h2>
  {table(low_conf_rows, ["日期", "论文", "期刊", "可信度"])}

  <h2>来源数量</h2>
  <ul>{counts_html}</ul>

  <h2>日期可信度</h2>
  <ul>{confidence_html}</ul>

  <h2>Source Registry</h2>
  <p>用于判断每本期刊当前依赖官网、RSS、Crossref 还是特殊中文适配器。</p>
  <h3>配置状态</h3>
  <ul>{registry_status_html}</ul>
  <h3>平台分布</h3>
  <ul>{registry_platform_html}</ul>

  <h2>最近每日记录数</h2>
  <table><thead><tr><th>日期</th><th>记录数</th></tr></thead><tbody>{daily_rows}</tbody></table>

  <h2>运行状态</h2>
  {table(source_rows, ["来源", "状态", "数量", "更新时间 UTC", "信息"])}
</body>
</html>
"""
    output = ROOT / "local_admin" / "status.html"
    write_text(output, html)
    print(output)


if __name__ == "__main__":
    main()
