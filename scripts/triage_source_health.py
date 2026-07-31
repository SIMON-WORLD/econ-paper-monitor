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


def collect_source_health_errors(source_health: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (name, error_text) pairs from source_health.json degraded entries."""
    errors: list[tuple[str, str]] = []
    degraded = source_health.get("degraded") or []
    for entry in degraded:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("journal") or entry.get("journal_id") or "")
        failed = entry.get("failed_paths") or []
        if isinstance(failed, list):
            for item in failed:
                if isinstance(item, dict) and item.get("message"):
                    errors.append((name, str(item["message"])))
    # Fall back to the whole coverage/status string when no structured paths.
    for entry in degraded:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("journal") or entry.get("journal_id") or "")
        if any(name == existing for existing, _ in errors):
            continue
        message = entry.get("coverage") or entry.get("level") or ""
        if message:
            errors.append((name, str(message)))
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


def triage(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    source_health = read_json(data_dir / "source_health.json", {})
    status = read_json(data_dir / "status.json", {})
    errors = collect_source_health_errors(source_health) + collect_status_errors(status)

    by_source: dict[str, dict[str, Any]] = {}
    for name, message in errors:
        entry = by_source.setdefault(
            name,
            {"source": name, "messages": [], "categories": {}},
        )
        if message not in entry["messages"]:
            entry["messages"].append(message)
        category = categorize_error(message)
        entry["categories"][category] = entry["categories"].get(category, 0) + 1

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
            }
        )
        category_counts[primary] = category_counts.get(primary, 0) + 1

    report = {
        "checked_at": datetime.now(BEIJING_TZ).isoformat(),
        "total_degraded": len(triaged),
        "categories": dict(sorted(category_counts.items())),
        "sources": triaged,
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
