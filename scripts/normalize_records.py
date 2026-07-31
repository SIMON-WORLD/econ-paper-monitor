"""Normalize existing daily records after fetch/enrichment steps."""

from __future__ import annotations

import argparse
import html
import re
from datetime import date
from pathlib import Path
from typing import Any

from common import DATA_DIR, clean_abstract_text, read_json, today_str, write_json
from public_integrity import repair_public_integrity
from status import record_source


CN_JOURNAL_IDS = {
    "journal-379b4022ce",
    "journal-edcb877d78",
    "journal-bf2aa9381f",
    "journal-f69300dae2",
    "journal-679eaa2a0c",
    "journal-ba9f46c919",
}

NON_ARTICLE_TITLES = {
    "front matter",
    "back matter",
    "cover",
    "contents",
    "table of contents",
}

# The source registry is authoritative for the public paper/journal split.
# A malformed upstream item must not be able to turn an NBER or other working
# paper record into a journal article merely by carrying a bad source_type.
WORKING_SOURCE_TYPES = {
    "nber": "working_paper",
    "iza": "working_paper",
    "cepr-dp": "working_paper",
    "bis-working-papers": "working_paper",
    "oecd-working-papers": "policy_paper",
    "cesifo-working-papers": "working_paper",
    "fed-feds": "working_paper",
    "imf-working-papers": "policy_paper",
    "world-bank-prwp": "policy_paper",
    "repec-nep": "aggregator",
    "repec-nep-cna": "aggregator",
    "repec-nep-dev": "aggregator",
    "repec-nep-hea": "aggregator",
    "repec-nep-ifn": "aggregator",
    "repec-nep-mac": "aggregator",
    "ssrn-economics-research-network": "aggregator",
    "ssrn-health-economics-network": "aggregator",
    "voxeu-cepr-columns": "policy_commentary",
    "brookings-economic-studies": "policy_commentary",
    "iza-newsroom": "policy_commentary",
}


def has_chinese(value: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value or "")


def clean_inline_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def valid_iso_date(value: Any) -> bool:
    text = str(value or "").strip()
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def normalize_date_fields(record: dict[str, Any]) -> bool:
    """Remove malformed upstream labels before they reach public templates."""
    changed = False
    for field in ("accepted_date", "available_online", "published_online", "issue_date"):
        value = record.get(field)
        if value in (None, "") or valid_iso_date(value):
            continue
        record[field] = None
        changed = True
    if changed and not any(record.get(field) for field in ("accepted_date", "available_online", "published_online", "issue_date")):
        if record.get("date_source") != "unknown":
            record["date_source"] = "unknown"
            changed = True
        if record.get("date_confidence") != "F":
            record["date_confidence"] = "F"
            changed = True
    return changed


def normalize_nep_issue_date(record: dict[str, Any]) -> bool:
    if not str(record.get("source_id") or "").startswith("repec-nep-"):
        return False
    if str(record.get("date_source") or "") != "nep_issue_date":
        return False
    first_seen = str(record.get("first_seen_at") or record.get("first_seen") or "")[:10]
    if not valid_iso_date(first_seen):
        return False
    current = str(record.get("available_online") or record.get("published_online") or "")[:10]
    if not valid_iso_date(current) or current <= first_seen:
        return False
    record["available_online"] = first_seen
    record["published_online"] = first_seen
    record["date_source"] = "nep_first_seen_issue_date"
    return True


def canonical_title_text(value: Any) -> str:
    text = clean_inline_html(value).casefold()
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_cepr_paper_number(record: dict[str, Any], title: str) -> tuple[str, bool]:
    if str(record.get("source_id") or "") != "cepr-dp":
        return title, False
    match = re.match(r"^(DP\d{4,6})\s+(.+)$", title.strip(), flags=re.IGNORECASE)
    if not match:
        return title, False
    paper_number, clean_title = match.groups()
    changed = False
    if record.get("paper_number") != paper_number.upper():
        record["paper_number"] = paper_number.upper()
        changed = True
    if clean_title and clean_title != title:
        record["title"] = clean_title
        record.pop("title_zh", None)
        record.pop("translation_status", None)
        changed = True
    return clean_title, changed


def looks_like_abstract(value: str | None) -> bool:
    text = " ".join(str(value or "").split())
    if not text:
        return False
    lowered = text.casefold()
    starts = (
        "this paper ",
        "this study ",
        "we analyze ",
        "we analyse ",
        "we examine ",
        "we investigate ",
        "using data ",
        "based on ",
    )
    return len(text) > 260 or any(lowered.startswith(prefix) for prefix in starts)


def confidence_from_record(record: dict[str, Any]) -> str:
    if record.get("date_confidence"):
        return str(record["date_confidence"])
    source = str(record.get("date_source") or "")
    if record.get("accepted_date") or record.get("available_online"):
        return "A"
    if source.startswith("publisher_") or source in {"official_publish_date", "file_upload_date", "rss_published", "cnki_rss_pubdate"}:
        return "B"
    if source.startswith("crossref_"):
        return "C"
    if record.get("source_issue") or record.get("issue_date"):
        return "D"
    return "F"


def is_chinese_journal(record: dict[str, Any]) -> bool:
    fields = set(record.get("fields") or [])
    source = str(record.get("source") or "")
    journal_id = str(record.get("journal_id") or "")
    return "chinese" in fields or source == "cn-official" or journal_id in CN_JOURNAL_IDS


def infer_registered_source_id(record: dict[str, Any]) -> str:
    """Recover a source id from sparse historical ``seen`` records."""
    for value in (record.get("source_id"), record.get("journal_id")):
        candidate = str(value or "").casefold().removeprefix("source-")
        if candidate in WORKING_SOURCE_TYPES:
            return candidate
    journal = " ".join(str(record.get(key) or "").casefold() for key in ("journal", "publisher", "series"))
    url = " ".join(str(record.get(key) or "").casefold() for key in ("url", "source_url"))
    signatures = {
        "nber": (("nber working papers",), ("nber.org/papers/w",)),
        "iza": (("iza discussion papers",), ("iza.org/publications/dp/",)),
        "cepr-dp": (("cepr discussion papers",), ("cepr.org/publications/dp",)),
        "world-bank-prwp": (("world bank policy research working papers",), ("openknowledge.worldbank.org/entities/publication/",)),
        "imf-working-papers": (("imf working papers",), ("imf.org/en/publications/wp",)),
        "voxeu-cepr-columns": (("voxeu / cepr columns", "voxeu/cepr columns"), ("cepr.org/voxeu/",)),
        "brookings-economic-studies": (("brookings economic studies",), ("brookings.edu/",)),
        "iza-newsroom": (("iza newsroom",), ("newsroom.iza.org/",)),
        "cesifo-working-papers": (("cesifo working papers",), ("cesifo.org/",)),
        "fed-feds": (("federal reserve feds working papers",), ("federalreserve.gov/econres/feds",)),
        "bis-working-papers": (("bis working papers",), ("bis.org/publ/work",)),
        "oecd-working-papers": (("oecd working papers",), ("oecd.org/",)),
        "repec-nep-cna": (("repec nep china",), ("nep.repec.org/nep-cna",)),
        "repec-nep-dev": (("repec nep development",), ("nep.repec.org/nep-dev",)),
        "repec-nep-hea": (("repec nep health",), ("nep.repec.org/nep-hea",)),
        "repec-nep-ifn": (("repec nep international finance",), ("nep.repec.org/nep-ifn",)),
        "repec-nep-mac": (("repec nep macroeconomics",), ("nep.repec.org/nep-mac",)),
        "repec-nep": (("repec nep",), ("nep.repec.org/",)),
    }
    for source_id, (journal_tokens, url_tokens) in signatures.items():
        if any(token in journal for token in journal_tokens) or any(token in url for token in url_tokens):
            return source_id
    return ""


def canonicalize_source_type(record: dict[str, Any]) -> bool:
    """Apply the registered source class before any public rendering.

    Working-paper records normally arrive with ``source=working_papers`` and
    a source-specific id. The fallback also repairs records where only the
    ``source-nber`` style journal id survived an interrupted fetch.
    """
    source_id = infer_registered_source_id(record)
    registered_type = WORKING_SOURCE_TYPES.get(source_id)
    is_registered_working = registered_type is not None
    is_working_namespace = str(record.get("source") or "") == "working_papers"
    if not is_registered_working and not is_working_namespace:
        return False

    changed = False
    if record.get("source") != "working_papers":
        record["source"] = "working_papers"
        changed = True
    if source_id and not record.get("source_id"):
        record["source_id"] = source_id
        changed = True
    if source_id and not str(record.get("journal_id") or "").casefold().startswith("source-"):
        record["journal_id"] = f"source-{source_id}"
        changed = True
    expected_type = registered_type or str(record.get("source_type") or "working_paper")
    if record.get("source_type") != expected_type:
        record["source_type"] = expected_type
        changed = True
    return changed


def normalize_authors(record: dict[str, Any]) -> bool:
    authors = record.get("authors")
    if not isinstance(authors, list):
        return False
    normalized: list[str] = []
    for raw in authors:
        for value in re.split(r"\s*;\s*", clean_inline_html(raw)):
            value = value.strip()
            if value and value not in normalized:
                normalized.append(value)
    if normalized == authors:
        return False
    record["authors"] = normalized[:20]
    return True


def normalize_record(record: dict[str, Any]) -> bool:
    changed = False
    if normalize_date_fields(record):
        changed = True
    if normalize_nep_issue_date(record):
        changed = True
    if normalize_authors(record):
        changed = True
    for field in ("abstract", "abstract_zh"):
        value = record.get(field)
        if not value:
            continue
        cleaned = clean_abstract_text(value)
        if cleaned != value:
            record[field] = cleaned
            changed = True
    if not record.get("doi"):
        url = html.unescape(str(record.get("url") or ""))
        match = re.search(r"(?:doi\.org/|/doi/)(10\.\d{4,9}/[^?&#]+)", url, flags=re.I)
        if match:
            record["doi"] = match.group(1).strip("/ ").casefold()
            changed = True
    if canonicalize_source_type(record):
        changed = True
    title = str(record.get("title") or "")
    cleaned_title = clean_inline_html(title)
    if cleaned_title and cleaned_title != title:
        record["title"] = cleaned_title
        title = cleaned_title
        record.pop("title_zh", None)
        record.pop("translation_status", None)
        changed = True
    title, cepr_changed = strip_cepr_paper_number(record, title)
    if cepr_changed:
        changed = True
    if str(record.get("source_id") or "").startswith("repec-nep-") and looks_like_abstract(title):
        if not record.get("abstract"):
            record["abstract"] = title
        paper_number = record.get("paper_number") or str(record.get("url") or "").split("#")[-1]
        fallback_title = f"{record.get('journal') or 'RePEc NEP'} item {paper_number} (题名待解析)"
        record["title"] = fallback_title
        title = fallback_title
        if looks_like_abstract(record.get("title_zh")):
            record["abstract_zh"] = record.get("title_zh")
            record["title_zh"] = "题名待解析"
        record["title_parse_status"] = "needs_repec_detail_title"
        record["public_visible"] = False
        changed = True
    if has_chinese(title):
        if record.get("title_zh") != title:
            record["title_zh"] = title
            changed = True
        if record.get("translation_status") != "native_chinese":
            record["translation_status"] = "native_chinese"
            changed = True
    if is_chinese_journal(record):
        updates = {
            "china_related": True,
            "china_related_source": record.get("china_related_source") or "rule",
            "china_relevance_status": "confirmed",
            "china_relevance_reason": record.get("china_relevance_reason") or "中文期刊默认与中国相关",
        }
        for key, value in updates.items():
            if record.get(key) != value:
                record[key] = value
                changed = True
    date_source = str(record.get("date_source") or "")
    crossref_source = str((record.get("raw_data") or {}).get("crossref_date_source") or date_source)
    if crossref_source in {"crossref_published", "crossref_issue", "crossref_created"} and record.get("published_online"):
        if not record.get("issue_date"):
            record["issue_date"] = record.get("published_online")
        record["published_online"] = None
        if date_source == "crossref_published":
            record["date_source"] = "crossref_issue"
        changed = True
    confidence = confidence_from_record(record)
    if record.get("date_confidence") != confidence:
        record["date_confidence"] = confidence
        changed = True
    if not record.get("date_source"):
        record["date_source"] = "unknown"
        changed = True
    return changed


def normalized_title(value: Any) -> str:
    return " ".join(canonical_title_text(value).split())


def is_non_article_record(record: dict[str, Any]) -> bool:
    return normalized_title(record.get("title")) in NON_ARTICLE_TITLES


def record_keys(record: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for key in ("doi", "id", "url"):
        value = record.get(key)
        if value:
            keys.add(f"{key}:{str(value).casefold()}")
    title = normalized_title(record.get("title"))
    journal = str(record.get("journal_id") or record.get("journal") or "").casefold()
    if title and len(title) > 24:
        authors = record.get("authors") or []
        first_author = str(authors[0]).casefold() if isinstance(authors, list) and authors else ""
        keys.add(f"title:{journal}:{title}:{first_author}")
        source_id = str(record.get("source_id") or "").casefold()
        if source_id.startswith("repec-nep-"):
            keys.add(f"repec-title:{source_id}:{title}")
        source_scope = str(
            record.get("source_id")
            or record.get("journal_id")
            or record.get("source")
            or record.get("journal")
            or ""
        ).casefold()
        if source_scope:
            keys.add(f"source-title:{source_scope}:{title}")
    return keys


def remove_cross_day_duplicates(paths: list[Path]) -> tuple[int, int]:
    seen: set[str] = set()
    removed = touched = 0
    for path in sorted(paths):
        records = read_json(path, [])
        kept = []
        path_removed = 0
        for record in records:
            keys = record_keys(record)
            if keys and keys & seen:
                path_removed += 1
                continue
            seen.update(keys)
            kept.append(record)
        if path_removed:
            write_json(path, kept)
            removed += path_removed
            touched += 1
    return removed, touched


def daily_paths(daily_dir: Path, date_filter: str | None) -> list[Path]:
    if date_filter:
        path = daily_dir / f"{date_filter}.json"
        return [path] if path.exists() else []
    return sorted(daily_dir.glob("*.json"))


def normalize_seen_source_types() -> int:
    """Persist source classes for sparse historical records restored by the site."""
    path = DATA_DIR / "seen.json"
    payload = read_json(path, {"papers": {}})
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, dict):
        return 0
    changed = 0
    for record in papers.values():
        if isinstance(record, dict) and canonicalize_source_type(record):
            changed += 1
    if changed:
        write_json(path, payload)
    return changed


def normalize_seen_abstracts() -> int:
    path = DATA_DIR / "seen.json"
    payload = read_json(path, {"papers": {}})
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, dict):
        return 0
    changed = 0
    for record in papers.values():
        if not isinstance(record, dict):
            continue
        record_changed = False
        for field in ("abstract", "abstract_zh"):
            value = record.get(field)
            if not value:
                continue
            cleaned = clean_abstract_text(value)
            if cleaned != value:
                record[field] = cleaned
                record_changed = True
        if record_changed:
            changed += 1
    if changed:
        write_json(path, payload)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    paths = daily_paths(args.daily_dir, args.date)
    changed = touched = 0
    for path in paths:
        records = read_json(path, [])
        path_changed = False
        before = len(records)
        records = [record for record in records if not is_non_article_record(record)]
        if len(records) != before:
            changed += before - len(records)
            path_changed = True
        for record in records:
            if normalize_record(record):
                changed += 1
                path_changed = True
        if path_changed:
            write_json(path, records)
            touched += 1
    duplicate_removed = duplicate_files = 0
    if not args.date:
        duplicate_removed, duplicate_files = remove_cross_day_duplicates(paths)
    seen_changed = normalize_seen_source_types() if not args.date else 0
    seen_abstracts = normalize_seen_abstracts() if not args.date else 0
    integrity = repair_public_integrity(DATA_DIR) if not args.date else None
    integrity_repairs = sum((integrity or {}).get("repairs", {}).get(key, 0) for key in (
        "daily_duplicates_removed",
        "seen_duplicates_removed",
        "seen_records_seeded_from_daily",
    ))
    record_source(
        "normalize-records",
        ok=True,
        count=changed + duplicate_removed + seen_changed + seen_abstracts + integrity_repairs,
        message=(
            f"files={touched} duplicates_removed={duplicate_removed} duplicate_files={duplicate_files} "
            f"seen_source_types={seen_changed} seen_abstracts={seen_abstracts} "
            f"public_integrity_repairs={integrity_repairs}"
        ),
    )
    print(
        f"normalize records changed={changed} files={touched} duplicates_removed={duplicate_removed} "
        f"duplicate_files={duplicate_files} seen_source_types={seen_changed} "
        f"seen_abstracts={seen_abstracts} public_integrity_repairs={integrity_repairs}"
    )


if __name__ == "__main__":
    main()
