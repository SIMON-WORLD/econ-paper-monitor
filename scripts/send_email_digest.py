"""Send an optional daily email digest through Resend.

The script is intentionally optional. GitHub Actions calls it only when
RESEND_API_KEY, DIGEST_EMAIL_FROM, and DIGEST_EMAIL_TO are configured.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from common import DATA_DIR, html_escape, read_json, today_str


SITE_URL = "https://simon-world.github.io/econ-paper-monitor/"


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


def digest_html(records: list[dict[str, Any]], date_value: str) -> str:
    china = [record for record in records if is_china_related(record)]
    selected = china[:30] or records[:30]
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
    args = parser.parse_args()

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to_addrs = [item.strip() for item in args.to.split(",") if item.strip()]
    if not api_key or not args.from_addr or not to_addrs:
        print("email digest skipped: missing RESEND_API_KEY, DIGEST_EMAIL_FROM, or DIGEST_EMAIL_TO")
        return
    records = load_today(args.date)
    subject = f"Econ Papers Daily: {args.date} new papers ({len(records)})"
    send_resend(api_key, args.from_addr, to_addrs, subject, digest_html(records, args.date))


if __name__ == "__main__":
    main()
