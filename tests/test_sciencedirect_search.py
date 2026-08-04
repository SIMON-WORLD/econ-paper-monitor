from __future__ import annotations

import sys
from datetime import date, timedelta
import unittest
import urllib.error
from email.message import Message
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

    @patch.object(fetch_sciencedirect_search, "fetch_text")
    def test_run_journal_records_captcha_reason_in_source_health_message(self, fetch_mock) -> None:
        fetch_mock.return_value = (
            "Title: Just a moment...\n# Are you a robot?\n"
            "Please complete the captcha challenge below."
        )
        journal = {
            "id": "journal-of-development-economics",
            "title": "Journal of Development Economics",
            "issn": "0304-3878",
        }
        records, message, error = fetch_sciencedirect_search.run_journal(
            journal,
            days=4,
            timeout=5,
            max_items=5,
        )
        self.assertEqual(records, [])
        self.assertIn("blocked-captcha", message)
        self.assertIsInstance(error, ValueError)

    def test_status_message_reflects_jina_key_state(self) -> None:
        with patch.dict(fetch_sciencedirect_search.os.environ, {"JINA_API_KEY": "test-key"}, clear=False):
            on_message = fetch_sciencedirect_search.build_status_message(2, 0, ["Journal A: 1"])
        with patch.dict(fetch_sciencedirect_search.os.environ, {}, clear=True):
            off_message = fetch_sciencedirect_search.build_status_message(2, 1, ["Journal A: blocked"])
        self.assertIn("jina_key=on", on_message)
        self.assertIn("failures=0", on_message)
        self.assertIn("jina_key=off", off_message)
        self.assertIn("failures=1", off_message)

    @patch.object(fetch_sciencedirect_search, "fetch_text")
    @patch.object(fetch_sciencedirect_search, "elsevier_core_metadata")
    def test_run_journal_success_with_jina_key(self, core_mock, fetch_mock) -> None:
        months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        recent = date.fromisoformat(fetch_sciencedirect_search.today_str()) - timedelta(days=1)
        label = f"{recent.day} {months[recent.month - 1]} {recent.year}"
        fetch_mock.return_value = (
            "## [A test paper](http://www.sciencedirect.com/science/article/pii/S0000000000000000)\n"
            f"[Journal of Development Economics](http://www.sciencedirect.com/science/journal/03043878)Available online {label}\n"
            "    1. Alice Author\n"
        )
        core_mock.return_value = {
            "doi": "10.1016/j.jdeveco.2026.103892",
            "title": "A test paper",
            "journal": "Journal of Development Economics",
            "available_online": recent.isoformat(),
        }
        journal = {
            "id": "journal-of-development-economics",
            "title": "Journal of Development Economics",
            "issn": "0304-3878",
            "publisher": "Elsevier",
        }
        with patch.dict(fetch_sciencedirect_search.os.environ, {"JINA_API_KEY": "test-key"}, clear=False):
            records, message, error = fetch_sciencedirect_search.run_journal(
                journal,
                days=4,
                timeout=5,
                max_items=5,
            )
        self.assertEqual(error, None)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["raw_data"]["pii"], "S0000000000000000")
        self.assertIn("Journal of Development Economics: 1", message)

    def test_fetch_text_retries_with_jina_key_header(self) -> None:
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        exc = urllib.error.HTTPError(
            "https://r.jina.ai/http://www.sciencedirect.com/search",
            429,
            "Too Many Requests",
            Message(),
            None,
        )
        response = FakeResponse(
            b"Title: ok\n## [A real result](http://www.sciencedirect.com/science/article/pii/S0000000000000000)\nAvailable online 1 August 2026"
        )
        with patch.object(fetch_sciencedirect_search, "time") as time_mock, patch.object(
            fetch_sciencedirect_search.urllib.request, "urlopen", side_effect=[exc, response]
        ) as urlopen_mock, patch.dict(fetch_sciencedirect_search.os.environ, {"JINA_API_KEY": "test-key"}, clear=False):
            result = fetch_sciencedirect_search.fetch_text("https://r.jina.ai/x", timeout=5)

        self.assertEqual(urlopen_mock.call_count, 2)
        self.assertTrue(result.startswith("Title: ok"))
        request_headers = urlopen_mock.call_args.args[0].headers
        self.assertEqual(request_headers.get("Authorization"), "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
