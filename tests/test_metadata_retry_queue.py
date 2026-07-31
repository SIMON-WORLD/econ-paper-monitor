import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from build_metadata_retry_queue import queue_item


def test_queue_prioritizes_recent_missing_abstract():
    item = queue_item(
        {
            "title": "Recent paper",
            "journal": "Example Journal",
            "doi": "10.1234/example",
            "first_seen": "2026-07-28T10:00:00+00:00",
            "available_online": "2026-07-28",
            "date_confidence": "B",
        },
        date(2026, 7, 28),
        date(2026, 7, 1),
    )

    assert item is not None
    assert item["reasons"] == ["missing_abstract", "missing_authors"]
    assert item["priority"][:3] == [0, 0, 0]


def test_complete_record_is_not_queued():
    assert queue_item(
        {
            "title": "Complete paper",
            "authors": ["A. Author"],
            "abstract": "A sufficiently complete abstract.",
            "first_seen": "2026-07-20",
            "available_online": "2026-07-20",
            "date_confidence": "A",
        },
        date(2026, 7, 28),
        date(2026, 7, 1),
    ) is None


def test_old_official_date_is_not_made_recent_by_recent_backfill_detection():
    item = queue_item(
        {
            "title": "Historical backfill",
            "journal": "Example Journal",
            "authors": ["A. Author"],
            "first_seen": "2026-07-28T10:00:00+00:00",
            "official_date": "2025-01-15",
            "historical_backfill": True,
            "date_confidence": "B",
        },
        date(2026, 7, 28),
        date(2026, 7, 1),
    )

    assert item is not None
    assert item["priority"][0] == 1
    assert item["recency_basis"] == "official_date"
    assert item["historical_backfill"] is True


def test_first_seen_is_used_only_when_no_official_date_exists():
    item = queue_item(
        {
            "title": "New paper without official date",
            "journal": "Example Journal",
            "authors": ["A. Author"],
            "first_seen": "2026-07-28T10:00:00+00:00",
            "date_confidence": "F",
        },
        date(2026, 7, 28),
        date(2026, 7, 1),
    )

    assert item is not None
    assert item["priority"][0] == 0
    assert item["recency_basis"] == "first_seen"


def test_acceptance_date_does_not_satisfy_official_date_recovery():
    item = queue_item(
        {
            "title": "Accepted but not published",
            "journal": "Example Journal",
            "authors": ["A. Author"],
            "first_seen": "2026-07-28T10:00:00+00:00",
            "accepted_date": "2025-01-15",
            "date_confidence": "A",
        },
        date(2026, 7, 28),
        date(2026, 7, 1),
    )

    assert item is not None
    assert item["official_date"] is None
    assert item["recency_basis"] == "first_seen"


def test_nonpaper_record_never_enters_metadata_retry_queue():
    assert queue_item(
        {
            "title": "Review of Economics and Statistics 2026 Annual Report",
            "journal": "Review of Economics and Statistics",
            "first_seen": "2026-07-28T10:00:00+00:00",
            "date_confidence": "B",
        },
        date(2026, 7, 28),
        date(2026, 7, 1),
    ) is None
