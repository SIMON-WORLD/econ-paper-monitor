"""Render a local-only admin status page.

Output is written to local_admin/status.html, which is ignored by git.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from common import BEIJING_TZ, DATA_DIR, ROOT, html_escape, load_journals, read_json, write_text
from status import load_status


ADMIN_URL = "http://127.0.0.1:8765/"

CONFIDENCE_LABELS = {
    "A": "A 高：出版社网页/PDF 明确日期",
    "B": "B 中：RSS/出版社候选日期",
    "C": "C 低：Crossref 元数据",
    "D": "D 低：卷期/印刷日期",
    "F": "F 待核：仅首次监测",
    "unknown": "unknown：未标注",
}


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


def beijing_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(BEIJING_TZ)


def next_hourly_run(value: str | None) -> str:
    now_dt = datetime.now(BEIJING_TZ)
    dt = max(beijing_dt(value) or now_dt, now_dt)
    next_dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_dt.strftime("%Y-%m-%d %H:%M 北京时间")


def next_daily_full_run(value: str | None) -> str:
    now_dt = datetime.now(BEIJING_TZ)
    dt = max(beijing_dt(value) or now_dt, now_dt)
    candidate = dt.replace(hour=8, minute=30, second=0, microsecond=0)
    if candidate <= dt:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d %H:%M 北京时间")


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


def latest_daily_count() -> tuple[str, int]:
    today = datetime.now(BEIJING_TZ).date().isoformat()
    today_path = DATA_DIR / "daily" / f"{today}.json"
    if today_path.exists():
        payload = read_json(today_path, [])
        return today, len(payload) if isinstance(payload, list) else 0
    rows = daily_counts()
    return rows[0] if rows else (today, 0)


def hourly_journal_count() -> int:
    path = DATA_DIR / "monitor_tiers.yml"
    if not path.exists():
        return 0
    count = 0
    in_hourly = False
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw_line.strip()
        if stripped == "hourly:":
            in_hourly = True
            continue
        if in_hourly and stripped and not stripped.startswith("- "):
            break
        if in_hourly and stripped.startswith("- "):
            count += 1
    return count


def working_source_stage_count(max_stage: int) -> int:
    path = DATA_DIR / "working_paper_sources.yml"
    if not path.exists():
        return 0
    count = 0
    current_stage: int | None = None
    current_status = "active"
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- id:"):
            if current_stage is not None and current_stage <= max_stage and current_status != "paused":
                count += 1
            current_stage = None
            current_status = "active"
        elif stripped.startswith("stage:"):
            try:
                current_stage = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                current_stage = None
        elif stripped.startswith("status:"):
            current_status = stripped.split(":", 1)[1].strip().strip('"').strip("'")
    if current_stage is not None and current_stage <= max_stage and current_status != "paused":
        count += 1
    return count


def has_chinese(value: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value or "")


def pct(done: int, total: int) -> str:
    return "0%" if total == 0 else f"{min(done, total) / total:.1%}"


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
    if record.get("date_precision") == "month" and (record.get("available_online") or record.get("published_online")):
        return "在线月份"
    if record.get("available_online") or record.get("published_online"):
        return "在线日期"
    if record.get("accepted_date"):
        return "接受日期"
    if record.get("source_issue"):
        return "来源期次"
    if record.get("issue_date"):
        return "卷期日期"
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


def public_date_line(record: dict[str, Any]) -> str:
    value = public_date(record)
    if record.get("date_precision") == "month" and value and value.count("-") == 2:
        value = value[:7]
    if value in {"待解析", "寰呰В鏋?", ""}:
        return f"日期待解析 · 来源：{date_source_label(record)}"
    return f"{public_date_label(record)} {value} · 来源：{date_source_label(record)}"


def date_evidence_cell(record: dict[str, Any]) -> str:
    raw = record.get("raw_data") if isinstance(record.get("raw_data"), dict) else {}
    items = [
        ("前台日期", public_date_line(record)),
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


def is_working_paper(record: dict[str, Any]) -> bool:
    source_type = str(record.get("source_type") or "")
    return str(record.get("source") or "") == "working_papers" or source_type in {"working_paper", "policy_paper", "aggregator"}


def main() -> None:
    records = load_records()
    status = load_status()
    workflow = status.get("workflow") or {}
    sources = status.get("sources") or {}
    cn_group = (status.get("source_groups") or {}).get("cn-journals") or {}
    cnki_group = (status.get("source_groups") or {}).get("cnki-rss") or {}
    publisher_group = (status.get("source_groups") or {}).get("publisher-detail") or {}
    ingestion = read_json(DATA_DIR / "ingestion_audit.json", {})

    english_titles = sum(1 for record in records if record.get("title") and not has_chinese(str(record.get("title"))))
    english_translated = sum(
        1
        for record in records
        if record.get("title")
        and not has_chinese(str(record.get("title")))
        and record.get("title_zh")
    )
    translated = sum(1 for record in records if record.get("title_zh"))
    china_confirmed = sum(1 for record in records if record.get("china_related") is True or record.get("china_relevance_status") == "confirmed")
    china_candidates = latest_records(records, lambda record: record.get("china_relevance_status") == "candidate")
    untranslated = latest_records(records, lambda record: record.get("title") and not has_chinese(str(record.get("title"))) and not record.get("title_zh"))
    low_confidence = latest_records(records, lambda record: (record.get("date_confidence") or "F") in {"D", "F", "unknown"})
    date_evidence_records = latest_records(records, lambda record: True, 30)
    working_papers = [record for record in records if is_working_paper(record)]
    latest_working_papers = latest_records(records, is_working_paper, 30)
    china_working_papers = latest_records(
        records,
        lambda record: is_working_paper(record)
        and (record.get("china_related") is True or record.get("china_relevance_status") == "confirmed"),
        30,
    )
    by_source = Counter(record.get("source") or "unknown" for record in records)
    by_confidence = Counter(record.get("date_confidence") or "unknown" for record in records)
    today_date, today_total = latest_daily_count()
    today_records = [record for record in records if record.get("_daily_date") == today_date]
    today_journal_total = sum(1 for record in today_records if not is_working_paper(record))
    today_working_total = sum(1 for record in today_records if is_working_paper(record))
    latest_dedupe = sources.get("dedupe") or {}
    latest_dedupe_message = str(latest_dedupe.get("message") or "")
    crossref_new_deposits = sum(
        1
        for record in today_records
        if "created" in str(record.get("date_source") or "").casefold()
        or "created" in str((record.get("raw_data") or {}).get("crossref_date_source") or "").casefold()
    )
    fallback_today = sum(1 for record in today_records if "crossref" in str(record.get("date_source") or "").casefold())
    light_journal_count = hourly_journal_count()
    light_working_source_count = working_source_stage_count(1)
    full_journal_count = len(load_journals(DATA_DIR / "journals.yml"))
    full_working_source_count = working_source_stage_count(2)

    health: list[str] = []
    failures = [key for key, item in sources.items() if not item.get("ok")]
    if failures:
        health.append("存在失败来源：" + ", ".join(failures))
    if not workflow.get("finished_at"):
        health.append("尚未记录端到端 workflow 完成时间，下一次监测后会自动补齐。")
    if not workflow.get("last_full_finished_at"):
        health.append("尚未记录成功完成的全量监测；请关注下一次北京时间 08:30 的自动任务，或在 Actions 手动运行 full。")
    zero_cn = [
        str(item.get("journal") or item.get("journal_id"))
        for item in cn_group.get("journals", [])
        if item.get("ok") and int(item.get("count") or 0) == 0
    ]
    if zero_cn:
        health.append("中文期刊抓取成功但返回 0 条，需持续观察页面结构或检索入口：" + "、".join(zero_cn))
    if today_total == 0:
        health.append("今日归档目前为 0 条：这可能是当天确实暂无新记录，也可能是上游延迟；请重点查看 Crossref newly deposited、CNKI RSS 和本地补充状态。")
    if latest_dedupe_message and "daily_total=0" in latest_dedupe_message and today_total > 0:
        health.append("最近一次任务本身没有新增，但今日归档已有记录；后台已将“本次新增”和“今日累计”分开显示。")
    if fallback_today:
        health.append(f"今日有 {fallback_today} 条记录依赖 Crossref/备用元数据；出版社详情页若受限，online date 可能仍需后续增强。")
    if crossref_new_deposits:
        health.append(f"今日有 {crossref_new_deposits} 条 Crossref newly deposited 记录；这是为减少刚入库 DOI 漏抓而新增的监测口径。")
    if not health:
        health.append("暂无需要立即处理的来源异常。")

    source_rows = [
        f"<tr><td>{html_escape(source_id)}</td><td>{'OK' if item.get('ok') else 'FAIL'}</td>"
        f"<td>{html_escape(item.get('count'))}</td><td>{html_escape(beijing_stamp(item.get('updated_at')))}</td>"
        f"<td>{html_escape(item.get('message'))}</td></tr>"
        for source_id, item in sorted(sources.items())
    ]
    wp_source_rows = [
        f"<tr><td>{html_escape(str(source_id).removeprefix('working-paper:'))}</td><td>{'OK' if item.get('ok') else 'FAIL'}</td>"
        f"<td>{html_escape(item.get('count'))}</td><td>{html_escape(beijing_stamp(item.get('updated_at')))}</td>"
        f"<td>{html_escape(item.get('message'))}</td></tr>"
        for source_id, item in sorted(sources.items())
        if str(source_id).startswith("working-paper:")
    ]
    cn_rows = [
        f"<tr class='{'warn' if item.get('ok') and int(item.get('count') or 0) == 0 else ''}'><td>{html_escape(item.get('journal'))}</td><td>{'OK' if item.get('ok') else 'FAIL'}</td>"
        f"<td>{html_escape(item.get('count'))}</td><td>{html_escape(item.get('mode'))}</td>"
        f"<td>{html_escape(item.get('message') if item.get('message') and item.get('message') != 'ok' else ('抓取成功但 0 条，可能是暂无新内容或页面结构需继续适配' if item.get('ok') and int(item.get('count') or 0) == 0 else item.get('message')))}</td></tr>"
        for item in cn_group.get("journals", [])
    ]
    cnki_rows = [
        f"<tr class='{'warn' if not item.get('ok') else ''}'><td>{html_escape(item.get('journal'))}</td><td>{'OK' if item.get('ok') else 'FAIL'}</td>"
        f"<td>{html_escape(item.get('count'))}</td><td>{html_escape(item.get('filtered'))}</td>"
        f"<td>{html_escape(item.get('channel_updated_at'))}</td><td>{html_escape(item.get('latest_research_date') or item.get('latest_research'))}</td>"
        f"<td>{html_escape(item.get('message'))}</td></tr>"
        for item in cnki_group.get("journals", [])
    ]
    publisher_rows = [
        f"<tr><td>{html_escape(item.get('publisher'))}</td>"
        f"<td>{html_escape(item.get('attempted'))}</td>"
        f"<td>{html_escape(item.get('ab_dates'))} / {html_escape(item.get('attempted'))} ({float(item.get('success_rate') or 0):.1%})</td>"
        f"<td>{html_escape(item.get('changed'))}</td>"
        f"<td>{html_escape(item.get('failures'))}</td>"
        f"<td>{html_escape(item.get('message'))}</td></tr>"
        for item in publisher_group.get("publishers", [])
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
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(public_date_line(record))}</td>"
        f"<td>{date_evidence_cell(record)}</td></tr>"
        for record in date_evidence_records
    ]
    latest_wp_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td>"
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(public_date_line(record))}</td>"
        f"<td>{html_escape(record.get('paper_number') or '')}</td></tr>"
        for record in latest_working_papers
    ]
    china_wp_rows = [
        f"<tr><td>{html_escape(record.get('_daily_date'))}</td><td>{title_cell(record)}</td>"
        f"<td>{html_escape(record.get('journal'))}</td><td>{html_escape(record.get('china_relevance_reason'))}</td></tr>"
        for record in china_working_papers
    ]
    daily_rows = "".join(f"<tr><td>{html_escape(day)}</td><td>{count}</td></tr>" for day, count in daily_counts())
    source_counts = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(by_source.items()))
    total_conf = sum(by_confidence.values()) or 1
    confidence_counts = "".join(
        f"<li><b>{html_escape(CONFIDENCE_LABELS.get(str(key), str(key)))}</b>: {value} ({value / total_conf:.1%})</li>"
        for key, value in sorted(by_confidence.items())
    )
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
    .section{{border:1px solid #d0d7de;border-radius:8px;padding:18px;margin-top:20px}}.section h2{{margin-top:0}}.warn td,.warn{{background:#fff8c5}}.bad{{color:#cf222e;font-weight:700}}.ok{{color:#1f883d;font-weight:700}}
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
    <div class="card"><strong>{pct(english_translated, max(english_titles, 1))}</strong><span>英文标题翻译覆盖率</span></div>
    <div class="card"><strong>{china_confirmed}</strong><span>已确认中国相关</span></div>
    <div class="card"><strong>{len(china_candidates)}</strong><span>中国相关待审核</span></div>
    <div class="card"><strong>{len(untranslated)}</strong><span>未翻译英文标题样本</span></div>
    <div class="card"><strong>{len(low_confidence)}</strong><span>低可信日期样本</span></div>
    <div class="card"><strong>{html_escape(cn_group.get('count', 0))}</strong><span>中文期刊本轮抓取</span></div>
    <div class="card"><strong>{html_escape(workflow.get('mode_label') or '暂无')}</strong><span>最近监测类型</span></div>
    <div class="card"><strong>{html_escape(beijing_stamp(workflow.get('finished_at')))}</strong><span>最近监测完成</span></div>
    <div class="card"><strong>{html_escape(beijing_stamp(workflow.get('last_light_finished_at')))}</strong><span>快速监测最近完成</span></div>
    <div class="card"><strong>{light_journal_count} / {light_working_source_count}</strong><span>快速监测覆盖：期刊 / 工作论文源</span></div>
    <div class="card"><strong>{html_escape(beijing_stamp(workflow.get('last_full_finished_at')))}</strong><span>全量监测最近完成</span></div>
    <div class="card"><strong>{full_journal_count} / {full_working_source_count}</strong><span>全量监测覆盖：期刊 / 工作论文源</span></div>
    <div class="card"><strong>{today_total}</strong><span>{html_escape(today_date)} 今日累计记录</span></div>
    <div class="card"><strong>{today_journal_total} / {today_working_total}</strong><span>今日期刊 / 工作论文</span></div>
    <div class="card"><strong>{html_escape(latest_dedupe.get('count', 0))}</strong><span>最近一次跨日期新增</span></div>
  </div>

  <section class="section">
  <h2>运行状态</h2>
  <table><thead><tr><th>项目</th><th>值</th></tr></thead><tbody>
    <tr><td>最近监测</td><td>{html_escape(workflow.get('mode_label') or '自动监测')} / {html_escape(beijing_stamp(workflow.get('finished_at')))}</td></tr>
    <tr><td>最近全量监测</td><td>{html_escape(beijing_stamp(workflow.get('last_full_finished_at')))}</td></tr>
    <tr><td>最近快速监测</td><td>{html_escape(beijing_stamp(workflow.get('last_light_finished_at')))}</td></tr>
    <tr><td>下次快速监测</td><td>每小时整点，预计 {html_escape(next_hourly_run(workflow.get('last_light_finished_at') or workflow.get('finished_at')))}</td></tr>
    <tr><td>下次全量监测</td><td>每天北京时间 08:30，预计 {html_escape(next_daily_full_run(workflow.get('last_full_finished_at') or workflow.get('finished_at')))}</td></tr>
    <tr><td>GitHub Actions</td><td><a href="{html_escape(workflow.get('run_url') or '#')}" target="_blank" rel="noreferrer">{html_escape(workflow.get('run_id') or '暂无')}</a></td></tr>
  </tbody></table>

  <h2>健康提醒</h2>
  <ul>{health_rows}</ul>
  </section>

  <section class="section">
  <h2>入库诊断</h2>
  <p class="muted">对比今日原始候选和最终展示记录，用于判断是否存在“抓到但未入库”。RSS 无精确日期记录会作为“今日新发现”展示，但不会被当作“在线日期为今日”。</p>
  <table><thead><tr><th>指标</th><th>当前值</th><th>说明</th></tr></thead><tbody>
    <tr><td>诊断日期</td><td>{html_escape(ingestion.get('date') or today_date)}</td><td>与今日页使用同一个北京时间日期。</td></tr>
    <tr><td>原始候选</td><td>{html_escape(ingestion.get('raw_candidates', '未生成'))}</td><td>RSS、Crossref、中文官网、工作论文等原始抓取候选总数。</td></tr>
    <tr><td>今日展示记录</td><td>{html_escape(ingestion.get('daily_records', today_total))}</td><td>去重、清理和归一化后进入今日页面的记录。</td></tr>
    <tr><td>RSS 无精确日期候选</td><td>{html_escape(ingestion.get('rss_without_precise_date_candidates', '未生成'))}</td><td>已抓到但只有卷期、月份或待解析日期的 RSS 记录。</td></tr>
    <tr><td>RSS 无精确日期入库</td><td>{html_escape(ingestion.get('rss_without_precise_date_daily', '未生成'))}</td><td>进入今日新发现，但前台会标为日期待解析或较低可信度。</td></tr>
  </tbody></table>
  </section>

  <section class="section">
  <h2>工作论文来源状态</h2>
  <p class="muted">按来源拆分显示抓取结果；这里能看到 NBER、IZA、CEPR、Fed FEDS、World Bank、IMF、BIS、SSRN 等入口是否成功。</p>
  {table(wp_source_rows, ["来源", "状态", "数量", "更新时间", "信息"])}
  <h2>最新工作论文/政策论文</h2>
  {table(latest_wp_rows, ["日期", "论文", "来源", "公开日期", "编号"])}
  <h2>与中国相关工作论文/政策论文</h2>
  {table(china_wp_rows, ["日期", "论文", "来源", "判定原因"])}
  </section>

  <section class="section">
  <h2>中国相关</h2>
  <p class="muted">公开页面只展示已确认的中国相关；候选记录可在本地审核后台确认或排除。</p>
  <p><a class="btn" href="{ADMIN_URL}">打开本地审核后台</a></p>
  {table(candidate_rows, ["日期", "论文", "期刊", "判定原因"])}
  </section>

  <section class="section">
  <h2>中文期刊状态</h2>
  <h3>期刊官网</h3>
  {table(cn_rows, ["期刊", "状态", "数量", "抓取方式", "信息"])}
  <h3>CNKI RSS 补充</h3>
  {table(cnki_rows, ["期刊", "状态", "接受", "过滤", "频道日期", "最新研究日期", "信息"])}
  </section>

  <section class="section">
  <h2>日期可信度</h2>
  <ul>{confidence_counts}</ul>
  {table(date_evidence_rows, ["日期", "论文", "期刊", "前台显示", "完整证据链"])}
  <h2>出版社在线日期解析</h2>
  <p class="muted">按出版社统计详情页解析结果；A/B 日期覆盖率越高，说明 online date/accepted date 越稳定。</p>
  {table(publisher_rows, ["出版社", "尝试", "A/B 日期覆盖", "本轮更新", "失败/受限", "最近状态"])}
  </section>

  <section class="section">
  <h2>翻译与低可信样本</h2>
  <h2>未翻译英文标题样本</h2>
  {table(untranslated_rows, ["日期", "论文", "期刊", "翻译状态"])}

  <h2>低可信日期样本</h2>
  {table(low_conf_rows, ["日期", "论文", "期刊", "可信度"])}
  </section>

  <h2>来源数量</h2>
  <ul>{source_counts}</ul>

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
