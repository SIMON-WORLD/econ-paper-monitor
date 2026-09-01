"""Regression: translated title_zh must not carry working-paper number prefixes.

P0 2026-09-01 follow-up: translation of CEPR/NBER titles (e.g. "DP21895
Educating like China") can copy the number prefix into title_zh, which trips
the public data integrity gate (title_zh_number_prefixes). translate.py must
strip those prefixes after translation; paper_number is preserved / filled.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import translate


def test_clean_title_zh_strips_dp_prefix() -> None:
    record = {
        "title": "DP21895 Educating like China",
        "title_zh": "DP21895 像中国一样教育",
        "paper_number": "DP21895",
    }
    changed = translate.clean_title_zh(record)
    assert changed is True
    assert record["title_zh"] == "像中国一样教育"
    assert record["paper_number"] == "DP21895"


def test_clean_title_zh_fills_missing_paper_number() -> None:
    record = {"title": "NBER Working Paper 31093 The Long-Run Effects", "title_zh": "NBER Working Paper 31093 长期效应"}
    changed = translate.clean_title_zh(record)
    assert changed is True
    assert record["title_zh"] == "长期效应"
    assert record["paper_number"] == "NBER Working Paper 31093"


def test_clean_title_zh_leaves_clean_titles_untouched() -> None:
    record = {"title": "Some Paper", "title_zh": "一些论文", "paper_number": "DP1"}
    changed = translate.clean_title_zh(record)
    assert changed is False
    assert record["title_zh"] == "一些论文"


def test_clean_title_zh_ignores_missing_translation() -> None:
    record = {"title": "Some Paper", "title_zh": ""}
    assert translate.clean_title_zh(record) is False
