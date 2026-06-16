"""Render the production static public site into docs/."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, DOCS_DIR, html_escape, load_journals, read_json, today_str


SITE_NAME = "Econ Papers Daily"
SITE_SUBTITLE = "每日追踪 TOP 经济学期刊论文"
BASE = "__BASE__"
CN_TZ = BEIJING_TZ
CHINA_KEYWORDS = [
    "china",
    "chinese",
    "prc",
    "hong kong",
    "taiwan",
    "beijing",
    "shanghai",
    "guangdong",
    "rural china",
    "chinese firms",
    "china shock",
    "中国",
    "中国企业",
    "中国农村",
    "香港",
    "台湾",
]

FIELD_LABELS = {
    "general": "综合",
    "development": "发展",
    "agriculture_environment_resource": "农业/环境/资源期刊",
    "applied_empirical": "应用实证",
    "macroeconomics": "宏观",
    "finance": "金融",
    "econometrics": "计量",
    "environmental": "环境",
    "labor": "劳动",
    "international": "国际",
    "public_political": "公共/政治经济学",
    "theory": "理论",
    "economic_history": "经济史",
    "industrial_organization": "产业组织",
    "game_theory": "博弈",
    "microeconomics": "微观",
    "population": "人口",
    "urban": "城市",
    "behavior_organization": "行为/组织",
    "law_comparative": "法律/比较",
    "experimental": "实验",
    "chinese": "中文期刊",
}

TOPIC_LABELS = {
    "china": "与中国相关",
    "agriculture": "农业与食品",
    "environment": "环境与气候",
    "development": "发展经济学",
    "finance": "金融",
    "macro": "宏观与货币",
    "labor": "劳动",
    "public": "公共与政治经济学",
    "trade": "国际贸易",
    "urban": "城市与区域",
    "econometrics": "计量方法",
    "theory": "理论与博弈",
    "behavior": "行为与组织",
    "health": "健康",
    "education": "教育",
    "firms": "企业与产业",
    "inequality": "不平等",
    "history": "经济史",
}

TOPIC_RULES = {
    "agriculture": ["agricultur", "farm", "food", "rice", "dairy", "rural", "crop", "land use"],
    "environment": ["climate", "weather", "carbon", "emission", "environment", "forest", "pollution", "energy", "electricity"],
    "development": ["development", "poverty", "displacement", "household", "informal", "low-income"],
    "finance": ["finance", "financial", "bank", "stock", "market", "asset", "investor", "credit"],
    "macro": ["monetary", "inflation", "growth", "business cycle", "exchange rate", "macro", "productivity"],
    "labor": ["labor", "labour", "wage", "worker", "employment", "unemployment", "migration"],
    "public": ["tax", "public", "policy", "political", "government", "regulation", "welfare"],
    "trade": ["trade", "export", "import", "tariff", "global", "supply chain"],
    "urban": ["urban", "city", "cities", "housing", "regional", "zimbabwe households"],
    "econometrics": ["estimator", "identification", "causal", "regression", "bayesian", "machine learning"],
    "theory": ["equilibrium", "game", "theory", "mechanism", "auction", "contract"],
    "behavior": ["behavior", "behaviour", "willingness", "preferences", "consumer", "profiles"],
    "health": ["health", "mortality", "hospital", "medical", "disease"],
    "education": ["education", "school", "student", "teacher"],
    "firms": ["firm", "enterprise", "industrial", "organization", "outsourcing", "services"],
    "inequality": ["inequality", "distribution", "mobility", "gender", "racial"],
    "history": ["history", "historical", "nineteenth", "twentieth"],
}


STYLE = """
:root{color-scheme:light;--ink:#1f2328;--muted:#656d76;--line:#d0d7de;--soft:#f6f8fa;--panel:#ffffff;--blue:#0969da;--blue-soft:#ddf4ff;--accent:#8250df;--warn:#9a6700}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.55}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.shell{display:grid;grid-template-columns:340px minmax(0,1fr);min-height:100vh}
.sidebar{background:var(--soft);border-right:1px solid var(--line);padding:24px;position:sticky;top:0;height:100vh;overflow:auto}
.brand{font-size:22px;font-weight:800;letter-spacing:0;margin:0}.subtitle{color:var(--muted);font-size:14px;margin:4px 0 22px}
.side-block{margin:22px 0}.side-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;margin-bottom:8px}
.side-link{display:flex;justify-content:space-between;gap:12px;border-radius:6px;padding:7px 9px;color:var(--ink);font-size:14px}.side-link:hover{background:#fff;text-decoration:none}.side-link span{color:var(--muted)}.side-main{min-width:0}.side-main strong{display:block;white-space:normal}.side-main em{display:block;color:var(--muted);font-style:normal;font-size:12px;line-height:1.35;margin-top:1px}.count{flex:0 0 auto;color:var(--muted)}
.content{min-width:0}.topbar{border-bottom:1px solid var(--line);background:#fff}.topbar-inner{max-width:1180px;margin:0;padding:18px 30px;display:flex;justify-content:space-between;align-items:center;gap:20px}
.nav a{margin-left:18px;color:var(--muted);font-size:14px}.nav a.active,.nav a:hover{color:var(--blue);text-decoration:none}
.wrap{max-width:1180px;margin:0;padding:26px 30px 48px}
.banner{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:linear-gradient(135deg,#f7fbff 0%,#ffffff 48%,#eaf5ff 100%);display:grid;grid-template-columns:minmax(0,1fr) 360px;min-height:190px}
.banner-main{padding:34px 36px}.eyebrow{color:var(--blue);font-size:15px;font-weight:800;letter-spacing:.02em;margin:0 0 8px}.banner h1{font-family:Georgia,"Times New Roman",serif;font-size:46px;line-height:1.08;margin:0 0 12px;letter-spacing:.01em}.banner p{color:var(--muted);font-size:20px;max-width:760px;margin:0}
.signal{border-left:1px solid var(--line);padding:30px 24px;background:rgba(255,255,255,.62);display:flex;flex-direction:column;justify-content:center;gap:13px}.signal-row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:18px;color:var(--muted);font-size:14px;align-items:start}.signal-row strong{color:var(--ink);font-size:15px;line-height:1.35;white-space:nowrap}
.stats{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px;margin:20px 0}.stat{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:14px}.stat strong{display:block;font-size:26px;line-height:1.1}.stat span{font-size:13px;color:var(--muted)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 8px}.control{border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--muted);padding:8px 10px;font-size:14px;min-height:38px}.control.primary{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}.control.toggle.active{background:var(--blue-soft);border-color:#54aeff;color:var(--blue);font-weight:600}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding-bottom:10px;margin-top:26px}.section-head h2{font-size:20px;margin:0}.section-head p{margin:0;color:var(--muted);font-size:14px}
.event{display:grid;grid-template-columns:88px minmax(0,1fr);gap:18px;border-bottom:1px solid var(--line);padding:18px 0}.event[hidden]{display:none}.time{font-weight:700;color:var(--blue);font-size:14px}.date-note{color:var(--muted);font-size:12px;margin-top:2px}.event h3{font-size:18px;line-height:1.35;margin:0 0 5px}.title-zh{color:var(--ink);font-size:15px;margin:0 0 7px}.title-zh.pending{color:var(--muted)}.authors{color:var(--muted);margin:0 0 9px}.meta-block{display:grid;gap:4px;color:var(--muted);font-size:13px}.meta-line{display:flex;gap:8px;align-items:center;min-height:24px}.meta-values{display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-width:0;line-height:24px}.meta-label{color:var(--ink);font-weight:600;flex:0 0 64px;line-height:24px}.pill{border:1px solid var(--line);background:var(--soft);border-radius:999px;padding:2px 7px;line-height:18px}.pill.china{background:#fff1f0;border-color:#ffccc7;color:#cf222e;font-weight:700}.doi{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;line-height:24px}
.journal-table{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}.journal-table th,.journal-table td{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}.journal-table th{background:var(--soft);font-weight:700}.journal-table .muted{color:var(--muted)}
.empty{border:1px dashed var(--line);border-radius:8px;padding:28px;color:var(--muted);background:var(--soft)}
.archive-list{padding-left:18px}.archive-list li{margin:8px 0}
@media(max-width:920px){.shell{display:block}.sidebar{position:static;height:auto}.topbar-inner{display:block}.nav{margin-top:10px}.nav a{margin:0 16px 0 0}.banner{display:block}.banner h1{font-size:36px}.banner p{font-size:17px}.signal{border-left:0;border-top:1px solid var(--line)}.stats{grid-template-columns:repeat(2,1fr)}.event{grid-template-columns:1fr}}
"""


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field.replace("_", " "))


def topic_label(topic: str) -> str:
    return TOPIC_LABELS.get(topic, topic.replace("_", " "))


def normalize_attr(value: Any) -> str:
    return str(value or "").lower().replace('"', "&quot;")


def record_url(record: dict[str, Any]) -> str:
    return record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#")


def authors(record: dict[str, Any], limit: int = 5) -> str:
    names = record.get("authors") or []
    if len(names) > limit:
        return ", ".join(names[:limit]) + " 等"
    return ", ".join(names)


def beijing_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(CN_TZ)


def beijing_date(value: str | None) -> str:
    dt = beijing_datetime(value)
    return dt.date().isoformat() if dt else ""


def beijing_time(value: str | None) -> str:
    dt = beijing_datetime(value)
    return dt.strftime("%H:%M") if dt else "监测"


def beijing_stamp(value: str | None) -> str:
    dt = beijing_datetime(value)
    return dt.strftime("%Y-%m-%d %H:%M 北京时间") if dt else "暂无"


def load_all_daily(daily_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not daily_dir.exists():
        return records
    for path in sorted(daily_dir.glob("*.json"), reverse=True):
        for record in read_json(path, []):
            record["_daily_date"] = path.stem
            records.append(record)
    return sorted(records, key=lambda item: item.get("detected_at") or "", reverse=True)


def detected_date(record: dict[str, Any]) -> str:
    return beijing_date(record.get("detected_at")) or record.get("_daily_date") or ""


def detected_time(record: dict[str, Any]) -> str:
    return beijing_time(record.get("detected_at"))


def stats(records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> dict[str, Any]:
    today_journals = {record.get("journal_id") for record in today_records if record.get("journal_id")}
    all_journals = {record.get("journal_id") for record in records if record.get("journal_id")}
    sources = {record.get("source") for record in records if record.get("source")}
    last_seen = max((record.get("detected_at") or "" for record in records), default="")
    today = today_str()
    return {
        "today": len(today_records),
        "online_today": sum(
            1
            for record in today_records
            if record.get("available_online") == today
            or record.get("accepted_date") == today
            or record.get("published_online") == today
        ),
        "source_date_today": sum(1 for record in today_records if record.get("published_online") == today),
        "today_journals": len(today_journals),
        "all_records": len(records),
        "all_journals": len(all_journals),
        "sources": len(sources),
        "last_seen": beijing_stamp(last_seen),
    }


def date_confidence_label(record: dict[str, Any]) -> str:
    if record.get("accepted_date"):
        return "Accepted"
    if record.get("available_online"):
        return "在线日期"
    if record.get("date_source") in {"publisher_meta", "publisher_published_online"}:
        return "出版社发布日期"
    if record.get("date_source") == "publisher_available_online":
        return "Available online"
    if record.get("date_source") == "crossref_published_online":
        return "Crossref在线日期"
    if record.get("date_source") in {"crossref_published", "crossref_issue", "crossref_created"} or record.get("source") == "crossref":
        return "Crossref发布日期"
    if record.get("date_source") == "official_publish_date":
        return "发布日期"
    if record.get("date_source") == "file_upload_date":
        return "官网上传日期"
    if record.get("published_online"):
        return "来源日期"
    if record.get("source_issue"):
        return "来源期次"
    return "日期待解析"


def date_type(record: dict[str, Any]) -> str:
    if record.get("accepted_date"):
        return "accepted"
    if record.get("available_online"):
        return "available_online"
    if record.get("published_online"):
        return "published_online"
    if record.get("source_issue") or record.get("issue_date"):
        return "issue"
    return "first_seen"


def date_type_label(value: str) -> str:
    return {
        "accepted": "接受日期",
        "available_online": "Online日期",
        "published_online": "发布日期",
        "issue": "来源期次",
        "first_seen": "首次监测",
    }.get(value, value)


def confidence_value(record: dict[str, Any]) -> str:
    if record.get("date_confidence"):
        return str(record.get("date_confidence"))
    return {
        "accepted": "A",
        "available_online": "A",
        "published_online": "B",
        "issue": "D",
        "first_seen": "F",
    }.get(date_type(record), "F")


def confidence_label(value: str) -> str:
    return {
        "A": "A 最高",
        "B": "B 官网/RSS",
        "C": "C Crossref在线",
        "D": "D 卷期/印刷",
        "F": "F 仅首次监测",
    }.get(value, value)


def is_china_related(record: dict[str, Any]) -> bool:
    if "chinese" in (record.get("fields") or []):
        return True
    haystack = " ".join(
        str(value or "")
        for value in [
            record.get("title"),
            record.get("title_zh"),
            record.get("abstract"),
            record.get("abstract_zh"),
        ]
    ).casefold()
    return any(keyword.casefold() in haystack for keyword in CHINA_KEYWORDS)


def article_topics(record: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        str(value or "")
        for value in [
            record.get("title"),
            record.get("title_zh"),
            record.get("abstract"),
            record.get("abstract_zh"),
            record.get("journal"),
        ]
    ).casefold()
    topics = []
    if is_china_related(record):
        topics.append("china")
    for topic, keywords in TOPIC_RULES.items():
        if any(keyword in haystack for keyword in keywords):
            topics.append(topic)
    if topics:
        return list(dict.fromkeys(topics))[:4]

    fallback = []
    for field in record.get("fields", []):
        if field == "agriculture_environment_resource":
            fallback.extend(["agriculture", "environment"])
        elif field == "public_political":
            fallback.append("public")
        elif field == "industrial_organization":
            fallback.append("firms")
        elif field == "game_theory":
            fallback.append("theory")
        elif field == "economic_history":
            fallback.append("history")
        elif field == "applied_empirical":
            fallback.append("econometrics")
        elif field in {"development", "finance", "urban", "labor", "international", "econometrics", "theory"}:
            fallback.append("trade" if field == "international" else field)
    return list(dict.fromkeys(fallback))[:3] or ["development"]


def journal_lookup() -> dict[str, dict[str, Any]]:
    return {journal["id"]: journal for journal in load_journals(DATA_DIR / "journals.yml")}


def sidebar(records: list[dict[str, Any]]) -> str:
    topic_counts = Counter(topic for record in records for topic in article_topics(record))
    journal_counts = Counter(record.get("journal_id") for record in records if record.get("journal_id"))
    journals_by_id = journal_lookup()
    topics = "".join(
        f'<a class="side-link" href="{BASE}/topics/{html_escape(topic)}/"><span class="side-main"><strong>{html_escape(topic_label(topic))}</strong></span><span class="count">{count}</span></a>'
        for topic, count in topic_counts.most_common(12)
    )
    journal_links = []
    for journal_id, count in journal_counts.most_common(10):
        journal = journals_by_id.get(journal_id, {})
        title = journal.get("title") or journal_id
        chinese_name = journal.get("chinese_name") or ""
        journal_links.append(
            f'<a class="side-link" href="{BASE}/journals/{html_escape(journal_id)}/"><span class="side-main"><strong>{html_escape(title)}</strong><em>{html_escape(chinese_name)}</em></span><span class="count">{count}</span></a>'
        )
    journals = "".join(journal_links)
    return f"""<aside class="sidebar">
  <h1 class="brand">{SITE_NAME}</h1>
  <div class="subtitle">{SITE_SUBTITLE}</div>
  <div class="side-block"><div class="side-title">导航</div>
    <a class="side-link" href="{BASE}/"><span class="side-main"><strong>今日速递</strong></span><span class="count">Today</span></a>
    <a class="side-link" href="{BASE}/topics/china/"><span class="side-main"><strong>与中国相关</strong></span><span class="count">Topic</span></a>
    <a class="side-link" href="{BASE}/archive/"><span class="side-main"><strong>历史归档</strong></span><span class="count">Archive</span></a>
    <a class="side-link" href="{BASE}/journals/"><span class="side-main"><strong>监测期刊</strong></span><span class="count">List</span></a>
  </div>
  <div class="side-block"><div class="side-title">文章主题</div>{topics}</div>
  <div class="side-block"><div class="side-title">今日涉及期刊</div>{journals}<a class="side-link" href="{BASE}/journals/"><span class="side-main"><strong>查看完整监测名单</strong></span><span class="count">84</span></a></div>
</aside>"""


def page(title: str, records: list[dict[str, Any]], body: str, active: str = "") -> str:
    nav = {
        "home": f"{BASE}/",
        "archive": f"{BASE}/archive/",
        "feed": f"{BASE}/feed.xml",
    }
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>{STYLE}</style>
</head>
<body>
  <div class="shell">
    {sidebar(records)}
    <div class="content">
      <header class="topbar"><div class="topbar-inner">
        <div><strong>{SITE_NAME}</strong> <span class="subtitle">{SITE_SUBTITLE}</span></div>
        <nav class="nav">
          <a class="{ 'active' if active == 'home' else '' }" href="{nav['home']}">今日</a>
          <a href="{BASE}/topics/china/">与中国相关</a>
          <a class="{ 'active' if active == 'archive' else '' }" href="{nav['archive']}">归档</a>
          <a href="{BASE}/journals/">监测期刊</a>
          <a href="{nav['feed']}">RSS</a>
        </nav>
      </div></header>
      <main class="wrap">{body}</main>
    </div>
  </div>
</body>
</html>
"""


def paper_events(records: list[dict[str, Any]], limit: int | None = None) -> str:
    selected = records[:limit] if limit else records
    if not selected:
        return '<div class="empty">今天暂未发现新论文。可以前往归档查看历史记录。</div>'
    chunks = []
    for record in selected:
        if record.get("doi"):
            link_or_doi = f'<a class="doi" href="https://doi.org/{html_escape(record.get("doi"))}">{html_escape(record.get("doi"))}</a>'
        elif record.get("url"):
            link_or_doi = f'<a class="doi" href="{html_escape(record.get("url"))}">文章链接</a>'
        else:
            link_or_doi = '<span class="doi">暂无链接</span>'
        date_label = date_confidence_label(record)
        official_date = html_escape(record.get("accepted_date") or record.get("available_online") or record.get("published_online") or record.get("source_issue") or "待解析")
        fields = "".join(f'<span class="pill">{html_escape(topic_label(topic))}</span>' for topic in article_topics(record)[:3] if topic != "china")
        title_zh = record.get("title_zh")
        if title_zh and str(title_zh).strip() == str(record.get("title") or "").strip():
            title_zh = None
        title_zh_html = f'<p class="title-zh">{html_escape(title_zh)}</p>' if title_zh else ""
        china_related = is_china_related(record)
        china_tag = '<span class="pill china">与中国相关</span>' if china_related else ""
        search_text = " ".join(
            str(value or "")
            for value in [
                record.get("title"),
                record.get("title_zh"),
                authors(record),
                record.get("journal"),
                record.get("doi"),
            ]
        )
        field_attr = " ".join(article_topics(record))
        date_type_attr = date_type(record)
        confidence_attr = confidence_value(record)
        chunks.append(
            f"""<article class="event" data-search="{html_escape(normalize_attr(search_text))}" data-journal="{html_escape(normalize_attr(record.get('journal_id')))}" data-fields="{html_escape(normalize_attr(field_attr))}" data-china="{str(china_related).lower()}" data-date-type="{html_escape(date_type_attr)}" data-confidence="{html_escape(confidence_attr)}">
  <div><div class="time">{html_escape(detected_time(record))}</div><div class="date-note">{html_escape(detected_date(record))}</div></div>
  <div>
    <h3><a href="{html_escape(record_url(record))}">{html_escape(record.get('title'))}</a></h3>
    {title_zh_html}
    <p class="authors">{html_escape(authors(record))}</p>
    <div class="meta-block">
      <div class="meta-line"><span class="meta-label">期刊</span><span class="meta-values"><span>{html_escape(record.get('journal'))}</span><span>{date_label} {official_date}</span></span></div>
      <div class="meta-line"><span class="meta-label">链接/DOI</span><span class="meta-values">{link_or_doi}{fields}{china_tag}</span></div>
    </div>
  </div>
</article>"""
        )
    return "\n".join(chunks)


FILTER_SCRIPT = """
<script>
(() => {
  const search = document.getElementById('searchInput');
  const journal = document.getElementById('journalFilter');
  const field = document.getElementById('fieldFilter');
  const dateType = document.getElementById('dateTypeFilter');
  const confidence = document.getElementById('confidenceFilter');
  const china = document.getElementById('chinaToggle');
  const empty = document.getElementById('filterEmpty');
  const events = Array.from(document.querySelectorAll('.event'));
  if (!search || !journal || !field || !china) return;

  function applyFilters() {
    const q = (search.value || '').trim().toLowerCase();
    const journalValue = journal.value;
    const fieldValue = field.value;
    const dateTypeValue = dateType ? dateType.value : '';
    const confidenceValue = confidence ? confidence.value : '';
    const chinaOnly = china.getAttribute('aria-pressed') === 'true';
    let visible = 0;
    for (const item of events) {
      const okSearch = !q || item.dataset.search.includes(q);
      const okJournal = !journalValue || item.dataset.journal === journalValue;
      const okField = !fieldValue || item.dataset.fields.split(' ').includes(fieldValue);
      const okDateType = !dateTypeValue || item.dataset.dateType === dateTypeValue;
      const okConfidence = !confidenceValue || item.dataset.confidence === confidenceValue;
      const okChina = !chinaOnly || item.dataset.china === 'true';
      const show = okSearch && okJournal && okField && okDateType && okConfidence && okChina;
      item.hidden = !show;
      if (show) visible += 1;
    }
    if (empty) empty.hidden = visible !== 0;
  }

  search.addEventListener('input', applyFilters);
  journal.addEventListener('change', applyFilters);
  field.addEventListener('change', applyFilters);
  if (dateType) dateType.addEventListener('change', applyFilters);
  if (confidence) confidence.addEventListener('change', applyFilters);
  china.addEventListener('click', () => {
    const active = china.getAttribute('aria-pressed') !== 'true';
    china.setAttribute('aria-pressed', String(active));
    china.classList.toggle('active', active);
    applyFilters();
  });
  applyFilters();
})();
</script>
"""


def filter_toolbar(records: list[dict[str, Any]], *, include_rss: bool = False) -> str:
    if not records:
        return ""
    journals = sorted(
        {
            (record.get("journal_id"), record.get("journal"))
            for record in records
            if record.get("journal_id") and record.get("journal")
        },
        key=lambda item: item[1],
    )
    topics = sorted({topic for record in records for topic in article_topics(record)}, key=topic_label)
    date_types = sorted({date_type(record) for record in records}, key=date_type_label)
    confidences = sorted({confidence_value(record) for record in records})
    journal_options = "".join(f'<option value="{html_escape(jid)}">{html_escape(title)}</option>' for jid, title in journals)
    field_options = "".join(f'<option value="{html_escape(topic)}">{html_escape(topic_label(topic))}</option>' for topic in topics)
    date_type_options = "".join(f'<option value="{html_escape(value)}">{html_escape(date_type_label(value))}</option>' for value in date_types)
    confidence_options = "".join(f'<option value="{html_escape(value)}">{html_escape(confidence_label(value))}</option>' for value in confidences)
    rss = f'<a class="control primary" href="{BASE}/feed.xml">RSS 订阅</a>' if include_rss else ""
    return f"""<div class="toolbar" id="filters">
  <input class="control" id="searchInput" type="search" placeholder="搜索标题/作者">
  <select class="control" id="journalFilter"><option value="">筛选期刊</option>{journal_options}</select>
  <select class="control" id="fieldFilter"><option value="">筛选主题</option>{field_options}</select>
  <select class="control" id="dateTypeFilter"><option value="">筛选日期类型</option>{date_type_options}</select>
  <select class="control" id="confidenceFilter"><option value="">筛选可信度</option>{confidence_options}</select>
  <button class="control toggle" id="chinaToggle" type="button" aria-pressed="false">与中国相关</button>
  {rss}
</div>
<div class="empty" id="filterEmpty" hidden>没有符合当前筛选条件的论文。</div>"""


def home_body(records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> str:
    s = stats(records, today_records)
    init_note = (
        f'<div class="empty">今天暂未监测到新论文。你可以先查看<a href="{BASE}/archive/">历史归档</a>或<a href="{BASE}/journals/">监测期刊</a>；部署到 GitHub Actions 后，首页会按每小时监测结果更新。</div>'
        if not today_records
        else '<div class="empty">说明：“今日新发现”指今天首次被本站监测到的记录；“在线日期为今日”优先按出版社 RSS/页面识别，缺失时仍显示来源日期。Crossref 日期可能是 online date、issue date 或卷期日期，系统上线初期回看过去 14 天，因此前几轮新发现数量会偏高。</div>'
    )
    events_html = paper_events(today_records) if today_records else ""
    return f"""<section class="banner">
  <div class="banner-main">
    <p class="eyebrow">Today&apos;s economics papers</p>
    <h1>{SITE_NAME}</h1>
    <p>{SITE_SUBTITLE}</p>
  </div>
  <div class="signal">
    <div class="signal-row"><span>排序依据</span><strong>监测时间</strong></div>
    <div class="signal-row"><span>最后监测</span><strong>{html_escape(s['last_seen'])}</strong></div>
    <div class="signal-row"><span>运行方式</span><strong>GitHub Actions</strong></div>
  </div>
</section>
<section class="stats">
  <div class="stat"><strong>{s['today']}</strong><span>今日新发现</span></div>
  <div class="stat"><strong>{s['online_today']}</strong><span>在线日期为今日</span></div>
  <div class="stat"><strong>{s['today_journals']}</strong><span>今日涉及期刊</span></div>
  <div class="stat"><strong>{s['all_records']}</strong><span>当前索引记录</span></div>
</section>
{filter_toolbar(today_records, include_rss=True)}
<section class="section-head"><div><h2>今日论文流</h2><p>按本站监测时间倒序排列。</p></div><p>{html_escape(today_str())}</p></section>
{init_note}
{events_html}
{FILTER_SCRIPT}
"""


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    relative_parent = path.parent.relative_to(DOCS_DIR)
    depth = len(relative_parent.parts)
    page_base = "." if depth == 0 else "/".join([".."] * depth)
    content = content.replace(BASE, page_base)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    args = parser.parse_args()

    records = load_all_daily(args.daily_dir)
    today_records = [record for record in records if detected_date(record) == today_str()]

    write_page(args.docs_dir / "index.html", page(SITE_NAME, records, home_body(records, today_records), active="home"))

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_journal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_date[detected_date(record) or record.get("_daily_date") or "unknown"].append(record)
        by_journal[record.get("journal_id") or "unknown"].append(record)
        for field in record.get("fields", []) or ["unknown"]:
            by_field[field].append(record)
        for topic in article_topics(record):
            by_topic[topic].append(record)

    archive_links = []
    for daily_date, daily_records in sorted(by_date.items(), reverse=True):
        body = (
            f'<section class="section-head"><div><h2>{html_escape(daily_date)} 监测记录</h2>'
            f'<p>按监测时间倒序排列，可按期刊、主题或“与中国相关”筛选。</p></div></section>'
            f'{filter_toolbar(daily_records)}{paper_events(daily_records)}{FILTER_SCRIPT}'
        )
        write_page(args.docs_dir / "daily" / daily_date / "index.html", page(f"{daily_date} 归档", records, body, active="archive"))
        archive_links.append(f'<li><a href="{BASE}/daily/{html_escape(daily_date)}/">{html_escape(daily_date)}</a> ({len(daily_records)})</li>')

    journals = load_journals(DATA_DIR / "journals.yml")
    journals_by_id = {journal["id"]: journal for journal in journals}
    for journal_id, journal_records in by_journal.items():
        title = str(journal_records[0].get("journal") or journals_by_id.get(journal_id, {}).get("title") or journal_id)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该期刊历史发现记录。</p></div></section>{paper_events(journal_records)}'
        write_page(args.docs_dir / "journals" / journal_id / "index.html", page(title, records, body))

    for journal in journals:
        if journal["id"] in by_journal:
            continue
        title = str(journal.get("title") or journal["id"])
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该期刊暂未保留有效论文记录。</p></div></section>{paper_events([])}'
        write_page(args.docs_dir / "journals" / journal["id"] / "index.html", page(title, records, body))

    journal_rows = []
    for journal in journals:
        fields = ", ".join(field_label(field) for field in journal.get("fields", []))
        issn = journal.get("issn") or "待补充"
        publisher = journal.get("publisher") or "待补充"
        journal_rows.append(
            f"""<tr>
  <td><a href="{BASE}/journals/{html_escape(journal['id'])}/">{html_escape(journal.get('title'))}</a><div class="muted">{html_escape(journal.get('chinese_name'))}</div></td>
  <td>{html_escape(journal.get('short_name'))}</td>
  <td>{html_escape(fields)}</td>
  <td>{html_escape(issn)}</td>
  <td>{html_escape(publisher)}</td>
</tr>"""
        )
    journals_body = f"""<section class="section-head"><div><h2>监测期刊</h2><p>当前监测清单共 {len(journals)} 本期刊。优先级只用于本地抓取策略，不在公开页面展示。</p></div></section>
<table class="journal-table"><thead><tr><th>期刊</th><th>缩写</th><th>领域</th><th>ISSN</th><th>出版社</th></tr></thead><tbody>{"".join(journal_rows)}</tbody></table>"""
    write_page(args.docs_dir / "journals" / "index.html", page("监测期刊", records, journals_body))

    for field, field_records in by_field.items():
        title = field_label(field)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该领域历史发现记录。</p></div></section>{paper_events(field_records)}'
        write_page(args.docs_dir / "fields" / field / "index.html", page(title, records, body))

    china_records = [record for record in records if is_china_related(record)]
    china_body = f"""<section class="section-head"><div><h2>与中国相关</h2><p>基于标题和摘要关键词初筛，后续可升级为 AI 主题判断。</p></div><p>{len(china_records)} 篇</p></section>
{paper_events(china_records)}"""
    write_page(args.docs_dir / "topics" / "china" / "index.html", page("与中国相关", records, china_body))

    for topic, topic_records in by_topic.items():
        if topic == "china":
            continue
        title = topic_label(topic)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>基于标题、摘要和期刊信息的文章主题标签，后续可升级为 AI 主题判断。</p></div><p>{len(topic_records)} 篇</p></section>{paper_events(topic_records)}'
        write_page(args.docs_dir / "topics" / topic / "index.html", page(title, records, body))

    archive_body = '<section class="section-head"><div><h2>历史归档</h2><p>按本站首次监测日期整理。</p></div></section><ul class="archive-list">' + "\n".join(archive_links) + "</ul>"
    write_page(args.docs_dir / "archive" / "index.html", page("历史归档", records, archive_body, active="archive"))
    print(f"rendered {len(records)} records into {args.docs_dir}")


if __name__ == "__main__":
    main()
