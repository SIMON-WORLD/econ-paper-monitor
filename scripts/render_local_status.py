"""Render a local-only admin status page.

Output is written to local_admin/status.html, which is ignored by git.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from common import BEIJING_TZ, DATA_DIR, ROOT, html_escape, read_json, write_text
from status import load_status


ADMIN_URL = "http://127.0.0.1:8765/"


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
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True)[:14]:
        payload = read_json(path, [])
        rows.append((path.stem, len(payload) if isinstance(payload, list) else 0))
    return rows


def has_chinese(value: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value or "")


def pct(done: int, total: int) -> str:
    return "0%" if total == 0 else f"{done / total:.1%}"


def record_link(record: dict[str, Any]) -> str:
    if record.get("url"):
        return str(record["url"])
    if record.get("doi"):
        return f"https://doi.org/{record['doi']}"
    return "#"


def title_cell(record: dict[str, Any]) -> str:
    title = html_escape(record.get("title") or "Untitled")
    title_zh = record.get("title_zh")
    zh = f"<div class='muted'>{html_escape(title_zh)}</div>" if title_zh and title_zh != record.get("title") else ""
    return f"<a href='{html_escape(record_link(record))}' target='_blank' rel='noreferrer'>{title}</a>{zh}"


def public_date_label(record: dict[str, Any]) -> str:
    if record.get("available_online") or record.get("published_online"):
        return "在线日期"
    if record.get("accepted_date"):
        return "接受日期"
    if record.get("source_issue") or record.get("issue_date"):
        return "来源期次"
    return "日期待解析"


def public_date(record: dict[str, Any]) -> str:
    return str(
        record.get("available_online")
        or record.get("published_online")
        or record.get("accepted_date")
        or record.get("source_issue")
        or record.get("issue_date")
        or "待解析"
    )


def date_source_label(record: dict[str, Any]) -> str:
    source = str(record.get("source") or "").casefold()
    date_source = str(record.get("date_source") or "").casefold()
    source_url = str(record.get("source_url") or "").casefold()
    if "pdf" in date_source:
        return "PDF"
    if date_source == "tandf_issue_date_fallback":
        return "T&F 备选日期"
    if "publisher" in date_source or "detail" in date_source:
        return "出版社网页"
    if "rss" in source or "rss" in date_source:
        return "RSS"
    if "crossref" in source or "crossref" in date_source or "crossref" in source_url:
        return "Crossref"
    if source in {"cn", "cn-journal", "official-source"} or record.get("source_issue"):
        return "期刊官网"
    if record.get("url"):
        return "文章页面"
    return "待解析"


def date_evidence_cell(record: dict[str, Any]) -> str:
    raw = record.get("raw_data") if isinstance(record.get("raw_data"), dict) else {}
    items = [
        ("前台日期", f"{public_date_label(record)} {public_date(record)}"),
        ("前台来源", date_source_label(record)),
        ("date_source", record.get("date_source")),
        ("date_confidence", record.get("date_confidence")),
        ("accepted_date", record.get("accepted_date")),
        ("available_online", record.get("available_online")),
        ("published_online", record.get("published_online")),
        ("issue_date", record.get("issue_date")),
        ("source_issue", record.get("source_issue")),
        ("source", record.get("source")),
        ("source_url", record.get("source_url")),
        ("crossref_date_source", raw.get("crossref_date_source")),
        ("doi", record.get("doi")),
        ("pdf_url", record.get("pdf_url")),
    ]
    lines = [f"<div><b>{html_escape(key)}</b>: {html_escape(value)}</div>" for key, value in items if value]
    return "".join(lines) or "暂无"


def table(rows: list[str], headers: list[str]) -> str:
    head = "".join(f"<th>{html_escape(header)}</th>" for header in headers)
    body = "".join(rows) or f"<tr><td colspan='{len(headers)}'>暂无</td></tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def latest_records(records: list[dict[str, Any]], predicate, limit: int = 20) -> list[dict[str, Any]]:
    selected = [record for record in records if predicate(record)]
    return sorted(selected, key=lambda item: item.get("detected_at") or item.get("_daily_date") or "", reverse=True)[:limit]


def main() -> None:
    records = load_records()
    status = load_status()
    workflow = status.get("workflow") or {}
    sources = status.get("sources") or {}
    cn_group = (status.get("source_groups") or {}).get("cn-journals") or {}

    english_titles = sum(1 for record in records if record.get("title") and not has_chinese(str(record.get("title"))))
    translated = sum(1 for record in records if record.get("title_zh"))
    china_confirmed = sum(1 for record in records if record.get("china_related") is True or record.get("china_relevance_status") == "confirmed")
    china_candidates = latest_records(records, lambda record: record.get("china_relevance_status") == "candidate")
    untranslated = latest_records(records, lambda record: record.get("title") and not has_chinese(str(record.get("title"))) and not record.get("title_zh"))
    low_confidence = latest_records(records, lambda record: (record.get("date_confidence") or "F") in {"D", "F", "unknown"})
    date_evidence_records = latest_records(records, lambda record: True, 30)
    by_source = Counter(record.get("source") or "unknown" for record in records)
    by_confidence = Counter(record.get("date_confidence") or "unknown" for record in records)

    health: list[str] = []
    failures = [key for key, item in sources.items() if not item.get("ok")]
    if failures:
        health.append("存在失败来源：" + ", ".join(failures))
    if not workflow.get("finished_at"):
        health.append("尚未记录端到端 workflow 完成时间，下一次监测后会自动补齐。")
    if not health:
        health.append("暂无需要立即处理的来源异常。")

    source_rows = [
        f"<tr><td>{html_escape(source_id)}</td><td>{'OK' if item.get('ok') else 'FAIL'}</td>"
        f"<td>{html_escape(item.get('count'))}</td><td>{html_escape(beijing_stamp(item.get('updated_at')))}</td>"
        f"<td>{html_escape(item.get('message'))}</td></tr>"
        for source_id, item in sorted(sources.items())
    ]
    cn_rows = [
        f"<tr><td>{html_escape(item.get('journal'))}</td><td>{'OK' if item.get('ok') else 'FAIL'}</td>"
        f"<td>{html_escape(item.get('count'))}</td><td>{html_escape(item.get('mode'))}</td>"
        f"<td>{html_escape(item.get('message'))}</td></tr>"
        for item in cn_group.get("journals", [])
    ]
    candidate_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td>"
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('china_relevance_reason'))}</td></tr>"
        for record in china_candidates
    ]
    untranslated_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td>"
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('translation_status'))}</td></tr>"
        for record in untranslated
    ]
    low_conf_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td>"
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('date_confidence'))}</td></tr>"
        for record in low_confidence
    ]
    date_evidence_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td>"
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(public_date_label(record))} {html_escape(public_date(record))} · 来源：{html_escape(date_source_label(record))}</td>"
        f"<td>{date_evidence_cell(record)}</td></tr>"
        for record in date_evidence_records
    ]
    daily_rows = "".join(f"<tr><td>{html_escape(day)}</td><td>{count}</td></tr>" for day, count in daily_counts())
    source_counts = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(by_source.items()))
    confidence_counts = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(by_confidence.items()))
    health_rows = "".join(f"<li>{html_escape(item)}</li>" for item in health)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Econ Papers Daily 本地后台</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:32px;color:#1f2328;line-height:1.5}}
    table{{border-collapse:collapse;width:100%;margin-top:12px;font-size:14px}}td,th{{border:1px solid #d0d7de;padding:8px;text-align:left;vertical-align:top}}
    th{{background:#f6f8fa}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(150px,1fr));gap:12px}}.card{{border:1px solid #d0d7de;padding:14px;border-radius:8px}}
    strong{{font-size:24px;display:block}}.muted{{color:#656d76;font-size:13px}}h2{{margin-top:30px}}a{{color:#0969da;text-decoration:none}}
    .actions{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 24px}}.btn{{border:1px solid #0969da;background:#0969da;color:#fff;border-radius:8px;padding:9px 12px}}.btn.secondary{{background:#fff;color:#0969da}}
  </style>
</head>
<body>
  <h1>Econ Papers Daily 本地后台</h1>
  <div class="actions">
    <a class="btn" href="{ADMIN_URL}">打开审核后台</a>
    <a class="btn secondary" href="{ADMIN_URL}?tab=confirmed">已确认中国相关</a>
    <a class="btn secondary" href="{ADMIN_URL}?tab=rejected">已排除</a>
  </div>

  <div class="grid">
    <div class="card"><strong>{len(records)}</strong><span>总记录</span></div>
    <div class="card"><strong>{translated}</strong><span>已有中文标题</span></div>
    <div class="card"><strong>{pct(translated, max(english_titles, 1))}</strong><span>英文标题翻译覆盖率</span></div>
    <div class="card"><strong>{china_confirmed}</strong><span>已确认中国相关</span></div>
    <div class="card"><strong>{len(china_candidates)}</strong><span>中国相关待审核</span></div>
    <div class="card"><strong>{len(untranslated)}</strong><span>未翻译英文标题样本</span></div>
    <div class="card"><strong>{len(low_confidence)}</strong><span>低可信日期样本</span></div>
    <div class="card"><strong>{html_escape(cn_group.get('count', 0))}</strong><span>中文期刊本轮抓取</span></div>
    <div class="card"><strong>{html_escape(workflow.get('mode_label') or '暂无')}</strong><span>最近监测类型</span></div>
    <div class="card"><strong>{html_escape(beijing_stamp(workflow.get('finished_at')))}</strong><span>最近监测完成</span></div>
  </div>

  <h2>运行概览</h2>
  <table><thead><tr><th>项目</th><th>值</th></tr></thead><tbody>
    <tr><td>最近监测</td><td>{html_escape(workflow.get('mode_label') or '自动监测')} / {html_escape(beijing_stamp(workflow.get('finished_at')))}</td></tr>
    <tr><td>最近全量监测</td><td>{html_escape(beijing_stamp(workflow.get('last_full_finished_at')))}</td></tr>
    <tr><td>最近快速监测</td><td>{html_escape(beijing_stamp(workflow.get('last_light_finished_at')))}</td></tr>
    <tr><td>GitHub Actions</td><td><a href="{html_escape(workflow.get('run_url') or '#')}" target="_blank" rel="noreferrer">{html_escape(workflow.get('run_id') or '暂无')}</a></td></tr>
  </tbody></table>

  <h2>健康提醒</h2>
  <ul>{health_rows}</ul>

  <h2>中文期刊状态</h2>
  {table(cn_rows, ["期刊", "状态", "数量", "抓取方式", "信息"])}

  <h2>中国相关待审核</h2>
  {table(candidate_rows, ["日期", "论文", "期刊", "判定原因"])}

  <h2>未翻译英文标题样本</h2>
  {table(untranslated_rows, ["日期", "论文", "期刊", "翻译状态"])}

  <h2>低可信日期样本</h2>
  {table(low_conf_rows, ["日期", "论文", "期刊", "可信度"])}

  <h2>日期证据链样本</h2>
  {table(date_evidence_rows, ["日期", "论文", "期刊", "前台显示", "完整证据链"])}

  <h2>来源数量</h2>
  <ul>{source_counts}</ul>

  <h2>日期可信度</h2>
  <ul>{confidence_counts}</ul>

  <h2>最近每日记录数</h2>
  <table><thead><tr><th>日期</th><th>记录数</th></tr></thead><tbody>{daily_rows}</tbody></table>

  <h2>来源运行状态</h2>
  {table(source_rows, ["来源", "状态", "数量", "更新时间", "信息"])}
</body>
</html>
"""
    output = ROOT / "local_admin" / "status.html"
    write_text(output, html)
    print(output)


if __name__ == "__main__":
    main()
