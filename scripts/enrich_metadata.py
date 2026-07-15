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
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, date_from_parts, fetch_json, fetch_text, read_json, today_str, write_json
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


def crossref_created_date(item: dict[str, Any]) -> str | None:
    created = item.get("created")
    if not isinstance(created, dict):
        return None
    date_time = created.get("date-time")
    if isinstance(date_time, str) and date_time:
        try:
            parsed = datetime.fromisoformat(date_time.replace("Z", "+00:00"))
            return parsed.astimezone(BEIJING_TZ).date().isoformat()
        except ValueError:
            pass
    return date_from_parts(created)


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
    if "abstract" not in result:
        abstract_patterns = (
            r'<div\b[^>]*class=["\'][^"\']*\babstract\b[^"\']*["\'][^>]*>[\s\S]*?<h[1-6]\b[^>]*>\s*Abstract\s*</h[1-6]>([\s\S]*?)</div>\s*</div>',
            r'<section\b[^>]*class=["\'][^"\']*\babstract\b[^"\']*["\'][^>]*>[\s\S]*?<h[1-6]\b[^>]*>\s*Abstract\s*</h[1-6]>([\s\S]*?)</section>',
        )
        for pattern in abstract_patterns:
            match = re.search(pattern, html, flags=re.I)
            abstract = clean_text(match.group(1)) if match else ""
            if len(abstract) > 80:
                result["abstract"] = abstract
                result["abstract_source"] = "publisher_body:abstract"
                break
    return result


def extract_markdown_abstract(markdown: str) -> str | None:
    match = re.search(r"(?ims)^##\s+Abstract\s*$\s*(.*?)(?=^##\s+|\Z)", markdown)
    if not match:
        return None
    abstract = match.group(1)
    abstract = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", abstract)
    abstract = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", abstract)
    abstract = re.sub(r"[*_`#>]", " ", abstract)
    abstract = re.sub(r"\s+", " ", html_lib.unescape(abstract)).strip()
    return abstract if len(abstract) > 80 else None


def elsevier_api_metadata(doi: str, timeout: int) -> dict[str, str]:
    encoded_doi = urllib.parse.quote(doi, safe="")
    url = f"https://api.elsevier.com/content/article/doi/{encoded_doi}?httpAccept=application%2Fjson"
    try:
        payload = fetch_json(url, timeout=timeout)
    except Exception:
        return {}
    response = payload.get("full-text-retrieval-response") if isinstance(payload, dict) else None
    core = response.get("coredata") if isinstance(response, dict) else None
    if not isinstance(core, dict):
        return {}
    result: dict[str, str] = {}
    pii = extract_elsevier_pii(str(core.get("prism:url") or ""), str(core.get("pii") or ""))
    if pii:
        result["pii"] = pii
    display_date = str(core.get("prism:coverDisplayDate") or "")
    cover_date = str(core.get("prism:coverDate") or "")
    parsed = parse_date(display_date) or parse_date(cover_date)
    if parsed and "available online" in display_date.casefold():
        result["available_online"] = parsed
        result["published_online"] = parsed
        result["date_source"] = "elsevier_article_api"
        result["date_confidence"] = "B"
    abstract = core.get("dc:description")
    if abstract and len(clean_text(str(abstract))) > 80:
        result["abstract"] = clean_text(str(abstract))
        result["abstract_source"] = "elsevier_article_api"
    return result


def publisher_proxy_metadata(url: str, timeout: int) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.casefold()
    allowed_hosts = {
        "www.sciencedirect.com",
        "sciencedirect.com",
        "onlinelibrary.wiley.com",
        "www.tandfonline.com",
        "tandfonline.com",
        "academic.oup.com",
    }
    if host not in allowed_hosts:
        return {}
    target = f"http://{host}{parsed.path}"
    if parsed.query:
        target += f"?{parsed.query}"
    try:
        markdown = fetch_text(f"https://r.jina.ai/{target}", timeout=timeout)
    except Exception:
        return {"_status": "proxy-request-failed"}
    lowered = markdown.casefold()
    if "are you a robot" in lowered or "requiring captcha" in lowered or "captcha challenge" in lowered:
        return {"_status": "blocked-captcha"}
    abstract = extract_markdown_abstract(markdown)
    if not abstract:
        return {"_status": "abstract-not-exposed"}
    return {"abstract": abstract, "abstract_source": "publisher_page_via_readonly_proxy"}


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
    created = crossref_created_date(item)
    issue_date = published_print or published or issued
    result: dict[str, str] = {}
    if published_online:
        result["available_online"] = published_online
        result["published_online"] = published_online
        result["date_source"] = "crossref_doi_published_online"
        result["date_confidence"] = "C"
    elif doi.startswith("10.1016/") and created:
        result["available_online"] = created
        result["published_online"] = created
        if issue_date:
            result["issue_date"] = issue_date
        result["date_source"] = "crossref_doi_elsevier_created_online"
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


def merge_metadata(record: dict[str, Any], metadata: dict[str, str]) -> bool:
    changed = False
    confidence_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4, "unknown": 5, "": 6}
    existing_confidence = str(record.get("date_confidence") or "")
    incoming_confidence = str(metadata.get("date_confidence") or "")
    protect_existing_dates = bool(record.get("available_online") or record.get("published_online")) and (
        confidence_rank.get(incoming_confidence, 6) > confidence_rank.get(existing_confidence, 6)
    )
    date_fields = {
        "accepted_date",
        "available_online",
        "published_online",
        "issue_date",
        "date_source",
        "date_confidence",
    }
    for field, value in metadata.items():
        if field == "_evidence_changed":
            changed = True
            continue
        if protect_existing_dates and field in date_fields and record.get(field):
            continue
        if value and record.get(field) != value:
            record[field] = value
            changed = True
    return changed


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


def enrich_priority(record: dict[str, Any]) -> tuple[int, int, int, float]:
    bucket = publisher_bucket(record)
    core_rank = {"Elsevier": 0, "Taylor & Francis": 1, "Wiley": 2, "OUP": 3}.get(bucket, 8)
    confidence = str(record.get("date_confidence") or "F")
    weak_date = 0 if not has_ab_date(record) or confidence in {"C", "D", "F", "unknown"} else 1
    missing_abstract = 0 if not str(record.get("abstract") or "").strip() else 1
    try:
        detected_rank = -datetime.fromisoformat(str(record.get("detected_at") or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        detected_rank = 0.0
    return (weak_date, missing_abstract, core_rank, detected_rank)


def enrich_record(record: dict[str, Any], timeout: int, allow_proxy_abstract: bool = True) -> tuple[bool, str]:
    urls = candidate_urls(record)
    if not urls:
        return False, "missing-url"
    metadata: dict[str, str] = {}
    last_status = "no-metadata"
    doi = str(record.get("doi") or "").strip()
    resolved_elsevier_pii = False
    elsevier_api_attempted = False
    missing_abstract = not str(record.get("abstract") or "").strip()
    changed = False
    if doi.startswith("10.1016/") and not has_ab_date(record):
        metadata = crossref_doi_metadata(doi, timeout)
        evidence_changed = append_date_evidence(record, "crossref-doi", metadata)
        if metadata:
            metadata_changed = merge_metadata(record, metadata)
            changed = evidence_changed or metadata_changed or changed
            last_status = "crossref-doi-fallback"
            if not missing_abstract:
                return changed, last_status
            metadata = {}
        if evidence_changed:
            changed = True
            last_status = "crossref-doi-evidence"

    if missing_abstract and publisher_bucket(record) == "Elsevier":
        if doi.startswith("10.1016/"):
            elsevier_api_attempted = True
            elsevier_metadata = elsevier_api_metadata(doi, timeout)
            if elsevier_metadata:
                changed = append_date_evidence(record, "elsevier-article-api", elsevier_metadata) or changed
                changed = merge_metadata(record, elsevier_metadata) or changed
                if elsevier_metadata.get("pii"):
                    resolved_elsevier_pii = True
                last_status = "elsevier-article-api"
        pii = extract_elsevier_pii(record.get("pii"), record.get("url"), record.get("source_url"))
        if allow_proxy_abstract and pii:
            proxy_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
            proxy_metadata = publisher_proxy_metadata(proxy_url, timeout)
            if proxy_metadata.get("abstract"):
                changed = merge_metadata(record, proxy_metadata) or changed
                return changed, "publisher-proxy-abstract"
            return changed, str(proxy_metadata.get("_status") or "abstract-proxy-empty")
        if pii:
            return changed, "elsevier-metadata-only"
    for url in urls:
        try:
            html, final_url = fetch_text_and_url(str(url), timeout)
            pii = extract_elsevier_pii(final_url, html) if doi.startswith("10.1016/") else None
            if pii and record.get("pii") != pii:
                record["pii"] = pii
                resolved_elsevier_pii = True
                pii_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
                if pii_url not in urls:
                    urls.append(pii_url)
            metadata = extract_page_metadata(html)
            if metadata:
                break
        except Exception as exc:  # noqa: BLE001
            last_status = type(exc).__name__
            continue
    if not metadata:
        if doi:
            metadata, api_status = api_fallback_metadata(record, doi, timeout)
            if metadata:
                last_status = api_status
        if resolved_elsevier_pii:
            changed = True
    if metadata:
        changed = merge_metadata(record, metadata) or changed

    if not elsevier_api_attempted and doi.startswith("10.1016/") and (
        missing_abstract or not has_ab_date(record) or str(record.get("date_confidence") or "") in {"C", "D", "F", "unknown"}
    ):
        elsevier_metadata = elsevier_api_metadata(doi, timeout)
        if elsevier_metadata:
            changed = append_date_evidence(record, "elsevier-article-api", elsevier_metadata) or changed
            changed = merge_metadata(record, elsevier_metadata) or changed
            if elsevier_metadata.get("pii"):
                resolved_elsevier_pii = True
            last_status = "elsevier-article-api"

    if missing_abstract and allow_proxy_abstract and not str(record.get("abstract") or "").strip():
        proxy_url = ""
        pii = extract_elsevier_pii(record.get("pii"), record.get("url"), record.get("source_url"))
        if pii:
            proxy_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
        else:
            for candidate in candidate_urls(record):
                if urllib.parse.urlparse(candidate).netloc.casefold() in {
                    "onlinelibrary.wiley.com",
                    "www.tandfonline.com",
                    "tandfonline.com",
                    "academic.oup.com",
                }:
                    proxy_url = candidate
                    break
        proxy_metadata = publisher_proxy_metadata(proxy_url, timeout) if proxy_url else {}
        if proxy_metadata:
            changed = merge_metadata(record, proxy_metadata) or changed
            last_status = "publisher-proxy-abstract"

    if missing_abstract and doi and not str(record.get("abstract") or "").strip():
        api_metadata, api_status = api_fallback_metadata(record, doi, timeout)
        abstract = api_metadata.get("abstract")
        if abstract:
            record["abstract"] = abstract
            record["abstract_source"] = api_metadata.get("abstract_source", api_status)
            changed = True
            last_status = "abstract-api-fallback"
        elif api_metadata.get("_evidence_changed"):
            changed = True
            last_status = "abstract-api-no-abstract"
    changed = correct_tandf_date(record) or changed
    if resolved_elsevier_pii and not changed:
        changed = True
    if not metadata and not changed:
        return False, last_status
    if last_status.endswith("-fallback"):
        return changed, last_status
    return changed, "updated" if changed else "metadata-unchanged"


def enrich_abstract_record(record: dict[str, Any], timeout: int) -> tuple[bool, str]:
    if str(record.get("abstract") or "").strip():
        return False, "abstract-present"
    changed = False
    bucket = publisher_bucket(record)
    doi = str(record.get("doi") or "").strip()
    proxy_url = ""
    if doi:
        for source, getter in (("crossref-doi", crossref_doi_metadata), ("openalex", openalex_doi_metadata)):
            metadata = getter(doi, timeout)
            if not metadata:
                continue
            changed = append_date_evidence(record, source, metadata) or changed
            changed = merge_metadata(record, metadata) or changed
            if str(record.get("abstract") or "").strip():
                return True, f"abstract-updated:{source}"
    if bucket == "Elsevier":
        if doi.startswith("10.1016/"):
            metadata = elsevier_api_metadata(doi, timeout)
            if metadata:
                changed = append_date_evidence(record, "elsevier-article-api", metadata) or changed
                changed = merge_metadata(record, metadata) or changed
        pii = extract_elsevier_pii(record.get("pii"), record.get("url"), record.get("source_url"))
        if pii:
            proxy_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
    elif bucket in {"Taylor & Francis", "Wiley", "OUP"}:
        for candidate in candidate_urls(record):
            if urllib.parse.urlparse(candidate).netloc.casefold() in {
                "onlinelibrary.wiley.com",
                "www.tandfonline.com",
                "tandfonline.com",
                "academic.oup.com",
            }:
                proxy_url = candidate
                break
    if not proxy_url:
        return changed, "abstract-route-missing" if not changed else "metadata-only"
    metadata = publisher_proxy_metadata(proxy_url, timeout)
    if not metadata.get("abstract"):
        proxy_status = str(metadata.get("_status") or "abstract-proxy-empty")
        return changed, proxy_status if not changed else f"metadata-only:{proxy_status}"
    changed = merge_metadata(record, metadata) or changed
    return changed, "abstract-updated"


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
    parser.add_argument("--doi", default=None, help="Only enrich the matching DOI (useful for retries and audits).")
    parser.add_argument("--latest-days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--proxy-abstract-limit", type=int, default=20)
    parser.add_argument("--abstract-only", action="store_true", help="Skip slow publisher HTML and only run abstract fallbacks.")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    try:
        anchor = date.fromisoformat(args.date)
    except ValueError:
        anchor = date.fromisoformat(today_str())
    paths = [
        args.daily_dir / f"{(anchor - timedelta(days=offset)).isoformat()}.json"
        for offset in range(max(1, args.latest_days))
    ]
    attempted = changed = 0
    messages: list[str] = []
    publisher_stats: dict[str, dict[str, Any]] = {}
    records_by_path: dict[Path, list[dict[str, Any]]] = {}
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        records = read_json(path, [])
        records_by_path[path] = records
        candidates.extend(
            (path, record)
            for record in records
            if should_enrich(record)
            and (not args.doi or str(record.get("doi") or "").strip().casefold() == args.doi.strip().casefold())
        )
    candidates.sort(key=lambda item: enrich_priority(item[1]))

    changed_paths: set[Path] = set()
    proxy_abstract_attempted = 0
    for path, record in candidates:
        if attempted >= args.limit:
            break
        attempted += 1
        bucket = publisher_bucket(record)
        stats = publisher_stats.setdefault(
            bucket,
            {"attempted": 0, "changed": 0, "ab_dates": 0, "failures": 0, "status_counts": Counter()},
        )
        stats["attempted"] += 1
        try:
            needs_proxy = not str(record.get("abstract") or "").strip() and publisher_bucket(record) in {
                "Elsevier",
                "Taylor & Francis",
                "Wiley",
                "OUP",
            }
            allow_proxy = needs_proxy and proxy_abstract_attempted < max(0, args.proxy_abstract_limit)
            if allow_proxy:
                proxy_abstract_attempted += 1
            if args.abstract_only:
                did_change, status = enrich_abstract_record(record, args.timeout)
            else:
                did_change, status = enrich_record(record, args.timeout, allow_proxy_abstract=allow_proxy)
            changed += int(did_change)
            if did_change:
                changed_paths.add(path)
            stats["changed"] += int(did_change)
            stats["status_counts"][status] += 1
            record_has_ab_date = has_ab_date(record)
            if record_has_ab_date:
                stats["ab_dates"] += 1
            if not record_has_ab_date and status not in {"updated", "metadata-unchanged", "tandf-date-corrected"}:
                stats["failures"] += 1
            if status not in {"no-dates", "no-metadata"}:
                messages.append(f"{path.stem} {record.get('journal')}: {status}")
        except Exception as exc:  # noqa: BLE001
            error_name = type(exc).__name__
            stats["failures"] += 1
            stats["status_counts"][error_name] += 1
            messages.append(f"{path.stem} {record.get('journal')}: {error_name}")
            continue

    for path in sorted(changed_paths):
        write_json(path, records_by_path[path])
    record_source(
        "publisher-detail",
        ok=True,
        count=changed,
        message=f"attempted={attempted}; proxy_abstract_attempted={proxy_abstract_attempted}; " + "; ".join(messages[-20:]),
    )
    record_publisher_group(publisher_stats)
    print(f"publisher detail attempted={attempted} changed={changed}")


if __name__ == "__main__":
    main()
