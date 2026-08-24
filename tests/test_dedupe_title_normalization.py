from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dedupe import record_match_keys  # noqa: E402


class TitleKeyNormalizationTests(unittest.TestCase):
    def test_fullwidth_and_halfwidth_colon_titles_match(self) -> None:
        raw = {
            "source": "cnki-rss",
            "source_type": "journal",
            "journal": "中国农村经济",
            "journal_id": "journal-f69300dae2",
            "title": "“三链协同”何以可能:返乡入乡创业者赋能乡村产业振兴的逻辑与路径",
            "url": "https://kns.cnki.net/kcms2/article/abstract?v=AAA",
        }
        existing = {
            "source": "cn-official",
            "source_type": "journal",
            "journal": "中国农村经济",
            "journal_id": "journal-f69300dae2",
            "title": "“三链协同”何以可能：返乡入乡创业者赋能乡村产业振兴的逻辑与路径",
            "url": "https://zgncjj.ajcass.com/#/detail?contentId=123394",
        }
        self.assertTrue(record_match_keys(raw) & record_match_keys(existing))

    def test_distinct_titles_still_do_not_match(self) -> None:
        first = {
            "source": "cnki-rss",
            "source_type": "journal",
            "journal": "中国农村经济",
            "journal_id": "journal-f69300dae2",
            "title": "“三链协同”何以可能:返乡入乡创业者赋能乡村产业振兴的逻辑与路径",
        }
        second = {
            "source": "cnki-rss",
            "source_type": "journal",
            "journal": "中国农村经济",
            "journal_id": "journal-f69300dae2",
            "title": "另一篇完全不同的论文：主题并不相同",
        }
        self.assertFalse(record_match_keys(first) & record_match_keys(second))

    def test_short_title_cnki_rss_matches_cn_official(self) -> None:
        raw = {
            "source": "cnki-rss",
            "source_type": "journal",
            "journal": "中国农村经济",
            "journal_id": "journal-f69300dae2",
            "title": "共建“一带一路”的粮食安全效应",
        }
        existing = {
            "source": "cn-official",
            "source_type": "journal",
            "journal": "中国农村经济",
            "journal_id": "journal-f69300dae2",
            "title": "共建“一带一路”的粮食安全效应",
        }
        self.assertTrue(record_match_keys(raw) & record_match_keys(existing))


if __name__ == "__main__":
    unittest.main()
