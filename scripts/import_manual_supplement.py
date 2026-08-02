"""Import a manual supplement package (e.g. CNKI issue abstracts) into seen.

The source package lives in the gitignored ``local_admin/manual-supplements/``
workspace and is only an input. This script writes data-layer artifacts only:

* ``data/seen.json`` (backfilled or newly added canonical catalogue records)
* ``data/manual_supplement_imports.json`` (audit ledger, last 50 runs)

Conventions are documented in ``data/manual_import_conventions.md``.

Rules enforced here:

* The package ``source`` must start with ``manual-``.
* ``doi`` is never fabricated; a missing DOI stays missing and is counted.
* ``accepted_date`` / detection time are never treated as an online date.
* Title matching is normalised (NFKC, punctuation/whitespace stripped) and
  prefers an exact canonical match in ``seen.json`` before adding a record.
* A matched record only receives a manual abstract when it has none.
* Re-importing the same package is idempotent.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, load_journals, now_iso, read_json, write_json
from public_integrity import calculate_detail_key, normalized_title


MANUAL_IMPORTS_PATH = DATA_DIR / "manual_supplement_imports.json"


def normalized_manual_title(value: Any) -> str:
    return normalized_title(value)


def parse_manual_authors(value: Any) -> list[str]:
    """Best-effort split of CNKI author strings with affiliation numbers."""
    if not value:
        return []
    parts = re.split(r"\d+", str(value))
    authors: list[str] = []
    for part in parts:
        cleaned = re.sub(r"[\s,，、;；]+", "", part).strip()
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
    record: dict[str, Any] = {
        "id": f"manual:{slug}:{index}",
        "title": str(item.get("title") or "").strip(),
        "authors": parse_manual_authors(item.get("authors")),
        "authors_status_code": "available",
        "abstract": str(item.get("abstract") or "").strip() or None,
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
    abstract = str(item.get("abstract") or "").strip()
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
    journal = lookup["by_title"].get(normalized_manual_title(journal_title))
    if not journal:
        journal = lookup["by_id"].get(str(package.get("journal_id") or ""))
    if not journal:
        raise ValueError(f"unresolved manual journal: {journal_title!r}")

    by_title: dict[str, str] = {}
    for key, record in papers.items():
        if not isinstance(record, dict):
            continue
        by_title.setdefault(normalized_manual_title(record.get("title")), key)

    matched_backfilled = 0
    added = 0
    skipped = 0
    doi_merged = 0
    missing_doi: list[str] = []
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

        manual_key = next(
            (
                key
                for key, record in papers.items()
                if isinstance(record, dict)
                and str(record.get("source") or "") == source
                and normalized_manual_title(record.get("title")) == norm
            ),
            None,
        )
        if manual_key is not None:
            if merge_doi_identity(papers[manual_key], item.get("doi")):
                doi_merged += 1
                changed = True
            else:
                skipped += 1
            continue

        owner_key = by_title.get(norm)
        if owner_key is not None and isinstance(papers.get(owner_key), dict):
            if apply_backfill(papers[owner_key], item, package):
                matched_backfilled += 1
                changed = True
            else:
                skipped += 1
            if merge_doi_identity(papers[owner_key], item.get("doi")):
                doi_merged += 1
                changed = True
        else:
            record = build_manual_record(item, package, slug, journal, index)
            papers[record["id"]] = record
            by_title[norm] = record["id"]
            added += 1
            if str(item.get("doi") or "").strip():
                doi_merged += 1
            changed = True

        if not str(item.get("doi") or "").strip():
            missing_doi.append(title)

    if changed:
        seen_payload["papers"] = papers
        write_json(seen_path, seen_payload)

    report = {
        "imported_at": now_iso(),
        "slug": slug,
        "journal": journal_title,
        "journal_id": journal.get("id"),
        "issue": package.get("issue"),
        "source": source,
        "package_records": len(records),
        "matched_backfilled": matched_backfilled,
        "added": added,
        "doi_merged": doi_merged,
        "skipped": skipped,
        "missing_doi_count": len(missing_doi),
        "missing_doi_titles": missing_doi,
        "note": "DOI 缺失如实标注，不编造；manual-* 记录以 issue_date + date_confidence=D 表达期次日期。",
    }
    history = read_json(MANUAL_IMPORTS_PATH, {"imports": []})
    imports = history.get("imports")
    if not isinstance(imports, list):
        imports = []
    imports.append(report)
    history["imports"] = imports[-50:]
    history["latest"] = report
    write_json(MANUAL_IMPORTS_PATH, history)
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
        f"skipped={report['skipped']} missing_doi={report['missing_doi_count']}"
    )


if __name__ == "__main__":
    main()
