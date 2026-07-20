from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_ingestion  # noqa: E402
import dedupe  # noqa: E402
import enrich_china_relevance  # noqa: E402
import render_site  # noqa: E402


class ChinaRelevanceAndNepTests(unittest.TestCase):
    def test_nep_paper_number_is_scoped_to_issue(self) -> None:
        first = {
            "source_id": "repec-nep-mac",
            "paper_number": "p8",
            "source_url": "https://nep.repec.org/nep-mac/2026-06-15",
            "url": "https://nep.repec.org/nep-mac/2026-06-15#p8",
        }
        second = {
            "source_id": "repec-nep-mac",
            "paper_number": "p8",
            "source_url": "https://nep.repec.org/nep-mac/2026-06-22",
            "url": "https://nep.repec.org/nep-mac/2026-06-22#p8",
        }
        self.assertFalse(dedupe.record_match_keys(first) & dedupe.record_match_keys(second))

    def test_nep_article_and_anchor_match_within_same_issue(self) -> None:
        anchor = {
            "source_id": "repec-nep-mac",
            "paper_number": "p8",
            "source_url": "https://nep.repec.org/nep-mac/2026-06-15",
            "url": "https://nep.repec.org/nep-mac/2026-06-15#p8",
        }
        article = {
            "source_id": "repec-nep-mac",
            "paper_number": "p8",
            "source_url": "https://nep.repec.org/nep-mac/2026-06-15",
            "url": "https://econpapers.repec.org/RePEc:ris:kiepwe:022515",
        }
        self.assertTrue(dedupe.record_match_keys(anchor) & dedupe.record_match_keys(article))

    def test_author_name_and_source_label_are_not_direct_china_evidence(self) -> None:
        record = {
            "title": "A study of banking risk",
            "authors": ["China Smith"],
            "source_issue": "RePEc NEP China",
        }
        self.assertFalse(enrich_china_relevance.has_explicit_china_signal(record))

    def test_single_incidental_china_mention_is_only_candidate(self) -> None:
        record = {
            "title": "Global inflation spillovers",
            "abstract": "All EU regions are exposed to shocks from non-EU countries, namely Russia and China.",
        }
        self.assertEqual(enrich_china_relevance.classify(record)[0], "candidate")

    def test_direct_china_application_is_confirmed(self) -> None:
        record = {
            "title": "Public Pollution Information and Private Health Insurance Purchase",
            "abstract": "We study the staggered rollout of China's real-time air pollution monitoring program.",
        }
        self.assertEqual(enrich_china_relevance.classify(record)[0], "confirmed")

    def test_deepseek_shock_is_confirmed_without_literal_china(self) -> None:
        record = {
            "title": "Low-Cost AI and the Value of Compute Scarcity: Evidence from the DeepSeek Shock",
        }
        self.assertEqual(enrich_china_relevance.classify(record)[0], "confirmed")

    def test_renminbi_is_confirmed_as_direct_china_evidence(self) -> None:
        record = {
            "abstract": "We study how the renminbi can become an international reserve currency.",
        }
        self.assertEqual(enrich_china_relevance.classify(record)[0], "confirmed")

    def test_chinese_sounding_authors_alone_do_not_confirm_currency_paper(self) -> None:
        record = {
            "title": "A two-pronged approach to currency internationalization",
            "authors": ["Qing Liu", "Wenlan Luo", "Jiatong Niu"],
        }
        self.assertNotEqual(enrich_china_relevance.classify(record)[0], "confirmed")

    def test_ai_exclusion_remains_stable_during_rule_refresh(self) -> None:
        record = {
            "title": "A study of the United States",
            "china_related": False,
            "china_related_source": "ai",
            "china_relevance_reason": "研究对象为美国，不涉及中国",
        }
        updates, status = enrich_china_relevance.classification_updates(record)
        self.assertEqual(status, "none")
        self.assertFalse(updates["china_related"])
        self.assertEqual(updates["china_related_source"], "ai")

    def test_detail_page_separates_acceptance_from_online_date(self) -> None:
        record = {
            "title": "A just accepted paper",
            "authors": ["Test Author"],
            "available_online": "2026-07-20",
            "accepted_date": "2026-07-17",
            "detected_at": "2026-07-20T17:24:00+00:00",
            "source_type": "journal",
        }
        body = render_site.paper_detail_body(record, [record])
        self.assertIn("官方在线 2026-07-20", body)
        self.assertIn("接受日期", body)
        self.assertIn("不等同于正式上线", body)

    def test_editorial_board_is_suppressed_from_ingestion_audit(self) -> None:
        self.assertTrue(dedupe.is_source_navigation_noise({"title": "Editorial Board"}))


if __name__ == "__main__":
    unittest.main()
