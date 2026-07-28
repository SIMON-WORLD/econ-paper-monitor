import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from dedupe import archive_date_for_new_record


def test_openalex_recall_never_enters_public_daily_archive():
    record = {
        "source": "openalex_recall",
        "available_online": "2026-07-28",
        "published_online": "2026-07-28",
    }

    assert archive_date_for_new_record(record, "2026-07-28") is None


def test_openalex_recall_does_not_claim_a_future_public_date():
    record = {
        "source": "openalex_recall",
        "available_online": "2026-07-29",
    }

    assert archive_date_for_new_record(record, "2026-07-28") is None
