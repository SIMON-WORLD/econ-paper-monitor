from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backfill_cepr_authors import apply_author_state, normalize_authors  # noqa: E402


def test_normalize_authors_flattens_combined_meta_and_deduplicates() -> None:
    values = [
        "Benjamin Born",
        "Luis Huxel",
        "Gernot Müller",
        "Johannes Pfeifer",
        "Benjamin Born; Luis Huxel; Gernot Müller; Johannes Pfeifer",
    ]
    assert normalize_authors(values) == ["Benjamin Born", "Luis Huxel", "Gernot Müller", "Johannes Pfeifer"]


def test_normalize_authors_drops_empty_and_duplicate_parts() -> None:
    assert normalize_authors(["Alice Smith", "", "Alice Smith", "Bob Lee"]) == ["Alice Smith", "Bob Lee"]


def test_apply_author_state_marks_available() -> None:
    record = {"authors": ["Alice Smith"]}
    apply_author_state(record)
    assert record["authors_status_code"] == "available"
    assert record["authors_status"] is None
