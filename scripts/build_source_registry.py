"""Build and maintain the source registry used by fetchers.

The registry is intentionally conservative. It records where a journal should
be checked and what confidence we have in that source, but individual fetchers
remain responsible for parsing publisher-specific pages.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import DATA_DIR, load_journals, normalize_text, now_iso, read_json, write_json


REGISTRY_PATH = DATA_DIR / "source_registry.json"

CHINESE_SOURCES: dict[str, dict[str, Any]] = {
    "journal-f69300dae2": {
        "platform": "ajcass",
        "homepage": "https://zgncjj.ajcass.com/#/",
        "latest": "https://zgncjj.ajcass.com/#/",
        "adapter": "ajcass-api",
    },
    "journal-ba9f46c919": {
        "platform": "ajcass",
        "homepage": "https://erj.ajcass.com/#/index",
        "latest": "https://erj.ajcass.com/#/index",
        "adapter": "ajcass-api",
    },
    "journal-679eaa2a0c": {
        "platform": "magtech",
        "homepage": "https://sjjj.magtech.com.cn/CN/home",
        "latest": "https://sjjj.magtech.com.cn/CN/current",
        "adapter": "magtech-toc",
    },
    "journal-379b4022ce": {
        "platform": "cnki-wkb",
        "homepage": "https://glsj.chinajournal.net.cn/WKB/WebPublication/index.aspx?mid=glsj",
        "latest": "https://glsj.chinajournal.net.cn/WKB/WebPublication/advSearchPaperList.aspx?ys=2026&st=year",
        "adapter": "glsj-ajax",
        "notes": "CNKI/WKB may show CAPTCHA; scheduled runs should fail soft.",
    },
    "journal-bf2aa9381f": {
        "platform": "ajcass-cie",
        "homepage": "http://ciejournal.ajcass.com/?jumpnotice=201606280001",
        "latest": "http://ciejournal.ajcass.com/Magazine",
        "adapter": "cie-toc",
    },
    "journal-edcb877d78": {
        "platform": "jqte",
        "homepage": "https://www.jqte.net/sljjjsjjyj/ch/index.aspx",
        "latest": "https://www.jqte.net/sljjjsjjyj/ch/index.aspx",
        "adapter": "jqte-toc",
    },
}

ISSN_OVERRIDES: dict[str, dict[str, str]] = {
    "journal-of-economic-behavior-and-organization": {
        "print_issn": "0167-2681",
        "online_issn": "1879-1751",
    },
    "journal-of-finance": {
        "print_issn": "0022-1082",
        "online_issn": "1540-6261",
    },
    "journal-of-law-and-economics": {
        "print_issn": "0022-2186",
        "online_issn": "1537-5285",
    },
}

PUBLISHER_HOME: list[tuple[str, str, str]] = [
    ("elsevier", "sciencedirect", "https://www.sciencedirect.com/journal/{slug}"),
    ("wiley", "wiley", "https://onlinelibrary.wiley.com/journal/{issn_digits}"),
    ("oxford", "oup", "https://academic.oup.com/search-results?page=1&q={title_q}&fl_SiteID=191"),
    ("cambridge", "cambridge", "https://www.cambridge.org/core/search?filters%5Bkeywords%5D={title_q}"),
    ("springer", "springer", "https://link.springer.com/journal/{issn_digits}"),
    ("chicago", "uchicago", "https://www.journals.uchicago.edu/action/showPublications"),
    ("american economic association", "aea", "https://www.aeaweb.org/journals"),
    ("taylor", "tandf", "https://www.tandfonline.com/action/doSearch?AllField={title_q}"),
    ("informa", "tandf", "https://www.tandfonline.com/action/doSearch?AllField={title_q}"),
    ("mit press", "mitpress", "https://direct.mit.edu/journals"),
]


def slugify(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def issn_digits(value: str | None) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "")


def source_for_journal(journal: dict[str, Any]) -> dict[str, Any]:
    journal_id = str(journal["id"])
    title = str(journal.get("title") or journal_id)
    publisher = str(journal.get("publisher") or "")
    issn = str(journal.get("issn") or "")
    override = ISSN_OVERRIDES.get(journal_id, {})
    source_entry: dict[str, Any] = {
        "title": title,
        "publisher": publisher or None,
        "issn": issn or None,
        "online_issn": override.get("online_issn") or journal.get("online_issn") or journal.get("eissn"),
        "print_issn": override.get("print_issn") or journal.get("print_issn"),
        "rss": [],
        "sources": [],
        "status": "needs-source",
        "updated_at": now_iso(),
    }

    if journal_id in CHINESE_SOURCES:
        cn = CHINESE_SOURCES[journal_id]
        source_entry.update(
            {
                "platform": cn["platform"],
                "adapter": cn["adapter"],
                "status": "configured",
                "sources": [
                    {"type": "homepage", "url": cn["homepage"], "confidence": "B"},
                    {"type": "latest", "url": cn["latest"], "confidence": "B"},
                ],
            }
        )
        if cn.get("notes"):
            source_entry["notes"] = cn["notes"]
        return source_entry

    pub_lower = publisher.casefold()
    title_q = title.replace(" ", "+")
    slug = slugify(title)
    digits = issn_digits(issn)
    for needle, platform, template in PUBLISHER_HOME:
        if needle in pub_lower:
            url = template.format(slug=slug, title_q=title_q, issn_digits=digits)
            source_entry.update(
                {
                    "platform": platform,
                    "adapter": "publisher-generic",
                    "status": "candidate",
                    "sources": [{"type": "homepage", "url": url, "confidence": "C"}],
                }
            )
            return source_entry

    if issn:
        source_entry.update(
            {
                "platform": "crossref",
                "adapter": "crossref",
                "status": "crossref-only",
                "sources": [{"type": "crossref", "issn": issn, "confidence": "C"}],
            }
        )
    return source_entry


def build_registry(journals: list[dict[str, Any]], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing_journals = (existing or {}).get("journals", {})
    journals_out: dict[str, Any] = {}
    for journal in journals:
        entry = source_for_journal(journal)
        old = existing_journals.get(str(journal["id"]), {})
        if old.get("rss"):
            entry["rss"] = old["rss"]
            entry["rss_status"] = old.get("rss_status", "discovered")
        if old.get("last_checked_at"):
            entry["last_checked_at"] = old["last_checked_at"]
        for key, value in old.items():
            if key.startswith("last_") and key not in entry:
                entry[key] = value
        journals_out[str(journal["id"])] = entry
    return {
        "version": 1,
        "updated_at": now_iso(),
        "notes": "Generated from journals.yml. RSS URLs discovered later are appended by fetch_rss.py --discover.",
        "journals": journals_out,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()

    journals = load_journals(args.journals)
    existing = read_json(args.output, {"journals": {}})
    registry = build_registry(journals, existing)
    write_json(args.output, registry)
    counts: dict[str, int] = {}
    for entry in registry["journals"].values():
        counts[entry.get("status", "unknown")] = counts.get(entry.get("status", "unknown"), 0) + 1
    print(f"wrote {len(registry['journals'])} journal source entries to {args.output}")
    print(counts)


if __name__ == "__main__":
    main()
