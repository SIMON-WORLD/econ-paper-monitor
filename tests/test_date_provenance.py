from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_daily_vnext  # noqa: E402
import date_provenance  # noqa: E402


# The generator is 405/414 CRLF, so the two-line wiring is applied by the
# display owner locally rather than pushed through the API. These assertions
# activate as soon as that lands.
GENERATOR_IS_WIRED = "provenance_text" in Path(build_daily_vnext.__file__).read_text(encoding="utf-8")


class DateProvenanceLabelTests(unittest.TestCase):
    """PRODUCT.md: official dates are evidence, not decoration.

    A Crossref registry date and a publisher page date must not be presented
    with the same words, and every date must name the evidence behind it.
    """

    def test_publisher_and_official_rss_dates_are_official(self) -> None:
        for source in ("publisher_detail", "publisher_published_online", "rss_published", "rss_description_online", "elsevier_article_api", "cnki_rss_pubdate"):
            with self.subTest(source=source):
                self.assertEqual(date_provenance.date_kind({"date_source": source}), date_provenance.OFFICIAL)

    def test_crossref_and_openalex_dates_are_registry_not_official(self) -> None:
        for source in ("crossref_published_online", "crossref_doi_created", "crossref_elsevier_created_online", "openalex_publication_date"):
            with self.subTest(source=source):
                self.assertEqual(date_provenance.date_kind({"date_source": source}), date_provenance.REGISTRY)

    def test_issue_dates_are_issue_dates(self) -> None:
        for source in ("crossref_issue", "nep_issue_date", "iza_detail_month"):
            with self.subTest(source=source):
                self.assertEqual(date_provenance.date_kind({"date_source": source}), date_provenance.ISSUE)

    def test_missing_or_unknown_source_is_not_claimed_as_official(self) -> None:
        for record in ({"date_source": "unknown"}, {"date_source": ""}, {}):
            with self.subTest(record=record):
                self.assertEqual(date_provenance.date_kind(record), date_provenance.UNKNOWN)
                self.assertEqual(date_provenance.date_source_label(record), "未标注")

    def test_provenance_text_names_the_evidence(self) -> None:
        self.assertEqual(
            date_provenance.provenance_text({"date_source": "publisher_detail"}, "2026-08-03"),
            "官方在线日期：2026-08-03 · 来源：出版社页面",
        )
        self.assertEqual(
            date_provenance.provenance_text({"date_source": "crossref_published_online"}, "2026-08-03"),
            "登记日期：2026-08-03 · 来源：Crossref",
        )

    def test_no_date_is_stated_plainly(self) -> None:
        self.assertEqual(date_provenance.provenance_text({"date_source": "crossref_doi_created"}, ""), "官方日期暂未获取")


@unittest.skipUnless(GENERATOR_IS_WIRED, "build_daily_vnext is not wired to date_provenance yet")
class DailyHomepageDisclosesTheSourceTests(unittest.TestCase):
    """The panel is labelled 查看来源与日期, so it must actually show a source."""

    def _markup(self, date_source: str) -> str:
        record = {
            "id": "test-1",
            "title": "A test record",
            "url": "https://example.invalid/a",
            "journal": "Journal of Public Economics",
            "source_type": "journal",
            "official_date": "2026-08-03",
            "date_source": date_source,
            "detected_at": "2026-08-03T01:23:00+00:00",
        }
        markup, _ = build_daily_vnext.paper_markup(record, "2026-08-03", None)
        return markup

    def test_panel_contains_a_source_label(self) -> None:
        markup = self._markup("crossref_published_online")
        self.assertIn("查看来源与日期", markup)
        self.assertIn("来源：Crossref", markup)

    def test_registry_date_is_not_labelled_as_an_official_online_date(self) -> None:
        markup = self._markup("crossref_published_online")
        self.assertIn("登记日期：2026-08-03", markup)
        self.assertNotIn("官方在线日期", markup)

    def test_publisher_date_keeps_the_official_wording(self) -> None:
        markup = self._markup("publisher_detail")
        self.assertIn("官方在线日期：2026-08-03", markup)
        self.assertIn("来源：出版社页面", markup)


if __name__ == "__main__":
    unittest.main()
