"""Triage degraded sources into rate-limited, page-structure, transient, and permanent categories.

Reads data/status.json source health data and categorizes each degraded source,
writing data/source_health_triage.json.

Run: python scripts/triage_source_health.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common import BEIJING_TZ, DATA_DIR, read_json, write_json

TRIAGE_REPORT_PATH = DATA_DIR / "source_health_triage.json"

# Error patterns for categorization
RATE_LIMITED_PATTERNS = (
    "429", "rate limit", "too many requests", "throttl",
    "503 service unavailable", "503 service temporarily unavailable",
)

PAGE_STRUCTURE_PATTERNS = (
    "indexerror", "keyerror", "attributeerror", "typeerror",
    "no element found", "element not found", "cannot find",
    "selector", "parse error", "parseerror", "unexpected token",
    "expected", "json decode", "jsondecode",
)

TRANSIENT_NETWORK_PATTERNS = (
    "timeout", "timed out", "connection reset", "connection refused",
    "eof", "econnreset", "econnrefused", "broken pipe",
    "dns", "name resolution", "getaddrinfo", "ssl",
    "certificate", "tls", "temporary failure",
    "host unreachable", "network unreachable",
)

PERMANENT_PATTERNS = (
    "403", "forbidden", "418", "blocked",
    "captcha", "cloudflare", "access denied",
    "not found", "404",
    "gone", "410",
)


def categorize_error(error_text: str) -> str:
    """Categorize a source error into one of five categories."""
    lower = error_text.lower()

    # Check in priority order: page-structure (code errors) > permanent (access denied) > rate-limit > transient
    # Page structure errors (KeyError, JSONDecodeError) must be checked before "not found" in permanent
    for pat in PAGE_STRUCTURE_PATTERNS:
        if pat in lower:
            return "page_structure_change"

    for pat in PERMANENT_PATTERNS:
        if pat in lower:
            return "permanently_unavailable"

    for pat in RATE_LIMITED_PATTERNS:
        if pat in lower:
            return "rate_limited"

    for pat in TRANSIENT_NETWORK_PATTERNS:
        if pat in lower:
            return "transient_network"

    return "needs_investigation"


def triage_source(source_name: str, info: dict[str, Any]) -> dict[str, Any]:
    """Triage a single source, returning its triage entry."""
    ok = info.get("ok", True)
    last_error = str(info.get("last_error", "") or "")

    if ok:
        return {
            "source": source_name,
            "category": "healthy",
            "last_error": "",
            "last_success": info.get("last_success", ""),
        }

    category = categorize_error(last_error)
    return {
        "source": source_name,
        "category": category,
        "last_error": last_error[:200],
        "last_success": info.get("last_success", ""),
        "consecutive_failures": info.get("consecutive_failures", 0),
    }


def main():
    status = read_json(DATA_DIR / "status.json", {})
    sources = status.get("sources", {})
    if not sources:
        print("No source data found in status.json")
        return

    triaged = []
    categories: dict[str, int] = {}

    for name, info in sorted(sources.items()):
        entry = triage_source(name, info)
        triaged.append(entry)
        cat = entry["category"]
        categories[cat] = categories.get(cat, 0) + 1

    report = {
        "generated_at": datetime.now(BEIJING_TZ).isoformat(),
        "total_sources": len(triaged),
        "categories": categories,
        "sources": triaged,
    }

    write_json(TRIAGE_REPORT_PATH, report)

    print(f"--- Source Health Triage ---")
    print(f"Total sources:      {report['total_sources']}")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat:30s}: {count}")
    print(f"\nReport written to: {TRIAGE_REPORT_PATH}")

    # Highlight critical sources
    critical = [
        e for e in triaged
        if e["category"] in ("permanently_unavailable", "rate_limited")
    ]
    if critical:
        print(f"\n--- Critical Sources ({len(critical)}) ---")
        for e in critical:
            print(f"  [{e['category']}] {e['source']}: {e['last_error'][:100]}")


if __name__ == "__main__":
    main()