"""Write a concise GitHub Actions job summary for monitor runs."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, today_str
from status import load_status


def load_today_records() -> list[dict[str, Any]]:
    path = DATA_DIR / "daily" / f"{today_str()}.json"
    payload = read_json(path, [])
    return payload if isinstance(payload, list) else []


def main() -> None:
    output = os.environ.get("GITHUB_STEP_SUMMARY")
    if not output:
        print("GITHUB_STEP_SUMMARY is not set")
        return

    status = load_status()
    records = load_today_records()
    by_source = Counter(record.get("source") or "unknown" for record in records)
    by_confidence = Counter(record.get("date_confidence") or "unknown" for record in records)
    sources = status.get("sources", {})

    lines = [
        "# Econ Papers Daily run summary",
        "",
        f"- Date: `{today_str()}`",
        f"- Today's records: `{len(records)}`",
        "",
        "## Sources",
        "",
        "| Source | OK | Count | Message |",
        "| --- | --- | ---: | --- |",
    ]
    for source_id, item in sorted(sources.items()):
        message = str(item.get("message") or "").replace("|", "\\|")
        lines.append(f"| {source_id} | {item.get('ok')} | {item.get('count')} | {message[:500]} |")

    lines.extend(["", "## Today's records by source", ""])
    for key, value in sorted(by_source.items()):
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Date confidence", ""])
    for key, value in sorted(by_confidence.items()):
        lines.append(f"- `{key}`: {value}")

    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
