"""Translate missing paper titles in daily archives.

The script uses an OpenAI-compatible chat completions endpoint when configured.
If no API key is present, it exits successfully without modifying data.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, write_json


def api_settings() -> tuple[str | None, str, str]:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("TRANSLATION_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("TRANSLATION_BASE_URL") or "https://api.openai.com/v1"
    model = os.environ.get("TRANSLATION_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    return key, base_url.rstrip("/"), model


def translate_title(title: str, key: str, base_url: str, model: str, timeout: int) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是经济学论文标题翻译助手。只输出一个忠实、简洁、学术风格的中文标题，不要解释。",
            },
            {"role": "user", "content": title},
        ],
        "temperature": 0.1,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    translated = data["choices"][0]["message"]["content"].strip()
    return translated.strip("\"'“”")


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"), reverse=True)


def translate_daily_file(path: Path, args: argparse.Namespace, key: str, base_url: str, model: str) -> tuple[int, int]:
    records = read_json(path, [])
    changed = 0
    attempted = 0
    for record in records:
        if args.limit and attempted >= args.limit:
            break
        title = str(record.get("title") or "").strip()
        if not title or record.get("title_zh"):
            continue
        attempted += 1
        try:
            record["title_zh"] = translate_title(title, key, base_url, model, args.timeout)
            record["translation_status"] = "title_translated"
            changed += 1
        except (KeyError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            record["translation_status"] = f"title_failed: {exc}"
            if args.stop_on_error:
                raise
    if changed and not args.dry_run:
        write_json(path, records)
    return attempted, changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=None)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()

    key, base_url, model = api_settings()
    if not key:
        print("translation skipped: OPENAI_API_KEY or TRANSLATION_API_KEY is not configured")
        return

    total_attempted = 0
    total_changed = 0
    for path in daily_paths(args.daily_dir, args.date):
        attempted, changed = translate_daily_file(path, args, key, base_url, model)
        total_attempted += attempted
        total_changed += changed
    print(f"translation attempted={total_attempted} changed={total_changed}")


if __name__ == "__main__":
    main()
