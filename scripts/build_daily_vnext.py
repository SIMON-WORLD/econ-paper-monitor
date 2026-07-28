"""Build the isolated Daily Door vNext prototype from canonical daily records."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "daily"
OUT_DIR = ROOT / "docs" / "daily-vnext"
ASSET_DIR = ROOT / "docs" / "assets"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def is_working(record: dict) -> bool:
    return record.get("source_type") in {"working_paper", "policy_paper", "aggregator"} or record.get("source") == "working_papers"


def topics(record: dict) -> list[str]:
    values = record.get("fields") or record.get("topics") or []
    if isinstance(values, str):
        values = [values]
    return [str(value) for value in values if value]


def detected_at(record: dict) -> str:
    return str(record.get("detected_at") or record.get("detected") or "")


def display_time(record: dict) -> str:
    raw = detected_at(record)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError:
        return raw[11:16] if len(raw) >= 16 else "--:--"


def author_text(record: dict) -> str:
    authors = record.get("authors") or []
    if isinstance(authors, str):
        return authors
    return ", ".join(str(author) for author in authors if author) or "作者信息待补"


def load_latest() -> tuple[str, list[dict]]:
    paths = sorted(DATA_DIR.glob("*.json"), reverse=True)
    if not paths:
        return "", []
    latest = paths[0]
    records = json.loads(latest.read_text(encoding="utf-8"))
    records = sorted(records, key=detected_at, reverse=True)
    return latest.stem, records


def paper_markup(record: dict) -> str:
    working = is_working(record)
    china = str(record.get("china_relevance_status") or "").lower() in {"confirmed", "likely", "true"}
    title = record.get("title") or "未命名记录"
    title_zh = record.get("title_zh") or ""
    source = record.get("journal") or record.get("source") or "来源待补"
    source_kind = "工作论文" if working else "期刊论文"
    official = record.get("available_online") or record.get("published_online") or record.get("issue_date") or "日期待补"
    topic_markup = "".join(f'<span class="tag">{esc(topic)}</span>' for topic in topics(record))
    if china:
        topic_markup += '<span class="tag tag-china">与中国相关</span>'
    original = record.get("url") or record.get("source_url") or "#"
    doi = record.get("doi") or ""
    return f'''
      <article class="paper-entry" data-kind="{'working' if working else 'journal'}" data-china="{'true' if china else 'false'}" data-search="{esc(' '.join(str(record.get(key) or '') for key in ('title','title_zh','authors','journal','doi'))).lower()}">
        <div class="paper-time"><time>{esc(display_time(record))}</time><span>{esc(latest_date)}</span></div>
        <div class="paper-body">
          <div class="paper-kicker"><span>{esc(source_kind)}</span><span>{esc(source)}</span></div>
          <h3><a href="{esc(original)}" target="_blank" rel="noreferrer">{esc(title_zh or title)}</a></h3>
          {f'<p class="english-title">{esc(title)}</p>' if title_zh else ''}
          <p class="authors">{esc(author_text(record))}</p>
          <div class="paper-foot"><div class="tags">{topic_markup}</div><a class="read-link" href="{esc(original)}" target="_blank" rel="noreferrer">打开原文 <span aria-hidden="true">↗</span></a></div>
          <details class="paper-details"><summary>查看来源与日期</summary><p>官方日期：{esc(official)} · 首次监测：{esc(detected_at(record)[:10]) or '待补'}{f' · DOI：{esc(doi)}' if doi else ''}</p></details>
        </div>
      </article>'''


def build() -> None:
    global latest_date
    latest_date, records = load_latest()
    latest_date = latest_date or datetime.now().strftime("%Y-%m-%d")
    journal_count = sum(not is_working(record) for record in records)
    working_count = sum(is_working(record) for record in records)
    china_count = sum(str(record.get("china_relevance_status") or "").lower() in {"confirmed", "likely", "true"} for record in records)
    latest_seen = max((detected_at(record) for record in records), default="")
    latest_seen_label = latest_seen.replace("T", " ")[:16] or "待更新"
    papers = "\n".join(paper_markup(record) for record in records)
    html_doc = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Econ Papers Daily：每日追踪 TOP 经济学期刊与重要工作论文，沿时间流发现新的研究。">
  <link rel="canonical" href="https://academic-door.github.io/econ-paper-monitor/daily-vnext/">
  <link rel="icon" type="image/png" href="../assets/academic-door-logo.png">
  <title>Daily Door · Econ Papers Daily</title>
  <style>
    :root{{--paper:#f4f1ea;--ink:#202426;--muted:#6f716d;--line:#d8d3c9;--blue:#1d5f83;--blue-deep:#16445e;--red:#a94236;--white:#fbfaf7;--mono:"IBM Plex Mono",Consolas,monospace;--serif:Georgia,"Noto Serif SC","Songti SC",serif;--sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.6}}a{{color:inherit;text-decoration:none}}a:focus-visible,button:focus-visible,summary:focus-visible{{outline:3px solid #84b8d3;outline-offset:4px}}.skip{{position:absolute;left:1rem;top:-3rem;background:var(--blue-deep);color:#fff;padding:.6rem 1rem;z-index:5}}.skip:focus{{top:1rem}}
    .site-header{{border-bottom:1px solid var(--line);background:rgba(244,241,234,.94);position:sticky;top:0;z-index:3;backdrop-filter:blur(12px)}}.header-inner{{max-width:1280px;margin:auto;padding:1rem 2rem;display:flex;align-items:center;gap:2rem}}.wordmark{{font-family:var(--serif);font-size:1.2rem;white-space:nowrap}}.wordmark small{{display:block;font:600 .66rem var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--blue)}}.nav{{display:flex;gap:1.4rem;margin-left:auto;font-size:.88rem;color:var(--muted)}}.nav a:hover{{color:var(--blue)}}.presence{{font-size:.76rem;white-space:nowrap;color:var(--muted)}}.presence::before{{content:"";display:inline-block;width:.45rem;height:.45rem;border-radius:50%;background:#3e8b61;margin-right:.4rem;vertical-align:1px}}.menu{{display:none;border:0;background:none;font-size:1.3rem}}
    .page{{max-width:1280px;margin:auto;padding:0 2rem}}.hero{{min-height:470px;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr);gap:5rem;align-items:end;padding:7rem 0 5rem;border-bottom:1px solid var(--line)}}.eyebrow{{color:var(--blue);font:600 .75rem var(--mono);letter-spacing:.16em}}h1{{font:400 clamp(3.8rem,9vw,8rem)/.9 var(--serif);letter-spacing:-.04em;margin:1.2rem 0 1.5rem;max-width:760px}}.hero-lede{{font:400 1.25rem/1.55 var(--serif);max-width:560px;margin:0}}.hero-side{{border-left:1px solid var(--line);padding-left:2rem;padding-bottom:.3rem}}.hero-side .date{{font:600 .8rem var(--mono);color:var(--blue)}}.hero-total{{font:400 5rem/.95 var(--serif);margin:.7rem 0 .25rem}}.hero-note{{color:var(--muted);font-size:.9rem}}
    .overview{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--line)}}.overview-item{{padding:1.25rem 1rem 1.35rem 0}}.overview-item+ .overview-item{{padding-left:1.5rem;border-left:1px solid var(--line)}}.overview strong{{display:block;font:400 1.7rem var(--serif)}}.overview span{{font-size:.78rem;color:var(--muted)}}
    .flow-head{{display:flex;align-items:end;justify-content:space-between;gap:1rem;padding:5.5rem 0 1.2rem}}.flow-head h2{{font:400 2.6rem/1 var(--serif);margin:0}}.flow-head p{{font:600 .75rem var(--mono);color:var(--muted);margin:0}}.filters{{display:flex;gap:.55rem;flex-wrap:wrap;margin-bottom:1.5rem}}.filter{{border:1px solid var(--line);background:transparent;padding:.55rem .85rem;font:500 .8rem var(--sans);color:var(--muted);cursor:pointer}}.filter:hover,.filter[aria-pressed="true"]{{background:var(--blue);border-color:var(--blue);color:#fff}}.search{{margin-left:auto;border:1px solid var(--line);background:var(--white);padding:.55rem .8rem;min-width:220px;font:inherit}}
    .timeline{{border-top:1px solid var(--ink)}}.paper-entry{{display:grid;grid-template-columns:100px minmax(0,1fr);gap:2rem;padding:2rem 0;border-bottom:1px solid var(--line)}}.paper-time{{font:600 .76rem var(--mono);color:var(--blue);padding-top:.35rem}}.paper-time span{{display:block;color:var(--muted);font-weight:400;margin-top:.2rem}}.paper-body{{min-width:0}}.paper-kicker{{display:flex;gap:.8rem;align-items:center;text-transform:uppercase;letter-spacing:.09em;font-size:.68rem;color:var(--muted)}}.paper-kicker span:first-child{{color:var(--blue-deep);font-weight:700}}.paper-body h3{{font:400 clamp(1.45rem,2.8vw,2.1rem)/1.2 var(--serif);margin:.55rem 0 .35rem;max-width:940px}}.paper-body h3 a:hover{{color:var(--blue)}}.english-title{{font:400 .98rem/1.45 var(--serif);color:var(--muted);margin:0 0 .55rem;max-width:900px}}.authors{{font-size:.86rem;color:var(--muted);margin:0 0 1rem}}.paper-foot{{display:flex;align-items:center;justify-content:space-between;gap:1rem}}.tags{{display:flex;gap:.45rem;flex-wrap:wrap}}.tag{{font-size:.7rem;color:var(--blue-deep);border-bottom:1px solid #a8c0ca;padding-bottom:.1rem}}.tag-china{{color:var(--red);border-color:#cf9188}}.read-link{{font-size:.78rem;color:var(--blue);white-space:nowrap}}.read-link:hover{{text-decoration:underline}}.paper-details{{margin-top:.8rem;color:var(--muted);font-size:.75rem}}.paper-details summary{{cursor:pointer;color:var(--muted)}}.paper-details p{{margin:.4rem 0 0}}.paper-entry[hidden]{{display:none}}
    footer{{margin-top:7rem;border-top:1px solid var(--ink);padding:3rem 0 4rem}}.footer-inner{{display:flex;justify-content:space-between;gap:2rem;align-items:end}}.footer-brand{{font:400 2rem var(--serif)}}.footer-note{{color:var(--muted);font-size:.85rem;margin-top:.4rem}}.qr{{width:112px;height:112px;object-fit:cover}}
    @media(max-width:800px){{.header-inner,.page{{padding-left:1rem;padding-right:1rem}}.nav{{display:none;position:absolute;left:0;right:0;top:100%;background:var(--paper);border-bottom:1px solid var(--line);padding:1rem;flex-direction:column;gap:.6rem}}.nav.open{{display:flex}}.menu{{display:block;margin-left:auto}}.hero{{display:block;min-height:0;padding:5rem 0 3rem}}.hero-side{{border-left:0;border-top:1px solid var(--line);padding:1.2rem 0 0;margin-top:3rem}}.hero-total{{font-size:4.5rem}}.overview{{grid-template-columns:repeat(2,1fr)}}.overview-item:nth-child(3){{border-left:0;padding-left:0;border-top:1px solid var(--line)}}.overview-item:nth-child(4){{border-top:1px solid var(--line)}}.flow-head{{padding-top:3.8rem;display:block}}.flow-head p{{margin-top:.7rem}}.search{{width:100%;margin-left:0;order:5}}.paper-entry{{grid-template-columns:1fr;gap:.7rem;padding:1.5rem 0}}.paper-time span{{display:inline;margin-left:.6rem}}.paper-foot{{align-items:flex-start;flex-direction:column}}.footer-inner{{align-items:flex-start;flex-direction:column}}.qr{{width:96px;height:96px}}}}
    @media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
  </style>
</head>
<body>
  <a class="skip" href="#main">跳到今日论文</a>
  <header class="site-header"><div class="header-inner"><a class="wordmark" href="../"><small>Academic Door</small>Econ Papers Daily</a><nav class="nav" id="primary-nav"><a href="../">今日</a><a href="../recent72/">最近72小时</a><a href="../topics/china/">中国研究</a><a href="../journals/">期刊</a><a href="../archive/">归档</a><a href="../search/">搜索</a></nav><span class="presence" data-presence-count title="匿名在线人数，按短时心跳统计">在线</span><button class="menu" type="button" aria-controls="primary-nav" aria-expanded="false" aria-label="打开导航">☰</button></div></header>
  <main id="main"><div class="page">
    <section class="hero"><div><div class="eyebrow">DAILY DOOR / {esc(latest_date)}</div><h1>今日之门<br>已经开启</h1><p class="hero-lede">每日追踪 TOP 经济学期刊与重要工作论文，沿着时间流发现值得打开的研究。</p></div><div class="hero-side"><div class="date">TODAY'S DISCOVERY</div><div class="hero-total">{len(records)}</div><div class="hero-note">篇论文已进入今日发现流</div></div></section>
    <section class="overview" aria-label="今日概览"><div class="overview-item"><strong>{journal_count}</strong><span>期刊论文</span></div><div class="overview-item"><strong>{working_count}</strong><span>工作论文</span></div><div class="overview-item"><strong>{china_count}</strong><span>与中国相关</span></div><div class="overview-item"><strong>{esc(latest_seen_label)}</strong><span>最后更新时间</span></div></section>
    <section class="flow-head"><div><h2>今日论文时间流</h2></div><p>{esc(latest_date)} · 按首次监测时间</p></section>
    <section class="filters" aria-label="论文筛选"><button class="filter" type="button" data-filter="all" aria-pressed="true">全部</button><button class="filter" type="button" data-filter="journal" aria-pressed="false">期刊论文</button><button class="filter" type="button" data-filter="working" aria-pressed="false">工作论文</button><button class="filter" type="button" data-filter="china" aria-pressed="false">与中国相关</button><input class="search" type="search" aria-label="搜索今日论文" placeholder="搜索标题、作者或期刊"></section>
    <section class="timeline" aria-live="polite">{papers}</section>
    <footer><div class="footer-inner"><div><div class="footer-brand">Academic Door</div><div class="footer-note">读好文献，用好论文。Econ Papers Daily 是每日之门里的研究发现流。</div></div><img class="qr" src="../assets/academic-portal-qr.jpg" alt="学术传送门二维码"></div></footer>
  </div></main>
  <script>
    (() => {{
      const nav = document.querySelector('.nav'), menu = document.querySelector('.menu');
      menu.addEventListener('click', () => {{ const open = nav.classList.toggle('open'); menu.setAttribute('aria-expanded', String(open)); }});
      const buttons = [...document.querySelectorAll('[data-filter]')], search = document.querySelector('.search'), entries = [...document.querySelectorAll('.paper-entry')];
      let active = 'all';
      function apply() {{ const query = search.value.trim().toLowerCase(); entries.forEach((entry) => {{ const matches = !query || entry.dataset.search.includes(query); const type = active === 'china' ? entry.dataset.china === 'true' : active === 'all' || entry.dataset.kind === active; entry.hidden = !(matches && type); }}); }}
      buttons.forEach((button) => button.addEventListener('click', () => {{ active = button.dataset.filter; buttons.forEach((item) => item.setAttribute('aria-pressed', String(item === button))); apply(); }}));
      search.addEventListener('input', apply);
      const endpoint = 'https://econ-paper-monitor-presence.academic-door.workers.dev/presence'; const target = document.querySelector('[data-presence-count]'); const key = 'epd_presence_client';
      const clientId = localStorage.getItem(key) || (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2)); localStorage.setItem(key, clientId);
      const heartbeat = () => fetch(endpoint + '?client_id=' + encodeURIComponent(clientId), {{headers: {{Accept: 'application/json'}}}}).then(r => r.ok ? r.json() : null).then(d => {{ if (d && Number.isFinite(Number(d.online))) target.textContent = d.online + ' 人在线'; }}).catch(() => {{}});
      heartbeat(); window.setInterval(heartbeat, 60000);
    }})();
  </script>
</body></html>'''
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(html_doc, encoding="utf-8")
    print(f"built {OUT_DIR / 'index.html'} from {len(records)} records dated {latest_date}")


if __name__ == "__main__":
    build()
