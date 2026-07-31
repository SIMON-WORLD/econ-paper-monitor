"""Regression tests for abstract/author/date recovery via OpenAlex and Semantic Scholar."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from recover_abstracts_openalex import (
    is_placeholder_abstract,
    record_needs_abstract,
    record_needs_authors,
    record_needs_date,
    needs_recovery,
    deduplicate_candidates,
    apply_recovery,
)


class TestPlaceholderAbstract:
    def test_none_is_placeholder(self):
        assert is_placeholder_abstract(None) is True

    def test_short_text_is_placeholder(self):
        assert is_placeholder_abstract("Short") is True
        assert is_placeholder_abstract("A" * 49) is True

    def test_login_boilerplate_is_placeholder(self):
        assert is_placeholder_abstract("You do not currently have access to this article.") is True
        assert is_placeholder_abstract("Please login to access this paper.") is True
        assert is_placeholder_abstract("Sign in to access this content.") is True
        assert is_placeholder_abstract("Subscribe to access full text.") is True

    def test_real_abstract_is_not_placeholder(self):
        long_text = (
            "This paper investigates the causal effect of education on earnings "
            "using a regression discontinuity design. We find that an additional "
            "year of schooling increases annual earnings by approximately 8%."
        )
        assert is_placeholder_abstract(long_text) is False


class TestNeedsDetection:
    def test_missing_abstract(self):
        assert record_needs_abstract({"abstract": None}) is True
        assert record_needs_abstract({}) is True

    def test_has_abstract(self):
        record = {"abstract": "A real abstract with enough content to pass the minimum length threshold check."}
        assert record_needs_abstract(record) is False

    def test_missing_authors_none(self):
        assert record_needs_authors({"authors": None}) is True

    def test_missing_authors_empty_list(self):
        assert record_needs_authors({"authors": []}) is True

    def test_has_authors(self):
        assert record_needs_authors({"authors": ["Alice", "Bob"]}) is False

    def test_missing_date(self):
        assert record_needs_date({"date_confidence": ""}) is True
        assert record_needs_date({"date_confidence": "C"}) is True
        assert record_needs_date({"date_confidence": "unknown"}) is True

    def test_has_good_date(self):
        assert record_needs_date({"date_confidence": "A"}) is False
        assert record_needs_date({"date_confidence": "B"}) is False

    def test_needs_recovery_all(self):
        record = {}
        assert needs_recovery(record) == (True, True, True)

    def test_needs_recovery_none(self):
        record = {
            "abstract": "A real abstract with enough content to pass the minimum length threshold check here.",
            "authors": ["Alice", "Bob"],
            "date_confidence": "A",
        }
        assert needs_recovery(record) == (False, False, False)


class TestDeduplicateCandidates:
    def test_empty(self):
        assert deduplicate_candidates([]) == {}

    def test_dedup_by_doi(self):
        records = {"abstract": None, "authors": [], "date_confidence": "C", "doi": "10.1234/test"}
        files_records = [
            (Path("/tmp/2026-07-01.json"), [records]),
        ]
        result = deduplicate_candidates(files_records)
        assert len(result) == 1

    def test_no_need_skipped(self):
        records = {
            "abstract": "A real abstract with enough content to pass the minimum length threshold check here ok.",
            "authors": ["Alice"],
            "date_confidence": "A",
            "doi": "10.1234/test",
        }
        files_records = [
            (Path("/tmp/2026-07-01.json"), [records]),
        ]
        result = deduplicate_candidates(files_records)
        assert len(result) == 0

    def test_duplicate_doi_merged(self):
        r1 = {"abstract": None, "authors": [], "date_confidence": "C", "doi": "10.1234/test", "title": "Test"}
        r2 = {"abstract": None, "authors": ["Alice"], "date_confidence": "C", "doi": "10.1234/test", "title": "Test"}
        files_records = [
            (Path("/tmp/2026-07-01.json"), [r1]),
            (Path("/tmp/2026-07-02.json"), [r2]),
        ]
        result = deduplicate_candidates(files_records)
        assert len(result) == 1


class TestApplyRecovery:
    def test_apply_abstract(self):
        record = {"abstract": None}
        metadata = {"abstract": "A new abstract with enough content to satisfy the minimum character requirement.", "abstract_source": "openalex"}
        recovered = apply_recovery(record, metadata, "openalex")
        assert "abstract" in recovered
        assert record["abstract_source"] == "openalex"

    def test_apply_authors(self):
        record = {"authors": []}
        metadata = {"authors": ["Alice", "Bob", "Charlie"]}
        recovered = apply_recovery(record, metadata, "openalex")
        assert "authors" in recovered
        assert record["authors"] == ["Alice", "Bob", "Charlie"]

    def test_apply_date_upgrade(self):
        record = {"date_confidence": "C"}
        metadata = {
            "published_online": "2026-07-01",
            "date_source": "openalex_crossvalidated",
            "date_confidence": "B",
        }
        recovered = apply_recovery(record, metadata, "openalex")
        assert "date" in recovered

    def test_no_date_downgrade(self):
        """A confidence dates must not be downgraded by lower-confidence recovery."""
        record = {
            "published_online": "2026-07-01",
            "date_confidence": "A",
            "date_source": "crossref",
        }
        metadata = {
            "published_online": "2026-06-15",
            "date_confidence": "C",
            "date_source": "openalex",
        }
        recovered = apply_recovery(record, metadata, "openalex")
        assert "date" not in recovered
        assert record["date_confidence"] == "A"

    def test_skip_placeholder_abstract(self):
        record = {"abstract": None}
        metadata = {"abstract": "Short", "abstract_source": "openalex"}
        recovered = apply_recovery(record, metadata, "openalex")
        assert len(recovered) == 0