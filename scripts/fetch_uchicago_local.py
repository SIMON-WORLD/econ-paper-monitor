"""Fetch UChicago Press etoc RSS feeds from the local machine.

UChicago Press returns HTTP 403 to shared CI IPs for its etoc RSS endpoints
(``journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=...``), while
residential IPs fetch them normally. This script is the data-line counterpart
for a Windows scheduled task: it fetches the four UChicago journals, writes
normalized records to ``data/raw/uchicago-local/<date>.json`` so the shared
``scripts/dedupe.py`` rglob pass picks them up without any workflow change,
and mirrors a status file at ``data/local_uchicago_status.json`` in the style
of ``data/local_cnki_status.json``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import DATA_DIR, now_iso, read_json, today_str, write_json
from fetch_rss import (
    feed_identity_matches,
    fetch_feed_with_retry,
    parse_feed,
)


JOURNAL_MAPPING: dict[str, str] = {
    "journal-of-political-economy": "jpe",
    "journal-of-law-and-economics": "jle",
    "journal-of-labor-economics": "jole",
    "economic-development-and-cultural-change": "edcc",
}

JOURNAL_TITLES: dict[str, str] = {
    "journal-of-political-economy": "Journal of Political Economy",
    "journal-of-law-and-economics": "Journal of Law and Economics",
    "journal-of-labor-economics": "Journal of Labor Economics",
    "economic-development-and-cultural-change": "Economic Development and Cultural Change",
}

JOURNAL_SHORT_NAMES: dict[str, str] = {
    "journal-of-political-economy": "JPE",
    "journal-of-law-and-economics": "JLE",
    "journal-of-labor-economics": "JOLE",
    "economic-development-and-cultural-change": "EDCC",
}

JOURNAL_ISSNS: dict[str, str] = {
    "journal-of-political-economy": "0022-3808",
    "journal-of-law-and-economics": "0022-2186",
    "journal-of-labor-economics": "0734-306X",
    "economic-development-and-cultural-change": "0013-0079",
}

FEED_URL_TEMPLATE = "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc={code}"


def configure_console() -> None:
    """Keep scheduled-task logging alive on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def uchicago_journals() -> list[dict[str, Any]]:
    """Return the four UChicago journal descriptors used by this channel."""
    journals: list[dict[str, Any]] = []
    for journal_id, code in JOURNAL_MAPPING.items():
        journals.append(
            {
                "id": journal_id,
                "title": JOURNAL_TITLES[journal_id],
                "short_name": JOURNAL_SHORT_NAMES[journal_id],
                "publisher": "The University of Chicago Press",
                "issn": JOURNAL_ISSNS[journal_id],
                "jc": code,
                "feed_url": FEED_URL_TEMPLATE.format(code=code),
            }
        )
    return journals


def default_output_path() -> Path:
    return DATA_DIR / "raw" / "uchicago-local" / f"{today_str()}.json"


def select_journals(only: list[str] | None = None) -> list[dict[str, Any]]:
    """Resolve ``--only`` values (journal id or jc code) to journal dicts."""
    journals = uchicago_journals()
    if not only:
        return journals
    by_alias = {journal["id"]: journal for journal in journals}
    by_alias.update({journal["jc"]: journal for journal in journals})
    unknown = [value for value in only if value not in by_alias]
    if unknown:
        raise ValueError(f"unknown UChicago journal id/jc: {', '.join(sorted(unknown))}")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in only:
        journal = by_alias[value]
        if journal["id"] not in seen:
            seen.add(journal["id"])
            selected.append(journal)
    return selected


def fetch_one(journal: dict[str, Any], *, timeout: int = 30, attempts: int = 2) -> list[dict[str, Any]]:
    """Fetch and parse one UChicago etoc feed with identity validation."""
    xml_text = fetch_feed_with_retry(journal["feed_url"], timeout=timeout, attempts=attempts)
    if not feed_identity_matches(xml_text, journal):
        raise ValueError("RSS feed identity does not match configured journal")
    return parse_feed(xml_text, journal, journal["feed_url"])


def fetch_all(
    only: list[str] | None = None,
    *,
    timeout: int = 30,
    attempts: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch the selected journals; a failed source never aborts the batch."""
    selected = select_journals(only)
    records: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for journal in selected:
        try:
            fetched = fetch_one(journal, timeout=timeout, attempts=attempts)
            records.extend(fetched)
        except Exception as exc:  # noqa: BLE001 - keep the scheduled job moving.
            failed.append({"id": journal["id"], "error": f"{type(exc).__name__}: {exc}"})
    return records, selected, failed


def build_status(
    records: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the status payload mirrored from data/local_cnki_status.json.

    All sources must succeed for state="published". On partial failure the
    successful records are still written and the last successful run time is
    preserved.
    """
    ok = not failed
    updated_at = now_iso()
    if ok:
        last_success_at = updated_at
    else:
        last_success_at = (previous or {}).get("last_success_at")
    if ok:
        message = f"UChicago etoc RSS 全部成功：{len(selected)}/{len(selected)}"
    else:
        failed_ids = ", ".join(entry["id"] for entry in failed)
        message = (
            f"UChicago etoc RSS 部分失败：{len(selected) - len(failed)}/{len(selected)} 成功，"
            f"失败：{failed_ids}；已写入已成功记录"
        )
    return {
        "ok": ok,
        "state": "published" if ok else "error",
        "count": len(records),
        "selected_sources": len(selected),
        "successful_sources": len(selected) - len(failed),
        "failed_sources": len(failed),
        "last_success_at": last_success_at,
        "updated_at": updated_at,
        "message": message,
    }


def run_pipeline(
    *,
    output: Path,
    status_path: Path,
    only: list[str] | None = None,
    timeout: int = 30,
    attempts: int = 2,
) -> dict[str, Any]:
    """Fetch, write raw records + status, and print a concise summary."""
    previous = read_json(status_path, {})
    records, selected, failed = fetch_all(only, timeout=timeout, attempts=attempts)
    payload = build_status(records, selected, failed, previous=previous)
    write_json(output, records)
    write_json(status_path, payload)
    print(f"wrote {len(records)} UChicago records to {output}")
    for journal in selected:
        error = next((entry["error"] for entry in failed if entry["id"] == journal["id"]), None)
        journal_records = [record for record in records if record.get("journal_id") == journal["id"]]
        if error:
            print(f"{journal['title']}: ERROR {error}")
        else:
            print(f"{journal['title']}: {len(journal_records)}")
    print(
        f"sources={len(selected) - len(failed)}/{len(selected)} "
        f"ok={payload['ok']} state={payload['state']}"
    )
    return payload


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description="Fetch UChicago Press etoc RSS feeds locally.")
    parser.add_argument("--output", type=Path, default=default_output_path())
    parser.add_argument("--status", type=Path, default=DATA_DIR / "local_uchicago_status.json")
    parser.add_argument("--only", action="append", default=[], help="journal id or jc code; repeatable")
    args = parser.parse_args()
    try:
        run_pipeline(output=args.output, status_path=args.status, only=args.only)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
