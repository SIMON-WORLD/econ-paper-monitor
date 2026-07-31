"""Enrich daily records from publisher article pages.

This step is intentionally best-effort. It should improve metadata when
publisher pages are accessible, but never block the monitor when a site uses
Cloudflare, CAPTCHA, or institutional access controls.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, date_from_parts, fetch_json, fetch_text, normalize_doi, read_json, today_str, write_json
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


def meta_values(html: str, names: tuple[str, ...]) -> list[str]:
    wanted = {name.casefold() for name in names}
    values: list[str] = []
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        key_match = re.search(r"(?:name|property)=['\"]([^'\"]+)['\"]", tag, flags=re.I)
        content_match = re.search(r"content=['\"]([^'\"]*)['\"]", tag, flags=re.I)
        if not key_match or not content_match or key_match.group(1).casefold() not in wanted:
            continue
        value = clean_text(content_match.group(1))
        if value and value not in values:
            values.append(value)
    return values


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


def extract_page_metadata(html: str) -> dict[str, Any]:
    meta = parse_meta(html)
    text = clean_text(html)
    result: dict[str, Any] = {}
    authors = meta_values(html, ("citation_author", "dc.creator", "dc.contributor.author"))
    if authors:
        result["authors"] = authors[:12]

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


def fetch_elsevier_json(url: str, timeout: int, api_key: str = "", insttoken: str = "") -> dict[str, Any]:
    headers = {
        "User-Agent": "econ-paper-monitor/1.0 (https://github.com/academic-door/econ-paper-monitor)",
        "Accept": "application/json",
    }
    if api_key:
        headers["X-ELS-APIKey"] = api_key
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def nested_text(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return clean_text(" ".join(nested_text(item) for item in value))
    if isinstance(value, dict):
        preferred = ("ce:para", "para", "$", "_", "content")
        parts = [nested_text(value[key]) for key in preferred if key in value]
        if not any(parts):
            parts = [nested_text(item) for key, item in value.items() if not str(key).startswith("@")]
        return clean_text(" ".join(part for part in parts if part))
    return ""


def extract_elsevier_api_abstract(response: dict[str, Any], core: dict[str, Any]) -> str | None:
    candidates: list[Any] = [core.get("dc:description")]
    item = response.get("item")
    if isinstance(item, dict):
        bibrecord = item.get("bibrecord")
        if isinstance(bibrecord, dict):
            head = bibrecord.get("head")
            if isinstance(head, dict):
                abstracts = head.get("abstracts")
                if isinstance(abstracts, dict):
                    candidates.append(abstracts.get("abstract"))
                elif abstracts:
                    candidates.append(abstracts)
    original_text = response.get("originalText")
    if isinstance(original_text, str):
        match = re.search(r"<ce:abstract\b[^>]*>([\s\S]*?)</ce:abstract>", original_text, flags=re.I)
        if match:
            candidates.append(match.group(1))
    for candidate in candidates:
        abstract = nested_text(candidate)
        if len(abstract) > 80:
            return abstract
    return None


def elsevier_api_metadata(doi: str, timeout: int) -> dict[str, str]:
    encoded_doi = urllib.parse.quote(doi, safe="")
    api_key = (os.environ.get("ELSEVIER_API_KEY") or os.environ.get("ELS_API_KEY") or "").strip()
    insttoken = (os.environ.get("ELSEVIER_INSTTOKEN") or "").strip()
    query = {"httpAccept": "application/json"}
    if api_key:
        query["view"] = "FULL"
    url = f"https://api.elsevier.com/content/article/doi/{encoded_doi}?{urllib.parse.urlencode(query)}"
    try:
        payload = fetch_elsevier_json(url, timeout=timeout, api_key=api_key, insttoken=insttoken)
    except Exception:
        return {}
    response = payload.get("full-text-retrieval-response") if isinstance(payload, dict) else None
    core = response.get("coredata") if isinstance(response, dict) else None
    if not isinstance(core, dict):
        return {}
    result: dict[str, str] = {}
    abstract = extract_elsevier_api_abstract(response or {}, core)
    if abstract:
        result["abstract"] = abstract
        result["abstract_source"] = "elsevier_api"
    authors = []
    for creator in core.get("dc:creator") or []:
        name = clean_text(str(creator.get("$") or "")) if isinstance(creator, dict) else ""
        if name and name not in authors:
            authors.append(name)
    if authors:
        result["authors"] = authors[:12]
    # Date extraction from Elsevier API
    date_fields = {
        "available_online": core.get("prism:coverDate"),
        "published_online": core.get("prism:coverDate"),
    }
    for field, value in date_fields.items():
        parsed = parse_date(str(value)) if value else None
        if parsed:
            result[field] = parsed
            result.setdefault("date_source", "elsevier_api")
            result.setdefault("date_confidence", "A")
    return result


def publisher_proxy_metadata(url: str, timeout: int) -> dict[str, str]:
    try:
        html, final_url = fetch_text_and_url(url, timeout)
    except Exception as e:
        error_text = str(e).lower()
        if "403" in error_text or "forbidden" in error_text:
            return {"abstract": "CAPTCHA or access control blocked the publisher page.", "abstract_source": "proxy_blocked"}
        return {}
    result = extract_page_metadata(html)
    if not result:
        return {}
    return result


def openalex_abstract(index: Any) -> str | None:
    if not isinstance(index, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, pos_list in index.items():
        if isinstance(pos_list, list):
            for pos in pos_list:
                if isinstance(pos, int):
                    positions.append((pos, str(word)))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def openalex_doi_metadata(doi: str, timeout: int) -> dict[str, Any]:
    try:
        payload = fetch_json(f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}", timeout=timeout)
    except Exception:
        return {}
    published = payload.get("publication_date")
    result: dict[str, Any] = {}
    authors = []
    for authorship in payload.get("authorships") or []:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = clean_text(str(author.get("display_name") or "")) if isinstance(author, dict) else ""
        if name and name not in authors:
            authors.append(name)
    if authors:
        result["authors"] = authors[:12]
    parsed = parse_date(str(published)) if published else None
    if parsed:
        result["available_online"] = parsed
        result["published_online"] = parsed
        result["date_source"] = "openalex_publication_date"
        # Upgrade to B when publication_date year is in a reasonable range
        try:
            year = int(parsed[:4])
            result["date_confidence"] = "B" if 1990 <= year <= 2030 else "C"
        except (ValueError, IndexError):
            result["date_confidence"] = "C"
    abstract = openalex_abstract(payload.get("abstract_inverted_index"))
    if abstract and len(clean_text(abstract)) > 80:
        result["abstract"] = clean_text(abstract)
        result["abstract_source"] = "openalex"
    return result


def semantic_scholar_doi_metadata(doi: str, timeout: int) -> dict[str, Any]:
    fields = urllib.parse.urlencode({"fields": "abstract,authors,publicationDate,externalIds"})
    try:
        payload = fetch_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}?{fields}",
            timeout=timeout,
        )
    except Exception:
        return {}
    result: dict[str, Any] = {}
    abstract = clean_text(str(payload.get("abstract") or ""))
    if len(abstract) > 80:
        result["abstract"] = abstract
        result["abstract_source"] = "semantic_scholar"
    authors = []
    for author in payload.get("authors") or []:
        name = clean_text(str(author.get("name") or "")) if isinstance(author, dict) else ""
        if name and name not in authors:
            authors.append(name)
    if authors:
        result["authors"] = authors[:12]
    published = parse_date(str(payload.get("publicationDate") or ""))
    if published:
        result["published_online"] = published
        result["date_source"] = "semantic_scholar_publication_date"
        result["date_confidence"] = "C"
    return result


def crossref_doi_metadata(doi: str, timeout: int) -> dict[str, Any]:
    try:
        payload = fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}", timeout=timeout)
    except Exception:
        return {}
    item = (payload.get("message") or {}) if isinstance(payload, dict) else {}
    result: dict[str, Any] = {}
    authors = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = clean_text(" ".join(str(author.get(key) or "") for key in ("given", "family")))
        if name and name not in authors:
            authors.append(name)
    if authors:
        result["authors"] = authors[:12]
    abstract = clean_text(str(item.get("abstract") or ""))
    if len(abstract) > 80:
        result["abstract"] = abstract
        result["abstract_source"] = "crossref"
    # Date extraction
    date_parts = (item.get("published-online") or {}).get("date-parts")
    if date_parts:
        parsed = date_from_parts({"date-parts": date_parts})
        if parsed:
            result["published_online"] = parsed
            result["date_source"] = "crossref_online"
            result["date_confidence"] = "A"
    if not result.get("published_online"):
        date_parts = (item.get("issued") or {}).get("date-parts")
        if date_parts:
            parsed = date_from_parts({"date-parts": date_parts})
            if parsed:
                result["published_online"] = parsed
                result["date_source"] = "crossref_issued"
                result["date_confidence"] = "B"
    if not result.get("published_online"):
        date_parts = (item.get("created") or {}).get("date-parts")
        if date_parts:
            parsed = date_from_parts({"date-parts": date_parts})
            if parsed:
                result["published_online"] = parsed
                result["date_source"] = "crossref_created"
                result["date_confidence"] = "C"
    return result


def crossref_title_metadata(title: str, timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"query.title": title, "rows": 3})
    try:
        payload = fetch_json(f"https://api.crossref.org/works?{query}", timeout=timeout)
    except Exception:
        return {}
    normalized = " ".join(title.casefold().split())
    for item in (payload.get("message") or {}).get("items") or []:
        candidate = " ".join(str(item.get("title", [""])[0] or "").casefold().split())
        if not candidate or (normalized not in candidate and candidate not in normalized):
            continue
        authors = []
        for author in item.get("author") or []:
            if not isinstance(author, dict):
                continue
            name = clean_text(" ".join(str(author.get(key) or "") for key in ("given", "family")))
            if name and name not in authors:
                authors.append(name)
        result: dict[str, Any] = {"authors": authors[:12]} if authors else {}
        doi = item.get("DOI")
        if doi:
            result["doi"] = normalize_doi(str(doi))
        return result
    return {}


def unpaywall_doi_metadata(doi: str, timeout: int) -> dict[str, str]:
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    query = urllib.parse.urlencode({"email": email})
    try:
        payload = fetch_json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?{query}", timeout=timeout)
    except Exception:
        return {}
    result: dict[str, str] = {}
    title = (payload.get("title") or "") if isinstance(payload, dict) else ""
    if title:
        result["title"] = clean_text(str(title))
    genre = (payload.get("genre") or "") if isinstance(payload, dict) else ""
    if genre:
        result["genre"] = clean_text(str(genre))
    return result


def append_date_evidence(record: dict[str, Any], source: str, metadata: dict[str, Any]) -> bool:
    """Record date evidence without overwriting higher-confidence dates."""
    confidence_rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4, "unknown": 5, "": 6}
    existing_conf = str(record.get("date_confidence") or "")
    incoming_conf = str(metadata.get("date_confidence") or "")

    # Never downgrade
    if confidence_rank.get(incoming_conf, 6) > confidence_rank.get(existing_conf, 6):
        return False

    changed = False
    for date_field in ("available_online", "published_online"):
        if metadata.get(date_field) and record.get(date_field) != metadata[date_field]:
            record[date_field] = metadata[date_field]
            changed = True
    for meta_field in ("date_source", "date_confidence"):
        if metadata.get(meta_field) and record.get(meta_field) != metadata[meta_field]:
            record[meta_field] = metadata[meta_field]
            changed = True
    return changed


def api_fallback_metadata(record: dict[str, Any], doi: str, timeout: int) -> tuple[dict[str, Any], str]:
    providers = [
        ("crossref-doi", crossref_doi_metadata),
        ("openalex", openalex_doi_metadata),
        ("semantic-scholar", semantic_scholar_doi_metadata),
        ("unpaywall", unpaywall_doi_metadata),
    ]
    first: dict[str, Any] = {}
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
        if metadata.get("authors") and not first.get("authors"):
            first["authors"] = metadata["authors"]
    if evidence_changed:
        first["_evidence_changed"] = "true"
    return first, first_source


def merge_metadata(record: dict[str, Any], metadata: dict[str, Any]) -> bool:
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
    if source_type == "journal":
        return True
    if source_type == "working_paper":
        return True
    return False


def candidate_urls(record: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    url = record.get("url") or record.get("source_url") or ""
    if url and url.strip():
        urls.append(url.strip())
    doi = record.get("doi")
    if doi:
        doi_clean = normalize_doi(doi)
        if doi_clean:
            urls.append(f"https://doi.org/{doi_clean}")
    for link in record.get("links") or []:
        if isinstance(link, dict):
            href = link.get("href") or link.get("url") or ""
            if href and href.strip():
                urls.append(href.strip())
        elif isinstance(link, str) and link.strip():
            urls.append(link.strip())
    return urls[:5]


def publisher_bucket(record: dict[str, Any]) -> str:
    url = str(record.get("url") or record.get("source_url") or "")
    journal = str(record.get("journal") or "")
    doi = str(record.get("doi") or "")
    combined = f"{url} {journal} {doi}".lower()
    if "elsevier" in combined or "sciencedirect" in combined:
        return "Elsevier"
    if "springer" in combined or "link.springer" in combined:
        return "Springer"
    if "tandfonline" in combined or "taylor" in combined or "tandf" in combined:
        return "Taylor & Francis"
    if "wiley" in combined:
        return "Wiley"
    if "oxford" in combined or "oup" in combined:
        return "OUP"
    if "aeaweb" in combined:
        return "AEA"
    if "uchicago" in combined or "journals.uchicago" in combined:
        return "Chicago"
    if "mitpress" in combined or "direct.mit" in combined:
        return "MIT"
    if "aeaweb.org" in combined:
        return "AEA"
    return "other"


def has_ab_date(record: dict[str, Any]) -> bool:
    return bool(record.get("available_online") or record.get("published_online"))


def enrich_priority(record: dict[str, Any]) -> tuple[int, int, int, int, float]:
    has_abstract = int(bool(str(record.get("abstract") or "").strip()))
    has_authors = int(bool(record.get("authors")))
    has_date = int(has_ab_date(record))
    source_score = 1 if str(record.get("source_type") or "") == "journal" else 0
    date_conf = {"A": 1.0, "B": 0.8, "C": 0.5, "": 0.2, "unknown": 0.1}.get(
        str(record.get("date_confidence") or ""), 0.0
    )
    return (has_abstract, has_authors, has_date, source_score, date_conf)


def abstract_enrich_priority(record: dict[str, Any]) -> tuple[int, float, int]:
    missing = 0 if str(record.get("abstract") or "").strip() else 1
    date_conf = {"A": 1.0, "B": 0.8, "C": 0.5, "": 0.2, "unknown": 0.1}.get(
        str(record.get("date_confidence") or ""), 0.0
    )
    source_score = 1 if str(record.get("source_type") or "") == "journal" else 0
    return (missing, date_conf, source_score)


def enrich_record(record: dict[str, Any], timeout: int, allow_proxy_abstract: bool = True) -> tuple[bool, str]:
    doi = normalize_doi(record.get("doi"))
    changed = False
    status = "no-metadata"

    # Try publisher page first
    urls = candidate_urls(record)
    for url in urls:
        try:
            page_md = publisher_proxy_metadata(url, timeout)
            if page_md:
                if merge_metadata(record, page_md):
                    changed = True
                    status = "updated"
        except Exception:
            continue

    # Try CrossRef
    if doi:
        try:
            cr_md = crossref_doi_metadata(doi, timeout)
            if cr_md and merge_metadata(record, cr_md):
                changed = True
                status = "updated"
        except Exception:
            pass

    # OpenAlex and Semantic Scholar as last resort
    if doi:
        try:
            oa_md = openalex_doi_metadata(doi, timeout)
            if oa_md and merge_metadata(record, oa_md):
                changed = True
                status = "updated"
        except Exception:
            pass

        try:
            ss_md = semantic_scholar_doi_metadata(doi, timeout)
            if ss_md and merge_metadata(record, ss_md):
                changed = True
                status = "updated"
        except Exception:
            pass

    if not changed:
        status = "metadata-unchanged"
    return changed, status


def enrich_abstract_record(record: dict[str, Any], timeout: int) -> tuple[bool, str]:
    doi = normalize_doi(record.get("doi"))
    if not doi:
        return False, "no-doi"

    changed = False
    # Try OpenAlex first
    try:
        oa_md = openalex_doi_metadata(doi, timeout)
        if oa_md.get("abstract"):
            record["abstract"] = oa_md["abstract"]
            record["abstract_source"] = oa_md.get("abstract_source", "openalex")
            changed = True
    except Exception:
        pass

    # Then Semantic Scholar
    if not str(record.get("abstract") or "").strip():
        try:
            ss_md = semantic_scholar_doi_metadata(doi, timeout)
            if ss_md.get("abstract"):
                record["abstract"] = ss_md["abstract"]
                record["abstract_source"] = ss_md.get("abstract_source", "semantic_scholar")
                changed = True
        except Exception:
            pass

    # Then publisher page for abstract only
    if not str(record.get("abstract") or "").strip():
        urls = candidate_urls(record)
        for url in urls[:2]:
            try:
                page_md = publisher_proxy_metadata(url, timeout)
                if page_md.get("abstract"):
                    record["abstract"] = page_md["abstract"]
                    record["abstract_source"] = page_md.get("abstract_source", "publisher_page")
                    changed = True
                    break
            except Exception:
                continue

    return changed, "updated" if changed else "no-abstract-found"


def enrich_author_record(record: dict[str, Any], timeout: int) -> tuple[bool, str]:
    doi = normalize_doi(record.get("doi"))
    if not doi:
        # Try title-based Crossref lookup
        title = str(record.get("title") or "")
        if title.strip():
            try:
                title_md = crossref_title_metadata(title, timeout)
                if title_md.get("authors"):
                    record["authors"] = title_md["authors"]
                    return True, "updated-via-crossref-title"
            except Exception:
                pass
        return False, "no-doi"

    changed = False
    # Try Crossref
    try:
        cr_md = crossref_doi_metadata(doi, timeout)
        if cr_md.get("authors"):
            record["authors"] = cr_md["authors"]
            changed = True
    except Exception:
        pass

    # OpenAlex
    if not record.get("authors"):
        try:
            oa_md = openalex_doi_metadata(doi, timeout)
            if oa_md.get("authors"):
                record["authors"] = oa_md["authors"]
                changed = True
        except Exception:
            pass

    # Semantic Scholar
    if not record.get("authors"):
        try:
            ss_md = semantic_scholar_doi_metadata(doi, timeout)
            if ss_md.get("authors"):
                record["authors"] = ss_md["authors"]
                changed = True
        except Exception:
            pass

    return changed, "updated" if changed else "no-authors-found"


def needs_date_recovery(record: dict[str, Any]) -> bool:
    conf = str(record.get("date_confidence") or "")
    if conf in {"A", "B"}:
        return False
    return not has_ab_date(record)


def queue_metadata_retry(record: dict[str, Any], status: str) -> bool:
    """Record failed enrichment attempts for retry."""
    retries = record.setdefault("_retries", {})
    retries[status] = now()
    return True


def update_abstract_attempt_status(record: dict[str, Any], status: str) -> bool:
    """Track abstract enrichment attempts."""
    attempts = record.setdefault("_abstract_attempts", {})
    attempts[status] = now()
    return False  # This doesn't change the record's content data


def record_publisher_group(stats: dict[str, dict[str, Any]]) -> None:
    """Record publisher-level enrichment stats in status."""
    current = load_status()
    current.setdefault("publisher_detail", {})
    current["publisher_detail"] = stats
    save_status(current)


def correct_tandf_date(record: dict[str, Any]) -> bool:
    """Fix T&F articles where online date mirrors accepted date."""
    journal = str(record.get("journal") or "")
    publisher = str(record.get("publisher") or "")
    if "taylor" not in journal.lower() and "taylor" not in publisher.lower():
        return False
    if "tandf" not in journal.lower() and "tandfonline" not in str(record.get("url") or "").lower():
        return False
    # T&F often has accepted=online dates; flag for review
    if record.get("accepted_date") and record.get("available_online") == record.get("accepted_date"):
        record["date_confidence"] = "B"
        record["date_source"] = "tandf_corrected"
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich daily records with publisher metadata")
    parser.add_argument("--abstract-only", action="store_true")
    parser.add_argument("--authors-only", action="store_true")
    parser.add_argument("--date-only", action="store_true")
    parser.add_argument("--days", type=int, default=7, dest="latest_days")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--source-id", type=str, default="")
    parser.add_argument("--doi", type=str, default="")
    parser.add_argument("--proxy-abstract-limit", type=int, default=15)
    parser.add_argument("--seen", type=str, default="")
    args = parser.parse_args()

    anchor = date.today()
    oldest = anchor - timedelta(days=max(1, args.latest_days) - 1)
    daily_dir = DATA_DIR / "daily"

    records_by_path: dict[Path, dict[str, Any]] = {}
    daily_identities: set[str] = set()
    identity = strong_identity_keys if "strong_identity_keys" in dir() else lambda r: str(r.get("id", ""))  # noqa: E731

    for path in sorted(daily_dir.glob("*.json")):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < oldest or file_date > anchor:
            continue
        records = read_json(path, [])
        if not isinstance(records, list):
            continue
        records_by_path[path] = records
        for record in records:
            if isinstance(record, dict):
                daily_identities.add(identity(record))

    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path, records in records_by_path.items():
        for record in records:
            if not isinstance(record, dict):
                continue
            if identity(record) in daily_identities:
                pass
            if args.abstract_only and str(record.get("abstract") or "").strip():
                continue
            if args.authors_only and record.get("authors"):
                continue
            if args.date_only and has_ab_date(record) and str(record.get("date_confidence") or "") in {"A", "B"}:
                continue
            if args.date_only and not needs_date_recovery(record):
                continue
            if args.source_id and str(record.get("source_id") or "") != args.source_id:
                continue
            if args.doi and str(record.get("doi") or "").strip().casefold() != args.doi.strip().casefold():
                continue
            if should_enrich(record) or args.abstract_only or args.authors_only or args.date_only:
                candidates.append((path, record))

    if args.seen:
        seen_payload = read_json(Path(args.seen), {})
        seen_papers = seen_payload.get("papers") if isinstance(seen_payload, dict) else None
        if isinstance(seen_papers, dict):
            records_by_path[args.seen] = seen_payload
            oldest = anchor - timedelta(days=max(1, args.latest_days) - 1)
            for record in seen_papers.values():
                if not isinstance(record, dict) or identity(record) in daily_identities:
                    continue
                seen_date = str(record.get("first_seen") or "")[:10]
                try:
                    is_recent = date.fromisoformat(seen_date) >= oldest
                except ValueError:
                    is_recent = False
                if (
                    (
                        is_recent
                        or (args.authors_only and not record.get("authors"))
                        or (args.date_only and needs_date_recovery(record))
                    )
                    and (args.authors_only or args.abstract_only or args.date_only or should_enrich(record))
                    and (not args.source_id or str(record.get("source_id") or "") == args.source_id)
                    and (not args.authors_only or not record.get("authors"))
                    and (not args.date_only or needs_date_recovery(record))
                    and (not args.doi or str(record.get("doi") or "").strip().casefold() == args.doi.strip().casefold())
                ):
                    candidates.append((args.seen, record))
    priority = abstract_enrich_priority if args.abstract_only else enrich_priority
    candidates.sort(key=lambda item: priority(item[1]))

    changed_paths: set[Path] = set()
    selected: list[tuple[Path, dict[str, Any], bool]] = []
    proxy_abstract_attempted = 0
    for path, record in candidates[: max(0, args.limit)]:
        bucket = publisher_bucket(record)
        needs_proxy = not str(record.get("abstract") or "").strip() and bucket in {
            "Elsevier",
            "Springer",
            "Taylor & Francis",
            "Wiley",
            "OUP",
        }
        allow_proxy = needs_proxy and proxy_abstract_attempted < max(0, args.proxy_abstract_limit)
        if allow_proxy:
            proxy_abstract_attempted += 1
        selected.append((path, record, allow_proxy))

    def run_candidate(item: tuple[Path, dict[str, Any], bool]) -> tuple[Path, dict[str, Any], bool, str, Exception | None]:
        path, record, allow_proxy = item
        try:
            if args.authors_only:
                did_change, status = enrich_author_record(record, args.timeout)
            elif args.abstract_only:
                did_change, status = enrich_abstract_record(record, args.timeout)
                did_change = update_abstract_attempt_status(record, status) or did_change
            elif args.date_only:
                if str(record.get("source_id") or "") in {"cepr-dp", "fed-feds"}:
                    did_change, status = enrich_abstract_record(record, args.timeout)
                else:
                    did_change, status = enrich_record(record, args.timeout, allow_proxy_abstract=False)
            else:
                did_change, status = enrich_record(record, args.timeout, allow_proxy_abstract=allow_proxy)
        except Exception as exc:  # noqa: BLE001
            return path, record, False, type(exc).__name__, exc
        return path, record, did_change, status, None

    changed = 0
    attempted = 0
    messages: list[str] = []
    publisher_stats: dict[str, dict[str, Any]] = {}

    attempted = len(selected)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        results = executor.map(run_candidate, selected)
        for path, record, did_change, status, error in results:
            bucket = publisher_bucket(record)
            stats = publisher_stats.setdefault(
                bucket,
                {"attempted": 0, "changed": 0, "ab_dates": 0, "failures": 0, "status_counts": Counter()},
            )
            stats["attempted"] += 1
            if error is not None:
                stats["failures"] += 1
                stats["status_counts"][status] += 1
                if queue_metadata_retry(record, status):
                    changed_paths.add(path)
                messages.append(f"{path.stem} {record.get('journal')}: {status}")
                continue
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

    for path in sorted(changed_paths):
        write_json(path, records_by_path[path])
    total_failures = sum(int(item.get("failures") or 0) for item in publisher_stats.values())
    record_source(
        "publisher-detail",
        ok=total_failures == 0,
        count=changed,
        message=f"attempted={attempted}; proxy_abstract_attempted={proxy_abstract_attempted}; " + "; ".join(messages[-20:]),
        details={
            "attempted": attempted,
            "failures": total_failures,
            "retryable": total_failures > 0,
            "fallbacks": ["crossref-doi", "openalex", "readonly-proxy"],
        },
    )
    record_publisher_group(publisher_stats)
    print(f"publisher detail attempted={attempted} changed={changed}")


if __name__ == "__main__":
    main()