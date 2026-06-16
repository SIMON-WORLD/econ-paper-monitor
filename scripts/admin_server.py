"""Local review server for Econ Papers Daily.

Run with:
  python scripts/admin_server.py

Then open http://127.0.0.1:8765/
"""

from __future__ import annotations

import argparse
import html
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from apply_overrides import load_overrides
from common import DATA_DIR, ROOT, read_json, stable_id, write_text


OVERRIDES_PATH = DATA_DIR / "manual_overrides.yml"


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def q(value: Any) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def record_key(record: dict[str, Any]) -> str:
    return str(record.get("doi") or record.get("id") or stable_id(record))


def load_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((DATA_DIR / "daily").glob("*.json"), reverse=True):
        payload = read_json(path, [])
        if isinstance(payload, list):
            for record in payload:
                record["_daily_date"] = path.stem
                records.append(record)
    return sorted(records, key=lambda item: item.get("detected_at") or item.get("_daily_date") or "", reverse=True)


def candidates() -> list[dict[str, Any]]:
    return [record for record in load_records() if record.get("china_relevance_status") == "candidate"][:80]


def write_overrides(overrides: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# Manual record corrections. Keys are DOI values when available.",
        "# Use this for high-confidence fixes that upstream metadata does not expose.",
        "records:",
    ]
    for key in sorted(overrides):
        entry = overrides[key]
        lines.append(f"  {q(key)}:")
        for field in [
            "china_related",
            "china_reason",
            "title_zh",
            "accepted_date",
            "available_online",
            "published_online",
            "date_confidence",
        ]:
            if field not in entry or entry[field] in {None, ""}:
                continue
            value = entry[field]
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = q(value)
            lines.append(f"    {field}: {rendered}")
    write_text(OVERRIDES_PATH, "\n".join(lines) + "\n")


def upsert_review(key: str, action: str) -> str:
    records = {record_key(record): record for record in load_records()}
    record = records.get(key)
    if not record:
        return "没有找到这条记录，可能已被更新。"
    overrides = load_overrides(OVERRIDES_PATH)
    entry = dict(overrides.get(key, {}))
    entry["china_related"] = action == "confirm"
    entry["china_reason"] = (
        "本地后台人工确认：中国相关"
        if action == "confirm"
        else "本地后台人工确认：排除中国相关"
    )
    if record.get("title_zh"):
        entry.setdefault("title_zh", record.get("title_zh"))
    overrides[key] = entry
    write_overrides(overrides)
    run_refresh()
    return "已保存并重新生成页面。"


def run_refresh() -> None:
    commands = [
        [sys.executable, "scripts/apply_overrides.py"],
        [sys.executable, "scripts/enrich_china_relevance.py"],
        [sys.executable, "scripts/render_site.py"],
        [sys.executable, "scripts/build_feed.py", "--site-url", "https://simon-world.github.io/econ-paper-monitor/"],
        [sys.executable, "scripts/render_local_status.py"],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def render_candidate(record: dict[str, Any]) -> str:
    key = record_key(record)
    title = h(record.get("title"))
    title_zh = f"<div class='zh'>{h(record.get('title_zh'))}</div>" if record.get("title_zh") else ""
    authors = h(", ".join(record.get("authors") or []))
    reason = h(record.get("china_relevance_reason"))
    journal = h(record.get("journal"))
    date = h(record.get("_daily_date"))
    url = h(record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else "#"))
    return f"""
<article class="item">
  <div class="meta">{date} · {journal}</div>
  <h3><a href="{url}" target="_blank" rel="noreferrer">{title}</a></h3>
  {title_zh}
  <p class="authors">{authors}</p>
  <p class="reason">{reason}</p>
  <form method="post" action="/review">
    <input type="hidden" name="key" value="{h(key)}">
    <button name="action" value="confirm" class="yes">确认中国相关</button>
    <button name="action" value="reject" class="no">排除</button>
  </form>
</article>
"""


def render_page(message: str = "") -> str:
    items = candidates()
    cards = "\n".join(render_candidate(record) for record in items)
    if not cards:
        cards = "<div class='empty'>当前没有需要人工确认的候选项。</div>"
    msg = f"<div class='msg'>{h(message)}</div>" if message else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Econ Papers Daily 本地审核</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;margin:32px;color:#1f2328;background:#fff;line-height:1.55}}
    a{{color:#0969da;text-decoration:none}}a:hover{{text-decoration:underline}}
    .top{{display:flex;align-items:end;justify-content:space-between;gap:20px;border-bottom:1px solid #d0d7de;padding-bottom:16px;margin-bottom:18px}}
    h1{{margin:0;font-size:28px}}.sub{{color:#656d76;margin:4px 0 0}}.msg{{background:#dafbe1;border:1px solid #4ac26b;border-radius:8px;padding:10px 12px;margin:16px 0}}
    .item{{border-bottom:1px solid #d0d7de;padding:18px 0;max-width:980px}}.meta,.authors,.reason,.zh{{color:#656d76}}.zh{{margin-top:4px;color:#1f2328}}
    h3{{font-size:18px;margin:6px 0}}button{{border:1px solid #d0d7de;border-radius:6px;padding:8px 12px;margin-right:8px;cursor:pointer;background:#fff}}
    .yes{{background:#1f883d;color:#fff;border-color:#1f883d}}.no{{background:#fff;color:#cf222e;border-color:#ffccc7}}.empty{{padding:24px;border:1px dashed #d0d7de;border-radius:8px;color:#656d76}}
  </style>
</head>
<body>
  <section class="top">
    <div>
      <h1>Econ Papers Daily 本地审核</h1>
      <p class="sub">点击按钮会自动写入 data/manual_overrides.yml，并重新生成本地/线上静态页面文件。</p>
    </div>
    <a href="/refresh">刷新候选列表</a>
  </section>
  {msg}
  {cards}
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/refresh"):
            run_refresh()
            self.respond(render_page("已刷新候选列表。"))
            return
        self.respond(render_page())

    def do_POST(self) -> None:
        if self.path != "/review":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        data = urllib.parse.parse_qs(body)
        key = data.get("key", [""])[0]
        action = data.get("action", [""])[0]
        message = upsert_review(key, action) if key and action in {"confirm", "reject"} else "请求无效。"
        self.respond(render_page(message))

    def respond(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Local admin server: http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
