"""Render the production static public site into docs/."""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, DOCS_DIR, html_escape, load_journals, read_json, today_str, write_text
from status import load_status


SITE_NAME = "Econ Papers Daily"
SITE_SUBTITLE = "每日追踪 TOP 经济学期刊论文"
BASE = "__BASE__"
CN_TZ = BEIJING_TZ

FIELD_LABELS = {
    "general": "综合",
    "development": "发展经济学",
    "agriculture_environment_resource": "农业/环境/资源",
    "applied_empirical": "应用实证",
    "macroeconomics": "宏观经济学",
    "finance": "金融",
    "econometrics": "计量经济学",
    "environmental": "环境经济学",
    "labor": "劳动经济学",
    "international": "国际经济学",
    "public_political": "公共/政治经济学",
    "theory": "经济理论",
    "economic_history": "经济史",
    "industrial_organization": "产业组织",
    "game_theory": "博弈论",
    "microeconomics": "微观经济学",
    "population": "人口经济学",
    "urban": "城市经济学",
    "behavior_organization": "行为/组织",
    "law_comparative": "法律/比较制度",
    "experimental": "实验经济学",
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
    "trade": ["trade", "export", "import", "tariff", "global", "supply chain", "cross-border"],
    "urban": ["urban", "city", "cities", "housing", "regional"],
    "econometrics": ["estimator", "identification", "causal", "regression", "bayesian", "machine learning"],
    "theory": ["equilibrium", "game", "theory", "mechanism", "auction", "contract"],
    "behavior": ["behavior", "behaviour", "preferences", "consumer", "discrimination", "organization"],
    "health": ["health", "mortality", "hospital", "medical", "disease", "height"],
    "education": ["education", "school", "student", "teacher"],
    "firms": ["firm", "enterprise", "industrial", "outsourcing", "services", "innovation"],
    "inequality": ["inequality", "distribution", "mobility", "gender", "racial"],
    "history": ["history", "historical", "nineteenth", "twentieth"],
}

STYLE = """
:root{color-scheme:light;--ink:#1f2328;--muted:#656d76;--line:#d0d7de;--soft:#f6f8fa;--page:#fafafa;--panel:#fff;--blue:#0969da;--blue-soft:#ddf4ff;--red:#cf222e;--red-soft:#fff1f0;--shadow:0 1px 2px rgba(31,35,40,.05)}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.55}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.shell{display:grid;grid-template-columns:340px minmax(0,1fr);min-height:100vh}.sidebar{background:var(--soft);border-right:1px solid var(--line);padding:24px;position:sticky;top:0;height:100vh;overflow:auto}.brand{font-size:22px;font-weight:800;margin:0}.subtitle{color:var(--muted);font-size:14px;margin:4px 0 22px}
.side-block{margin:22px 0}.side-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;margin-bottom:8px}.side-link{display:flex;justify-content:space-between;gap:12px;border-radius:6px;padding:7px 9px;color:var(--ink);font-size:14px}.side-link:hover{background:#fff;text-decoration:none}.side-main{min-width:0}.side-main strong{display:block;white-space:normal}.side-main em{display:block;color:var(--muted);font-style:normal;font-size:12px;line-height:1.35;margin-top:1px}.count{flex:0 0 auto;color:var(--muted)}
.content{min-width:0}.topbar{border-bottom:1px solid var(--line);border-top:3px solid var(--blue);background:#fff}.topbar-inner{max-width:1180px;margin:0;padding:16px 30px;display:flex;justify-content:space-between;align-items:center;gap:20px}.nav a{margin-left:18px;color:var(--muted);font-size:14px}.nav a.active,.nav a:hover{color:var(--blue);text-decoration:none}.wrap{max-width:1180px;margin:0;padding:26px 30px 48px}
.banner{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);box-shadow:var(--shadow)}.banner-main{padding:34px 40px 30px}.hero-layout{display:grid;grid-template-columns:minmax(0,1fr) 190px;gap:28px;align-items:center}.eyebrow{color:var(--blue);font-size:14px;font-weight:800;letter-spacing:0;margin:0 0 8px}.banner h1{font-family:Georgia,"Times New Roman",serif;font-size:48px;line-height:1.06;margin:0 0 12px}.banner p{color:var(--muted);font-size:20px;max-width:760px;margin:0}.hero-stats{display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:14px;margin-top:26px;max-width:900px}.hero-stat{border-top:3px solid var(--blue);background:#fff;border-radius:8px;padding:13px 14px;box-shadow:var(--shadow);color:var(--ink)}.hero-stat:hover{text-decoration:none;box-shadow:0 0 0 1px var(--blue)}.hero-stat.china{border-top-color:var(--red)}.hero-stat strong{display:block;font-size:28px;line-height:1.05}.hero-stat span{color:var(--muted);font-size:13px}.operator-card{border:1px solid var(--line);border-radius:10px;background:#fff;padding:14px;box-shadow:var(--shadow);text-align:center;align-self:center}.operator-card img{display:block;width:128px;height:128px;object-fit:cover;margin:0 auto 10px;border-radius:6px}.operator-card strong{display:block;font-size:16px}.operator-card span{display:block;color:var(--ink);font-size:13px;font-weight:700;margin-top:3px}.operator-card em{display:block;color:var(--red);font-style:normal;font-size:12px;font-weight:800;margin-top:4px}.operator-line{margin-top:18px;color:var(--muted);font-size:13px}.operator-line strong{color:var(--ink)}.status-strip{display:flex;gap:16px;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;background:var(--soft);padding:9px 12px;margin:14px 0 0;color:var(--muted);font-size:13px}.status-strip strong{color:var(--ink);font-weight:700}.stats{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0 18px}.stat{display:flex;align-items:baseline;gap:8px;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:10px 12px;color:var(--ink);box-shadow:var(--shadow)}.stat.china{border-top:3px solid var(--red)}.stat:hover{border-color:var(--blue);text-decoration:none}.stat strong{display:inline;font-size:22px;line-height:1}.stat span{font-size:13px;color:var(--muted)}
.live-count{font-size:14px;color:var(--muted);font-weight:500}.live-count .num{color:var(--red);font-weight:800}
.toolbar{display:grid;grid-template-columns:minmax(170px,1.05fr) minmax(190px,1.45fr) minmax(125px,.75fr) minmax(118px,.65fr) minmax(118px,.65fr) minmax(118px,.65fr) auto auto;gap:9px;align-items:center;margin:18px 0 8px}.control{border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--muted);padding:8px 10px;font-size:14px;min-height:38px;min-width:0}.control:focus{outline:2px solid rgba(9,105,218,.16);border-color:var(--blue)}.control.primary{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600;white-space:nowrap}.control.toggle{white-space:nowrap}.control.toggle.active{background:var(--red-soft);border-color:#ffccc7;color:var(--red);font-weight:700}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding-bottom:10px;margin-top:26px}.section-head.split-section{margin-top:58px}.section-head h2{font-size:20px;margin:0}.section-head p{margin:0;color:var(--muted);font-size:14px}
.event{position:relative;display:grid;grid-template-columns:78px minmax(0,1fr);gap:18px;border:1px solid transparent;border-bottom-color:var(--line);border-radius:8px;padding:16px 14px 16px 18px;background:transparent}.event:before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:3px;border-radius:3px;background:#b6d7ff}.event[data-china="true"]:before{background:var(--red)}.event:hover{background:#fff;border-color:var(--line);box-shadow:var(--shadow)}.event:hover:before{background:var(--blue)}.event[data-china="true"]:hover:before{background:var(--red)}.event[hidden]{display:none}.time{font-weight:700;color:var(--blue);font-size:14px}.date-note{color:var(--muted);font-size:12px;margin-top:2px}.event h3{font-size:18px;line-height:1.35;margin:0 0 5px}.title-zh{color:#3b434c;font-size:15px;margin:0 0 7px}.authors{color:var(--muted);margin:0 0 10px}.meta-block{display:grid;gap:6px;color:var(--muted);font-size:13px}.meta-line{display:flex;gap:8px;align-items:flex-start;min-height:24px}.meta-values{display:flex;flex-wrap:wrap;gap:8px;align-items:center;min-width:0;line-height:24px}.meta-label{color:var(--ink);font-weight:700;flex:0 0 72px;line-height:24px}.journal-chip{background:var(--blue-soft);border:1px solid #b6e3ff;color:#0550ae;border-radius:999px;padding:2px 8px;line-height:18px}.source-chip{color:var(--muted)}.pill{border:1px solid var(--line);background:var(--soft);border-radius:999px;padding:2px 7px;line-height:18px}.pill.china{background:var(--red-soft);border-color:#ffccc7;color:var(--red);font-weight:800}.doi{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;line-height:24px;word-break:break-word}
.journal-table{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}.journal-table th,.journal-table td{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}.journal-table th{background:var(--soft);font-weight:700}.muted{color:var(--muted)}.empty{border:1px dashed var(--line);border-radius:8px;padding:20px;color:var(--muted);background:var(--soft)}.home-note{padding:14px 16px;font-size:14px}.archive-list{padding-left:18px}.archive-list li{margin:8px 0}.view-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.view-tab{border:1px solid var(--line);border-radius:999px;background:#fff;padding:7px 11px;color:var(--ink);font-size:14px}.view-tab:hover{text-decoration:none;border-color:var(--blue)}.view-tab.active{background:var(--blue);border-color:var(--blue);color:#fff}.source-status{display:inline-flex;border-radius:999px;border:1px solid var(--line);padding:2px 8px;font-size:12px;font-weight:700;background:var(--soft);white-space:nowrap}.source-status.ok{background:#dafbe1;border-color:#aceebb;color:#116329}.source-status.todo{background:#fff8c5;border-color:#f0d98c;color:#7d4e00}.source-status.pause{background:var(--red-soft);border-color:#ffccc7;color:var(--red)}
.audit-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:18px 0}.audit-card{border:1px solid var(--line);border-radius:8px;background:#fff;padding:14px;box-shadow:var(--shadow)}.audit-card strong{display:block;font-size:26px}.audit-list{display:grid;gap:12px}.audit-item{border:1px solid var(--line);border-radius:8px;background:#fff;padding:14px}.audit-item h3{font-size:16px;margin:0 0 6px}.audit-meta{color:var(--muted);font-size:13px}.audit-reason{margin-top:8px;color:#3b434c;font-size:14px}.gate{max-width:620px;border:1px solid var(--line);border-radius:10px;background:#fff;padding:24px;box-shadow:var(--shadow)}.gate input{width:100%;border:1px solid var(--line);border-radius:7px;padding:10px;margin:12px 0}.gate button{border:1px solid var(--blue);background:var(--blue);color:#fff;border-radius:7px;padding:9px 12px}.gate-note{color:var(--muted);font-size:13px}.hidden{display:none!important}
@media(max-width:1100px){.toolbar{grid-template-columns:minmax(180px,1fr) minmax(220px,1.4fr) minmax(140px,.8fr) minmax(130px,.7fr);}.toolbar .control.toggle,.toolbar .control.primary{width:max-content}}
@media(max-width:920px){.shell{display:block}.sidebar{position:static;height:auto}.topbar-inner{display:block}.nav{margin-top:10px}.nav a{margin:0 16px 0 0}.banner h1{font-size:36px}.banner p{font-size:17px}.banner-main{padding:30px 24px}.hero-layout{grid-template-columns:1fr}.operator-card{max-width:210px;text-align:left;display:grid;grid-template-columns:92px 1fr;gap:12px;align-items:center}.operator-card img{width:92px;height:92px;margin:0}.hero-stats{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr}.toolbar .control.toggle,.toolbar .control.primary{width:100%}.event{grid-template-columns:1fr}.audit-grid{grid-template-columns:1fr}}
"""


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field.replace("_", " "))


def topic_label(topic: str) -> str:
    return TOPIC_LABELS.get(topic, topic.replace("_", " "))


def ordered_topic_counts(records: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts = Counter(topic for record in records for topic in article_topics(record))
    items = list(counts.items())
    return sorted(items, key=lambda item: (0 if item[0] == "china" else 1, -item[1], topic_label(item[0])))


def normalize_attr(value: Any) -> str:
    return str(value or "").lower().replace('"', "&quot;")


def record_url(record: dict[str, Any]) -> str:
    return record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#")


def authors(record: dict[str, Any], limit: int = 5) -> str:
    names = record.get("authors") or []
    return ", ".join(names[:limit]) + (" 等" if len(names) > limit else "")


def beijing_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
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


def next_hourly_run(value: str | None) -> str:
    dt = beijing_datetime(value) or datetime.now(CN_TZ)
    next_dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_dt.strftime("%Y-%m-%d %H:%M 北京时间")


def next_daily_full_run(value: str | None) -> str:
    dt = beijing_datetime(value) or datetime.now(CN_TZ)
    candidate = dt.replace(hour=8, minute=30, second=0, microsecond=0)
    if candidate <= dt:
        candidate += timedelta(days=1)
    return candidate.strftime("%Y-%m-%d %H:%M 北京时间")


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


def is_china_related(record: dict[str, Any]) -> bool:
    return record.get("china_related") is True or record.get("china_relevance_status") == "confirmed"


def has_public_title(record: dict[str, Any]) -> bool:
    title = str(record.get("title") or "").strip()
    lowered = title.casefold()
    abstract_starts = (
        "this paper ",
        "this study ",
        "we analyze ",
        "we analyse ",
        "we examine ",
        "we investigate ",
        "using data ",
        "based on ",
    )
    if not title or "题名待解析" in title or lowered.startswith("untitled"):
        return False
    if len(title) > 260 or any(lowered.startswith(prefix) for prefix in abstract_starts):
        return False
    if record.get("public_visible") is False or record.get("title_parse_status") == "needs_repec_detail_title":
        return False
    return True


def is_public_china_related(record: dict[str, Any]) -> bool:
    return is_china_related(record) and has_public_title(record)


def is_working_paper(record: dict[str, Any]) -> bool:
    source_type = str(record.get("source_type") or "")
    return str(record.get("source") or "") == "working_papers" or source_type in {"working_paper", "policy_paper", "aggregator"}


def display_key(record: dict[str, Any]) -> str:
    for key in ("doi", "id", "url"):
        value = record.get(key)
        if value:
            return f"{key}:{str(value).casefold()}"
    title = " ".join(str(record.get("title") or "").casefold().split())
    return f"title:{title}"


def unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = display_key(record)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def source_type_label(record: dict[str, Any]) -> str:
    source_type = str(record.get("source_type") or "")
    return {
        "working_paper": "工作论文",
        "policy_paper": "政策论文",
        "aggregator": "聚合源",
        "journal_article": "期刊论文",
    }.get(source_type, "工作论文" if is_working_paper(record) else "期刊论文")


def article_topics(record: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        str(value or "")
        for value in [record.get("title"), record.get("title_zh"), record.get("abstract"), record.get("abstract_zh"), record.get("journal")]
    ).casefold()
    topics: list[str] = []
    if is_china_related(record):
        topics.append("china")
    for topic, keywords in TOPIC_RULES.items():
        if any(keyword in haystack for keyword in keywords):
            topics.append(topic)
    if topics:
        return list(dict.fromkeys(topics))[:4]
    fallback: list[str] = []
    for field in record.get("fields", []):
        fallback.extend(
            {
                "agriculture_environment_resource": ["agriculture", "environment"],
                "public_political": ["public"],
                "industrial_organization": ["firms"],
                "game_theory": ["theory"],
                "economic_history": ["history"],
                "applied_empirical": ["econometrics"],
                "international": ["trade"],
            }.get(field, [field] if field in TOPIC_LABELS else [])
        )
    return list(dict.fromkeys(fallback))[:3] or ["development"]


def working_paper_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return unique_records([record for record in records if is_working_paper(record) and has_public_title(record)])


def public_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if has_public_title(record)]


def journal_lookup() -> dict[str, dict[str, Any]]:
    lookup = {journal["id"]: journal for journal in load_journals(DATA_DIR / "journals.yml")}
    for source in load_working_paper_sources():
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        lookup[f"source-{source_id}"] = {
            "id": f"source-{source_id}",
            "title": source.get("title") or source_id,
            "chinese_name": SOURCE_CN_NAMES.get(source_id) or source.get("chinese_name") or "",
        }
    return lookup


SOURCE_STATUS = {
    "iza": ("已跑通", "ok", "RSS/页面入口可抓取，已纳入第一批测试。"),
    "cepr-dp": ("已跑通", "ok", "公开页面可抓取，已纳入第二批测试。"),
    "fed-feds": ("已跑通", "ok", "公开页面可抓取，已纳入第二批测试。"),
    "nber": ("已增强", "ok", "已接入 NBER 列表 API 和论文详情页。"),
    "world-bank-prwp": ("已增强", "ok", "已接入 World Bank Open Knowledge 详情 API，用详情页校验标题、摘要和日期。"),
    "imf-working-papers": ("替代源已接入", "ok", "官方页面访问不稳定，当前使用 IDEAS/RePEc 的 IMF Working Papers 公开系列页。"),
    "bis-working-papers": ("已跑通", "ok", "已接入 BIS 官方 RSS，并过滤 Working Papers。"),
    "cesifo-working-papers": ("已跑通", "ok", "已接入 IDEAS/RePEc 的 CESifo Working Papers 系列页。"),
    "oecd-working-papers": ("替代源已接入", "ok", "OECD/iLibrary 页面访问不稳定，当前使用 IDEAS/RePEc 的 OECD Economics Department Working Papers 公开系列页。"),
    "repec-nep-cna": ("已接入", "ok", "RePEc NEP 中国经济学细分类，优先补充与中国相关工作论文发现。"),
    "repec-nep-dev": ("已接入", "ok", "RePEc NEP 发展经济学细分类，用于补充机构工作论文源。"),
    "repec-nep-hea": ("已接入", "ok", "RePEc NEP 健康经济学细分类，作为 SSRN Health Economics 的公开替代入口之一。"),
    "repec-nep-mac": ("已接入", "ok", "RePEc NEP 宏观经济学细分类，用于补充 RePEc 新稿。"),
    "repec-nep-ifn": ("已接入", "ok", "RePEc NEP 国际金融细分类，用于补充 IMF/BIS/OECD 之外的宏观金融工作论文。"),
    "voxeu-cepr-columns": ("评估中", "todo", "政策评论源，不直接混入工作论文主流；后续如需要可单独开栏目。"),
    "brookings-economic-studies": ("评估中", "todo", "政策研究/评论源，先评估 RSS/API 稳定性。"),
    "iza-newsroom": ("评估中", "todo", "用于发现 IZA 发布动态，正式论文仍以 IZA Discussion Papers 为准。"),
    "repec-nep": ("暂缓", "pause", "聚合源噪声较高，先放到第三阶段。"),
    "ssrn-economics-research-network": ("受限待接邮件/feed", "pause", "SSRN 公开页面常返回访问限制；后续优先接邮件订阅或具体 eJournal feed。"),
    "ssrn-health-economics-network": ("受限待接邮件/feed", "pause", "SSRN 公开页面常返回访问限制；后续优先接邮件订阅或具体 eJournal feed。"),
}


SOURCE_TYPE_LABELS = {
    "working_paper": "工作论文",
    "policy_paper": "政策论文",
    "aggregator": "聚合源",
    "policy_commentary": "政策评论",
}


SOURCE_CN_NAMES = {
    "nber": "美国国家经济研究局工作论文",
    "iza": "IZA 讨论论文",
    "world-bank-prwp": "世界银行政策研究工作论文",
    "imf-working-papers": "IMF 工作论文",
    "repec-nep": "RePEc NEP 新经济学论文",
    "ssrn-economics-research-network": "SSRN 经济学研究网络",
    "ssrn-health-economics-network": "SSRN 健康经济学网络",
    "cepr-dp": "CEPR 讨论论文",
    "cesifo-working-papers": "CESifo 工作论文",
    "fed-feds": "美联储 FEDS 工作论文",
    "bis-working-papers": "国际清算银行工作论文",
    "oecd-working-papers": "OECD 工作论文",
    "repec-nep-cna": "RePEc NEP 中国经济学论文",
    "repec-nep-dev": "RePEc NEP 发展经济学论文",
    "repec-nep-hea": "RePEc NEP 健康经济学论文",
    "repec-nep-mac": "RePEc NEP 宏观经济学论文",
    "repec-nep-ifn": "RePEc NEP 国际金融论文",
    "voxeu-cepr-columns": "VoxEU / CEPR 专栏",
    "brookings-economic-studies": "Brookings 经济研究",
    "iza-newsroom": "IZA 新闻室",
}


def load_working_paper_sources(path: Path = DATA_DIR / "working_paper_sources.yml") -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sources = loaded.get("sources") or []
        return [source for source in sources if isinstance(source, dict)]
    except Exception:
        sources: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- id:"):
                if current:
                    sources.append(current)
                current = {"id": stripped.split(":", 1)[1].strip()}
            elif current is not None and ":" in stripped and not stripped.startswith("- "):
                key, value = stripped.split(":", 1)
                value = value.strip().strip('"').strip("'")
                if key.strip() == "stage":
                    try:
                        current[key.strip()] = int(value)
                    except ValueError:
                        current[key.strip()] = value
                else:
                    current[key.strip()] = value
        if current:
            sources.append(current)
        return sources


def working_paper_sources_body(records: list[dict[str, Any]]) -> str:
    sources = load_working_paper_sources()
    status = load_status()
    source_statuses = status.get("sources") or {}
    wp_records = working_paper_records(records)
    by_source = Counter(str(record.get("source_id") or "").removeprefix("source-") for record in wp_records)
    today_by_source = Counter(str(record.get("source_id") or "").removeprefix("source-") for record in wp_records if detected_date(record) == today_str())
    rows = []
    stable = partial = failed = 0
    for source in sources:
        source_id = str(source.get("id") or "")
        run_status = source_statuses.get(f"working-paper:{source_id}") or {}
        configured_label, configured_class, note = SOURCE_STATUS.get(source_id, ("待评估", "todo", "已加入配置，等待抓取验证。"))
        recent_count = int(run_status.get("count") or 0)
        total_count = by_source.get(source_id, 0)
        if run_status and not run_status.get("ok"):
            label, status_class = "失败/受限", "pause"
            failed += 1
            note = str(run_status.get("message") or note)
        elif recent_count > 0 or total_count > 0:
            label, status_class = "稳定出数据", "ok"
            stable += 1
        elif configured_class == "pause":
            label, status_class = configured_label, configured_class
            failed += 1
        else:
            label, status_class = "待增强", "todo"
            partial += 1
        chinese_name = SOURCE_CN_NAMES.get(source_id) or str(source.get("chinese_name") or "")
        homepage = str(source.get("homepage") or "")
        homepage_html = f'<a href="{html_escape(homepage)}">{html_escape(homepage)}</a>' if homepage else '<span class="muted">未配置</span>'
        rows.append(
            f"""<tr>
  <td><strong>{html_escape(str(source.get("title") or source_id))}</strong><div class="muted">{html_escape(chinese_name)}</div></td>
  <td>{html_escape(SOURCE_TYPE_LABELS.get(str(source.get("type") or ""), str(source.get("type") or "")))}</td>
  <td>{html_escape(str(source.get("stage") or ""))}</td>
  <td><span class="source-status {html_escape(status_class)}">{html_escape(label)}</span><div class="muted">{html_escape(note)}</div></td>
  <td>{recent_count}</td>
  <td>{today_by_source.get(source_id, 0)}</td>
  <td>{total_count}</td>
  <td>{html_escape(beijing_stamp(run_status.get("updated_at"))) if run_status else '<span class="muted">暂无</span>'}</td>
  <td>{homepage_html}</td>
</tr>"""
        )
    total_today = sum(today_by_source.values())
    total_records = len(wp_records)
    return f"""<section class="section-head">
  <div><h2>工作论文来源</h2><p>已接入 NBER、IZA、World Bank、IMF、CEPR、BIS、CESifo、OECD 等公开元数据来源；SSRN 暂以邮件/feed 方案待接入。这里只抓公开元数据，不批量下载 PDF。</p></div>
  <p>{len(sources)} 个来源</p>
</section>
<section class="stats">
  <a class="stat" href="{BASE}/working-papers/"><strong>{total_records}</strong><span>累计工作论文记录</span></a>
  <a class="stat" href="{BASE}/working-papers/today/"><strong>{total_today}</strong><span>今日新发现</span></a>
  <span class="stat"><strong>{stable}</strong><span>稳定出数据来源</span></span>
  <span class="stat"><strong>{partial}</strong><span>待增强来源</span></span>
  <span class="stat"><strong>{failed}</strong><span>失败/受限来源</span></span>
</section>
<div class="empty home-note">优先接入公开元数据稳定的工作论文与政策研究来源。</div>
<table class="journal-table"><thead><tr><th>来源</th><th>类型</th><th>阶段</th><th>状态/下一步</th><th>本轮</th><th>今日新增</th><th>累计</th><th>最近更新</th><th>入口</th></tr></thead><tbody>{"".join(rows)}</tbody></table>"""


def stats(records: list[dict[str, Any]], today_records: list[dict[str, Any]], flow_records: list[dict[str, Any]]) -> dict[str, Any]:
    today = today_str()
    today_journals = {record.get("journal_id") for record in today_records if record.get("journal_id")}
    all_journals = {record.get("journal_id") for record in records if record.get("journal_id")}
    status = load_status()
    workflow = status.get("workflow") or {}
    latest_run = workflow.get("finished_at") or (status.get("runs") or [{}])[0].get("updated_at") or ""
    latest_source = max(
        (str(item.get("updated_at") or "") for item in (status.get("sources") or {}).values()),
        default="",
    )
    last_record_seen = max((record.get("detected_at") or "" for record in records), default="")
    last_run = latest_run or latest_source or last_record_seen
    return {
        "today": len(today_records),
        "china_today": sum(1 for record in today_records if is_china_related(record)),
        "online_today": sum(1 for record in today_records if today in {record.get("available_online"), record.get("published_online")}),
        "today_journals": len(today_journals),
        "flow": len(flow_records),
        "china_flow": sum(1 for record in flow_records if is_china_related(record)),
        "online_today_flow": sum(1 for record in flow_records if today in {record.get("available_online"), record.get("published_online")}),
        "flow_journals": len({record.get("journal_id") for record in flow_records if record.get("journal_id")}),
        "all_records": len(records),
        "all_journals": len(all_journals),
        "last_run": beijing_stamp(last_run),
        "last_run_label": workflow.get("mode_label") or "自动监测",
        "last_full_run": beijing_stamp(workflow.get("last_full_finished_at")),
        "last_light_run": beijing_stamp(workflow.get("last_light_finished_at")),
        "next_light_run": next_hourly_run(workflow.get("last_light_finished_at") or last_run),
        "next_full_run": next_daily_full_run(workflow.get("last_full_finished_at") or last_run),
        "last_record_seen": beijing_stamp(last_record_seen),
    }


def date_type(record: dict[str, Any]) -> str:
    if record.get("available_online"):
        return "available_online"
    if record.get("published_online"):
        return "published_online"
    if record.get("accepted_date"):
        return "accepted"
    if record.get("source_issue") or record.get("issue_date"):
        return "issue"
    return "first_seen"


def date_type_label(value: str) -> str:
    return {
        "accepted": "接受日期",
        "available_online": "Online 日期",
        "published_online": "发布日期",
        "issue": "来源期次",
        "first_seen": "首次监测",
    }.get(value, value)


def confidence_value(record: dict[str, Any]) -> str:
    if record.get("date_confidence"):
        return str(record.get("date_confidence"))
    return {"accepted": "A", "available_online": "A", "published_online": "B", "issue": "D", "first_seen": "F"}.get(date_type(record), "F")


def confidence_label(value: str) -> str:
    return {
        "A": "A 高：出版社/PDF 明确日期",
        "B": "B 中：RSS/出版社备选日期",
        "C": "C 低：Crossref 元数据",
        "D": "D 低：卷期/印刷日期",
        "F": "F 待核：仅首次监测",
    }.get(value, value)


def public_date_label(record: dict[str, Any]) -> str:
    if record.get("available_online") or record.get("published_online"):
        return "在线日期"
    if record.get("accepted_date"):
        return "接受日期"
    if record.get("source_issue"):
        return "来源期次"
    if record.get("issue_date"):
        return "卷期日期"
    return "日期待解析"


def official_date(record: dict[str, Any]) -> str:
    return str(record.get("available_online") or record.get("published_online") or record.get("accepted_date") or record.get("source_issue") or record.get("issue_date") or "待解析")


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
    return f"{public_date_label(record)} {official_date(record)} · 来源：{date_source_label(record)}"


def sidebar(
    records: list[dict[str, Any]],
    *,
    context_records: list[dict[str, Any]] | None = None,
    context_date: str | None = None,
) -> str:
    side_records = public_records(context_records if context_records is not None else records)
    journal_side_records = [record for record in side_records if not is_working_paper(record)]
    working_side_records = [record for record in side_records if is_working_paper(record)]
    journal_counts = Counter(record.get("journal_id") for record in journal_side_records if record.get("journal_id"))
    working_counts = Counter(record.get("journal_id") for record in working_side_records if record.get("journal_id"))
    journals_by_id = journal_lookup()
    topics = "".join(
        f'<a class="side-link" href="{BASE}/topics/{html_escape(topic)}/"><span class="side-main"><strong>{html_escape(topic_label(topic))}</strong></span><span class="count">{count}</span></a>'
        for topic, count in ordered_topic_counts(side_records)[:12]
    )
    journal_target_date = context_date or today_str()
    is_today_context = journal_target_date == today_str()
    topic_title = "今日文章主题" if is_today_context else f"{journal_target_date} 文章主题"
    journal_source_title = "今日期刊论文来源" if is_today_context else f"{journal_target_date} 期刊论文来源"
    working_source_title = "今日工作论文来源" if is_today_context else f"{journal_target_date} 工作论文来源"
    journal_footer_label = "查看今日期刊论文" if is_today_context else f"查看 {journal_target_date} 期刊论文"
    working_footer_label = "查看今日工作论文" if is_today_context else f"查看 {journal_target_date} 工作论文"
    working_footer_href = f"{BASE}/working-papers/today/" if is_today_context else f"{BASE}/daily/{html_escape(journal_target_date)}/?sourceType=working_paper"

    def source_links(counts: Counter, *, working: bool) -> str:
        links = []
        for journal_id, count in counts.most_common(10):
            journal = journals_by_id.get(journal_id, {})
            title = journal.get("title") or journal_id
            chinese_name = journal.get("chinese_name") or ""
            target = f"{BASE}/working-papers/today/?journal={html_escape(journal_id)}" if working else f"{BASE}/daily/{html_escape(journal_target_date)}/?journal={html_escape(journal_id)}"
            links.append(
                f'<a class="side-link" href="{target}"><span class="side-main"><strong>{html_escape(title)}</strong><em>{html_escape(chinese_name)}</em></span><span class="count">{count}</span></a>'
            )
        if not links:
            label = "工作论文来源" if working else "期刊更新"
            links.append(f'<div class="side-link"><span class="side-main"><strong>暂无{html_escape(label)}</strong></span><span class="count">0</span></div>')
        return "".join(links)

    journal_links = source_links(journal_counts, working=False)
    working_links = source_links(working_counts, working=True)
    return f"""<aside class="sidebar">
  <h1 class="brand">{SITE_NAME}</h1>
  <div class="subtitle">{SITE_SUBTITLE}</div>
  <div class="side-block"><div class="side-title">导航</div>
    <a class="side-link" href="{BASE}/"><span class="side-main"><strong>今日论文</strong></span><span class="count">Today</span></a>
    <a class="side-link" href="{BASE}/topics/china/"><span class="side-main"><strong>与中国相关</strong></span><span class="count">Topic</span></a>
    <a class="side-link" href="{BASE}/archive/"><span class="side-main"><strong>历史归档</strong></span><span class="count">Archive</span></a>
    <a class="side-link" href="{BASE}/journals/"><span class="side-main"><strong>监测期刊</strong></span><span class="count">List</span></a>
    <a class="side-link" href="{BASE}/working-papers/"><span class="side-main"><strong>最新工作论文</strong></span><span class="count">WP</span></a>
    <a class="side-link" href="{BASE}/sources/working-papers/"><span class="side-main"><strong>工作论文来源</strong></span><span class="count">Beta</span></a>
  </div>
  <div class="side-block"><div class="side-title">{html_escape(topic_title)}</div>{topics}</div>
  <div class="side-block"><div class="side-title">{html_escape(journal_source_title)}</div>{journal_links}<a class="side-link" href="{BASE}/daily/{html_escape(journal_target_date)}/"><span class="side-main"><strong>{html_escape(journal_footer_label)}</strong></span><span class="count">Today</span></a></div>
  <div class="side-block"><div class="side-title">{html_escape(working_source_title)}</div>{working_links}<a class="side-link" href="{working_footer_href}"><span class="side-main"><strong>{html_escape(working_footer_label)}</strong></span><span class="count">Today</span></a></div>
</aside>"""


def analytics_snippet() -> str:
    provider = os.environ.get("ANALYTICS_PROVIDER", "none").strip().lower()
    if provider in {"", "none", "off", "false"}:
        return ""
    if provider == "plausible":
        domain = os.environ.get("PLAUSIBLE_DOMAIN", "").strip()
        script_url = os.environ.get("PLAUSIBLE_SCRIPT_URL", "https://plausible.io/js/script.js").strip()
        if not domain:
            return ""
        return f'<script defer data-domain="{html_escape(domain)}" src="{html_escape(script_url)}"></script>'
    if provider == "umami":
        website_id = os.environ.get("UMAMI_WEBSITE_ID", "").strip()
        script_url = os.environ.get("UMAMI_SCRIPT_URL", "").strip()
        if not website_id or not script_url:
            return ""
        return f'<script defer src="{html_escape(script_url)}" data-website-id="{html_escape(website_id)}"></script>'
    if provider in {"google", "ga", "gtag"}:
        measurement_id = os.environ.get("GA_MEASUREMENT_ID", "").strip()
        if not measurement_id:
            return ""
        escaped_id = html_escape(measurement_id)
        return f"""<script async src="https://www.googletagmanager.com/gtag/js?id={escaped_id}"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', '{escaped_id}');
</script>"""
    return ""


def page(
    title: str,
    records: list[dict[str, Any]],
    body: str,
    active: str = "",
    *,
    sidebar_records: list[dict[str, Any]] | None = None,
    sidebar_date: str | None = None,
) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  {analytics_snippet()}
  <style>{STYLE}</style>
</head>
<body>
  <div class="shell">
    {sidebar(records, context_records=sidebar_records, context_date=sidebar_date)}
    <div class="content">
      <header class="topbar"><div class="topbar-inner">
        <div><strong>{SITE_NAME}</strong> <span class="subtitle">{SITE_SUBTITLE}</span></div>
        <nav class="nav">
          <a class="{ 'active' if active == 'home' else '' }" href="{BASE}/">今日</a>
          <a href="{BASE}/topics/china/">与中国相关</a>
          <a class="{ 'active' if active == 'archive' else '' }" href="{BASE}/archive/">归档</a>
          <a href="{BASE}/journals/">监测期刊</a>
          <a class="{ 'active' if active == 'working-papers' else '' }" href="{BASE}/working-papers/">工作论文</a>
          <a href="{BASE}/feed.xml">RSS</a>
        </nav>
      </div></header>
      <main class="wrap">{body}</main>
    </div>
  </div>
</body>
</html>
"""


def paper_events(records: list[dict[str, Any]], limit: int | None = None, *, scope: str = "default", extra_class: str = "") -> str:
    public = public_records(records)
    selected = public[:limit] if limit else public
    if not selected:
        return '<div class="empty">暂无符合条件的论文记录。</div>'
    chunks = []
    for record in selected:
        online_today = today_str() in {str(record.get("available_online") or ""), str(record.get("published_online") or "")}
        if record.get("doi"):
            link_or_doi = f'<a class="doi" href="https://doi.org/{html_escape(record.get("doi"))}">{html_escape(record.get("doi"))}</a>'
        elif record.get("url"):
            link_or_doi = f'<a class="doi" href="{html_escape(record.get("url"))}">文章链接</a>'
        else:
            link_or_doi = '<span class="doi">暂无 DOI</span>'
        fields = "".join(f'<span class="pill">{html_escape(topic_label(topic))}</span>' for topic in article_topics(record)[:3] if topic != "china")
        title_zh = record.get("title_zh")
        if title_zh and str(title_zh).strip() == str(record.get("title") or "").strip():
            title_zh = None
        title_zh_html = f'<p class="title-zh">{html_escape(title_zh)}</p>' if title_zh else ""
        china_related = is_china_related(record)
        china_tag = '<span class="pill china">与中国相关</span>' if china_related else ""
        search_text = " ".join(str(value or "") for value in [record.get("title"), record.get("title_zh"), authors(record), record.get("journal"), record.get("doi")])
        field_attr = " ".join(article_topics(record))
        type_tag = f'<span class="pill">{html_escape(source_type_label(record))}</span>' if is_working_paper(record) else ""
        classes = "event" + (f" {extra_class}" if extra_class else "")
        chunks.append(
            f"""<article class="{html_escape(classes)}" data-event-scope="{html_escape(scope)}" data-search="{html_escape(normalize_attr(search_text))}" data-journal="{html_escape(normalize_attr(record.get('journal_id')))}" data-fields="{html_escape(normalize_attr(field_attr))}" data-china="{str(china_related).lower()}" data-online-today="{str(online_today).lower()}" data-date-type="{html_escape(date_type(record))}" data-confidence="{html_escape(confidence_value(record))}" data-source-type="{html_escape(str(record.get('source_type') or ('working_paper' if is_working_paper(record) else 'journal_article')))}">
  <div><div class="time">{html_escape(detected_time(record))}</div><div class="date-note">{html_escape(detected_date(record))}</div></div>
  <div>
    <h3><a href="{html_escape(record_url(record))}">{html_escape(record.get('title'))}</a></h3>
    {title_zh_html}
    <p class="authors">{html_escape(authors(record))}</p>
    <div class="meta-block">
      <div class="meta-line"><span class="meta-label">{'来源' if is_working_paper(record) else '期刊'}</span><span class="meta-values"><span class="journal-chip">{html_escape(record.get('journal'))}</span>{type_tag}<span class="source-chip">{html_escape(public_date_line(record))}</span></span></div>
      <div class="meta-line"><span class="meta-label">链接/DOI</span><span class="meta-values">{link_or_doi}{fields}{china_tag}</span></div>
    </div>
  </div>
</article>"""
        )
    return "\n".join(chunks)


FILTER_SCRIPT = """
<script>
(() => {
  const params = new URLSearchParams(window.location.search);
  document.querySelectorAll('.toolbar[data-filter-scope]').forEach((toolbar) => {
    const scope = toolbar.dataset.filterScope || 'default';
    const search = toolbar.querySelector('[data-filter-role="search"]');
    const journal = toolbar.querySelector('[data-filter-role="journal"]');
    const field = toolbar.querySelector('[data-filter-role="field"]');
    const dateType = toolbar.querySelector('[data-filter-role="dateType"]');
    const confidence = toolbar.querySelector('[data-filter-role="confidence"]');
    const sourceType = toolbar.querySelector('[data-filter-role="sourceType"]');
    const china = toolbar.querySelector('[data-filter-role="china"]');
    const counter = document.querySelector(`[data-filter-counter="${scope}"]`);
    const empty = document.querySelector(`[data-filter-empty="${scope}"]`);
    const events = Array.from(document.querySelectorAll(`.event[data-event-scope="${scope}"]`));
    if (!search || !journal || !field || !china) return;
    let preset = '';
    if (params.get('q')) search.value = params.get('q');
    if (params.get('journal')) journal.value = params.get('journal');
    if (params.get('field')) field.value = params.get('field');
    if (dateType && params.get('dateType')) dateType.value = params.get('dateType');
    if (confidence && params.get('confidence')) confidence.value = params.get('confidence');
    if (sourceType && params.get('sourceType')) sourceType.value = params.get('sourceType');
    if (params.get('china') === '1') {
      china.setAttribute('aria-pressed', 'true');
      china.classList.add('active');
    }
    if (params.get('onlineToday') === '1') preset = 'online-today';
    function setCounter(visible, chinaOnly) {
      if (!counter) return;
      if (chinaOnly || preset === 'china') {
        counter.innerHTML = `当前显示与中国相关研究 <span class="num">${visible}</span> 篇`;
      } else if (preset === 'online-today') {
        counter.innerHTML = `当前显示在线日期为今日的研究 <span class="num">${visible}</span> 篇`;
      } else {
        counter.innerHTML = `当前显示 <span class="num">${visible}</span> 篇`;
      }
    }
    function applyFilters() {
      const q = (search.value || '').trim().toLowerCase();
      const journalValue = journal.value;
      const fieldValue = field.value;
      const dateTypeValue = dateType ? dateType.value : '';
      const confidenceValue = confidence ? confidence.value : '';
      const sourceTypeValue = sourceType ? sourceType.value : '';
      const chinaOnly = china.getAttribute('aria-pressed') === 'true';
      let visible = 0;
      for (const item of events) {
        const okSearch = !q || item.dataset.search.includes(q);
        const okJournal = !journalValue || item.dataset.journal === journalValue;
        const okField = !fieldValue || item.dataset.fields.split(' ').includes(fieldValue);
        const okDateType = !dateTypeValue || item.dataset.dateType === dateTypeValue;
        const okConfidence = !confidenceValue || item.dataset.confidence === confidenceValue;
        const okSourceType = !sourceTypeValue || item.dataset.sourceType === sourceTypeValue;
        const okChina = (!chinaOnly && preset !== 'china') || item.dataset.china === 'true';
        const okPreset = preset !== 'online-today' || item.dataset.onlineToday === 'true';
        const show = okSearch && okJournal && okField && okDateType && okConfidence && okSourceType && okChina && okPreset;
        item.hidden = !show;
        if (show) visible += 1;
      }
      if (empty) empty.hidden = visible !== 0;
      setCounter(visible, chinaOnly);
    }
    search.addEventListener('input', applyFilters);
    journal.addEventListener('change', applyFilters);
    field.addEventListener('change', applyFilters);
    if (dateType) dateType.addEventListener('change', applyFilters);
    if (confidence) confidence.addEventListener('change', applyFilters);
    if (sourceType) sourceType.addEventListener('change', applyFilters);
    china.addEventListener('click', () => {
      const active = china.getAttribute('aria-pressed') !== 'true';
      china.setAttribute('aria-pressed', String(active));
      china.classList.toggle('active', active);
      applyFilters();
    });
    document.querySelectorAll(`[data-filter-preset][data-filter-scope-target="${scope}"]`).forEach((item) => {
      item.addEventListener('click', (event) => {
        event.preventDefault();
        preset = item.dataset.filterPreset || '';
        if (preset === 'all') {
          search.value = '';
          journal.value = '';
          field.value = '';
          if (dateType) dateType.value = '';
          if (confidence) confidence.value = '';
          if (sourceType) sourceType.value = '';
          china.setAttribute('aria-pressed', 'false');
          china.classList.remove('active');
        }
        if (preset === 'china') {
          china.setAttribute('aria-pressed', 'true');
          china.classList.add('active');
        }
        applyFilters();
        toolbar.scrollIntoView({behavior: 'smooth', block: 'start'});
      });
    });
    applyFilters();
  });
  document.querySelectorAll('[data-filter-preset]:not([data-filter-scope-target])').forEach((item) => {
    item.setAttribute('data-filter-scope-target', 'default');
  });
  for (const item of document.querySelectorAll('[data-filter-preset]')) {
    if (!item.dataset.boundScopeFallback) {
      item.dataset.boundScopeFallback = '1';
      if (!item.dataset.filterScopeTarget) {
        item.dataset.filterScopeTarget = 'default';
      }
    }
  }
})();
</script>
"""


def filter_toolbar(records: list[dict[str, Any]], *, include_rss: bool = False, source_label: str = "筛选期刊", scope: str = "default") -> str:
    if not records:
        return ""
    journals = sorted({(record.get("journal_id"), record.get("journal")) for record in records if record.get("journal_id") and record.get("journal")}, key=lambda item: item[1])
    topics = sorted({topic for record in records for topic in article_topics(record)}, key=topic_label)
    date_types = sorted({date_type(record) for record in records}, key=date_type_label)
    confidences = sorted({confidence_value(record) for record in records})
    source_types = sorted({str(record.get("source_type") or ("working_paper" if is_working_paper(record) else "journal_article")) for record in records})
    journal_options = "".join(f'<option value="{html_escape(jid)}">{html_escape(title)}</option>' for jid, title in journals)
    field_options = "".join(f'<option value="{html_escape(topic)}">{html_escape(topic_label(topic))}</option>' for topic in topics)
    date_type_options = "".join(f'<option value="{html_escape(value)}">{html_escape(date_type_label(value))}</option>' for value in date_types)
    confidence_options = "".join(f'<option value="{html_escape(value)}">{html_escape(confidence_label(value))}</option>' for value in confidences)
    source_type_options = "".join(f'<option value="{html_escape(value)}">{html_escape(SOURCE_TYPE_LABELS.get(value, source_type_label({"source_type": value})))}</option>' for value in source_types)
    rss = f'<a class="control primary" href="{BASE}/feed.xml">RSS 订阅</a>' if include_rss else ""
    return f"""<div class="toolbar" id="filters-{html_escape(scope)}" data-filter-scope="{html_escape(scope)}">
  <input class="control" data-filter-role="search" type="search" placeholder="搜索标题/作者/DOI">
  <select class="control" data-filter-role="journal"><option value="">{html_escape(source_label)}</option>{journal_options}</select>
  <select class="control" data-filter-role="field"><option value="">筛选主题</option>{field_options}</select>
  <select class="control" data-filter-role="dateType"><option value="">筛选日期类型</option>{date_type_options}</select>
  <select class="control" data-filter-role="confidence"><option value="">筛选可信度</option>{confidence_options}</select>
  <select class="control" data-filter-role="sourceType"><option value="">筛选来源类型</option>{source_type_options}</select>
  <button class="control toggle" data-filter-role="china" type="button" aria-pressed="false">与中国相关</button>
  {rss}
</div>
<div class="empty" data-filter-empty="{html_escape(scope)}" hidden>没有符合当前筛选条件的论文。</div>"""


def date_from_record(record: dict[str, Any]) -> datetime | None:
    value = detected_date(record)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def recent_records(records: list[dict[str, Any]], days: int = 7) -> list[dict[str, Any]]:
    dates = [date_from_record(record) for record in records]
    dates = [item for item in dates if item is not None]
    if not dates:
        return records
    cutoff = max(dates) - timedelta(days=days - 1)
    return [record for record in records if (date_from_record(record) or datetime.min) >= cutoff]


def journal_view_links(journal_id: str, journal_records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> str:
    latest_day = detected_date(journal_records[0]) if journal_records else today_str()
    today_count = len([record for record in today_records if record.get("journal_id") == journal_id])
    latest_count = len([record for record in journal_records if detected_date(record) == latest_day])
    recent_count = len(recent_records(journal_records, 7))
    today_label = f"今日 {today_count}" if today_count else f"最新日期 {latest_count}"
    target_day = today_str() if today_count else latest_day
    return f"""<div class="toolbar">
  <a class="control primary" href="{BASE}/daily/{html_escape(target_day)}/?journal={html_escape(journal_id)}">{html_escape(today_label)}</a>
  <a class="control" href="{BASE}/journals/{html_escape(journal_id)}/recent7/">最近 7 天 {recent_count}</a>
  <a class="control" href="{BASE}/journals/{html_escape(journal_id)}/">全部历史 {len(journal_records)}</a>
</div>"""


def topic_view_links(topic: str, topic_records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> str:
    topic_today = [record for record in today_records if topic in article_topics(record)]
    latest_day = detected_date(topic_records[0]) if topic_records else today_str()
    latest_count = len([record for record in topic_records if detected_date(record) == latest_day])
    recent = recent_records(topic_records, 7)
    target_day = today_str() if topic_today else latest_day
    today_label = f"今日 {len(topic_today)}" if topic_today else f"最新日期 {latest_count}"
    return f"""<div class="toolbar">
  <a class="control primary" href="{BASE}/daily/{html_escape(target_day)}/?field={html_escape(topic)}">{html_escape(today_label)}</a>
  <a class="control" href="{BASE}/topics/{html_escape(topic)}/recent7/">最近 7 天 {len(recent)}</a>
  <a class="control" href="{BASE}/topics/{html_escape(topic)}/">全部历史 {len(topic_records)}</a>
</div>"""


def home_body(records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> str:
    latest_day = detected_date(records[0]) if records else ""
    latest_records = [record for record in records if detected_date(record) == latest_day] if latest_day else []
    flow_records = today_records or latest_records
    journal_flow_records = [record for record in flow_records if not is_working_paper(record)]
    working_flow_records = [record for record in flow_records if is_working_paper(record)]
    all_working = working_paper_records(records)
    all_journal_count = sum(1 for record in records if not is_working_paper(record) and has_public_title(record))
    s = stats(records, today_records, flow_records)
    flow_date = today_str() if today_records else (latest_day or today_str())
    journal_note = ""
    working_note = ""
    journal_note_html = f"<p>{journal_note}</p>" if journal_note else ""
    working_note_html = f"<p>{working_note}</p>" if working_note else ""
    note = ""
    return f"""<section class="banner">
  <div class="banner-main">
      <div class="hero-layout">
      <div>
        <p class="eyebrow">TOP economics journals, updated daily</p>
        <h1>{SITE_NAME}</h1>
        <p>{SITE_SUBTITLE}</p>
        <div class="hero-stats">
          <a class="hero-stat" href="#journal-flow" data-filter-preset="all" data-filter-scope-target="journal"><strong>{len(journal_flow_records)}</strong><span>今日期刊论文新发现</span></a>
          <a class="hero-stat china" href="#journal-flow" data-filter-preset="china" data-filter-scope-target="journal"><strong>{sum(1 for record in journal_flow_records if is_china_related(record))}</strong><span>期刊论文中与中国相关</span></a>
          <a class="hero-stat" href="#journal-flow" data-filter-preset="online-today" data-filter-scope-target="journal"><strong>{sum(1 for record in journal_flow_records if today_str() in {str(record.get('available_online') or ''), str(record.get('published_online') or '')})}</strong><span>期刊在线日期为今日</span></a>
          <a class="hero-stat" href="#working-flow" data-filter-preset="all" data-filter-scope-target="working"><strong>{len(working_flow_records)}</strong><span>今日工作论文新发现</span></a>
          <a class="hero-stat china" href="#working-flow" data-filter-preset="china" data-filter-scope-target="working"><strong>{sum(1 for record in working_flow_records if is_public_china_related(record))}</strong><span>工作论文中与中国相关</span></a>
          <a class="hero-stat" href="{BASE}/archive/"><strong>{s['all_records']}</strong><span>累计监测记录</span></a>
        </div>
      </div>
      <aside class="operator-card">
        <img src="{BASE}/assets/academic-portal-qr.jpg" alt="学术传送门二维码">
        <div>
          <strong>学术传送门</strong>
          <span>本站由学术传送门运营</span>
          <em>读好文献，用好文献</em>
        </div>
      </aside>
      </div>
  </div>
</section>
<section class="status-strip">
  <span>最近监测 <strong>{html_escape(s['last_run'])}</strong></span>
  <span>监测类型 <strong>{html_escape(s['last_run_label'])}</strong></span>
  <span>下次快速 <strong>{html_escape(s['next_light_run'])}</strong></span>
  <span>下次全量 <strong>{html_escape(s['next_full_run'])}</strong></span>
</section>
<section id="journal-flow" class="section-head"><div><h2>今日 TOP 期刊论文 <span class="live-count" data-filter-counter="journal"></span></h2>{journal_note_html}</div><p>{html_escape(flow_date)}</p></section>
<section class="stats">
  <a class="stat" href="{BASE}/journals/"><strong>{len({record.get('journal_id') for record in journal_flow_records if record.get('journal_id')})}</strong><span>今日涉及期刊</span></a>
  <a class="stat china" href="#journal-flow" data-filter-preset="china" data-filter-scope-target="journal"><strong>{sum(1 for record in journal_flow_records if is_china_related(record))}</strong><span>期刊论文中与中国相关</span></a>
  <a class="stat" href="#journal-flow" data-filter-preset="online-today" data-filter-scope-target="journal"><strong>{sum(1 for record in journal_flow_records if today_str() in {str(record.get('available_online') or ''), str(record.get('published_online') or '')})}</strong><span>期刊在线日期为今日</span></a>
  <a class="stat" href="{BASE}/archive/"><strong>{all_journal_count}</strong><span>累计期刊论文记录</span></a>
</section>
{filter_toolbar(journal_flow_records, include_rss=True, scope="journal")}
{note}
{paper_events(journal_flow_records, scope="journal")}
<section id="working-flow" class="section-head split-section"><div><h2>今日工作论文 <span class="live-count" data-filter-counter="working"></span></h2>{working_note_html}</div><p><a href="{BASE}/working-papers/today/">查看全部 {len(working_flow_records)} 篇</a></p></section>
<section class="stats">
  <a class="stat" href="{BASE}/working-papers/today/"><strong>{len(working_flow_records)}</strong><span>工作论文新发现</span></a>
  <a class="stat china" href="{BASE}/working-papers/china/"><strong>{sum(1 for record in working_flow_records if is_public_china_related(record))}</strong><span>工作论文中与中国相关</span></a>
  <a class="stat" href="{BASE}/sources/working-papers/"><strong>{len({record.get('journal_id') for record in working_flow_records if record.get('journal_id')})}</strong><span>今日涉及来源</span></a>
  <a class="stat" href="{BASE}/working-papers/"><strong>{len(all_working)}</strong><span>累计工作论文记录</span></a>
</section>
{filter_toolbar(working_flow_records, source_label="筛选来源", scope="working")}
{paper_events(working_flow_records, scope="working", extra_class="home-wp-preview")}
{FILTER_SCRIPT}
"""


def working_papers_body(records: list[dict[str, Any]], *, view: str = "all") -> str:
    all_wp_records = working_paper_records(records)
    wp_records = all_wp_records
    if view == "today":
        wp_records = [record for record in all_wp_records if detected_date(record) == today_str()]
    elif view == "recent7":
        wp_records = recent_records(all_wp_records, 7)
    elif view == "china":
        wp_records = [record for record in all_wp_records if is_public_china_related(record)]
    elif view == "china-recent7":
        wp_records = [record for record in recent_records(all_wp_records, 7) if is_public_china_related(record)]
    latest_day = detected_date(wp_records[0]) if wp_records else ""
    today_count = sum(1 for record in all_wp_records if detected_date(record) == today_str())
    recent_count = len(recent_records(all_wp_records, 7))
    china_count = sum(1 for record in all_wp_records if is_public_china_related(record))
    title = {
        "today": "今日工作论文",
        "recent7": "最近 7 天工作论文",
        "china": "与中国相关工作论文",
        "china-recent7": "最近 7 天与中国相关工作论文",
    }.get(view, "全部工作论文")
    note = "覆盖工作论文和政策论文来源，按首次监测时间倒序排列；日期字段会区分发布/上线日期与本站首次监测日期。"
    tabs = [
        ("today", "今日", f"{BASE}/working-papers/today/", today_count),
        ("recent7", "最近 7 天", f"{BASE}/working-papers/recent7/", recent_count),
        ("all", "全部", f"{BASE}/working-papers/", len(all_wp_records)),
        ("china", "与中国相关", f"{BASE}/working-papers/china/", china_count),
    ]
    tabs_html = "".join(
        f'<a class="view-tab {"active" if key == view else ""}" href="{href}">{label} <strong>{count}</strong></a>'
        for key, label, href, count in tabs
    )
    return f"""<section class="section-head">
  <div><h2>{title} <span class="live-count" id="flowCounter"></span></h2><p>{note}</p></div>
  <p>{html_escape(latest_day or today_str())}</p>
</section>
<nav class="view-tabs">{tabs_html}</nav>
<section class="stats">
  <a class="stat" href="{BASE}/working-papers/"><strong>{len(all_wp_records)}</strong><span>累计工作论文记录</span></a>
  <a class="stat" href="{BASE}/working-papers/china/"><strong>{china_count}</strong><span>与中国相关</span></a>
  <a class="stat" href="{BASE}/working-papers/today/"><strong>{today_count}</strong><span>今日新发现</span></a>
  <a class="stat" href="{BASE}/sources/working-papers/"><strong>{len(load_working_paper_sources())}</strong><span>监测来源</span></a>
</section>
{filter_toolbar(wp_records, source_label="筛选来源")}
{paper_events(wp_records)}
{FILTER_SCRIPT}
"""


def china_topic_body(records: list[dict[str, Any]], topic_records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> str:
    public_topic_records = public_records(topic_records)
    journal_records = [record for record in public_topic_records if not is_working_paper(record)]
    wp_records = [record for record in public_topic_records if is_working_paper(record)]
    today_journals = [record for record in journal_records if detected_date(record) == today_str()]
    today_wp = [record for record in wp_records if detected_date(record) == today_str()]
    recent_journals = recent_records(journal_records, 7)
    recent_wp = recent_records(wp_records, 7)
    return f"""<section class="section-head">
  <div><h2>与中国相关</h2><p>期刊论文和工作论文分开浏览。</p></div>
  <p>{len(public_topic_records)} 篇</p>
</section>
<section class="stats">
  <a class="stat" href="#china-journals"><strong>{len(journal_records)}</strong><span>期刊论文</span></a>
  <a class="stat" href="#china-working"><strong>{len(wp_records)}</strong><span>工作论文</span></a>
  <a class="stat" href="{BASE}/daily/{today_str()}/?field=china"><strong>{len(today_journals)}</strong><span>今日期刊论文</span></a>
  <a class="stat" href="{BASE}/working-papers/china/"><strong>{len(today_wp)}</strong><span>今日工作论文</span></a>
</section>
<section id="china-journals" class="section-head"><div><h2>与中国相关：期刊论文 <span class="live-count" data-filter-counter="china-journal"></span></h2></div><p>最近 7 天 {len(recent_journals)} 篇</p></section>
{filter_toolbar(journal_records, include_rss=True, scope="china-journal")}
{paper_events(journal_records, scope="china-journal")}
<section id="china-working" class="section-head split-section"><div><h2>与中国相关：工作论文 <span class="live-count" data-filter-counter="china-working"></span></h2></div><p>最近 7 天 {len(recent_wp)} 篇</p></section>
{filter_toolbar(wp_records, source_label="筛选来源", scope="china-working")}
{paper_events(wp_records, scope="china-working")}
{FILTER_SCRIPT}
"""


def china_quality_body(records: list[dict[str, Any]]) -> str:
    latest = public_records(records[:500])
    confirmed = [record for record in latest if is_china_related(record)]
    candidates = [record for record in latest if record.get("china_relevance_status") == "candidate"]
    rejected = [
        record
        for record in latest
        if str(record.get("china_relevance_status") or "").lower() in {"rejected", "excluded", "none"}
        or record.get("china_related") is False
    ]
    working_confirmed = [record for record in confirmed if is_working_paper(record)]

    def item(record: dict[str, Any]) -> str:
        title_zh = record.get("title_zh")
        zh = f'<p class="title-zh">{html_escape(title_zh)}</p>' if title_zh and title_zh != record.get("title") else ""
        status = str(record.get("china_relevance_status") or ("confirmed" if is_china_related(record) else "none"))
        reason = record.get("china_relevance_reason") or record.get("china_related_reason") or "暂无判定说明"
        evidence = record.get("china_relevance_evidence") or record.get("china_related_source") or ""
        return f"""<article class="audit-item">
  <h3><a href="{html_escape(record_url(record))}">{html_escape(record.get('title') or 'Untitled')}</a></h3>
  {zh}
  <div class="audit-meta">{html_escape(record.get('journal') or '')} · {html_escape(detected_date(record))} · 状态：{html_escape(status)}</div>
  <div class="audit-reason"><b>判定理由</b>：{html_escape(reason)}</div>
  {f'<div class="audit-reason"><b>证据</b>：{html_escape(evidence)}</div>' if evidence else ''}
</article>"""

    confirmed_html = "".join(item(record) for record in confirmed[:25]) or '<div class="empty">暂无已确认记录。</div>'
    candidates_html = "".join(item(record) for record in candidates[:25]) or '<div class="empty">暂无候选记录。</div>'
    rejected_html = "".join(item(record) for record in rejected[:25]) or '<div class="empty">暂无排除样本。</div>'
    return f"""<section class="section-head">
  <div><h2>中国相关判定抽检</h2><p>集中查看 AI/规则判定结果，帮助校准“与中国相关”的召回率和误判率。</p></div>
  <p>最近样本 {len(latest)} 条</p>
</section>
<section class="audit-grid">
  <div class="audit-card"><strong>{len(confirmed)}</strong><span>最近样本中已确认中国相关</span></div>
  <div class="audit-card"><strong>{len(working_confirmed)}</strong><span>其中工作论文/政策论文</span></div>
  <div class="audit-card"><strong>{len(candidates)}</strong><span>待校准候选</span></div>
</section>
<nav class="view-tabs">
  <a class="view-tab active" href="#confirmed">已确认</a>
  <a class="view-tab" href="#candidates">候选</a>
  <a class="view-tab" href="#rejected">排除样本</a>
</nav>
<section id="confirmed" class="section-head"><div><h2>已确认中国相关</h2><p>公开页面只展示已确认结果；有争议样本优先留在候选或排除样本中。</p></div></section>
<div class="audit-list">{confirmed_html}</div>
<section id="candidates" class="section-head"><div><h2>候选记录</h2><p>这里用于发现漏判/误判模式，后续可继续接入摘要增强判定。</p></div></section>
<div class="audit-list">{candidates_html}</div>
<section id="rejected" class="section-head"><div><h2>排除样本</h2><p>抽查被排除记录，避免规则过严导致中国相关研究漏掉。</p></div></section>
<div class="audit-list">{rejected_html}</div>"""


def admin_status_body(records: list[dict[str, Any]]) -> str:
    token_hash = os.environ.get("ADMIN_STATUS_TOKEN_HASH", "").strip()
    status = load_status()
    workflow = status.get("workflow") or {}
    sources = status.get("sources") or {}
    failures = [source_id for source_id, item in sorted(sources.items()) if not item.get("ok")]
    wp_sources = [source_id for source_id in sources if str(source_id).startswith("working-paper:")]
    low_confidence = sum(1 for record in records if (record.get("date_confidence") or "F") in {"D", "F", "unknown"})
    china_count = sum(1 for record in records if is_china_related(record))
    body = f"""<section class="section-head">
  <div><h2>线上后台状态</h2><p>GitHub Pages 无法提供真正登录鉴权；这里仅发布公开安全摘要，敏感审核仍使用本地后台。</p></div>
</section>
<section class="audit-grid">
  <div class="audit-card"><strong>{len(records)}</strong><span>累计监测记录</span></div>
  <div class="audit-card"><strong>{china_count}</strong><span>已确认中国相关</span></div>
  <div class="audit-card"><strong>{low_confidence}</strong><span>低可信日期样本</span></div>
  <div class="audit-card"><strong>{len(wp_sources)}</strong><span>工作论文来源状态</span></div>
  <div class="audit-card"><strong>{len(failures)}</strong><span>失败/受限来源</span></div>
  <div class="audit-card"><strong>{html_escape(beijing_stamp(workflow.get('finished_at')))}</strong><span>最近监测完成</span></div>
</section>
<section class="section-head"><div><h2>后续私有化建议</h2><p>如需知道具体访问者或登录后访问，建议部署到 Cloudflare Access / Vercel + Auth，而不是纯 GitHub Pages。</p></div></section>
<div class="empty">当前公开页只放聚合状态，不放 API key、审核 token、原始后台操作入口或访问者身份信息。</div>"""
    if not token_hash:
        return f"""<section class="section-head">
  <div><h2>线上后台状态</h2><p>尚未启用线上后台 token。为避免公开未成熟后台，当前只提供本地后台。</p></div>
</section>
<div class="gate">
  <h3>未启用公开后台</h3>
  <p>请继续使用本地后台：<code>local_admin/status.html</code> 和 <code>http://127.0.0.1:8765/</code>。</p>
  <p class="gate-note">若以后需要线上查看，可在 GitHub Secrets 设置 <code>ADMIN_STATUS_TOKEN_HASH</code> 后重新运行 workflow。注意：静态页面 token 只能防误点，不等于真正登录鉴权。</p>
</div>"""
    return f"""<div id="gate" class="gate">
  <h3>输入后台访问 token</h3>
  <p class="gate-note">这是静态页面轻保护，只用于避免普通访客误入；不应放敏感数据。</p>
  <input id="adminToken" type="password" placeholder="访问 token">
  <button id="unlockAdmin" type="button">进入</button>
  <p id="gateError" class="gate-note"></p>
</div>
<div id="adminContent" class="hidden">{body}</div>
<script>
async function sha256(text) {{
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
}}
async function unlock() {{
  const token = document.getElementById('adminToken').value || localStorage.getItem('epd_admin_token') || '';
  const hash = await sha256(token);
  if (hash === '{html_escape(token_hash)}') {{
    localStorage.setItem('epd_admin_token', token);
    document.getElementById('gate').classList.add('hidden');
    document.getElementById('adminContent').classList.remove('hidden');
  }} else {{
    document.getElementById('gateError').textContent = 'token 不正确。';
  }}
}}
document.getElementById('unlockAdmin').addEventListener('click', unlock);
if (localStorage.getItem('epd_admin_token')) unlock();
</script>"""


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    relative_parent = path.parent.relative_to(DOCS_DIR)
    depth = len(relative_parent.parts)
    page_base = "." if depth == 0 else "/".join([".."] * depth)
    write_text(path, content.replace(BASE, page_base))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    args = parser.parse_args()

    records = load_all_daily(args.daily_dir)
    today_records = [record for record in records if detected_date(record) == today_str()]
    latest_day = detected_date(records[0]) if records else today_str()
    home_flow_records = today_records or ([record for record in records if detected_date(record) == latest_day] if latest_day else [])
    home_flow_date = today_str() if today_records else latest_day
    write_page(
        args.docs_dir / "index.html",
        page(SITE_NAME, records, home_body(records, today_records), active="home", sidebar_records=home_flow_records, sidebar_date=home_flow_date),
    )
    write_page(
        args.docs_dir / "sources" / "working-papers" / "index.html",
        page(
            "工作论文来源",
            records,
            working_paper_sources_body(records),
            active="working-papers",
            sidebar_records=home_flow_records,
            sidebar_date=home_flow_date,
        ),
    )
    write_page(
        args.docs_dir / "quality" / "china-relevance" / "index.html",
        page(
            "中国相关判定抽检",
            records,
            china_quality_body(records),
            sidebar_records=home_flow_records,
            sidebar_date=home_flow_date,
        ),
    )
    write_page(
        args.docs_dir / "admin" / "status" / "index.html",
        page(
            "线上后台状态",
            records,
            admin_status_body(records),
            sidebar_records=home_flow_records,
            sidebar_date=home_flow_date,
        ),
    )
    wp_records = working_paper_records(records)
    write_page(
        args.docs_dir / "working-papers" / "index.html",
        page(
            "全部工作论文",
            records,
            working_papers_body(records),
            active="working-papers",
            sidebar_records=wp_records[:40] or home_flow_records,
            sidebar_date=home_flow_date,
        ),
    )
    write_page(
        args.docs_dir / "working-papers" / "today" / "index.html",
        page(
            "今日工作论文",
            records,
            working_papers_body(records, view="today"),
            active="working-papers",
            sidebar_records=[record for record in wp_records if detected_date(record) == today_str()][:40] or wp_records[:40] or home_flow_records,
            sidebar_date=today_str(),
        ),
    )
    write_page(
        args.docs_dir / "working-papers" / "recent7" / "index.html",
        page(
            "最近 7 天工作论文",
            records,
            working_papers_body(records, view="recent7"),
            active="working-papers",
            sidebar_records=recent_records(wp_records, 7)[:40] or wp_records[:40] or home_flow_records,
            sidebar_date=home_flow_date,
        ),
    )
    write_page(
        args.docs_dir / "working-papers" / "china" / "index.html",
        page(
            "与中国相关工作论文",
            records,
            working_papers_body(records, view="china"),
            active="working-papers",
            sidebar_records=[record for record in wp_records if is_public_china_related(record)][:40] or wp_records[:40] or home_flow_records,
            sidebar_date=home_flow_date,
        ),
    )

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_journal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_date[detected_date(record) or record.get("_daily_date") or "unknown"].append(record)
        if not is_working_paper(record):
            by_journal[record.get("journal_id") or "unknown"].append(record)
        for field in record.get("fields", []) or ["unknown"]:
            by_field[field].append(record)
        for topic in article_topics(record):
            by_topic[topic].append(record)

    archive_links = []
    for daily_date, daily_records in sorted(by_date.items(), reverse=True):
        body = (
            f'<section class="section-head"><div><h2>{html_escape(daily_date)} 监测记录</h2>'
            f'<p>支持按期刊、主题、日期类型、可信度和“与中国相关”筛选。</p></div></section>'
            f'{filter_toolbar(daily_records)}{paper_events(daily_records)}{FILTER_SCRIPT}'
        )
        write_page(
            args.docs_dir / "daily" / daily_date / "index.html",
            page(f"{daily_date} 归档", records, body, active="archive", sidebar_records=daily_records, sidebar_date=daily_date),
        )
        archive_links.append(f'<li><a href="{BASE}/daily/{html_escape(daily_date)}/">{html_escape(daily_date)}</a> ({len(daily_records)})</li>')

    journals = load_journals(DATA_DIR / "journals.yml")
    journals_by_id = {journal["id"]: journal for journal in journals}
    for journal_id, journal_records in by_journal.items():
        title = str(journal_records[0].get("journal") or journals_by_id.get(journal_id, {}).get("title") or journal_id)
        latest_journal_date = detected_date(journal_records[0]) if journal_records else None
        latest_journal_records = [record for record in journal_records if detected_date(record) == latest_journal_date] if latest_journal_date else []
        view_links = journal_view_links(journal_id, journal_records, today_records)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该期刊历史发现记录。</p></div></section>{view_links}{filter_toolbar(journal_records)}{paper_events(journal_records)}{FILTER_SCRIPT}'
        write_page(
            args.docs_dir / "journals" / journal_id / "index.html",
            page(title, records, body, sidebar_records=latest_journal_records, sidebar_date=latest_journal_date),
        )
        recent = recent_records(journal_records, 7)
        recent_body = f'<section class="section-head"><div><h2>{html_escape(title)}：最近 7 天</h2><p>按该期刊最近有记录日期向前滚动 7 天。</p></div><p>{len(recent)} 篇</p></section>{view_links}{filter_toolbar(recent)}{paper_events(recent)}{FILTER_SCRIPT}'
        write_page(
            args.docs_dir / "journals" / journal_id / "recent7" / "index.html",
            page(f"{title} 最近 7 天", records, recent_body, sidebar_records=latest_journal_records, sidebar_date=latest_journal_date),
        )

    for journal in journals:
        if journal["id"] in by_journal:
            continue
        title = str(journal.get("title") or journal["id"])
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该期刊暂无有效论文记录。</p></div></section>{paper_events([])}'
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
    journals_body = f"""<section class="section-head"><div><h2>监测期刊</h2><p>当前监测清单共 {len(journals)} 本期刊。优先级仅用于抓取频率，不在公开页面展示。</p></div></section>
<table class="journal-table"><thead><tr><th>期刊</th><th>缩写</th><th>领域</th><th>ISSN</th><th>出版社</th></tr></thead><tbody>{"".join(journal_rows)}</tbody></table>"""
    write_page(args.docs_dir / "journals" / "index.html", page("监测期刊", records, journals_body))

    for field, field_records in by_field.items():
        title = field_label(field)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该领域历史发现记录。</p></div></section>{filter_toolbar(field_records)}{paper_events(field_records)}{FILTER_SCRIPT}'
        write_page(args.docs_dir / "fields" / field / "index.html", page(title, records, body))

    for topic, topic_records in by_topic.items():
        title = topic_label(topic)
        note = "基于规则、AI 判定和人工确认的中国相关记录。" if topic == "china" else "基于标题、摘要和期刊信息生成的文章主题标签。"
        topic_links = topic_view_links(topic, topic_records, today_records)
        latest_topic_date = detected_date(topic_records[0]) if topic_records else None
        latest_topic_records = [record for record in topic_records if detected_date(record) == latest_topic_date] if latest_topic_date else []
        body = (
            china_topic_body(records, topic_records, today_records)
            if topic == "china"
            else f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>{html_escape(note)}</p></div><p>{len(topic_records)} 篇</p></section>{topic_links}{filter_toolbar(topic_records)}{paper_events(topic_records)}{FILTER_SCRIPT}'
        )
        write_page(
            args.docs_dir / "topics" / topic / "index.html",
            page(title, records, body, sidebar_records=latest_topic_records, sidebar_date=latest_topic_date),
        )
        recent = recent_records(topic_records, 7)
        recent_body = (
            china_topic_body(records, recent, today_records)
            if topic == "china"
            else f'<section class="section-head"><div><h2>{html_escape(title)}：最近 7 天</h2><p>{html_escape(note)}</p></div><p>{len(recent)} 篇</p></section>{topic_links}{filter_toolbar(recent)}{paper_events(recent)}{FILTER_SCRIPT}'
        )
        write_page(
            args.docs_dir / "topics" / topic / "recent7" / "index.html",
            page(f"{title} 最近 7 天", records, recent_body, sidebar_records=latest_topic_records, sidebar_date=latest_topic_date),
        )

    archive_body = '<section class="section-head"><div><h2>历史归档</h2><p>按本站首次监测日期整理。</p></div></section><ul class="archive-list">' + "\n".join(archive_links) + "</ul>"
    write_page(args.docs_dir / "archive" / "index.html", page("历史归档", records, archive_body, active="archive"))
    print(f"rendered {len(records)} records into {args.docs_dir}")


if __name__ == "__main__":
    main()
