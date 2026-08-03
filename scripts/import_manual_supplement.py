"""Import a manual supplement package (e.g. CNKI issue abstracts) into seen.

The source package lives in the gitignored ``local_admin/manual-supplements/``
workspace and is only an input. This script writes data-layer artifacts only:

* ``data/seen.json`` (backfilled or newly added canonical catalogue records)
* ``data/daily/*.json`` (canonical daily records matched by DOI or title)
* ``data/manual_supplement_imports.json`` (audit ledger, last 50 runs)

Conventions are documented in ``data/manual_import_conventions.md``.

Rules enforced here:

* The package ``source`` must start with ``manual-``.
* ``doi`` is never fabricated; a missing DOI stays missing and is counted.
* ``accepted_date`` / detection time are never treated as an online date.
* DOI exact matching wins when a record supplies one; otherwise title matching
  is normalised (NFKC, punctuation/whitespace stripped) and prefers an exact
  canonical match in ``seen.json`` before adding a record.
* Multi-journal packages may set ``records[].journal`` / ``records[].journal_id``
  per record, falling back to the package-level journal.
* A matched record only receives a manual abstract when it has none.
* Re-importing the same package is idempotent.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import (
    DATA_DIR,
    clean_abstract_text,
    load_journals,
    normalize_doi,
    now_iso,
    read_json,
    write_json,
)
from public_integrity import calculate_detail_key, normalized_title


MANUAL_IMPORTS_PATH = DATA_DIR / "manual_supplement_imports.json"


def normalized_manual_title(value: Any) -> str:
    return normalized_title(value)


def normalize_publisher_abstract(value: Any) -> str:
    """Return a display-ready abstract for manual-publisher packages.

    ScienceDirect extraction often prefixes real abstracts with a Highlights
    section or an ``Abstract`` label.  Both are publisher furniture rather than
    abstract prose, so they are removed before the abstract is stored.
    """
    text = clean_abstract_text(value)
    if not text:
        return ""
    label = re.search(r"\babstract\s*(?:[:：.\-–—]?\s*)", text, flags=re.I)
    if label:
        prefix = text[: label.start()]
        if re.search(r"\bhighlights?\b", prefix, flags=re.I):
            text = text[label.end() :].strip()
    text = re.sub(
        r"^(?:abstract|摘要)\s*(?:[:：.\-–—]\s*|\s+)",
        "",
        text,
        flags=re.I,
    ).strip()
    return text


def parse_manual_authors(value: Any) -> list[str]:
    """Best-effort split of manual author strings or lists.

    Handles CNKI strings with superscript affiliation numbers and publisher
    lists with trailing single-letter affiliation markers such as
    ``"Meng Liu a"`` or ``"Elie Bouri a j"``.  Only space-separated single
    lowercase tokens at the end of a name are treated as affiliation markers,
    so names such as ``"Shinya Sugiura"`` are never shortened.
    """
    if isinstance(value, list):
        parts: list[str] = []
        for chunk in value:
            if isinstance(chunk, str):
                parts.extend(re.split(r"\s*[;；]\s*", chunk))
            elif chunk is not None:
                parts.append(str(chunk))
    else:
        parts = re.split(r"\d+", str(value or ""))
    authors: list[str] = []
    for part in parts:
        cleaned = re.sub(r"\d+", "", part)
        cleaned = re.sub(r"(?:\s+[a-z])+$", "", cleaned)
        cleaned = re.sub(r"[\s,，、;；]+", " ", cleaned).strip()
        if cleaned and cleaned not in authors:
            authors.append(cleaned)
    return authors[:12]


def issue_date_from_label(issue: Any) -> str:
    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*期", str(issue or ""))
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-01"
    return ""


def journal_lookup() -> dict[str, dict[str, Any]]:
    by_title: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for journal in load_journals():
        by_title.setdefault(normalized_manual_title(journal.get("title")), journal)
        by_id[journal["id"]] = journal
    return {"by_title": by_title, "by_id": by_id}


def resolve_journal(
    lookup: dict[str, dict[str, Any]],
    journal: Any,
    journal_id: Any,
) -> dict[str, Any] | None:
    """Resolve a journal entry from a title or id, never inventing one."""
    name = str(journal or "").strip()
    entry = lookup["by_title"].get(normalized_manual_title(name))
    if not entry:
        entry = lookup["by_id"].get(str(journal_id or ""))
    return entry


def build_manual_record(
    item: dict[str, Any],
    package: dict[str, Any],
    slug: str,
    journal: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """Construct a seen catalogue record without fabricating a DOI."""
    now = now_iso()
    issue_date = issue_date_from_label(package.get("issue"))
    abstract = normalize_publisher_abstract(item.get("abstract"))
    record: dict[str, Any] = {
        "id": f"manual:{slug}:{index}",
        "title": str(item.get("title") or "").strip(),
        "authors": parse_manual_authors(item.get("authors")),
        "authors_status_code": "available",
        "abstract": abstract or None,
        "abstract_source": package.get("source", "manual-cnki"),
        "abstract_completeness": "full",
        "abstract_status_code": "available",
        "journal": journal.get("title"),
        "journal_id": journal.get("id"),
        "journal_short": journal.get("short_name"),
        "source": package.get("source", "manual-cnki"),
        "source_type": "journal",
        "issue_date": issue_date or None,
        "date_source": "manual_issue",
        "date_confidence": "D",
        "official_date_status": "available" if issue_date else "missing_retry",
        "first_seen": now,
        "detected_at": now,
        "manual_supplement": slug,
        "manual_issue": str(package.get("issue") or ""),
        "manual_method": str(package.get("method") or ""),
        "raw_data": {
            "manual_source": package.get("source"),
            "manual_issue": package.get("issue"),
            "manual_extracted_at": package.get("extracted_at"),
        },
    }
    url = str(item.get("url") or "").strip()
    if url:
        record["url"] = url
        record["source_url"] = url
    # DOI is only included when the package actually provides one.
    doi = str(item.get("doi") or "").strip()
    if doi:
        record["doi"] = doi
        record["identity_aliases"] = [f"doi:{doi.casefold()}"]
    record["detail_key"] = calculate_detail_key(record)
    return record


def has_full_abstract(record: dict[str, Any]) -> bool:
    text = str(record.get("abstract") or "").strip()
    if not text:
        return False
    if str(record.get("abstract_completeness") or "") == "preview":
        return False
    if record.get("abstract_truncated") is True:
        return False
    if text.endswith(("...", "…")):
        return False
    return True


def apply_backfill(record: dict[str, Any], item: dict[str, Any], package: dict[str, Any]) -> bool:
    """Backfill or upgrade a matching canonical record with the manual abstract."""
    abstract = normalize_publisher_abstract(item.get("abstract"))
    if not abstract:
        return False
    if has_full_abstract(record):
        return False
    record["abstract"] = abstract
    record["abstract_source"] = package.get("source", "manual-cnki")
    record["abstract_completeness"] = "full"
    record["abstract_status_code"] = "available"
    record.pop("abstract_status", None)
    record.pop("abstract_truncated", None)
    record.pop("abstract_enrichment_status", None)
    if not record.get("authors"):
        parsed = parse_manual_authors(item.get("authors"))
        if parsed:
            record["authors"] = parsed
            record["authors_status_code"] = "available"
    return True


def merge_doi_identity(record: dict[str, Any], doi: Any) -> bool:
    """Merge a verified DOI into an existing record's identity, never fabricating."""
    doi = str(doi or "").strip().casefold()
    if not doi:
        return False
    changed = False
    if not str(record.get("doi") or "").strip():
        record["doi"] = doi
        changed = True
    aliases = set(record.get("identity_aliases") or [])
    if f"doi:{doi}" not in aliases:
        aliases.add(f"doi:{doi}")
        record["identity_aliases"] = sorted(aliases)
        changed = True
    return changed


def build_daily_index(
    daily_dir: Path,
) -> tuple[
    dict[str, list[tuple[Path, dict[str, Any]]]],
    dict[str, list[tuple[Path, dict[str, Any]]]],
    dict[Path, list[dict[str, Any]]],
]:
    """Index canonical daily records by DOI and normalized title."""
    by_doi: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    by_title: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    payloads: dict[Path, list[dict[str, Any]]] = {}
    if not daily_dir.is_dir():
        return by_doi, by_title, payloads
    for path in sorted(daily_dir.glob("*.json")):
        rows = read_json(path, [])
        if not isinstance(rows, list):
            continue
        payloads[path] = rows
        for record in rows:
            if not isinstance(record, dict):
                continue
            doi = normalize_doi(record.get("doi"))
            if doi:
                by_doi[doi].append((path, record))
            title = normalized_manual_title(record.get("title"))
            if title:
                by_title[title].append((path, record))
    return by_doi, by_title, payloads


def import_package(
    input_path: Path,
    *,
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    package = read_json(input_path, {})
    if not isinstance(package, dict):
        raise ValueError("manual supplement package must be a JSON object")
    source = str(package.get("source") or "")
    if not source.startswith("manual-"):
        raise ValueError(f"source must start with manual-, got {source!r}")
    slug = input_path.stem
    records = package.get("records")
    if not isinstance(records, list):
        raise ValueError("manual supplement package requires a records list")

    seen_path = data_dir / "seen.json"
    seen_payload = read_json(seen_path, {"papers": {}})
    papers = seen_payload.get("papers") if isinstance(seen_payload, dict) else {}
    if not isinstance(papers, dict):
        raise ValueError("seen.json must be a {papers: {...}} payload")

    lookup = journal_lookup()
    journal_title = str(package.get("journal") or "").strip()

    by_title: dict[str, str] = {}
    by_doi: dict[str, list[str]] = defaultdict(list)
    for key, record in papers.items():
        if not isinstance(record, dict):
            continue
        by_title.setdefault(normalized_manual_title(record.get("title")), key)
        doi = normalize_doi(record.get("doi"))
        if doi:
            by_doi[doi].append(key)
        for alias in record.get("identity_aliases") or []:
            if isinstance(alias, str) and alias.startswith("doi:"):
                alias_doi = normalize_doi(alias.removeprefix("doi:"))
                if alias_doi:
                    by_doi[alias_doi].append(key)

    daily_dir = data_dir / "daily"
    daily_by_doi, daily_by_title, daily_payloads = build_daily_index(daily_dir)
    changed_daily_files: set[Path] = set()

    matched_backfilled = 0
    matched_by_doi = 0
    matched_by_title = 0
    daily_backfilled = 0
    added = 0
    skipped = 0
    doi_merged = 0
    unresolved_journal: list[str] = []
    missing_doi: list[str] = []
    journals_used: set[str] = set()
    changed = False

    for index, item in enumerate(records):
        if not isinstance(item, dict):
            skipped += 1
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        norm = normalized_manual_title(title)
        journal = resolve_journal(
            lookup,
            item.get("journal") or package.get("journal"),
            item.get("journal_id") or package.get("journal_id"),
        )
        if not journal:
            unresolved_journal.append(title)
            skipped += 1
            continue
        journals_used.add(str(journal.get("title") or ""))
        item_doi = normalize_doi(item.get("doi"))

        target_key = None
        if item_doi:
            # DOI exact match wins over source/title heuristics.
            for key in by_doi.get(item_doi, []):
                if isinstance(papers.get(key), dict):
                    target_key = key
                    break
        if target_key is None:
            target_key = next(
                (
                    key
                    for key, record in papers.items()
                    if isinstance(record, dict)
                    and str(record.get("source") or "") == source
                    and normalized_manual_title(record.get("title")) == norm
                ),
                None,
            )
        if target_key is None:
            target_key = by_title.get(norm)

        if target_key is not None and isinstance(papers.get(target_key), dict):
            target = papers[target_key]
            if item_doi and normalize_doi(target.get("doi")) == item_doi:
                matched_by_doi += 1
            else:
                matched_by_title += 1
            if apply_backfill(target, item, package):
                matched_backfilled += 1
                changed = True
            else:
                skipped += 1
            if merge_doi_identity(target, item.get("doi")):
                doi_merged += 1
                changed = True
        else:
            record = build_manual_record(item, package, slug, journal, index)
            papers[record["id"]] = record
            by_title[norm] = record["id"]
            if item_doi:
                by_doi[item_doi].append(record["id"])
            added += 1
            if item_doi:
                doi_merged += 1
            changed = True

        daily_occurrences = list(daily_by_doi.get(item_doi, [])) if item_doi else []
        if not daily_occurrences:
            journal_scope = str(journal.get("title") or "").strip().casefold()
            daily_occurrences = [
                (path, record)
                for path, record in daily_by_title.get(norm, [])
                if str(record.get("journal") or "").strip().casefold() == journal_scope
            ]
        for path, record in daily_occurrences:
            if apply_backfill(record, item, package):
                changed_daily_files.add(path)
                daily_backfilled += 1

        if not item_doi:
            missing_doi.append(title)

    if changed:
        seen_payload["papers"] = papers
        write_json(seen_path, seen_payload)
    for path in sorted(changed_daily_files):
        write_json(path, daily_payloads[path])

    report = {
        "imported_at": now_iso(),
        "slug": slug,
        "journal": journal_title,
        "journal_id": package.get("journal_id"),
        "issue": package.get("issue"),
        "source": source,
        "package_records": len(records),
        "journals_used": sorted(j for j in journals_used if j),
        "matched_backfilled": matched_backfilled,
        "matched_by_doi": matched_by_doi,
        "matched_by_title": matched_by_title,
        "daily_backfilled": daily_backfilled,
        "daily_files_changed": len(changed_daily_files),
        "added": added,
        "doi_merged": doi_merged,
        "skipped": skipped,
        "unresolved_journal_count": len(unresolved_journal),
        "unresolved_journal_titles": unresolved_journal,
        "missing_doi_count": len(missing_doi),
        "missing_doi_titles": missing_doi,
        "note": (
            "DOI 缺失如实标注，不编造；DOI 精确匹配优先并回写 canonical daily；"
            "manual-* 记录以 issue_date + date_confidence=D 表达期次日期。"
        ),
    }
    history_path = data_dir / "manual_supplement_imports.json"
    history = read_json(history_path, {"imports": []})
    imports = history.get("imports")
    if not isinstance(imports, list):
        imports = []
    imports.append(report)
    history["imports"] = imports[-50:]
    history["latest"] = report
    write_json(history_path, history)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    report = import_package(args.input, data_dir=args.data_dir)
    print(
        f"manual supplement imported slug={report['slug']} "
        f"backfilled={report['matched_backfilled']} added={report['added']} "
        f"daily_backfilled={report['daily_backfilled']} "
        f"daily_files_changed={report['daily_files_changed']} "
        f"skipped={report['skipped']} missing_doi={report['missing_doi_count']}"
    )


if __name__ == "__main__":
    main()
