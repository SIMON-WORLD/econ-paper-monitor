"""Unit tests for scripts/fetch_uchicago_local.py (offline, no network)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_uchicago_local as uchicago  # noqa: E402
from common import DATA_DIR, today_str  # noqa: E402


# Mirror of the real UChicago Press etoc feed: RSS 1.0/RDF with namespaced
# <item> nodes directly under <rdf:RDF>, dc:identifier (doi:...), dc:date and
# prism:doi per item. Kept close to the live response so the parsing branch
# under test is the same one used in production.
RSS_1_0_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:content="http://purl.org/rss/1.0/modules/content/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">
   <channel rdf:about="https://www.journals.uchicago.edu/loi/jpe?af=R">
      <title>The University of Chicago Press: Journal of Political Economy: Table of Contents</title>
      <description>Table of Contents for Journal of Political Economy. List of articles from both the latest and ahead of print issues.</description>
      <link>https://www.journals.uchicago.edu/loi/jpe?af=R</link>
      <dc:title>The University of Chicago Press: Journal of Political Economy: Table of Contents</dc:title>
      <dc:publisher>The University of Chicago Press</dc:publisher>
      <dc:language>en-US</dc:language>
      <prism:publicationName>Journal of Political Economy</prism:publicationName>
      <items>
         <rdf:Seq>
            <rdf:li rdf:resource="https://www.journals.uchicago.edu/doi/abs/10.1086/740172?af=R"/>
            <rdf:li rdf:resource="https://www.journals.uchicago.edu/doi/abs/10.1086/740219?af=R"/>
         </rdf:Seq>
      </items>
   </channel>
   <item rdf:about="https://www.journals.uchicago.edu/doi/abs/10.1086/740172?af=R">
      <title>The Gas Trap: Outcompeting Coal versus Renewables</title>
      <link>https://www.journals.uchicago.edu/doi/abs/10.1086/740172?af=R</link>
      <content:encoded>Journal of Political Economy, &lt;a href="https://www.journals.uchicago.edu/toc/jpe/2026/134/7"&gt;Volume 134, Issue 7&lt;/a&gt;, Page 2166-2214, July 2026. &lt;br/&gt;</content:encoded>
      <description>Journal of Political Economy, Volume 134, Issue 7, Page 2166-2214, July 2026. &lt;br/&gt;</description>
      <dc:title>The Gas Trap: Outcompeting Coal versus Renewables</dc:title>
      <dc:identifier>doi:10.1086/740172</dc:identifier>
      <dc:source>Journal of Political Economy</dc:source>
      <dc:date>2026-05-05T02:02:24Z</dc:date>
      <dc:creator>Bård HarstadKatinka HoltsmarkStanford University, National Bureau of Economic Research, and Centre for Economic Policy ResearchUniversity of Oslo</dc:creator>
      <prism:publicationName>Journal of Political Economy</prism:publicationName>
      <prism:volume>134</prism:volume>
      <prism:number>7</prism:number>
      <prism:startingPage>2166</prism:startingPage>
      <prism:endingPage>2214</prism:endingPage>
      <prism:coverDate>2026-07-01T07:00:00Z</prism:coverDate>
      <prism:doi>10.1086/740172</prism:doi>
      <prism:url>https://www.journals.uchicago.edu/doi/abs/10.1086/740172?af=R</prism:url>
      <prism:copyright/>
   </item>
   <item rdf:about="https://www.journals.uchicago.edu/doi/abs/10.1086/740219?af=R">
      <title>Second article from the same issue</title>
      <link>https://www.journals.uchicago.edu/doi/abs/10.1086/740219?af=R</link>
      <description>Journal of Political Economy, Volume 134, Issue 7, Page 2215-2250, July 2026. &lt;br/&gt;</description>
      <dc:identifier>doi:10.1086/740219</dc:identifier>
      <dc:date>2026-05-06T02:02:24Z</dc:date>
      <prism:publicationName>Journal of Political Economy</prism:publicationName>
      <prism:doi>10.1086/740219</prism:doi>
      <prism:url>https://www.journals.uchicago.edu/doi/abs/10.1086/740219?af=R</prism:url>
   </item>
</rdf:RDF>
"""


def jpe_journal() -> dict:
    return next(j for j in uchicago.uchicago_journals() if j["id"] == "journal-of-political-economy")


def fake_record(journal: dict) -> dict:
    return {"title": f"Paper for {journal['id']}", "url": journal["feed_url"], "journal_id": journal["id"]}


class UChicagoRssParseTests(unittest.TestCase):
    def test_parse_uchicago_rdf_feed(self):
        journal = jpe_journal()
        self.assertTrue(uchicago.feed_identity_matches(RSS_1_0_SAMPLE, journal))
        records = uchicago.parse_feed(RSS_1_0_SAMPLE, journal, journal["feed_url"])
        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["title"], "The Gas Trap: Outcompeting Coal versus Renewables")
        self.assertEqual(first["url"], "https://www.journals.uchicago.edu/doi/abs/10.1086/740172?af=R")
        self.assertEqual(first["doi"], "10.1086/740172")
        self.assertEqual(first["published_online"], "2026-05-05")
        self.assertEqual(first["date_source"], "rss_published")
        self.assertEqual(first["date_confidence"], "A")
        self.assertEqual(first["journal_id"], "journal-of-political-economy")
        self.assertEqual(first["publisher"], "The University of Chicago Press")
        second = records[1]
        self.assertEqual(second["title"], "Second article from the same issue")
        self.assertEqual(second["doi"], "10.1086/740219")
        self.assertEqual(second["published_online"], "2026-05-06")


class UChicagoStatusTests(unittest.TestCase):
    def test_status_published_when_all_sources_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "2026-08-06.json"
            status_path = Path(tmp) / "status.json"
            with mock.patch.object(uchicago, "fetch_one", side_effect=lambda journal, **kwargs: [fake_record(journal)]):
                payload = uchicago.run_pipeline(output=output, status_path=status_path)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["state"], "published")
            self.assertEqual(payload["selected_sources"], 4)
            self.assertEqual(payload["successful_sources"], 4)
            self.assertEqual(payload["failed_sources"], 0)
            self.assertEqual(payload["count"], 4)
            self.assertEqual(payload["last_success_at"], payload["updated_at"])
            self.assertRegex(payload["updated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
            self.assertIn("全部成功", payload["message"])
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(written), 4)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(status, payload)

    def test_status_error_on_partial_failure_but_records_still_written(self):
        def flaky_fetch(journal, **kwargs):
            if journal["id"] == "journal-of-law-and-economics":
                raise RuntimeError("HTTP Error 403: Forbidden")
            return [fake_record(journal)]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "2026-08-06.json"
            status_path = Path(tmp) / "status.json"
            with mock.patch.object(uchicago, "fetch_one", side_effect=flaky_fetch):
                payload = uchicago.run_pipeline(output=output, status_path=status_path)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["state"], "error")
            self.assertEqual(payload["selected_sources"], 4)
            self.assertEqual(payload["successful_sources"], 3)
            self.assertEqual(payload["failed_sources"], 1)
            self.assertEqual(payload["count"], 3)
            self.assertIn("journal-of-law-and-economics", payload["message"])
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(written), 3)
            self.assertEqual(json.loads(status_path.read_text(encoding="utf-8"))["state"], "error")

    def test_last_success_at_preserved_on_later_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            status_path.write_text(
                json.dumps({"state": "published", "ok": True, "last_success_at": "2026-08-05T12:00:00+00:00"}),
                encoding="utf-8",
            )
            with mock.patch.object(
                uchicago, "fetch_one", side_effect=RuntimeError("HTTP Error 403: Forbidden")
            ):
                payload = uchicago.run_pipeline(output=Path(tmp) / "2026-08-06.json", status_path=status_path)
            self.assertEqual(payload["state"], "error")
            self.assertEqual(payload["last_success_at"], "2026-08-05T12:00:00+00:00")


class UChicagoPathAndSelectionTests(unittest.TestCase):
    def test_default_output_path_uses_today(self):
        expected = DATA_DIR / "raw" / "uchicago-local" / f"{today_str()}.json"
        self.assertEqual(uchicago.default_output_path(), expected)

    def test_only_accepts_journal_id_or_jc_code(self):
        selected = uchicago.select_journals(["jpe", "journal-of-labor-economics"])
        self.assertEqual(
            [journal["id"] for journal in selected],
            ["journal-of-political-economy", "journal-of-labor-economics"],
        )
        with self.assertRaises(ValueError):
            uchicago.select_journals(["not-a-journal"])

    def test_journal_descriptors_carry_identity_fields(self):
        for journal in uchicago.uchicago_journals():
            self.assertTrue(journal["id"])
            self.assertTrue(journal["title"])
            self.assertTrue(journal["short_name"])
            self.assertEqual(journal["publisher"], "The University of Chicago Press")
            self.assertIn("jc=", journal["feed_url"])


if __name__ == "__main__":
    unittest.main()
