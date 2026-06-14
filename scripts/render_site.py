"""Render static public pages into docs/."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import DATA_DIR, DOCS_DIR, html_escape, read_json, today_str


STYLE = """
:root{color-scheme:light;--ink:#182026;--muted:#5b6670;--line:#d9e0e6;--soft:#f5f7f9;--accent:#0f766e}
body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--ink);background:#fff;line-height:1.55}
header{border-bottom:1px solid var(--line);background:var(--soft)}
.wrap{max-width:1120px;margin:0 auto;padding:24px}
h1{margin:0 0 8px;font-size:30px;letter-spacing:0}
h2{font-size:20px;margin:28px 0 12px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.meta,.empty{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.paper{border-top:1px solid var(--line);padding:14px 0}
.paper h3{font-size:16px;margin:0 0 6px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tag{font-size:12px;background:var(--soft);border:1px solid var(--line);padding:2px 6px;border-radius:6px;color:var(--muted)}
nav a{margin-right:14px}
"""


def load_all_daily(daily_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not daily_dir.exists():
        return records
    for path in sorted(daily_dir.glob("*.json"), reverse=True):
        for record in read_json(path, []):
            record["_daily_date"] = path.stem
            records.append(record)
    return sorted(
        records,
        key=lambda item: (item.get("published_online") or "", item.get("detected_at") or ""),
        reverse=True,
    )


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>{STYLE}</style>
</head>
<body>
  <header><div class="wrap">
    <h1>经济学论文雷达</h1>
    <p class="meta">自动追踪重点经济学期刊的最新论文，按更新时间、期刊和领域整理为公开网页与订阅源。</p>
    <nav><a href="/econ-paper-monitor/">首页</a><a href="/econ-paper-monitor/archive/">归档</a><a href="/econ-paper-monitor/feed.xml">RSS 订阅</a></nav>
  </div></header>
  <main class="wrap">{body}</main>
</body>
</html>
"""


def paper_list(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<p class="empty">暂无新增论文。</p>'
    chunks = []
    for record in records:
        url = record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#")
        authors = ", ".join(record.get("authors") or [])
        meta = " · ".join(
            str(value)
            for value in [
                record.get("journal_short") or record.get("journal"),
                record.get("published_online"),
                record.get("source"),
            ]
            if value
        )
        fields = "".join(f'<span class="tag">{html_escape(field)}</span>' for field in record.get("fields", []))
        chunks.append(
            f"""<article class="paper">
  <h3><a href="{html_escape(url)}">{html_escape(record.get('title'))}</a></h3>
  <div class="meta">{html_escape(meta)}</div>
  <div>{html_escape(authors)}</div>
  <div class="tags">{fields}</div>
</article>"""
        )
    return "\n".join(chunks)


def write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    records = load_all_daily(args.daily_dir)
    today_records = [record for record in records if record.get("_daily_date") == today_str()]
    index_body = f"""
<section>
  <h2>项目简介</h2>
  <p>这里汇总经济学期刊的 online first、latest articles 和近期上线论文。公开页面只使用中性的期刊、领域和更新时间分类；本地优先级只服务于抓取频率和个人阅读排序，不在页面中展示。</p>
  <p class="meta">当前版本优先接入 Crossref 和已配置 RSS；后续会继续加入 NBER、CEPR、SSRN、RePEc、arXiv econ 等 working paper / preprint 来源。</p>
</section>
<h2>今日新增</h2>
{paper_list(today_records)}
<h2>最近更新</h2>
{paper_list(records[:args.limit])}
"""
    write_page(args.docs_dir / "index.html", page("经济学论文雷达", index_body))

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_journal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_field: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_date[record.get("_daily_date") or "unknown"].append(record)
        by_journal[record.get("journal_id") or "unknown"].append(record)
        for field in record.get("fields", []) or ["unknown"]:
            by_field[field].append(record)

    archive_links = []
    for daily_date, daily_records in sorted(by_date.items(), reverse=True):
        write_page(
            args.docs_dir / "daily" / daily_date / "index.html",
            page(f"{daily_date} 新增论文", f"<h2>{html_escape(daily_date)} 新增论文</h2>{paper_list(daily_records)}"),
        )
        archive_links.append(f'<li><a href="/econ-paper-monitor/daily/{html_escape(daily_date)}/">{html_escape(daily_date)}</a> ({len(daily_records)})</li>')

    for journal_id, journal_records in by_journal.items():
        title = journal_records[0].get("journal") or journal_id
        write_page(
            args.docs_dir / "journals" / journal_id / "index.html",
            page(str(title), f"<h2>{html_escape(title)}</h2>{paper_list(journal_records)}"),
        )

    for field, field_records in by_field.items():
        write_page(
            args.docs_dir / "fields" / field / "index.html",
            page(str(field), f"<h2>{html_escape(field)}</h2>{paper_list(field_records)}"),
        )

    archive_body = "<h2>归档</h2><ul>" + "\n".join(archive_links) + "</ul>"
    write_page(args.docs_dir / "archive" / "index.html", page("归档", archive_body))
    print(f"rendered {len(records)} records into {args.docs_dir}")


if __name__ == "__main__":
    main()
