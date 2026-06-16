"""Unified article record helpers for source adapters."""

from __future__ import annotations

from typing import Any

from common import now_iso


def article_record(
    journal: dict[str, Any],
    *,
    title: str,
    url: str | None,
    source: str,
    source_url: str | None = None,
    doi: str | None = None,
    authors: list[str] | None = None,
    abstract: str | None = None,
    published_online: str | None = None,
    available_online: str | None = None,
    accepted_date: str | None = None,
    issue_date: str | None = None,
    source_issue: str | None = None,
    date_source: str | None = None,
    date_confidence: str | None = None,
    raw_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title or "",
        "title_zh": None,
        "abstract": abstract,
        "abstract_zh": None,
        "authors": authors or [],
        "journal": journal["title"],
        "journal_short": journal.get("short_name"),
        "journal_id": journal["id"],
        "source_type": "journal",
        "source": source,
        "source_url": source_url,
        "publisher": journal.get("publisher"),
        "published_online": published_online,
        "available_online": available_online,
        "accepted_date": accepted_date,
        "issue_date": issue_date,
        "source_issue": source_issue,
        "date_source": date_source,
        "date_confidence": date_confidence,
        "detected_at": now_iso(),
        "doi": doi,
        "url": url,
        "pdf_url": None,
        "fields": journal.get("fields", []),
        "ai_tags": [],
        "translation_status": "missing_abstract",
        "raw_data": raw_data or {},
    }

