from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import load_journals  # noqa: E402
import fetch_crossref  # noqa: E402


class JournalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journals = {item["id"]: item for item in load_journals()}

    def test_journal_of_finance_identity(self) -> None:
        self.assertEqual(self.journals["journal-of-finance"]["issn"], "0022-1082")

    def test_journal_of_law_and_economics_identity(self) -> None:
        self.assertEqual(self.journals["journal-of-law-and-economics"]["issn"], "0022-2186")

    def test_journal_of_agricultural_and_resource_economics_identity(self) -> None:
        self.assertEqual(self.journals["journal-of-agricultural-and-resource-economics"]["issn"], "1068-5502")

    def test_configured_issn_excludes_stale_registry_identity(self) -> None:
        journal = self.journals["journal-of-finance"]
        self.assertEqual(fetch_crossref.journal_issns(journal), ["0022-1082"])

    def test_jebo_print_issn_included(self) -> None:
        journal = self.journals["journal-of-economic-behavior-and-organization"]
        issns = fetch_crossref.journal_issns(journal)
        self.assertIn("1879-1751", issns)
        self.assertIn("0167-2681", issns)

    def test_batch1_journal_identities(self) -> None:
        expected = {
            "management-science": ("0025-1909", "1526-5501"),
            "journal-of-accounting-and-economics": ("0165-4101", None),
            "journal-of-health-economics": ("0167-6296", None),
            "journal-of-financial-and-quantitative-analysis": ("0022-1090", "1756-6916"),
            "journal-of-human-resources": ("0022-166X", "1548-8004"),
            "journal-of-business-and-economic-statistics": ("0735-0015", "1537-2707"),
            "journal-of-financial-intermediation": ("1042-9573", "1096-0473"),
            "review-of-accounting-studies": ("1380-6653", "1573-7136"),
            "journal-of-risk-and-uncertainty": ("0895-5646", "1573-0476"),
            "journal-of-corporate-finance": ("0929-1199", None),
        }
        for journal_id, (issn, eissn) in expected.items():
            with self.subTest(journal_id=journal_id):
                journal = self.journals[journal_id]
                self.assertEqual(journal["issn"], issn)
                self.assertEqual(journal.get("eissn"), eissn)

    def test_render_journals_yml_preserves_optional_issns(self) -> None:
        from common import render_journals_yml

        journals = [{
            "id": "test-j",
            "title": "Test Journal",
            "short_name": "TJ",
            "aliases": ["TJ"],
            "chinese_name": "测试期刊",
            "fields": ["general"],
            "public_group": "综合",
            "priority_private": "A",
            "issn": "0000-0000",
            "eissn": "1111-1111",
            "print_issn": "2222-2222",
            "publisher": "Test Press",
            "sources": [{"type": "crossref", "issn": "0000-0000"}],
        }]
        text = render_journals_yml(journals)
        self.assertIn('eissn: "1111-1111"', text)
        self.assertIn('print_issn: "2222-2222"', text)


if __name__ == "__main__":
    unittest.main()
