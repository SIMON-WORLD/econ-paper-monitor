"""Render three visual theme previews for the public paper monitor site."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, DOCS_DIR, html_escape, read_json
from render_site import load_all_daily, write_page


BASE = "/docs/previews"
LIMIT = 36


def link_for(record: dict[str, Any]) -> str:
    return record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#")


def authors(record: dict[str, Any], limit: int = 4) -> str:
    names = record.get("authors") or []
    if len(names) > limit:
        return ", ".join(names[:limit]) + " 等"
    return ", ".join(names)


def field_label(field: str) -> str:
    labels = {
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
    }
    return labels.get(field, field.replace("_", " "))


def stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    journals = Counter(record.get("journal_short") or record.get("journal") for record in records)
    fields = Counter(field for record in records for field in record.get("fields", []))
    dates = Counter(record.get("published_online") or "未知日期" for record in records)
    return {
        "papers": len(records),
        "journals": len(journals),
        "fields": len(fields),
        "latest_date": max(dates) if dates else "暂无",
        "top_journals": journals.most_common(8),
        "top_fields": fields.most_common(10),
    }


def shell(title: str, style: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>{style}</style>
</head>
<body>{body}</body>
</html>
"""


def preview_nav(active: str) -> str:
    items = [
        ("minimal-mistakes", "Minimal Mistakes"),
        ("papermod", "PaperMod"),
        ("hybrid", "混合推荐版"),
    ]
    return "".join(
        f'<a class="{ "active" if key == active else "" }" href="{BASE}/{key}/">{html_escape(label)}</a>'
        for key, label in items
    )


def render_minimal_mistakes(records: list[dict[str, Any]]) -> str:
    s = stats(records)
    paper_cards = []
    for record in records[:LIMIT]:
        tags = "".join(f"<span>{html_escape(field_label(field))}</span>" for field in record.get("fields", [])[:3])
        paper_cards.append(
            f"""<article class="archive-item">
  <p class="type">{html_escape(record.get('journal_short') or record.get('journal'))} · {html_escape(record.get('published_online'))}</p>
  <h2><a href="{html_escape(link_for(record))}">{html_escape(record.get('title'))}</a></h2>
  <p class="authors">{html_escape(authors(record))}</p>
  <div class="tags">{tags}</div>
</article>"""
        )
    style = """
:root{--ink:#263238;--muted:#66757f;--line:#e0e6eb;--soft:#f6f8fa;--accent:#2f6f8f}
body{margin:0;font-family:Georgia,"Times New Roman",serif;color:var(--ink);background:#fff;line-height:1.6}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.masthead{border-bottom:1px solid var(--line);background:#fff}.masthead-inner{max-width:1180px;margin:0 auto;padding:18px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px}
.brand{font-family:Arial,sans-serif;font-weight:700;font-size:22px}.nav a{font-family:Arial,sans-serif;margin-left:18px;color:var(--muted)}.nav a.active{color:var(--ink);font-weight:700}
.hero{background:var(--soft);border-bottom:1px solid var(--line)}.hero-inner{max-width:1180px;margin:0 auto;padding:34px 28px}
.hero h1{font-size:38px;margin:0 0 8px}.hero p{max-width:760px;margin:0;color:var(--muted);font-family:Arial,sans-serif}
.layout{max-width:1180px;margin:0 auto;padding:30px 28px;display:grid;grid-template-columns:260px 1fr;gap:36px}
.sidebar{font-family:Arial,sans-serif;color:var(--muted);font-size:14px}.box{border-top:3px solid var(--accent);padding-top:14px;margin-bottom:26px}.metric{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:8px 0}
.archive-item{padding:22px 0;border-bottom:1px solid var(--line)}.archive-item .type{font-family:Arial,sans-serif;color:var(--muted);font-size:13px;margin:0 0 4px}.archive-item h2{font-size:23px;line-height:1.25;margin:0 0 8px}.authors{font-family:Arial,sans-serif;color:var(--muted);margin:0 0 10px}
.tags{display:flex;gap:8px;flex-wrap:wrap}.tags span{font-family:Arial,sans-serif;background:var(--soft);border:1px solid var(--line);border-radius:3px;padding:2px 7px;font-size:12px;color:var(--muted)}
@media(max-width:780px){.masthead-inner{display:block}.nav{margin-top:10px}.nav a{margin:0 14px 0 0}.layout{display:block}.hero h1{font-size:30px}}
"""
    sidebar = f"""<aside class="sidebar">
  <div class="box">
    <div class="metric"><span>论文</span><strong>{s['papers']}</strong></div>
    <div class="metric"><span>期刊</span><strong>{s['journals']}</strong></div>
    <div class="metric"><span>领域</span><strong>{s['fields']}</strong></div>
  </div>
  <div class="box"><strong>高频领域</strong>{"".join(f'<div class="metric"><span>{html_escape(field_label(k))}</span><span>{v}</span></div>' for k, v in s['top_fields'][:6])}</div>
</aside>"""
    body = f"""<header class="masthead"><div class="masthead-inner"><div class="brand">经济学论文雷达</div><nav class="nav">{preview_nav('minimal-mistakes')}</nav></div></header>
<section class="hero"><div class="hero-inner"><h1>最新论文归档</h1><p>参考 Minimal Mistakes 的学术归档气质：页面更像正式研究资料库，适合按日期、期刊、领域长期沉淀。</p></div></section>
<main class="layout">{sidebar}<section>{"".join(paper_cards)}</section></main>"""
    return shell("Minimal Mistakes 预览", style, body)


def render_papermod(records: list[dict[str, Any]]) -> str:
    s = stats(records)
    items = []
    for record in records[:LIMIT]:
        items.append(
            f"""<article class="post">
  <header><h2><a href="{html_escape(link_for(record))}">{html_escape(record.get('title'))}</a></h2></header>
  <p class="summary">{html_escape(authors(record))}</p>
  <footer>{html_escape(record.get('journal_short') or record.get('journal'))} · {html_escape(record.get('published_online'))} · {html_escape(", ".join(field_label(f) for f in record.get("fields", [])[:2]))}</footer>
</article>"""
        )
    style = """
:root{--theme:#fff;--entry:#fff;--primary:#1d1d1f;--secondary:#6b7280;--border:#e5e7eb;--accent:#2563eb}
body{margin:0;background:var(--theme);color:var(--primary);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.6}
a{color:inherit;text-decoration:none}a:hover{color:var(--accent)}
.top{max-width:920px;margin:0 auto;padding:22px 22px;display:flex;align-items:center;justify-content:space-between}.logo{font-weight:700;font-size:22px}.nav a{margin-left:18px;color:var(--secondary);font-size:14px}.nav a.active{color:var(--primary);font-weight:600}
.home{max-width:920px;margin:0 auto;padding:38px 22px 18px}.home h1{font-size:42px;line-height:1.15;margin:0 0 12px}.home p{font-size:17px;color:var(--secondary);max-width:680px;margin:0}.chips{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}.chip{border:1px solid var(--border);border-radius:999px;padding:6px 12px;color:var(--secondary);font-size:14px}
.feed{max-width:920px;margin:0 auto;padding:0 22px 46px}.post{border:1px solid var(--border);border-radius:8px;padding:18px 20px;margin:14px 0;background:var(--entry)}.post h2{font-size:22px;line-height:1.3;margin:0 0 8px}.summary{margin:0 0 10px;color:var(--secondary)}.post footer{font-size:13px;color:var(--secondary)}
@media(max-width:720px){.top{display:block}.nav{margin-top:10px}.nav a{margin:0 14px 0 0}.home h1{font-size:32px}}
"""
    body = f"""<header class="top"><div class="logo">经济学论文雷达</div><nav class="nav">{preview_nav('papermod')}</nav></header>
<section class="home"><h1>今天有哪些经济学论文值得先看？</h1><p>参考 Hugo PaperMod 的极简阅读流：少装饰、强标题、适合手机阅读和每日快速浏览。</p>
<div class="chips"><span class="chip">{s['papers']} 篇记录</span><span class="chip">{s['journals']} 本期刊</span><span class="chip">最新日期 {html_escape(s['latest_date'])}</span></div></section>
<main class="feed">{"".join(items)}</main>"""
    return shell("PaperMod 预览", style, body)


def render_hybrid(records: list[dict[str, Any]]) -> str:
    s = stats(records)
    entries = []
    for record in records[:LIMIT]:
        entries.append(
            f"""<article class="row">
  <div class="date">{html_escape(record.get('published_online'))}</div>
  <div class="main">
    <h3><a href="{html_escape(link_for(record))}">{html_escape(record.get('title'))}</a></h3>
    <p>{html_escape(authors(record))}</p>
    <div class="meta">{html_escape(record.get('journal_short') or record.get('journal'))} · {html_escape(record.get('source'))} · {html_escape(record.get('doi') or '')}</div>
  </div>
</article>"""
        )
    field_links = "".join(
        f'<a href="/docs/fields/{html_escape(k)}/">{html_escape(field_label(k))}<span>{v}</span></a>'
        for k, v in s["top_fields"][:10]
    )
    journal_links = "".join(
        f'<a href="#">{html_escape(k)}<span>{v}</span></a>'
        for k, v in s["top_journals"][:8]
        if k
    )
    style = """
:root{--ink:#172026;--muted:#667085;--line:#d7dde3;--panel:#f7f9fb;--accent:#0f766e;--warn:#b45309}
body{margin:0;font-family:Inter,"Segoe UI",Arial,sans-serif;color:var(--ink);background:#fff;line-height:1.55}
a{color:inherit;text-decoration:none}a:hover{color:var(--accent)}
.app{display:grid;grid-template-columns:260px 1fr;min-height:100vh}.side{background:var(--panel);border-right:1px solid var(--line);padding:24px;position:sticky;top:0;height:100vh;box-sizing:border-box}.brand{font-size:22px;font-weight:800;margin-bottom:8px}.hint{color:var(--muted);font-size:14px;margin-bottom:24px}.nav a{display:flex;justify-content:space-between;border-radius:6px;padding:8px 10px;color:var(--muted)}.nav a:hover,.nav a.active{background:#fff;color:var(--ink)}.nav span{color:var(--accent)}
.content{padding:28px 34px}.preview-nav{display:flex;gap:16px;margin-bottom:24px}.preview-nav a{color:var(--muted)}.preview-nav a.active{font-weight:700;color:var(--ink)}
.hero{border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:20px}.hero h1{font-size:34px;margin:0 0 8px}.hero p{max-width:780px;color:var(--muted);margin:0}.stats{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:12px;margin:20px 0}.stat{border:1px solid var(--line);border-radius:8px;padding:14px;background:#fff}.stat strong{display:block;font-size:24px}.stat span{color:var(--muted);font-size:13px}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}.input,.button{border:1px solid var(--line);border-radius:6px;padding:9px 11px;color:var(--muted);background:#fff}.button{color:var(--ink);font-weight:600}
.row{display:grid;grid-template-columns:110px 1fr;gap:18px;border-top:1px solid var(--line);padding:18px 0}.date{color:var(--warn);font-weight:700;font-size:13px}.row h3{margin:0 0 5px;font-size:18px;line-height:1.32}.row p{margin:0 0 6px;color:var(--muted)}.meta{font-size:13px;color:var(--muted)}
@media(max-width:860px){.app{display:block}.side{position:static;height:auto}.content{padding:22px}.stats{grid-template-columns:repeat(2,1fr)}.row{grid-template-columns:1fr}.date{font-size:12px}}
"""
    body = f"""<div class="app">
<aside class="side"><div class="brand">经济学论文雷达</div><div class="hint">Just the Docs 的导航结构 + Minimal Mistakes 的归档气质。</div><nav class="nav">{field_links}</nav><hr><nav class="nav">{journal_links}</nav></aside>
<main class="content"><nav class="preview-nav">{preview_nav('hybrid')}</nav><section class="hero"><h1>可筛选的经济学论文工作台</h1><p>这个版本更接近最终产品：左侧是领域/期刊索引，右侧是今日论文流，顶部保留数据状态和后续筛选入口。</p></section>
<section class="stats"><div class="stat"><strong>{s['papers']}</strong><span>论文记录</span></div><div class="stat"><strong>{s['journals']}</strong><span>覆盖期刊</span></div><div class="stat"><strong>{s['fields']}</strong><span>领域索引</span></div><div class="stat"><strong>{html_escape(s['latest_date'])}</strong><span>最新发布日期</span></div></section>
<div class="toolbar"><span class="input">搜索标题/作者</span><span class="input">选择期刊</span><span class="input">选择领域</span><span class="button">RSS 订阅</span></div>
{"".join(entries)}</main></div>"""
    return shell("混合推荐版预览", style, body)


def render_preview_index() -> str:
    style = """
body{margin:0;font-family:Inter,"Segoe UI",Arial,sans-serif;color:#172026;background:#f7f9fb;line-height:1.6}.wrap{max-width:980px;margin:0 auto;padding:42px 24px}h1{font-size:34px;margin:0 0 10px}p{color:#667085}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:26px}.card{background:#fff;border:1px solid #d7dde3;border-radius:8px;padding:18px}a{color:#0f766e;text-decoration:none;font-weight:700}.note{margin-top:24px;font-size:14px}
"""
    body = """<main class="wrap"><h1>经济学论文雷达：主题预览</h1><p>三套页面都使用同一批真实抓取数据，仅比较信息架构和视觉风格。</p><section class="grid">
<article class="card"><h2>Minimal Mistakes 气质</h2><p>学术归档、期刊索引、长期沉淀感更强。</p><a href="/docs/previews/minimal-mistakes/">查看预览</a></article>
<article class="card"><h2>Hugo PaperMod 气质</h2><p>极简阅读流，适合每日快速浏览和移动端。</p><a href="/docs/previews/papermod/">查看预览</a></article>
<article class="card"><h2>混合推荐版</h2><p>左侧导航 + 数据仪表盘 + 论文列表，更像论文雷达工作台。</p><a href="/docs/previews/hybrid/">查看预览</a></article>
</section><p class="note">这些是 HTML/CSS 样张，不直接复制第三方主题源码；确定方向后再把主站改成正式版本。</p></main>"""
    return shell("主题预览", style, body)


def main() -> None:
    records = load_all_daily(DATA_DIR / "daily")
    out = DOCS_DIR / "previews"
    write_page(out / "index.html", render_preview_index())
    write_page(out / "minimal-mistakes" / "index.html", render_minimal_mistakes(records))
    write_page(out / "papermod" / "index.html", render_papermod(records))
    write_page(out / "hybrid" / "index.html", render_hybrid(records))
    print(f"rendered theme previews from {len(records)} records")


if __name__ == "__main__":
    main()
