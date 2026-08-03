"""Build a manual-publisher extraction candidate list for Elsevier/Wiley DOIs.

Selects canonical records that still miss an abstract and whose DOI belongs to
ScienceDirect-family publishers (10.1016/10.1017) or Wiley (10.1111). Recent
records (available/published/issue year >= 2026-01) sort first. The output is a
gitignored handoff for the total-control browser extraction workflow.

Output: ``local_admin/manual-supplements/candidates/<date>-sd-abstract-candidates.json``
Fields per item: doi, title, journal, detail_key, pii, link, first_seen,
available_online.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import DATA_DIR, ROOT, read_json, today_str, write_json
from public_integrity import normalized_title


SD_DOI_PREFIXES = ("10.1016/", "10.1017/", "10.1111/")


def is_missing_abstract(record: dict[str, Any]) -> bool:
    return not str(record.get("abstract") or "").strip()


def is_sd_doi(doi: Any, prefixes: tuple[str, ...] = SD_DOI_PREFIXES) -> bool:
    value = str(doi or "").strip().casefold()
    return any(value.startswith(prefix) for prefix in prefixes)


def record_date_fields(record: dict[str, Any]) -> list[str]:
    values = []
    for field in ("available_online", "published_online", "issue_date"):
        value = str(record.get(field) or "").strip()
        if value:
            values.append(value[:10])
    return values


def is_recent(record: dict[str, Any], cutoff: str = "2026-01-01") -> bool:
    return any(value >= cutoff for value in record_date_fields(record))


def first_seen_stamp(record: dict[str, Any]) -> str:
    return str(
        record.get("first_seen")
        or record.get("first_seen_at")
        or record.get("detected_at")
        or ""
    )


def pii_from_record(record: dict[str, Any]) -> str:
    haystack = " ".join(
        str(record.get(field) or "")
        for field in ("url", "source_url", "doi")
    )
    raw = record.get("raw_data") if isinstance(record.get("raw_data"), dict) else {}
    haystack += " " + " ".join(str(raw.get(key) or "") for key in ("pii", "sciencedirect_search_journal"))
    match = re.search(r"/pii/(S\d{10,}[A-Z0-9]*)", haystack, flags=re.I)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b(S\d{14,}[A-Z0-9]*)\b", haystack)
    return match.group(1).upper() if match else ""


def build_candidates(
    data_dir: Path = DATA_DIR,
    *,
    limit: int = 150,
    doi_prefixes: tuple[str, ...] = SD_DOI_PREFIXES,
) -> dict[str, Any]:
    seen = read_json(data_dir / "seen.json", {"papers": {}})
    papers = seen.get("papers") if isinstance(seen, dict) else {}
    candidates = [
        record
        for record in papers.values()
        if isinstance(record, dict)
        and is_missing_abstract(record)
        and is_sd_doi(record.get("doi"), doi_prefixes)
    ]
    candidates.sort(
        key=lambda record: (
            1 if is_recent(record) else 0,
            first_seen_stamp(record),
        ),
        reverse=True,
    )
    selected = candidates if limit <= 0 else candidates[: max(0, limit)]

    by_journal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in selected:
        doi = str(record.get("doi") or "").strip()
        pii = pii_from_record(record)
        link = (
            f"https://www.sciencedirect.com/science/article/pii/{pii}"
            if pii
            else f"https://doi.org/{doi}"
        )
        by_journal[str(record.get("journal") or "unknown")].append(
            {
                "doi": doi,
                "title": str(record.get("title") or "").strip(),
                "journal": record.get("journal"),
                "journal_id": record.get("journal_id"),
                "detail_key": str(record.get("detail_key") or ""),
                "pii": pii,
                "link": link,
                "first_seen": first_seen_stamp(record),
                "available_online": str(record.get("available_online") or record.get("published_online") or ""),
            }
        )

    journals = {journal: sorted(items, key=lambda item: item["doi"]) for journal, items in sorted(by_journal.items())}
    return {
        "generated_for": today_str(),
        "source_filters": {
            "doi_prefixes": list(doi_prefixes),
            "missing_abstract": True,
            "recent_first": ">= 2026-01-01",
        },
        "limit": limit,
        "total_candidates": len(selected),
        "journals": journals,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument(
        "--doi-prefix",
        action="append",
        default=[],
        help="Restrict to these DOI prefixes; repeatable (default: 10.1016/10.1017/10.1111).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "local_admin" / "manual-supplements" / "candidates" / "2026-08-02-sd-abstract-candidates.json",
    )
    args = parser.parse_args()
    prefixes = tuple(args.doi_prefix) if args.doi_prefix else SD_DOI_PREFIXES
    report = build_candidates(args.data_dir, limit=args.limit, doi_prefixes=prefixes)
    write_json(args.output, report)
    print(
        f"sd abstract candidates={report['total_candidates']} "
        f"journals={len(report['journals'])} -> {args.output}"
    )


if __name__ == "__main__":
    main()
