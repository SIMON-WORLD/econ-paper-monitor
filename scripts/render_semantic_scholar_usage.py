"""Render the Semantic Scholar API usage page (docs/usage/index.html).

Reads ``data/semantic_scholar_usage.json`` produced by the data line and
writes a self-contained HTML page with cumulative and per-day request counts,
key status, and the official usage policy.  Missing data renders an honest
placeholder so the page always exists.

Display-line script: only reads ``data/**`` and writes ``docs/**``.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from common import DATA_DIR, DOCS_DIR, html_escape, read_json, write_text

POLICY_NOTE = (
    "Semantic Scholar 官方政策：API key 档位限速 1 请求/秒；未认证共享 1000 RPS 池并会在高峰节流；"
    "官方发布说明（2024-11）明确闲置约 60 天的 API key 会被自动回收。"
    "本页每次数据更新自动刷新，来源为本仓库每日落盘的 provider health 与 keep-alive 记录。"
)


def _row_html(row: dict[str, Any], max_attempts: int) -> str:
    attempts = int(row.get("attempts") or 0)
    available = int(row.get("available") or 0)
    not_found = int(row.get("not_found") or 0)
    rate_limited = int(row.get("rate_limited") or 0)
    skipped = int(row.get("skipped") or 0)
    other = max(0, attempts - available - not_found - rate_limited - skipped)
    width = 100.0 if max_attempts <= 0 else (attempts / max_attempts) * 100.0

    def pct(value: int) -> str:
        if attempts <= 0:
            return "0%"
        return f"{value / attempts * 100:.1f}%"
    seg_available = f'<div class="seg seg-avail" style="width:{pct(available)}"></div>'
    seg_rate = f'<div class="seg seg-rate" style="width:{pct(rate_limited)}"></div>'
    seg_notfound = f'<div class="seg seg-notfound" style="width:{pct(not_found)}"></div>'
    seg_other = f'<div class="seg seg-other" style="width:{pct(other)}"></div>'
    bar = (
        f'<div class="bar" style="width:{width:.2f}%">'
        f"{seg_available}{seg_rate}{seg_notfound}{seg_other}"
        "</div>"
    )
    return (
        f"<tr>"
        f"<td>{html_escape(row.get('date') or '')}</td>"
        f"<td class=\"num\">{int(row.get('runs') or 0)}</td>"
        f"<td class=\"num\">{attempts}</td>"
        f"<td class=\"num\">{available}</td>"
        f"<td class=\"num\">{not_found}</td>"
        f"<td class=\"num\">{rate_limited}</td>"
        f"<td class=\"num\">{skipped}</td>"
        f"<td>{bar}</td>"
        f"</tr>"
    )


def render_usage(data_dir: Path = DATA_DIR, docs_dir: Path = DOCS_DIR) -> Path:
    usage = read_json(data_dir / "semantic_scholar_usage.json", {})
    if not isinstance(usage, dict) or not usage:
        body = (
            "<p>用量数据尚未生成。数据更新流程首次运行后本页会自动填充。</p>"
        )
        cards = ""
        rows = ""
        updated = "—"
    else:
        total = usage.get("total") if isinstance(usage.get("total"), dict) else {}
        by_day = usage.get("by_day") if isinstance(usage.get("by_day"), list) else []
        updated = str(usage.get("updated_at") or "—")
        key_state = "已配置" if usage.get("key_configured") is True else "未配置"
        last_used = str(usage.get("last_used_at") or "—")
        last_keepalive = str(usage.get("last_keepalive_at") or "—")
        days_idle = usage.get("days_since_last_use")
        idle_text = "—" if days_idle is None else f"{int(days_idle)} 天"
        attempts = int(total.get("attempts") or 0)
        available = int(total.get("available") or 0)
        rate_limited = int(total.get("rate_limited") or 0)
        max_attempts = max([int(r.get("attempts") or 0) for r in by_day] + [0])
        cards = (
            f'<div class="cards">'
            f'<div class="card"><span class="k">Key 状态</span><span class="v">{key_state}</span></div>'
            f'<div class="card"><span class="k">累计请求</span><span class="v">{attempts}</span></div>'
            f'<div class="card"><span class="k">成功返回</span><span class="v">{available}</span></div>'
            f'<div class="card"><span class="k">被限流</span><span class="v">{rate_limited}</span></div>'
            f'<div class="card"><span class="k">最近使用</span><span class="v">{html_escape(last_used)}</span></div>'
            f'<div class="card"><span class="k">距上次使用</span><span class="v">{idle_text}</span></div>'
            f'<div class="card"><span class="k">最近保活</span><span class="v">{html_escape(last_keepalive)}</span></div>'
            "</div>"
        )
        if by_day:
            table_rows = "".join(_row_html(r, max_attempts) for r in by_day)
            rows = (
                "<h2>按日用量</h2>"
                '<div class="legend">'
                '<span class="lg seg-avail">成功</span>'
                '<span class="lg seg-rate">限流</span>'
                '<span class="lg seg-notfound">未找到</span>'
                '<span class="lg seg-other">其他</span>'
                "</div>"
                '<div class="table-wrap"><table>'
                "<thead><tr><th>日期</th><th>运行</th><th>请求</th><th>成功</th>"
                "<th>未找到</th><th>限流</th><th>跳过</th><th>构成</th></tr></thead>"
                f"<tbody>{table_rows}</tbody></table></div>"
            )
        else:
            rows = "<p>暂无按日数据。</p>"
        body = f"{cards}{rows}"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="index,follow">
<title>Semantic Scholar API 用量</title>
<style>
  :root {{ --ink:#1f2430; --muted:#6b7280; --line:#e5e7eb; --avail:#16a34a; --rate:#dc2626; --nf:#d97706; --other:#9ca3af; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; color:var(--ink); background:#fafafa; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:28px 20px 64px; }}
  a {{ color:#2563eb; text-decoration:none; }}
  h1 {{ font-size:26px; margin:12px 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 20px; font-size:14px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:20px 0; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px; display:flex; flex-direction:column; gap:4px; }}
  .card .k {{ color:var(--muted); font-size:12px; }}
  .card .v {{ font-size:18px; font-weight:600; word-break:break-all; }}
  h2 {{ font-size:18px; margin:28px 0 12px; }}
  .legend {{ display:flex; gap:14px; font-size:12px; color:var(--muted); margin-bottom:8px; }}
  .lg {{ display:inline-flex; align-items:center; gap:5px; }}
  .lg::before {{ content:""; width:10px; height:10px; border-radius:3px; display:inline-block; }}
  .table-wrap {{ overflow-x:auto; background:#fff; border:1px solid var(--line); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; min-width:640px; font-size:13px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }}
  th {{ background:#f3f4f6; font-weight:600; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .bar {{ height:14px; border-radius:7px; overflow:hidden; display:flex; background:#f3f4f6; min-width:2px; }}
  .seg {{ height:100%; }}
  .seg-avail {{ background:var(--avail); }}
  .seg-rate {{ background:var(--rate); }}
  .seg-notfound {{ background:var(--nf); }}
  .seg-other {{ background:var(--other); }}
  .note {{ margin-top:24px; padding:12px 14px; background:#fff7ed; border:1px solid #fed7aa; border-radius:10px; font-size:13px; color:#7c2d12; line-height:1.6; }}
  footer {{ margin-top:28px; color:var(--muted); font-size:12px; }}
</style>
</head>
<body>
<div class="wrap">
  <p><a href="../index.html">← 返回首页</a></p>
  <h1>Semantic Scholar API 用量</h1>
  <p class="sub">更新时间：{html_escape(updated)}</p>
  {body}
  <div class="note">{POLICY_NOTE}</div>
  <footer>数据来源：<code>data/metadata_provider_health.json</code> 与 <code>data/semantic_scholar_keepalive.json</code>（由数据线每日生成）。</footer>
</div>
</body>
</html>
"""
    out = docs_dir / "usage" / "index.html"
    write_text(out, html)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    args = parser.parse_args(argv)

    out = render_usage(args.data_dir, args.docs_dir)
    print(f"rendered {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())