from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_sciencedirect_search  # noqa: E402


SAMPLE = """
1.   
Research article 
## [_Persistent_ global growth differences and euro area adjustment: Real activity, trade and the real exchange rate](http://www.sciencedirect.com/science/article/pii/S0022199626001030)

[_Journal_ of _International_ _Economics_](http://www.sciencedirect.com/science/journal/00221996)Available online 19 July 2026 
    1.   Adrian Ifrim
    2.   Robert Kollmann
    3.   Werner Roeger

2.   
Research article 
## [An unrelated result](http://www.sciencedirect.com/science/article/pii/S0000000000000000)

[Economic Modelling](http://www.sciencedirect.com/science/journal/02649993)Available online 19 July 2026 
    1.   Other Author
"""


class ScienceDirectSearchTests(unittest.TestCase):
    def test_parser_filters_by_journal_and_keeps_online_date(self) -> None:
        journal = {
            "id": "journal-of-international-economics",
            "title": "Journal of International Economics",
            "issn": "0022-1996",
        }

        records = fetch_sciencedirect_search.parse_search_results(SAMPLE, journal)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pii"], "S0022199626001030")
        self.assertEqual(records[0]["available_online"], "2026-07-19")
        self.assertEqual(records[0]["authors"], ["Adrian Ifrim", "Robert Kollmann", "Werner Roeger"])
        self.assertTrue(records[0]["title"].startswith("Persistent global growth"))

    def test_month_only_issue_date_is_not_treated_as_online_date(self) -> None:
        self.assertIsNone(fetch_sciencedirect_search.parse_online_date("August 2026"))

    @patch.object(fetch_sciencedirect_search, "fetch_text")
    def test_captcha_page_is_reported_not_silently_empty(self, fetch_mock) -> None:
        fetch_mock.return_value = (
            "Title: Just a moment...\n# Are you a robot?\n"
            "Please confirm you are a human by completing the captcha challenge."
        )
        journal = {
            "id": "journal-of-development-economics",
            "title": "Journal of Development Economics",
            "issn": "0304-3878",
        }
        with self.assertRaisesRegex(ValueError, "blocked-captcha"):
            fetch_sciencedirect_search.fetch_journal(
                journal,
                days=4,
                timeout=5,
                max_items=5,
            )


if __name__ == "__main__":
    unittest.main()
