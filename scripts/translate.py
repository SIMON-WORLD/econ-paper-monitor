"""Translate missing English paper titles.

The script uses an OpenAI-compatible chat completions endpoint when configured.
Translations are cached by DOI/id/title to avoid repeated API cost.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from common import DATA_DIR, ROOT, read_json, stable_id, write_json
from status import record_source


CACHE_PATH = DATA_DIR / "translation_cache.json"


def has_chinese(value: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value or "")


def load_local_env() -> None:
    for env_path in (ROOT / ".env", ROOT / ".env.local"):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_settings() -> tuple[str | None, str, str]:
    load_local_env()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    key = deepseek_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("TRANSLATION_API_KEY")
    base_url = (
        os.environ.get("DEEPSEEK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("TRANSLATION_BASE_URL")
        or ("https://api.deepseek.com/v1" if deepseek_key else "https://api.openai.com/v1")
    )
    model = (
        os.environ.get("TRANSLATION_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or ("deepseek-chat" if deepseek_key else "gpt-4o-mini")
    )
    return key, base_url.rstrip("/"), model


def cache_key(record: dict[str, Any]) -> str:
    key = str(record.get("doi") or record.get("id") or stable_id(record)).casefold()
    if key:
        return key
    title = str(record.get("title") or "")
    return hashlib.sha1(title.encode("utf-8")).hexdigest()


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
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    translated = data["choices"][0]["message"]["content"].strip()
    return translated.strip("\"'“”")


def translate_title(title: str, key: str, base_url: str, model: str, timeout: int) -> str:  # type: ignore[no-redef]
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
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
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


def translate_daily_file(
    path: Path,
    args: argparse.Namespace,
    key: str,
    base_url: str,
    model: str,
    cache_records: dict[str, Any],
) -> tuple[int, int, int]:
    records = read_json(path, [])
    records_to_translate = sorted(records, key=lambda record: str(record.get("detected_at") or ""), reverse=True)
    changed = attempted = cached = 0
    started_at = time.monotonic()
    for record in records_to_translate:
        if args.max_seconds and time.monotonic() - started_at >= args.max_seconds:
            break
        if args.limit and attempted >= args.limit:
            break
        title = str(record.get("title") or "").strip()
        if not title:
            continue
        if has_chinese(title):
            if record.get("title_zh") != title or record.get("translation_status") != "native_chinese":
                record["title_zh"] = title
                record["translation_status"] = "native_chinese"
                changed += 1
            continue
        if record.get("title_zh"):
            continue

        key_id = cache_key(record)
        cached_value = cache_records.get(key_id)
        if isinstance(cached_value, dict) and cached_value.get("title_zh"):
            record["title_zh"] = cached_value["title_zh"]
            record["translation_status"] = "title_translated_cached"
            changed += 1
            cached += 1
            continue

        attempted += 1
        try:
            if args.sleep > 0 and attempted > 1:
                time.sleep(args.sleep)
            title_zh = translate_title(title, key, base_url, model, args.timeout)
            record["title_zh"] = title_zh
            record["translation_status"] = "title_translated"
            cache_records[key_id] = {"title": title, "title_zh": title_zh, "model": model}
            changed += 1
        except (KeyError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            record["translation_status"] = f"title_failed: {exc}"
            if args.stop_on_error:
                raise
    if changed and not args.dry_run:
        write_json(path, records)
    return attempted, changed, cached


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=None)
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--max-seconds", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()

    key, base_url, model = api_settings()
    if not key:
        print("translation skipped: DEEPSEEK_API_KEY, OPENAI_API_KEY, or TRANSLATION_API_KEY is not configured")
        record_source("translation", ok=False, count=0, message="missing api key")
        return

    cache = read_json(CACHE_PATH, {"records": {}})
    cache_records = cache.setdefault("records", {})
    total_attempted = total_changed = total_cached = 0
    for path in daily_paths(args.daily_dir, args.date):
        attempted, changed, cached = translate_daily_file(path, args, key, base_url, model, cache_records)
        total_attempted += attempted
        total_changed += changed
        total_cached += cached
    if not args.dry_run:
        write_json(CACHE_PATH, cache)
    record_source("translation", ok=True, count=total_changed, message=f"attempted={total_attempted} cached={total_cached}")
    print(f"translation attempted={total_attempted} changed={total_changed} cached={total_cached}")


if __name__ == "__main__":
    main()
