from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clean_issue_month_labels import clean_record, normalize_month  # noqa: E402
from product_audit import malformed_dates, valid_date_value  # noqa: E402


def test_parseable_month_moves_to_issue_date():
    record = {
        "available_online": "March 2026",
        "published_online": "March 2026",
        "issue_date": None,
        "date_confidence": "C",
    }

    assert clean_record(record) is True

    assert record["available_online"] is None
    assert record["published_online"] is None
    assert record["issue_date"] == "2026-03"
    assert record["date_confidence"] == "D"


def test_truncated_month_is_cleared_as_missing():
    record = {
        "available_online": "September ",
        "published_online": "September ",
        "issue_date": "September ",
        "date_confidence": "C",
    }

    assert clean_record(record) is True

    assert record["available_online"] is None
    assert record["published_online"] is None
    assert record["issue_date"] is None
    assert record["date_confidence"] == "F"


def test_partial_year_month_is_cleared_as_missing():
    record = {
        "available_online": "August 202",
        "published_online": "August 202",
        "issue_date": "October 20",
        "date_confidence": "C",
    }

    assert clean_record(record) is True

    assert record["available_online"] is None
    assert record["published_online"] is None
    assert record["issue_date"] is None
    assert record["date_confidence"] == "F"


def test_valid_iso_is_unchanged():
    record = {
        "available_online": "2026-08-06",
        "published_online": "2026-08-06",
        "issue_date": "2026-08-01",
        "date_confidence": "A",
    }

    assert clean_record(record) is False
    assert record == {
        "available_online": "2026-08-06",
        "published_online": "2026-08-06",
        "issue_date": "2026-08-01",
        "date_confidence": "A",
    }


def test_normalize_month_requires_year():
    assert normalize_month("March 2026") == "2026-03"
    assert normalize_month("March") is None


def test_audit_accepts_month_precision_for_issue_date():
    assert valid_date_value("issue_date", "2026-03") is True
    assert valid_date_value("available_online", "2026-03") is False
    assert malformed_dates({"issue_date": "2026-03"}) == []
    assert "available_online" in malformed_dates({"available_online": "March 2026"})
