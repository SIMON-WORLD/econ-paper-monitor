"""Triage degraded sources into actionable categories.

Reads ``data/source_health.json`` (journal-level degraded entries) and
``data/status.json`` (source-level errors), then categorizes each entry as:

* ``rate_limited``
* ``page_structure_change``
* ``transient_network``
* ``permanently_unavailable``
* ``needs_investigation``

Writes ``data/source_health_triage.json``. This is a data-line tool only.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, read_json, write_json


TRIAGE_REPORT_PATH = DATA_DIR / "source_health_triage.json"

RATE_LIMITED_PATTERNS = (
    "429",
    "rate limit",
    "too many requests",
    "throttl",
    "503 service unavailable",
    "503 service temporarily unavailable",
)

PAGE_STRUCTURE_PATTERNS = (
    "indexerror",
    "keyerror",
    "attributeerror",
    "typeerror",
    "no element found",
    "element not found",
    "cannot find",
    "selector",
    "parse error",
    "parseerror",
    "unexpected token",
    "expected",
    "json decode",
    "jsondecode",
)

TRANSIENT_NETWORK_PATTERNS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "eof",
    "econnreset",
    "econnrefused",
    "broken pipe",
    "dns",
    "name resolution",
    "getaddrinfo",
    "ssl",
    "certificate",
    "tls",
    "temporary failure",
    "host unreachable",
    "network unreachable",
)

PERMANENT_PATTERNS = (
    "403",
    "forbidden",
    "418",
    "blocked",
    "captcha",
    "cloudflare",
    "access denied",
    "not found",
    "404",
    "gone",
    "410",
)


def categorize_error(error_text: str) -> str:
    """Categorize an error message into one of five categories."""
    lower = error_text.casefold()
    # Code/parse errors must be detected before "not found" (permanent).
    for pattern in PAGE_STRUCTURE_PATTERNS:
        if pattern in lower:
            return "page_structure_change"
    for pattern in PERMANENT_PATTERNS:
        if pattern in lower:
            return "permanently_unavailable"
    for pattern in RATE_LIMITED_PATTERNS:
        if pattern in lower:
            return "rate_limited"
    for pattern in TRANSIENT_NETWORK_PATTERNS:
        if pattern in lower:
            return "transient_network"
    return "needs_investigation"


def collect_source_health_errors(
    source_health: dict[str, Any],
) -> list[tuple[str, list[str], dict[str, Any]]]:
    """Return every degraded journal with its failure messages.

    Entries without structured ``failed_paths`` still participate in the
    triage so ``total_degraded`` matches ``source_health.counts.degraded``.
    """
    errors: list[tuple[str, list[str], dict[str, Any]]] = []
    for entry in source_health.get("degraded") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("journal") or entry.get("journal_id") or "")
        if not name:
            continue
        messages: list[str] = []
        for item in entry.get("failed_paths") or []:
            if isinstance(item, dict) and item.get("message"):
                messages.append(str(item["message"]))
        if not messages:
            usable = ",".join(str(value) for value in entry.get("usable_paths") or []) or "none"
            messages.append(
                f"degraded coverage={entry.get('coverage') or '?'} level={entry.get('level') or '?'} usable={usable}"
            )
        errors.append((name, messages, entry))
    return errors


def collect_status_errors(status: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (name, error_text) pairs from status.json sources."""
    errors: list[tuple[str, str]] = []
    sources = status.get("sources") or {}
    for name, info in sources.items():
        if not isinstance(info, dict):
            continue
        if info.get("ok"):
            continue
        error = str(info.get("last_error") or info.get("message") or "")
        if error:
            errors.append((str(name), error))
    return errors


def match_status_source(
    entry: dict[str, Any],
    status_errors: list[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """Map a degraded journal to the status.json source that reports it."""
    title = str(entry.get("journal") or "").casefold()
    journal_id = str(entry.get("journal_id") or "").casefold()
    for name, message in status_errors:
        haystack = str(message).casefold()
        if title and title in haystack:
            return name, message
        if journal_id and journal_id in haystack:
            return name, message
    return None, None


def triage(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    source_health = read_json(data_dir / "source_health.json", {})
    status = read_json(data_dir / "status.json", {})
    journal_errors = collect_source_health_errors(source_health)
    status_errors = collect_status_errors(status)

    by_source: dict[str, dict[str, Any]] = {}
    for name, messages, entry in journal_errors:
        matched_status, matched_message = match_status_source(entry, status_errors)
        categories: dict[str, int] = {}
        for message in messages:
            category = categorize_error(message)
            categories[category] = categories.get(category, 0) + 1
        entry = by_source.setdefault(
            name,
            {
                "source": name,
                "journal_id": str(entry.get("journal_id") or ""),
                "messages": [],
                "categories": {},
                "status_source": matched_status,
                "status_category": (
                    categorize_error(matched_message) if matched_status and matched_message else None
                ),
                "usable_paths": entry.get("usable_paths") or [],
            },
        )
        for message in messages:
            if message not in entry["messages"]:
                entry["messages"].append(message)
        entry["categories"] = categories

    triaged: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    for name, entry in sorted(by_source.items()):
        primary = max(
            entry["categories"],
            key=lambda category: (entry["categories"][category], category),
        )
        triaged.append(
            {
                "source": name,
                "category": primary,
                "category_counts": entry["categories"],
                "sample_error": entry["messages"][0][:200],
                "status_source": entry["status_source"],
                "status_category": entry["status_category"],
                "journal_id": entry["journal_id"],
                "usable_paths": entry["usable_paths"],
            }
        )
        category_counts[primary] = category_counts.get(primary, 0) + 1

    source_status_failures = [
        {
            "source": name,
            "category": categorize_error(message),
            "sample_error": message[:200],
        }
        for name, message in status_errors
    ]
    health_count = int(source_health.get("counts", {}).get("degraded") or 0)
    aligned = health_count == len(triaged)
    report = {
        "checked_at": datetime.now(BEIJING_TZ).isoformat(),
        "total_degraded": len(triaged),
        "source_health_degraded_count": health_count,
        "categories": dict(sorted(category_counts.items())),
        "sources": triaged,
        "source_status_failures": source_status_failures,
        "status_json": {
            "aligned": aligned,
            "degraded_source_failures": len(source_status_failures),
        },
    }
    write_json(data_dir / "source_health_triage.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = triage(args.data_dir)
    output = args.output or args.data_dir / "source_health_triage.json"
    write_json(output, report)
    print(f"source health triage degraded={report['total_degraded']} categories={report['categories']}")


if __name__ == "__main__":
    main()
