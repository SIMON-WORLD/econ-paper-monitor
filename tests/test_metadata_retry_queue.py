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
