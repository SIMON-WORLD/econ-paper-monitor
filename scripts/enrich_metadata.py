"""Enrich daily records from publisher article pages.

This step is intentionally best-effort. It should improve metadata when
publisher pages are accessible, but never block the monitor when a site uses
Cloudflare, CAPTCHA, or institutional access controls.
"""

from __future__ import annotations

import argparse
import html as html_lib
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from common import DATA_DIR, date_from_parts, fetch_json, fetch_text, read_json, today_str, write_json
from status import load_status, now, record_source, save_status


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


def fetch_text_and_url(url: str, timeout: int) -> tuple[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        final_url = response.geturl()
    for encoding in (charset, "utf-8", "gb18030"):
        try:
            return payload.decode(encoding), final_url
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace"), final_url


def extract_elsevier_pii(*values: str | None) -> str | None:
    haystack = " ".join(value or "" for value in values)
    haystack = urllib.parse.unquote(html_lib.unescape(haystack))
    match = re.search(r"\b(S\d{14,18}[0-9X])\b", haystack, flags=re.I)
    return match.group(1).upper() if match else None


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


def crossref_doi_metadata(doi: str, timeout: int) -> dict[str, str]:
    try:
        payload = fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}", timeout=timeout)
        item = payload.get("message") or {}
    except Exception:
        return {}
    published_online = date_from_parts(item.get("published-online"))
    published = date_from_parts(item.get("published"))
    published_print = date_from_parts(item.get("published-print"))
    issued = date_from_parts(item.get("issued"))
    created = date_from_parts(item.get("created"))
    result: dict[str, str] = {}
    if published_online:
        result["available_online"] = published_online
        result["published_online"] = published_online
        result["date_source"] = "crossref_doi_published_online"
        result["date_confidence"] = "C"
    elif published:
        result["issue_date"] = published
        result["date_source"] = "crossref_doi_published"
        result["date_confidence"] = "C"
    elif published_print or issued:
        result["issue_date"] = published_print or issued or ""
        result["date_source"] = "crossref_doi_issue"
        result["date_confidence"] = "D"
    elif created:
        result["issue_date"] = created
        result["date_source"] = "crossref_doi_created"
        result["date_confidence"] = "D"
    abstract = item.get("abstract")
    if abstract and len(clean_text(str(abstract))) > 80:
        result["abstract"] = clean_text(str(abstract))
        result["abstract_source"] = "crossref_doi"
    return {key: value for key, value in result.items() if value}


def openalex_abstract(index: Any) -> str | None:
    if not isinstance(index, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in index.items():
        if not isinstance(indexes, list):
            continue
        for pos in indexes:
            try:
                positions.append((int(pos), str(word)))
            except Exception:
                continue
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))


def openalex_doi_metadata(doi: str, timeout: int) -> dict[str, str]:
    try:
        payload = fetch_json(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}", timeout=timeout)
    except Exception:
        return {}
    published = payload.get("publication_date")
    result: dict[str, str] = {}
    parsed = parse_date(str(published)) if published else None
    if parsed:
        result["available_online"] = parsed
        result["published_online"] = parsed
        result["date_source"] = "openalex_publication_date"
        result["date_confidence"] = "C"
    abstract = openalex_abstract(payload.get("abstract_inverted_index"))
    if abstract and len(clean_text(abstract)) > 80:
        result["abstract"] = clean_text(abstract)
        result["abstract_source"] = "openalex"
    return result


def unpaywall_doi_metadata(doi: str, timeout: int) -> dict[str, str]:
    email = os.environ.get("UNPAYWALL_EMAIL") or os.environ.get("CROSSREF_MAILTO") or "econ-paper-monitor@example.com"
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
    try:
        payload = fetch_json(url, timeout=timeout)
    except Exception:
        return {}
    result: dict[str, str] = {}
    parsed = parse_date(str(payload.get("published_date") or "")) if payload.get("published_date") else None
    if parsed:
        result["available_online"] = parsed
        result["published_online"] = parsed
        result["date_source"] = "unpaywall_published_date"
        result["date_confidence"] = "C"
    return result


def append_date_evidence(record: dict[str, Any], source: str, metadata: dict[str, str]) -> bool:
    if not metadata:
        return False
    raw_data = record.setdefault("raw_data", {})
    if not isinstance(raw_data, dict):
        raw_data = {}
        record["raw_data"] = raw_data
    evidence = raw_data.setdefault("date_evidence", [])
    if not isinstance(evidence, list):
        evidence = []
        raw_data["date_evidence"] = evidence
    item = {
        "source": source,
        "date_source": metadata.get("date_source"),
        "published_online": metadata.get("published_online"),
        "available_online": metadata.get("available_online"),
        "issue_date": metadata.get("issue_date"),
        "accepted_date": metadata.get("accepted_date"),
        "date_confidence": metadata.get("date_confidence"),
    }
    signature = (item["source"], item["date_source"], item["published_online"], item["issue_date"], item["accepted_date"])
    existing = {
        (entry.get("source"), entry.get("date_source"), entry.get("published_online"), entry.get("issue_date"), entry.get("accepted_date"))
        for entry in evidence
        if isinstance(entry, dict)
    }
    if signature not in existing:
        evidence.append({key: value for key, value in item.items() if value})
        return True
    return False


def api_fallback_metadata(record: dict[str, Any], doi: str, timeout: int) -> tuple[dict[str, str], str]:
    providers = [
        ("crossref-doi", crossref_doi_metadata),
        ("openalex", openalex_doi_metadata),
        ("unpaywall", unpaywall_doi_metadata),
    ]
    first: dict[str, str] = {}
    first_source = "api-fallback-empty"
    evidence_changed = False
    for source, getter in providers:
        metadata = getter(doi, timeout)
        evidence_changed = append_date_evidence(record, source, metadata) or evidence_changed
        if metadata and not first:
            first = metadata
            first_source = f"{source}-fallback"
        elif metadata and "abstract" in metadata and "abstract" not in first:
            first["abstract"] = metadata["abstract"]
            first["abstract_source"] = metadata.get("abstract_source", source)
    if evidence_changed:
        first["_evidence_changed"] = "true"
    return first, first_source


def should_enrich(record: dict[str, Any]) -> bool:
    source_type = str(record.get("source_type") or "")
    if str(record.get("source") or "") == "working_papers" or source_type in {"working_paper", "policy_paper", "aggregator"}:
        return False
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
            pii = extract_elsevier_pii(record.get("pii"), record.get("url"), record.get("source_url"))
            if pii:
                urls.append(f"https://www.sciencedirect.com/science/article/pii/{pii}")
        if doi.startswith("10.1093/"):
            urls.append(f"https://academic.oup.com/search-results?page=1&q={doi}")
        if doi.startswith("10.1111/") or doi.startswith("10.1002/"):
            urls.append(f"https://onlinelibrary.wiley.com/doi/full/{doi}")
    return list(dict.fromkeys(urls))


def publisher_bucket(record: dict[str, Any]) -> str:
    doi = str(record.get("doi") or "").strip().lower()
    url = " ".join(str(record.get(key) or "").lower() for key in ("url", "source_url"))
    journal = str(record.get("journal") or "").lower()
    haystack = f"{doi} {url} {journal}"
    if doi.startswith("10.1016/") or "sciencedirect.com" in haystack or "elsevier" in haystack:
        return "Elsevier"
    if doi.startswith("10.1080/") or "tandfonline.com" in haystack or "taylor" in haystack:
        return "Taylor & Francis"
    if doi.startswith(("10.1111/", "10.1002/")) or "onlinelibrary.wiley.com" in haystack or "wiley" in haystack:
        return "Wiley"
    if doi.startswith("10.1093/") or "academic.oup.com" in haystack or "oxford" in haystack:
        return "OUP"
    return "Other"


def has_ab_date(record: dict[str, Any]) -> bool:
    confidence = str(record.get("date_confidence") or "")
    return confidence in {"A", "B"} and bool(
        record.get("available_online") or record.get("published_online") or record.get("accepted_date")
    )


def enrich_record(record: dict[str, Any], timeout: int) -> tuple[bool, str]:
    urls = candidate_urls(record)
    if not urls:
        return False, "missing-url"
    metadata: dict[str, str] = {}
    last_status = "no-metadata"
    doi = str(record.get("doi") or "").strip()
    resolved_elsevier_pii = False
    for url in urls:
        try:
            html, final_url = fetch_text_and_url(str(url), timeout)
            pii = extract_elsevier_pii(final_url, html) if doi.startswith("10.1016/") else None
            if pii and record.get("pii") != pii:
                record["pii"] = pii
                resolved_elsevier_pii = True
            metadata = extract_page_metadata(html)
            if metadata:
                break
        except Exception as exc:  # noqa: BLE001
            last_status = type(exc).__name__
            continue
    changed = False
    if not metadata:
        if doi:
            metadata, api_status = api_fallback_metadata(record, doi, timeout)
            if metadata:
                last_status = api_status
        if resolved_elsevier_pii:
            changed = True
        if not metadata:
            changed = correct_tandf_date(record) or changed
            if changed and resolved_elsevier_pii:
                return changed, "elsevier-pii-only"
            return changed, "tandf-date-corrected" if changed else last_status
    for field, value in metadata.items():
        if field == "_evidence_changed":
            changed = True
            continue
        if value and record.get(field) != value:
            record[field] = value
            changed = True
    changed = correct_tandf_date(record) or changed
    if resolved_elsevier_pii and not changed:
        changed = True
    if last_status.endswith("-fallback"):
        return changed, last_status
    return changed, "updated" if changed else "metadata-unchanged"


def record_publisher_group(stats: dict[str, dict[str, Any]]) -> None:
    status = load_status()
    publishers = []
    for core_publisher in ("Elsevier", "Taylor & Francis", "Wiley", "OUP"):
        stats.setdefault(
            core_publisher,
            {"attempted": 0, "changed": 0, "ab_dates": 0, "failures": 0, "status_counts": Counter()},
        )
    for publisher, item in sorted(stats.items()):
        attempted = int(item.get("attempted") or 0)
        ab_dates = int(item.get("ab_dates") or 0)
        failures = int(item.get("failures") or 0)
        status_counts = item.get("status_counts") or {}
        top_status = ", ".join(f"{key}:{value}" for key, value in Counter(status_counts).most_common(4))
        publishers.append(
            {
                "publisher": publisher,
                "attempted": attempted,
                "changed": int(item.get("changed") or 0),
                "ab_dates": ab_dates,
                "success_rate": round(ab_dates / attempted, 4) if attempted else 0,
                "failures": failures,
                "statuses": dict(sorted(status_counts.items())),
                "message": top_status,
            }
        )
    status.setdefault("source_groups", {})["publisher-detail"] = {
        "updated_at": now(),
        "publishers": publishers,
    }
    save_status(status)


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
    publisher_stats: dict[str, dict[str, Any]] = {}
    for record in records:
        if attempted >= args.limit:
            break
        if not should_enrich(record):
            continue
        attempted += 1
        bucket = publisher_bucket(record)
        stats = publisher_stats.setdefault(
            bucket,
            {"attempted": 0, "changed": 0, "ab_dates": 0, "failures": 0, "status_counts": Counter()},
        )
        stats["attempted"] += 1
        try:
            did_change, status = enrich_record(record, args.timeout)
            changed += int(did_change)
            stats["changed"] += int(did_change)
            stats["status_counts"][status] += 1
            record_has_ab_date = has_ab_date(record)
            if record_has_ab_date:
                stats["ab_dates"] += 1
            if not record_has_ab_date and status not in {"updated", "metadata-unchanged", "tandf-date-corrected"}:
                stats["failures"] += 1
            if status not in {"no-dates", "no-metadata"}:
                messages.append(f"{record.get('journal')}: {status}")
        except Exception as exc:  # noqa: BLE001
            error_name = type(exc).__name__
            stats["failures"] += 1
            stats["status_counts"][error_name] += 1
            messages.append(f"{record.get('journal')}: {error_name}")
            continue

    if changed:
        write_json(path, records)
    record_source("publisher-detail", ok=True, count=changed, message=f"attempted={attempted}; " + "; ".join(messages[-20:]))
    record_publisher_group(publisher_stats)
    print(f"publisher detail attempted={attempted} changed={changed}")


if __name__ == "__main__":
    main()
