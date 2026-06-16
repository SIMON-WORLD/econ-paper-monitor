"""Render a local-only admin status page.

Output is written to local_admin/status.html, which is ignored by git.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, ROOT, html_escape, read_json
from status import load_status


def load_records() -> list[dict[str, Any]]:
    records = []
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True):
        payload = read_json(path, [])
        if isinstance(payload, list):
            records.extend(payload)
    return records


def daily_counts() -> list[tuple[str, int]]:
    rows = []
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True)[:10]:
        payload = read_json(path, [])
        rows.append((path.stem, len(payload) if isinstance(payload, list) else 0))
    return rows


def pct(done: int, total: int) -> str:
    return "0%" if total == 0 else f"{done / total:.1%}"


def health_items(status: dict[str, Any]) -> list[str]:
    items = []
    sources = status.get("sources", {})
    cn_message = str(sources.get("cn-journals", {}).get("message") or "")
    if "stale-latest" in cn_message:
        items.append("部分中文期刊官网/API 当前最新期仍早于当前年份，系统已排除这些旧期，不进入今日论文流。")
    if "latest-issue 0/" in cn_message:
        items.append("有中文期刊本轮抓到候选记录，但因期次过旧或不符合最新期规则，展示数量为 0。")
    translation = sources.get("translation", {})
    if translation and not translation.get("ok"):
        items.append("标题翻译未成功，请检查 DEEPSEEK_API_KEY 或翻译服务状态。")
    return items


def main() -> None:
    records = load_records()
    status = load_status()
    translated = sum(1 for record in records if record.get("title_zh"))
    by_source = Counter(record.get("source") or "unknown" for record in records)
    by_confidence = Counter(record.get("date_confidence") or "unknown" for record in records)
    registry = read_json(DATA_DIR / "source_registry.json", {"journals": {}})
    registry_items = registry.get("journals", {})
    registry_rss = sum(1 for item in registry_items.values() if item.get("rss"))
    registry_status = Counter(item.get("status") or "unknown" for item in registry_items.values())
    registry_platform = Counter(item.get("platform") or "unknown" for item in registry_items.values())
    health = health_items(status)
    rows = []
    for source_id, item in sorted(status.get("sources", {}).items()):
        ok = "OK" if item.get("ok") else "FAIL"
        rows.append(
            f"<tr><td>{html_escape(source_id)}</td><td>{ok}</td><td>{html_escape(item.get('count'))}</td>"
            f"<td>{html_escape(item.get('updated_at'))}</td><td>{html_escape(item.get('message'))}</td></tr>"
        )
    source_rows = "".join(rows) or "<tr><td colspan='5'>暂无状态记录</td></tr>"
    source_counts = "".join(f"<li>{html_escape(key)}: {value}</li>" for key, value in sorted(by_source.items()))
    confidence_counts = "".join(
        f"<li>{html_escape(key)}: {value}</li>"
        for key, value in sorted(by_confidence.items())
    )
    registry_status_counts = "".join(
        f"<li>{html_escape(key)}: {value}</li>"
        for key, value in sorted(registry_status.items())
    )
    registry_platform_counts = "".join(
        f"<li>{html_escape(key)}: {value}</li>"
        for key, value in sorted(registry_platform.items())
    )
    daily_rows = "".join(f"<tr><td>{html_escape(day)}</td><td>{count}</td></tr>" for day, count in daily_counts())
    health_rows = "".join(f"<li>{html_escape(item)}</li>" for item in health) or "<li>暂无需要处理的来源异常。</li>"
    latest_run = (status.get("runs") or [{}])[0]
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Econ Papers Daily 本地状态</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:32px;color:#1f2328}}
    table{{border-collapse:collapse;width:100%;margin-top:12px}}td,th{{border:1px solid #d0d7de;padding:8px;text-align:left;vertical-align:top}}
    th{{background:#f6f8fa}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px}}.card{{border:1px solid #d0d7de;padding:14px;border-radius:8px}}
    strong{{font-size:24px;display:block}}
  </style>
</head>
<body>
  <h1>Econ Papers Daily 本地状态</h1>
  <div class="grid">
    <div class="card"><strong>{len(records)}</strong><span>总记录</span></div>
    <div class="card"><strong>{translated}</strong><span>已翻译标题</span></div>
    <div class="card"><strong>{pct(translated, len(records))}</strong><span>标题翻译覆盖率</span></div>
    <div class="card"><strong>{html_escape(latest_run.get('new', '暂无'))}</strong><span>最近新增</span></div>
    <div class="card"><strong>{registry_rss}</strong><span>RSS Registry</span></div>
  </div>
  <h2>来源数量</h2>
  <ul>{source_counts}</ul>
  <h2>日期可信度</h2>
  <ul>{confidence_counts}</ul>
  <h2>Source Registry</h2>
  <p>用于判断每本期刊当前依赖官网、RSS、Crossref 还是特殊中文适配器。</p>
  <h3>配置状态</h3>
  <ul>{registry_status_counts}</ul>
  <h3>平台分布</h3>
  <ul>{registry_platform_counts}</ul>
  <h2>最近每日记录数</h2>
  <table><thead><tr><th>日期</th><th>记录数</th></tr></thead><tbody>{daily_rows}</tbody></table>
  <h2>健康提醒</h2>
  <ul>{health_rows}</ul>
  <h2>运行状态</h2>
  <table><thead><tr><th>来源</th><th>状态</th><th>数量</th><th>更新时间 UTC</th><th>信息</th></tr></thead><tbody>{source_rows}</tbody></table>
</body>
</html>
"""
    output = ROOT / "local_admin" / "status.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
