"""Unit tests for the future-official-date audit metric."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from product_audit import audit  # noqa: E402


def record(rid: str, **overrides) -> dict:
    base = {
        "id": rid,
        "title": f"Paper {rid}",
        "doi": f"10.1/{rid}",
        "url": f"https://example.com/{rid}",
        "journal": "Test Journal",
        "journal_id": "test-j",
        "source": "rss",
        "source_type": "journal",
        "authors": ["A"],
        "abstract": "Some abstract.",
        "date_confidence": "C",
        "date_source": "crossref_elsevier_created_online",
        "_daily_date": "2026-06-22",
        "available_online": "2026-06-20",
        "published_online": "2026-06-20",
        "issue_date": None,
        "fields": [],
    }
    base.update(overrides)
    return base


class FutureOfficialDateTests(unittest.TestCase):
    def _future_count(self, records: list[dict]) -> int:
        return audit(records, set())["totals"]["future_official_date_in_bucket"]

    def test_month_label_is_not_counted_as_future(self):
        records = [record("1", available_online="August 202", issue_date="August 2026")]
        self.assertEqual(self._future_count(records), 0)

    def test_iso_future_date_is_counted(self):
        records = [record("2", available_online="2099-01-01")]
        self.assertEqual(self._future_count(records), 1)

    def test_iso_past_date_is_not_counted(self):
        records = [record("3", available_online="2000-01-01")]
        self.assertEqual(self._future_count(records), 0)

    def test_future_confidence_f_is_excluded(self):
        records = [record("4", available_online="2099-01-01", date_confidence="F")]
        self.assertEqual(self._future_count(records), 0)

    def test_empty_online_date_is_not_counted(self):
        records = [record("5", available_online=None, published_online=None)]
        self.assertEqual(self._future_count(records), 0)


if __name__ == "__main__":
    unittest.main()
