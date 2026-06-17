"""Enrich daily records from publisher article pages.

This step is intentionally best-effort. It should improve metadata when
publisher pages are accessible, but never block the monitor when a site uses
Cloudflare, CAPTCHA, or institutional access controls.
"""

from __future__ import annotations

import argparse
import html as html_lib
import re
from datetime import date
from pathlib import Path
from typing import Any

from common import DATA_DIR, fetch_text, read_json, today_str, write_json
from status import record_source


MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

DATE_CAPTURE = (
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2}"
    r"|20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?"
)


def clean_text(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})", text)
    if match:
        month = MONTHS.get(match.group(1).casefold())
        if month:
            return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
    match = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})", text)
    if match:
        month = MONTHS.get(match.group(2).casefold())
        if month:
            return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(1)):02d}"
    return None


def parse_meta(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        key_match = re.search(r"(?:name|property)=['\"]([^'\"]+)['\"]", tag, flags=re.I)
        content_match = re.search(r"content=['\"]([^'\"]*)['\"]", tag, flags=re.I)
        if key_match and content_match:
            meta[key_match.group(1).casefold()] = content_match.group(1).strip()
    return meta


def extract_page_metadata(html: str) -> dict[str, str]:
    meta = parse_meta(html)
    text = clean_text(html)
    result: dict[str, str] = {}

    meta_date_fields = (
        ("available_online", "citation_online_date"),
        ("published_online", "article:published_time"),
        ("published_online", "dc.date"),
        ("published_online", "dc.date.issued"),
        ("published_online", "dc.date.available"),
        ("published_online", "prism.publicationdate"),
        ("published_online", "citation_publication_date"),
        ("accepted_date", "citation_acceptance_date"),
        ("accepted_date", "citation_accepted_date"),
        ("accepted_date", "dc.date.accepted"),
    )
    for field, key in meta_date_fields:
        parsed = parse_date(meta.get(key))
        if parsed:
            result.setdefault(field, parsed)
            if field in {"available_online", "published_online"}:
                result.setdefault("available_online", parsed)
                result.setdefault("published_online", parsed)
            result.setdefault("date_source", f"publisher_meta:{key}")
            result.setdefault("date_confidence", "A")

    patterns = [
        ("accepted_date", rf"(?:Accepted|Accepted on|Date accepted|录用日期|接受日期)\s*[:：]?\s*({DATE_CAPTURE})"),
        ("available_online", rf"(?:Available online|Online available|Article available online|上线日期|网络首发)\s*[:：]?\s*({DATE_CAPTURE})"),
        ("published_online", rf"(?:First published|Published online|Published Online|Publication date|Published|发布日期|出版日期)\s*[:：]?\s*({DATE_CAPTURE})"),
    ]
    for field, pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        parsed = parse_date(match.group(1)) if match else None
        if parsed:
            result[field] = parsed
            if field in {"available_online", "published_online"}:
                result["available_online"] = parsed
                result["published_online"] = parsed
            result["date_source"] = f"publisher_{field}"
            result["date_confidence"] = "A"
    for key in ("citation_abstract", "dc.description", "description", "og:description"):
        abstract = meta.get(key)
        if abstract and len(clean_text(abstract)) > 80:
            result.setdefault("abstract", clean_text(abstract))
            result.setdefault("abstract_source", f"publisher_meta:{key}")
            break
    return result


def should_enrich(record: dict[str, Any]) -> bool:
    if record.get("date_confidence") == "A" and record.get("accepted_date"):
        return False
    url = record.get("url") or (f"https://doi.org/{record['doi']}" if record.get("doi") else None)
    return bool(url and str(url).startswith(("http://", "https://")))


def candidate_urls(record: dict[str, Any]) -> list[str]:
    urls = []
    if record.get("url"):
        urls.append(str(record["url"]))
    doi = record.get("doi")
    if doi:
        doi = str(doi).strip()
        urls.append(f"https://doi.org/{doi}")
        if doi.startswith("10.1080/"):
            urls.append(f"https://www.tandfonline.com/doi/full/{doi}")
        if doi.startswith("10.1016/"):
            urls.append(f"https://www.sciencedirect.com/science/article/pii/{doi.rsplit('.', 1)[-1]}")
        if doi.startswith("10.1093/"):
            urls.append(f"https://academic.oup.com/search-results?page=1&q={doi}")
        if doi.startswith("10.1111/") or doi.startswith("10.1002/"):
            urls.append(f"https://onlinelibrary.wiley.com/doi/full/{doi}")
    return list(dict.fromkeys(urls))


def enrich_record(record: dict[str, Any], timeout: int) -> tuple[bool, str]:
    urls = candidate_urls(record)
    if not urls:
        return False, "missing-url"
    metadata: dict[str, str] = {}
    last_status = "no-metadata"
    for url in urls:
        try:
            html = fetch_text(str(url), timeout=timeout)
            metadata = extract_page_metadata(html)
            if metadata:
                break
        except Exception as exc:  # noqa: BLE001
            last_status = type(exc).__name__
            continue
    changed = False
    if not metadata:
        changed = correct_tandf_date(record)
        return changed, "tandf-date-corrected" if changed else last_status
    for field, value in metadata.items():
        if value and record.get(field) != value:
            record[field] = value
            changed = True
    changed = correct_tandf_date(record) or changed
    return changed, "updated" if changed else "unchanged"


def correct_tandf_date(record: dict[str, Any]) -> bool:
    doi = str(record.get("doi") or "")
    if not doi.startswith("10.1080/"):
        return False
    issue_date = record.get("issue_date")
    current = record.get("available_online") or record.get("published_online")
    if not issue_date or not current:
        return False
    try:
        issue = date.fromisoformat(str(issue_date))
        online = date.fromisoformat(str(current))
    except ValueError:
        return False
    if not (date(2020, 1, 1) <= issue <= online and (online - issue).days <= 14):
        return False
    changed = False
    for field in ("available_online", "published_online"):
        if record.get(field) != issue.isoformat():
            record[field] = issue.isoformat()
            changed = True
    if changed:
        record["date_source"] = "tandf_issue_date_fallback"
        record["date_confidence"] = "B"
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=today_str())
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    path = args.daily_dir / f"{args.date}.json"
    records = read_json(path, [])
    attempted = changed = 0
    messages: list[str] = []
    for record in records:
        if attempted >= args.limit:
            break
        if not should_enrich(record):
            continue
        attempted += 1
        try:
            did_change, status = enrich_record(record, args.timeout)
            changed += int(did_change)
            if status not in {"no-dates", "no-metadata"}:
                messages.append(f"{record.get('journal')}: {status}")
        except Exception as exc:  # noqa: BLE001
            messages.append(f"{record.get('journal')}: {type(exc).__name__}")
            continue

    if changed:
        write_json(path, records)
    record_source("publisher-detail", ok=True, count=changed, message=f"attempted={attempted}; " + "; ".join(messages[-20:]))
    print(f"publisher detail attempted={attempted} changed={changed}")


if __name__ == "__main__":
    main()
