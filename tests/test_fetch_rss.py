"""Unit tests for RSS record construction and Springer feed parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_rss  # noqa: E402


JOURNAL = {
    "id": "public-choice",
    "title": "Public Choice",
    "short_name": "PC",
    "publisher": "Springer-Verlag",
}
FEED_URL = "https://link.springer.com/search.rss?facet-journal-id=11127"


class RssRecordTests(unittest.TestCase):
    def test_bare_doi_guid_is_extracted(self):
        record = fetch_rss.make_record(
            "Fairness trade-offs in expert evaluation",
            "https://link.springer.com/article/10.1007/s11127-026-01444-z",
            "2026-08-04",
            JOURNAL,
            FEED_URL,
            guid="10.1007/s11127-026-01444-z",
        )
        self.assertEqual(record["doi"], "10.1007/s11127-026-01444-z")
        self.assertEqual(record["date_source"], "rss_published")
        self.assertEqual(record["date_confidence"], "A")

    def test_rss_published_date_is_grade_a(self):
        record = fetch_rss.make_record(
            "A title",
            "https://example.com/a",
            "2026-08-01",
            JOURNAL,
            "https://example.com/feed",
        )
        self.assertEqual(record["date_confidence"], "A")

    def test_no_date_falls_back_to_f(self):
        record = fetch_rss.make_record("A title", "https://example.com/a", None, JOURNAL, "https://example.com/feed")
        self.assertEqual(record["date_confidence"], "F")

    def test_parse_springer_rss_item(self):
        xml = (
            '<?xml version="1.0"?><rss version="2.0"><channel><title>Latest Results</title>'

            "<item><title>T</title><description><p>Abstract text with substance.</p></description>"
            "<link>https://link.springer.com/article/10.1007/s11127-026-01444-z</link>"
            "<pubDate>2026-08-04</pubDate><guid>10.1007/s11127-026-01444-z</guid></item>"
            "</channel></rss>"
        )
        records = fetch_rss.parse_feed(xml, JOURNAL, FEED_URL)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["doi"], "10.1007/s11127-026-01444-z")
        self.assertEqual(records[0]["published_online"], "2026-08-04")

    def test_child_text_any_reads_nested_elements(self):
        from xml.etree import ElementTree

        item = ElementTree.fromstring("<item><description><p>Nested text with substance.</p></description></item>")
        self.assertEqual(fetch_rss.child_text_any(item, ["description"]), "Nested text with substance.")


if __name__ == "__main__":
    unittest.main()

    def test_fetch_journal_feed_retries_transient_failure(self):
        xml = (
            '<?xml version="1.0"?><rss version="2.0"><channel><item>'
            "<title>T</title><link>https://example.com/a</link><pubDate>2026-08-01</pubDate></item>"
            "</channel></rss>"
        )
        real = fetch_rss.fetch_feed_with_retry
        calls = {"n": 0}

        def flaky_once(url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return xml

        with unittest.mock.patch.object(fetch_rss, "fetch_feed_with_retry", side_effect=flaky_once):
            records, error = fetch_rss.fetch_journal_feed(JOURNAL, {"url": "https://example.com/feed"})
        self.assertIsNone(error)
        self.assertEqual(len(records), 1)
        self.assertEqual(calls["n"], 2)

    def test_fetch_journal_feed_returns_error_after_retries(self):
        with unittest.mock.patch.object(fetch_rss, "fetch_feed_with_retry", side_effect=ConnectionError("blocked")):
            records, error = fetch_rss.fetch_journal_feed(JOURNAL, {"url": "https://example.com/feed"})
        self.assertEqual(records, [])
        self.assertIn("ConnectionError", error)
