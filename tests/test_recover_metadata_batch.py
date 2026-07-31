from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from recover_metadata_batch import (  # noqa: E402
    decide_date_update,
    is_placeholder_abstract,
    load_daily_candidates,
    record_needs_date,
    run_recovery,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def provider_metadata(date: str | None = "2026-07-28") -> dict:
    abstract = (
        "This paper uses a new dataset to estimate the causal effect of policy "
        "reform on firm outcomes. The results are robust to alternative "
        "specifications and heterogeneous effects across regions."
    )
    return {
        "openalex": {
            "authors": ["Alice Author", "Bob Author"],
            "abstract": abstract,
            "available_online": date,
            "published_online": date,
            "date_source": "openalex_publication_date",
            "date_confidence": "C",
        },
        "crossref": {
            "authors": ["Alice Author", "Bob Author"],
            "abstract": abstract,
            "available_online": date,
            "published_online": date,
            "date_source": "crossref_doi_published_online",
            "date_confidence": "C",
        },
        "semantic-scholar": {
            "authors": ["Alice Author", "Bob Author"],
            "abstract": abstract,
            "published_online": date,
        },
    }


def sample_record(**overrides) -> dict:
    record = {
        "id": "test-id",
        "title": "Test paper",
        "authors": [],
        "journal": "Test Journal",
        "source": "crossref",
        "source_type": "journal",
        "url": "https://doi.org/10.1234/test",
        "doi": "10.1234/test",
        "detail_key": "test-paper-abcdef123456",
        "fields": ["计量方法"],
        "first_seen": "2026-07-28T10:00:00+00:00",
        "abstract": None,
        "date_confidence": "C",
    }
    record.update(overrides)
    return record


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    daily_dir = data_dir / "daily"
    daily_dir.mkdir(parents=True)
    write_json(daily_dir / "2026-07-31.json", [sample_record()])
    write_json(
        data_dir / "seen.json",
        {"papers": {"seen-test": sample_record()}},
    )
    write_json(
        data_dir / "metadata_retry_queue.json",
        {
            "records": [
                {
                    "identity": "doi:10.1234/test",
                    "reasons": ["missing_abstract", "weak_date_evidence"],
                    "title": "Test paper",
                }
            ]
        },
    )
    write_json(
        data_dir / "ingestion_retry_queue.json",
        {
            "records": [
                {
                    "title": "Test paper",
                    "doi": "10.1234/test",
                    "retry_status": "pending",
                    "stage": "retry_reingestion",
                }
            ]
        },
    )
    write_json(
        data_dir / "ingestion_exclusion_ledger.json",
        {
            "records": [
                {
                    "title": "Test paper",
                    "doi": "10.1234/test",
                    "retry_status": "pending",
                    "stage": "retry_reingestion",
                }
            ]
        },
    )
    write_json(data_dir / "pending_date_records.json", [])
    write_json(data_dir / "historical_backfill_pending.json", {"records": []})
    write_json(
        data_dir / "source_health.json",
        {"counts": {}, "coverage_counts": {}},
    )
    return data_dir


class TestPlaceholderAbstract:
    def test_none_is_placeholder(self):
        assert is_placeholder_abstract(None) is True

    def test_short_text_is_placeholder(self):
        assert is_placeholder_abstract("Short abstract") is True

    def test_boilerplate_is_placeholder(self):
        assert is_placeholder_abstract("Please login to access this article.") is True
        assert is_placeholder_abstract("This is a preview of subscription content, log in via an institution to check access.") is True

    def test_real_abstract_is_not_placeholder(self):
        text = (
            "We study the causal effect of minimum wages on employment using a "
            "regression discontinuity design. Our estimates are precise and "
            "robust across a wide range of specifications."
        )
        assert is_placeholder_abstract(text) is False


class TestNeedsDetection:
    def test_missing_date(self):
        assert record_needs_date({"date_confidence": "", "abstract": "x"}) is True
        assert record_needs_date({"date_confidence": "C"}) is True

    def test_strong_date(self):
        assert record_needs_date(
            {"date_confidence": "B", "available_online": "2026-07-28"}
        ) is False


class TestDateDiscipline:
    def test_single_openalex_stays_c(self):
        record = sample_record()
        update = decide_date_update(
            record,
            {"openalex": provider_metadata()["openalex"], "crossref": {}, "semantic-scholar": {}},
        )
        assert update["date_confidence"] == "C"
        assert update["date_source"] == "openalex_publication_date"

    def test_single_crossref_stays_c(self):
        record = sample_record()
        update = decide_date_update(
            record,
            {"openalex": {}, "crossref": provider_metadata()["crossref"], "semantic-scholar": {}},
        )
        assert update["date_confidence"] == "C"
        assert update["date_source"] == "crossref_doi_published_online"

    def test_two_independent_sources_upgrade_to_b(self):
        record = sample_record()
        update = decide_date_update(record, provider_metadata("2026-07-28"))
        assert update["date_confidence"] == "B"
        assert update["date_source"] == "openalex+crossref_crossvalidated"
        assert update["available_online"] == "2026-07-28"

    def test_conflicting_sources_stay_c(self):
        record = sample_record()
        metadata = provider_metadata("2026-07-28")
        metadata["crossref"]["available_online"] = "2026-07-27"
        metadata["crossref"]["published_online"] = "2026-07-27"
        update = decide_date_update(record, metadata)
        assert update["date_confidence"] == "C"

    def test_unreasonable_year_never_upgrades(self):
        record = sample_record()
        metadata = provider_metadata("1900-01-01")
        update = decide_date_update(record, metadata)
        assert update is None

    def test_accepted_date_is_never_used_as_online_date(self):
        record = sample_record(
            accepted_date="2026-06-01",
            date_confidence="A",
        )
        update = decide_date_update(record, provider_metadata())
        assert update is None

    def test_existing_a_date_is_never_downgraded(self):
        record = sample_record(
            available_online="2026-07-01",
            published_online="2026-07-01",
            date_confidence="A",
        )
        update = decide_date_update(record, provider_metadata())
        assert update is None

    def test_existing_b_date_is_never_downgraded(self):
        record = sample_record(
            available_online="2026-07-01",
            published_online="2026-07-01",
            date_confidence="B",
        )
        update = decide_date_update(record, provider_metadata())
        assert update is None


class TestCandidateSelection:
    def test_limit_and_doi_filter(self, tmp_path: Path):
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir(parents=True)
        complete = sample_record(doi="10.1234/complete", abstract="A real abstract with enough length to be complete.", authors=["A. Author"], date_confidence="A", available_online="2026-07-28", published_online="2026-07-28")
        missing = sample_record(doi="10.1234/missing")
        no_doi = sample_record(doi=None)
        write_json(daily_dir / "2026-07-31.json", [complete, missing, no_doi])

        candidates, records_by_doi, _ = load_daily_candidates(
            daily_dir,
            limit=1,
            recent_days=5000,
        )
        assert len(records_by_doi) == 1
        assert "10.1234/missing" in records_by_doi
        assert candidates[0][1]["doi"] == "10.1234/missing"


class TestRecoveryPersistence:
    def test_write_mode_updates_all_stores(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        with patch("recover_metadata_batch.openalex_doi_metadata", return_value=provider_metadata()["openalex"]), patch(
            "recover_metadata_batch.crossref_doi_metadata", return_value=provider_metadata()["crossref"]
        ), patch(
            "recover_metadata_batch.semantic_scholar_doi_metadata",
            return_value=provider_metadata()["semantic-scholar"],
        ):
            report = run_recovery(
                data_dir=data_dir,
                limit=50,
                recent_days=5000,
                timeout=10,
                workers=2,
                dry_run=False,
            )

        assert report["recovered"]["abstract"] == 1
        assert report["recovered"]["authors"] == 1
        assert report["recovered"]["date"] == 1
        assert report["files"]["daily_changed"] == 1
        assert report["files"]["seen_updated"] == 1
        assert report["files"]["queue_resolved"] == 1
        assert report["files"]["ledger_resolved"] == 1

        daily = json.loads((data_dir / "daily" / "2026-07-31.json").read_text(encoding="utf-8"))
        assert daily[0]["abstract"]
        assert daily[0]["date_confidence"] == "B"
        assert daily[0]["abstract_status_code"] == "available"
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert seen["papers"]["seen-test"]["date_confidence"] == "B"
        queue = json.loads((data_dir / "metadata_retry_queue.json").read_text(encoding="utf-8"))
        assert queue["records"] == []
        assert len(queue["resolved_records"]) == 1

    def test_dry_run_writes_nothing(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        before_daily = (data_dir / "daily" / "2026-07-31.json").read_bytes()
        before_seen = (data_dir / "seen.json").read_bytes()
        before_queue = (data_dir / "metadata_retry_queue.json").read_bytes()
        with patch("recover_metadata_batch.openalex_doi_metadata", return_value=provider_metadata()["openalex"]), patch(
            "recover_metadata_batch.crossref_doi_metadata", return_value=provider_metadata()["crossref"]
        ), patch(
            "recover_metadata_batch.semantic_scholar_doi_metadata",
            return_value=provider_metadata()["semantic-scholar"],
        ):
            run_recovery(
                data_dir=data_dir,
                limit=50,
                recent_days=5000,
                timeout=10,
                workers=2,
                dry_run=True,
            )
        assert (data_dir / "daily" / "2026-07-31.json").read_bytes() == before_daily
        assert (data_dir / "seen.json").read_bytes() == before_seen
        assert (data_dir / "metadata_retry_queue.json").read_bytes() == before_queue

    def test_docs_tree_unchanged(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        before = tree_hash(ROOT / "docs")
        with patch("recover_metadata_batch.openalex_doi_metadata", return_value=provider_metadata()["openalex"]), patch(
            "recover_metadata_batch.crossref_doi_metadata", return_value=provider_metadata()["crossref"]
        ), patch(
            "recover_metadata_batch.semantic_scholar_doi_metadata",
            return_value=provider_metadata()["semantic-scholar"],
        ):
            run_recovery(
                data_dir=data_dir,
                limit=50,
                recent_days=5000,
                timeout=10,
                workers=2,
                dry_run=False,
            )
        assert tree_hash(ROOT / "docs") == before
