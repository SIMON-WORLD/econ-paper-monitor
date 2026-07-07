"""Send an optional daily email digest through Resend.

The script is intentionally optional. GitHub Actions calls it only when
RESEND_API_KEY, DIGEST_EMAIL_FROM, and DIGEST_EMAIL_TO are configured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from common import DATA_DIR, html_escape, read_json, today_str
from render_local_status import source_risks
from status import load_status


SITE_URL = "https://simon-world.github.io/econ-paper-monitor/"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def record_url(record: dict[str, Any]) -> str:
    if record.get("doi"):
        return f"https://doi.org/{record['doi']}"
    return str(record.get("url") or SITE_URL)


def is_china_related(record: dict[str, Any]) -> bool:
    fields = {str(field) for field in record.get("fields", []) or []}
    return (
        record.get("china_related") is True
        or record.get("china_relevance_status") == "confirmed"
        or "china" in fields
    )


def authors(record: dict[str, Any]) -> str:
    names = record.get("authors") or []
    if isinstance(names, list) and names:
        return ", ".join(str(name) for name in names[:5])
    return "Unknown Authors"


def load_today(date_value: str) -> list[dict[str, Any]]:
    path = DATA_DIR / "daily" / f"{date_value}.json"
    payload = read_json(path, [])
    return [record for record in payload if isinstance(record, dict)] if isinstance(payload, list) else []


def load_high_source_risks(limit: int = 5) -> list[dict[str, Any]]:
    status = load_status()
    risks = source_risks(
        status.get("sources") or {},
        (status.get("source_groups") or {}).get("cn-journals") or {},
        (status.get("source_groups") or {}).get("cnki-rss") or {},
        (status.get("source_groups") or {}).get("publisher-detail") or {},
    )
    return [risk for risk in risks if risk.get("level") == "高"][:limit]


def risk_html(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return ""
    items = []
    for risk in risks:
        area = html_escape(risk.get("area") or "未知来源")
        impact = html_escape(risk.get("impact") or "")
        evidence = html_escape(risk.get("evidence") or "")
        action = html_escape(risk.get("action") or "")
        items.append(
            "<li>"
            f"<p><strong>{area}</strong></p>"
            f"<p>{impact}</p>"
            f"<p><span style=\"color:#6b7280\">证据：</span>{evidence}</p>"
            f"<p><span style=\"color:#6b7280\">建议：</span>{action}</p>"
            "</li>"
        )
    return (
        "<section style=\"border:1px solid #f0c36d;background:#fff8e5;padding:12px;margin:16px 0\">"
        "<h3 style=\"margin-top:0\">高风险来源提醒</h3>"
        "<p>以下来源异常可能影响今日监测完整性，建议优先查看后台状态。</p>"
        f"<ol>{''.join(items)}</ol>"
        "</section>"
    )


def digest_html(records: list[dict[str, Any]], date_value: str, risks: list[dict[str, Any]] | None = None) -> str:
    china = [record for record in records if is_china_related(record)]
    selected = china[:30] or records[:30]
    risk_section = risk_html(risks or [])
    items = []
    for record in selected:
        title = html_escape(record.get("title") or "Untitled")
        journal = html_escape(record.get("journal") or "")
        author_text = html_escape(authors(record))
        url = html_escape(record_url(record))
        tag = " · 与中国相关" if is_china_related(record) else ""
        items.append(
            f"<li><p><a href=\"{url}\"><strong>{title}</strong></a>{tag}</p>"
            f"<p>{author_text}</p><p>{journal}</p></li>"
        )
    if not items:
        items.append("<li>今日暂无新发现。</li>")
    return f"""<!doctype html>
<html><body>
<h2>Econ Papers Daily · {html_escape(date_value)}</h2>
<p>今日新发现 {len(records)} 篇；其中与中国相关 {len(china)} 篇。</p>
<p><a href="{SITE_URL}">打开网站</a> · <a href="{SITE_URL}recent72/">最近 72 小时</a></p>
{risk_section}
<ol>
{''.join(items)}
</ol>
</body></html>"""


def send_resend(api_key: str, from_addr: str, to_addrs: list[str], subject: str, html: str) -> None:
    payload = json.dumps(
        {
            "from": from_addr,
            "to": to_addrs,
            "subject": subject,
            "html": html,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        print(response.read().decode("utf-8", errors="replace"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--to", default=os.environ.get("DIGEST_EMAIL_TO", ""))
    parser.add_argument("--from", dest="from_addr", default=os.environ.get("DIGEST_EMAIL_FROM", ""))
    parser.add_argument("--dry-run", action="store_true", help="print rendered HTML instead of sending email")
    args = parser.parse_args()

    records = load_today(args.date)
    risks = load_high_source_risks()
    html = digest_html(records, args.date, risks)
    if args.dry_run:
        print(html)
        return

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to_addrs = [item.strip() for item in args.to.split(",") if item.strip()]
    if not api_key or not args.from_addr or not to_addrs:
        print("email digest skipped: missing RESEND_API_KEY, DIGEST_EMAIL_FROM, or DIGEST_EMAIL_TO")
        return
    subject = f"Econ Papers Daily: {args.date} new papers ({len(records)})"
    send_resend(api_key, args.from_addr, to_addrs, subject, html)


if __name__ == "__main__":
    main()
