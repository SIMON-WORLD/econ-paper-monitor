"""Shared helpers for the econ-paper-monitor MVP pipeline."""

from __future__ import annotations

import hashlib
import html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

USER_AGENT = "econ-paper-monitor/0.1 (mailto:example@example.com)"
BEIJING_TZ = timezone(timedelta(hours=8))


def today_str() -> str:
    return datetime.now(BEIJING_TZ).date().isoformat()


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    ensure_parent(path)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fetch_json(url: str, params: dict[str, str | int] | None = None, timeout: int = 30) -> Any:
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError:
        if not url.startswith("https://"):
            raise
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    charset = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.URLError:
        if not url.startswith("https://"):
            raise
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"

    candidates = []
    if charset:
        candidates.append(charset)
    candidates.extend(["utf-8", "gb18030", "gbk"])
    for candidate in dict.fromkeys(candidates):
        try:
            return payload.decode(candidate)
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace")


def polite_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_scalar(value: str) -> str | None:
    value = value.strip()
    if value == "null":
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def load_journals(path: Path = DATA_DIR / "journals.yml") -> list[dict[str, Any]]:
    journals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    list_key: str | None = None
    source: dict[str, Any] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "journals:":
            continue
        if line.startswith("  - id:"):
            if current:
                journals.append(current)
            current = {
                "id": parse_scalar(stripped.removeprefix("- id:").strip()),
                "aliases": [],
                "fields": [],
                "sources": [],
            }
            list_key = None
            source = None
            continue
        if current is None:
            continue
        if line.startswith("    ") and not line.startswith("      "):
            key, _, value = stripped.partition(":")
            if value == "":
                list_key = key
                source = None
                continue
            current[key] = parse_scalar(value.strip())
            list_key = None
            source = None
            continue
        if line.startswith("      - ") and list_key in {"aliases", "fields"}:
            current[list_key].append(parse_scalar(stripped.removeprefix("- ").strip()))
            continue
        if line.startswith("      - ") and list_key == "sources":
            key, _, value = stripped.removeprefix("- ").partition(":")
            source = {key.strip(): parse_scalar(value.strip())}
            current["sources"].append(source)
            continue
        if line.startswith("        ") and source is not None:
            key, _, value = stripped.partition(":")
            source[key.strip()] = parse_scalar(value.strip())

    if current:
        journals.append(current)
    return journals


def render_journals_yml(journals: list[dict[str, Any]]) -> str:
    lines = [
        "# Generated/updated by econ-paper-monitor scripts.",
        "# priority_private is for local cadence/ranking only; do not display it on public pages.",
        "journals:",
    ]
    for journal in journals:
        lines.extend(
            [
                f"  - id: {yaml_quote(str(journal['id']))}",
                f"    title: {yaml_quote(str(journal['title']))}",
                f"    short_name: {yaml_quote(str(journal['short_name']))}",
                "    aliases:",
            ]
        )
        for alias in journal.get("aliases", []):
            lines.append(f"      - {yaml_quote(str(alias))}")
        lines.extend(
            [
                f"    chinese_name: {yaml_quote(str(journal.get('chinese_name') or journal['title']))}",
                "    fields:",
            ]
        )
        for field in journal.get("fields", []):
            lines.append(f"      - {yaml_quote(str(field))}")
        lines.extend(
            [
                f"    public_group: {yaml_quote(str(journal.get('public_group') or '未分类'))}",
                f"    priority_private: {yaml_quote(str(journal.get('priority_private') or ''))}",
                f"    issn: {yaml_quote(str(journal['issn'])) if journal.get('issn') else 'null'}",
                f"    publisher: {yaml_quote(str(journal['publisher'])) if journal.get('publisher') else 'null'}",
                "    sources:",
            ]
        )
        for source in journal.get("sources", []):
            lines.append(f"      - type: {source.get('type') or 'unknown'}")
            if "url" in source:
                lines.append(f"        url: {yaml_quote(str(source['url'])) if source.get('url') else 'null'}")
            if "issn" in source:
                lines.append(f"        issn: {yaml_quote(str(source['issn'])) if source.get('issn') else 'null'}")
    return "\n".join(lines) + "\n"


def write_journals(path: Path, journals: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    path.write_text(render_journals_yml(journals), encoding="utf-8")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value).casefold()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def stable_id(record: dict[str, Any]) -> str:
    doi = normalize_doi(record.get("doi"))
    if doi:
        return "doi:" + doi
    url = (record.get("url") or "").strip()
    if url:
        return "url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    title = normalize_text(record.get("title"))
    journal = normalize_text(record.get("journal"))
    digest = hashlib.sha1(f"{title}|{journal}".encode("utf-8")).hexdigest()[:16]
    return "title:" + digest


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    return value or None


def first_text(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


def date_from_parts(parts: Any) -> str | None:
    try:
        values = parts["date-parts"][0]
    except (KeyError, IndexError, TypeError):
        return None
    if not values:
        return None
    year = int(values[0])
    month = int(values[1]) if len(values) > 1 else 1
    day = int(values[2]) if len(values) > 2 else 1
    return date(year, month, day).isoformat()


def recent_cutoff(days: int) -> str:
    return (datetime.now(BEIJING_TZ).date() - timedelta(days=days)).isoformat()


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)
