"""Render the production static public site into docs/."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from common import DATA_DIR, DOCS_DIR, html_escape, read_json, today_str


SITE_NAME = "Econ Papers Daily"
SITE_SUBTITLE = "经济学论文速递"
BASE = "/docs"

FIELD_LABELS = {
    "general": "综合",
    "development": "发展",
    "agriculture_environment_resource": "农业/环境/资源",
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


STYLE = """
:root{color-scheme:light;--ink:#1f2328;--muted:#656d76;--line:#d0d7de;--soft:#f6f8fa;--panel:#ffffff;--blue:#0969da;--blue-soft:#ddf4ff;--accent:#8250df;--warn:#9a6700}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.55}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.shell{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:100vh}
.sidebar{background:var(--soft);border-right:1px solid var(--line);padding:24px;position:sticky;top:0;height:100vh;overflow:auto}
.brand{font-size:22px;font-weight:800;letter-spacing:0;margin:0}.subtitle{color:var(--muted);font-size:14px;margin:4px 0 22px}
.side-block{margin:22px 0}.side-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;margin-bottom:8px}
.side-link{display:flex;justify-content:space-between;gap:12px;border-radius:6px;padding:7px 9px;color:var(--ink);font-size:14px}.side-link:hover{background:#fff;text-decoration:none}.side-link span{color:var(--muted)}
.content{min-width:0}.topbar{border-bottom:1px solid var(--line);background:#fff}.topbar-inner{max-width:1180px;margin:0 auto;padding:18px 30px;display:flex;justify-content:space-between;align-items:center;gap:20px}
.nav a{margin-left:18px;color:var(--muted);font-size:14px}.nav a.active,.nav a:hover{color:var(--blue);text-decoration:none}
.wrap{max-width:1180px;margin:0 auto;padding:26px 30px 48px}
.banner{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:linear-gradient(135deg,#f6f8fa 0%,#fff 52%,#ddf4ff 100%);display:grid;grid-template-columns:1fr 260px;min-height:168px}
.banner-main{padding:26px 28px}.eyebrow{color:var(--blue);font-size:13px;font-weight:700;margin:0 0 8px}.banner h1{font-size:34px;line-height:1.18;margin:0 0 10px}.banner p{color:var(--muted);max-width:720px;margin:0}
.signal{border-left:1px solid var(--line);padding:24px;background:rgba(255,255,255,.55);display:flex;flex-direction:column;justify-content:center;gap:10px}.signal-row{display:flex;justify-content:space-between;gap:16px;color:var(--muted);font-size:13px}.signal-row strong{color:var(--ink)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px;margin:20px 0}.stat{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:14px}.stat strong{display:block;font-size:26px;line-height:1.1}.stat span{font-size:13px;color:var(--muted)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 8px}.control{border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--muted);padding:8px 10px;font-size:14px}.control.primary{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding-bottom:10px;margin-top:26px}.section-head h2{font-size:20px;margin:0}.section-head p{margin:0;color:var(--muted);font-size:14px}
.event{display:grid;grid-template-columns:88px minmax(0,1fr);gap:18px;border-bottom:1px solid var(--line);padding:18px 0}.time{font-weight:700;color:var(--blue);font-size:14px}.date-note{color:var(--muted);font-size:12px;margin-top:2px}.event h3{font-size:18px;line-height:1.35;margin:0 0 6px}.authors{color:var(--muted);margin:0 0 7px}.meta{display:flex;flex-wrap:wrap;gap:7px;color:var(--muted);font-size:13px}.pill{border:1px solid var(--line);background:var(--soft);border-radius:999px;padding:2px 7px}.doi{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.empty{border:1px dashed var(--line);border-radius:8px;padding:28px;color:var(--muted);background:var(--soft)}
.archive-list{padding-left:18px}.archive-list li{margin:8px 0}
@media(max-width:920px){.shell{display:block}.sidebar{position:static;height:auto}.topbar-inner{display:block}.nav{margin-top:10px}.nav a{margin:0 16px 0 0}.banner{display:block}.signal{border-left:0;border-top:1px solid var(--line)}.stats{grid-template-columns:repeat(2,1fr)}.event{grid-template-columns:1fr}}
"""


def field_label(field: str) -> str:
    return FIELD_LABELS.get(field, field.replace("_", " "))


def record_url(record: dict[str, Any]) -> str:
    return record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#")


def authors(record: dict[str, Any], limit: int = 5) -> str:
    names = record.get("authors") or []
    if len(names) > limit:
        return ", ".join(names[:limit]) + " 等"
    return ", ".join(names)


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
    detected = str(record.get("detected_at") or "")
    return detected[:10] if len(detected) >= 10 else record.get("_daily_date") or ""


def detected_time(record: dict[str, Any]) -> str:
    detected = str(record.get("detected_at") or "")
    if "T" in detected and len(detected) >= 16:
        return detected.split("T", 1)[1][:5]
    return "发现"


def stats(records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> dict[str, Any]:
    today_journals = {record.get("journal_id") for record in today_records if record.get("journal_id")}
    all_journals = {record.get("journal_id") for record in records if record.get("journal_id")}
    sources = {record.get("source") for record in records if record.get("source")}
    last_seen = max((record.get("detected_at") or "" for record in records), default="")
    return {
        "today": len(today_records),
        "today_journals": len(today_journals),
        "all_records": len(records),
        "all_journals": len(all_journals),
        "sources": len(sources),
        "last_seen": last_seen.replace("T", " ")[:16] if last_seen else "暂无",
    }


def sidebar(records: list[dict[str, Any]]) -> str:
    field_counts = Counter(field for record in records for field in record.get("fields", []))
    journal_counts = Counter(record.get("journal_short") or record.get("journal") for record in records)
    fields = "".join(
        f'<a class="side-link" href="{BASE}/fields/{html_escape(field)}/"><strong>{html_escape(field_label(field))}</strong><span>{count}</span></a>'
        for field, count in field_counts.most_common(12)
    )
    journals = "".join(
        f'<a class="side-link" href="#"><strong>{html_escape(str(journal))}</strong><span>{count}</span></a>'
        for journal, count in journal_counts.most_common(10)
        if journal
    )
    return f"""<aside class="sidebar">
  <h1 class="brand">{SITE_NAME}</h1>
  <div class="subtitle">{SITE_SUBTITLE}</div>
  <div class="side-block"><div class="side-title">导航</div>
    <a class="side-link" href="{BASE}/"><strong>今日速递</strong><span>Today</span></a>
    <a class="side-link" href="{BASE}/archive/"><strong>历史归档</strong><span>Archive</span></a>
    <a class="side-link" href="{BASE}/previews/"><strong>主题预览</strong><span>Preview</span></a>
  </div>
  <div class="side-block"><div class="side-title">领域</div>{fields}</div>
  <div class="side-block"><div class="side-title">期刊</div>{journals}</div>
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
          <a class="{ 'active' if active == 'archive' else '' }" href="{nav['archive']}">归档</a>
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
        fields = "".join(f'<span class="pill">{html_escape(field_label(field))}</span>' for field in record.get("fields", [])[:3])
        doi = f'<span class="pill doi">{html_escape(record.get("doi"))}</span>' if record.get("doi") else ""
        official_date = f'<span class="pill">官方日期 {html_escape(record.get("published_online"))}</span>' if record.get("published_online") else ""
        chunks.append(
            f"""<article class="event">
  <div><div class="time">{html_escape(detected_time(record))}</div><div class="date-note">{html_escape(detected_date(record))}</div></div>
  <div>
    <h3><a href="{html_escape(record_url(record))}">{html_escape(record.get('title'))}</a></h3>
    <p class="authors">{html_escape(authors(record))}</p>
    <div class="meta"><span class="pill">{html_escape(record.get('journal_short') or record.get('journal'))}</span><span class="pill">{html_escape(record.get('source'))}</span>{official_date}{fields}{doi}</div>
  </div>
</article>"""
        )
    return "\n".join(chunks)


def home_body(records: list[dict[str, Any]], today_records: list[dict[str, Any]]) -> str:
    s = stats(records, today_records)
    return f"""<section class="banner">
  <div class="banner-main">
    <p class="eyebrow">Today&apos;s economics papers</p>
    <h1>{SITE_NAME}</h1>
    <p>{SITE_SUBTITLE}：按发现时间追踪重点经济学期刊、工作论文与预印本来源。首页只展示今天新发现的论文，历史记录进入归档。</p>
  </div>
  <div class="signal">
    <div class="signal-row"><span>排序依据</span><strong>发现时间</strong></div>
    <div class="signal-row"><span>最后检测</span><strong>{html_escape(s['last_seen'])}</strong></div>
    <div class="signal-row"><span>数据来源</span><strong>Crossref / RSS</strong></div>
  </div>
</section>
<section class="stats">
  <div class="stat"><strong>{s['today']}</strong><span>今日新发现</span></div>
  <div class="stat"><strong>{s['today_journals']}</strong><span>今日涉及期刊</span></div>
  <div class="stat"><strong>{s['all_records']}</strong><span>当前索引记录</span></div>
  <div class="stat"><strong>{s['sources']}</strong><span>启用来源类型</span></div>
</section>
<div class="toolbar"><span class="control">搜索标题/作者</span><span class="control">筛选期刊</span><span class="control">筛选领域</span><a class="control primary" href="{BASE}/feed.xml">RSS 订阅</a></div>
<section class="section-head"><div><h2>今日论文流</h2><p>按本站发现时间倒序排列。</p></div><p>{html_escape(today_str())}</p></section>
<div class="empty">说明：首次建库当天会把抓取窗口内尚未见过的论文都记为“新发现”。后续定时运行后，这里会变成真正的当天增量流。</div>
{paper_events(today_records)}
"""


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    for record in records:
        by_date[record.get("_daily_date") or detected_date(record) or "unknown"].append(record)
        by_journal[record.get("journal_id") or "unknown"].append(record)
        for field in record.get("fields", []) or ["unknown"]:
            by_field[field].append(record)

    archive_links = []
    for daily_date, daily_records in sorted(by_date.items(), reverse=True):
        body = f'<section class="section-head"><div><h2>{html_escape(daily_date)} 发现记录</h2><p>按发现时间倒序排列。</p></div></section>{paper_events(daily_records)}'
        write_page(args.docs_dir / "daily" / daily_date / "index.html", page(f"{daily_date} 归档", records, body, active="archive"))
        archive_links.append(f'<li><a href="{BASE}/daily/{html_escape(daily_date)}/">{html_escape(daily_date)}</a> ({len(daily_records)})</li>')

    for journal_id, journal_records in by_journal.items():
        title = str(journal_records[0].get("journal") or journal_id)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该期刊历史发现记录。</p></div></section>{paper_events(journal_records)}'
        write_page(args.docs_dir / "journals" / journal_id / "index.html", page(title, records, body))

    for field, field_records in by_field.items():
        title = field_label(field)
        body = f'<section class="section-head"><div><h2>{html_escape(title)}</h2><p>该领域历史发现记录。</p></div></section>{paper_events(field_records)}'
        write_page(args.docs_dir / "fields" / field / "index.html", page(title, records, body))

    archive_body = '<section class="section-head"><div><h2>历史归档</h2><p>按本站首次发现日期整理。</p></div></section><ul class="archive-list">' + "\n".join(archive_links) + "</ul>"
    write_page(args.docs_dir / "archive" / "index.html", page("历史归档", records, archive_body, active="archive"))
    print(f"rendered {len(records)} records into {args.docs_dir}")


if __name__ == "__main__":
    main()
