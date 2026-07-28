from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_alohomora_coverage  # noqa: E402
import dedupe  # noqa: E402
import fetch_aea  # noqa: E402


class AeaIngestionTests(unittest.TestCase):
    def test_article_link_removes_tracking_parameters(self) -> None:
        html = '''<a href="/articles?id=10.1257/aer.20240666&amp;&amp;from=f">Durables and the Marginal Propensity to Spend</a>'''

        links = fetch_aea.article_links(html)

        self.assertEqual(
            links,
            [
                (
                    "https://www.aeaweb.org/articles?id=10.1257/aer.20240666",
                    "Durables and the Marginal Propensity to Spend",
                )
            ],
        )

    def test_external_sentinel_doi_removes_tracking_parameters(self) -> None:
        value = "https://www.aeaweb.org/articles?id=10.1257/aer.20240666&&from=f"
        self.assertEqual(audit_alohomora_coverage.doi_from_url(value), "10.1257/aer.20240666")

    def test_seen_records_preserve_first_discovery_without_fake_public_date(self) -> None:
        with patch.object(
            audit_alohomora_coverage,
            "read_json",
            return_value={"doi:test": {"title": "Forthcoming paper", "first_seen": "2026-07-28T10:00:00+00:00"}},
        ):
            records = audit_alohomora_coverage.seen_records()
        self.assertEqual(records[0]["_local_first_seen_date"], "2026-07-28")
        self.assertIsNone(audit_alohomora_coverage.public_date(records[0]))

    def test_article_url_provides_doi_without_detail_request(self) -> None:
        url = "https://www.aeaweb.org/articles?id=10.1257/aer.20240666"
        self.assertEqual(fetch_aea.doi_from_article_url(url), "10.1257/aer.20240666")

    def test_aea_article_query_is_part_of_dedupe_identity(self) -> None:
        first = {
            "title": "First paper",
            "url": "https://www.aeaweb.org/articles?id=10.1257/aer.first",
        }
        second = {
            "title": "Second paper",
            "url": "https://www.aeaweb.org/articles?id=10.1257/aer.second",
        }

        self.assertFalse(dedupe.record_match_keys(first) & dedupe.record_match_keys(second))

    def test_forthcoming_without_date_uses_first_detection_archive(self) -> None:
        record = {
            "source": "aea_toc",
            "date_source": "aea_forthcoming",
            "raw_data": {"aea_first_observed": True},
        }
        self.assertEqual(dedupe.archive_date_for_new_record(record, "2026-07-15"), "2026-07-15")

    def test_forthcoming_baseline_does_not_pollute_today(self) -> None:
        record = {
            "source": "aea_toc",
            "date_source": "aea_forthcoming",
            "raw_data": {"aea_first_observed": False, "aea_snapshot_baseline": True},
        }
        self.assertIsNone(dedupe.archive_date_for_new_record(record, "2026-07-15"))

    def test_uninitialized_snapshot_promotes_only_confirmed_external_new_items(self) -> None:
        records = [
            {
                "doi": "10.1257/aer.new",
                "url": "https://www.aeaweb.org/articles?id=10.1257/aer.new",
                "authors": [],
                "raw_data": {},
            },
            {
                "doi": "10.1257/aer.old",
                "url": "https://www.aeaweb.org/articles?id=10.1257/aer.old",
                "authors": [],
                "raw_data": {},
            },
        ]
        snapshot: dict[str, list[str]] = {}
        promotions = {
            "10.1257/aer.new": {
                "external_first_seen_date": "2026-07-16",
                "author": "One Author, Two Author",
            }
        }

        fetch_aea.annotate_snapshot_records(records, "american-economic-review", snapshot, promotions)

        self.assertTrue(records[0]["raw_data"]["aea_first_observed"])
        self.assertEqual(records[0]["authors"], ["One Author", "Two Author"])
        self.assertFalse(records[1]["raw_data"]["aea_first_observed"])
        self.assertTrue(records[1]["raw_data"]["aea_snapshot_baseline"])
        self.assertEqual(len(snapshot["american-economic-review"]), 2)

    def test_initialized_snapshot_marks_only_new_doi(self) -> None:
        records = [
            {"doi": "10.1257/aer.old", "url": "https://www.aeaweb.org/articles?id=10.1257/aer.old", "raw_data": {}},
            {"doi": "10.1257/aer.new", "url": "https://www.aeaweb.org/articles?id=10.1257/aer.new", "raw_data": {}},
        ]
        snapshot = {"american-economic-review": ["10.1257/aer.old"]}

        fetch_aea.annotate_snapshot_records(records, "american-economic-review", snapshot, {})

        self.assertFalse(records[0]["raw_data"]["aea_first_observed"])
        self.assertTrue(records[1]["raw_data"]["aea_first_observed"])

    def test_empty_failed_fetch_does_not_initialize_snapshot(self) -> None:
        snapshot: dict[str, list[str]] = {}

        fetch_aea.annotate_snapshot_records([], "american-economic-review", snapshot, {})

        self.assertNotIn("american-economic-review", snapshot)

    def test_partial_page_failure_keeps_journal_usable_when_records_exist(self) -> None:
        status = fetch_aea.journal_status_entry(
            [{"doi": "10.1257/jep.20251470"}],
            ["forthcoming: HTTPError: 404"],
        )
        self.assertTrue(status["ok"])
        self.assertEqual(status["count"], 1)
        self.assertIn("404", status["message"])

    @patch.object(fetch_aea, "enrich_article")
    @patch.object(fetch_aea, "fetch_text")
    def test_current_issue_limit_does_not_skip_forthcoming(self, fetch_mock, enrich_mock) -> None:
        forthcoming = '''
        <a href="/articles?id=10.1257/aer.new1&amp;&amp;from=f">New Paper One</a>
        <a href="/articles?id=10.1257/aer.new2&amp;&amp;from=f">New Paper Two</a>
        '''
        current = '''
        <a href="/articles?id=10.1257/aer.old1">Old Paper One</a>
        <a href="/articles?id=10.1257/aer.old2">Old Paper Two</a>
        '''
        fetch_mock.side_effect = [forthcoming, current]
        enrich_mock.side_effect = lambda url, title, timeout: {"title": title, "doi": url.split("id=")[-1]}
        journal = {"id": "american-economic-review", "title": "American Economic Review"}

        records, errors = fetch_aea.fetch_journal(journal, "aer", timeout=1, detail_limit=4, max_items=1)

        self.assertEqual(errors, [])
        self.assertEqual([record["doi"] for record in records], ["10.1257/aer.new1", "10.1257/aer.old1"])


if __name__ == "__main__":
    unittest.main()
