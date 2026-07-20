from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_ingestion  # noqa: E402
import dedupe  # noqa: E402
import enrich_china_relevance  # noqa: E402


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

    def test_editorial_board_is_suppressed_from_ingestion_audit(self) -> None:
        self.assertTrue(dedupe.is_source_navigation_noise({"title": "Editorial Board"}))


if __name__ == "__main__":
    unittest.main()
