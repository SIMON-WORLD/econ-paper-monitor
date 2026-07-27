import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_site  # noqa: E402


class PublicDateViewTests(unittest.TestCase):
    def test_seen_only_record_does_not_return_to_first_seen_day(self) -> None:
        record = {
            "_daily_date": "2026-07-27",
            "_from_seen_only": True,
            "first_seen": "2026-07-27T10:00:00+00:00",
            "available_online": "2025-06-04",
            "published_online": "2025-06-04",
        }

        self.assertFalse(render_site.record_is_on_date(record, "2026-07-27"))

    def test_seen_only_record_can_appear_when_officially_online_today(self) -> None:
        record = {
            "_daily_date": "2026-07-27",
            "_from_seen_only": True,
            "first_seen": "2026-07-27T10:00:00+00:00",
            "available_online": "2026-07-27",
            "published_online": "2026-07-27",
        }

        self.assertTrue(render_site.record_is_on_date(record, "2026-07-27"))

    def test_recent72_excludes_old_catalogue_backfill(self) -> None:
        record = {
            "detected_at": "2026-07-27T10:00:00+00:00",
            "available_online": "2025-06-04",
            "published_online": "2025-06-04",
            "title": "Banks vs. Firms: Who Benefits from Credit Guarantees?",
        }

        self.assertEqual(render_site.recent_detected_records([record], 3), [])


if __name__ == "__main__":
    unittest.main()
