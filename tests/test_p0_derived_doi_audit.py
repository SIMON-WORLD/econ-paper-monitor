"""Regression: Crossref parent DOIs split into child .rN records must not be
flagged as missing by ingestion / formal-journal audits.

P0 2026-09-01: dedupe splits a combined Crossref item (JEL Book Reviews,
parent DOI 10.1257/jel.64.3.1058) into child records (.r1, .r2, ...) that
enter the daily archive. The ingestion and formal coverage audits then look
for the *parent* DOI, find no exact key match, and report
ingestion_missing_candidates / formal_journal_candidates_not_archived. The
audits must accept the derived-child coverage instead.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_formal_journal_coverage
import audit_ingestion
import dedupe

PARENT_DOI = "10.1257/jel.64.3.1058"
CHILD_DOIS = [
    "10.1257/jel.64.3.1058.r1",
    "10.1257/jel.64.3.1058.r2",
]
DATE = "2026-09-01"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _parent_record() -> dict:
    return {
        "title": "Book Reviews",
        "journal": "Journal of Economic Literature",
        "journal_id": "journal-of-economic-literature",
        "doi": PARENT_DOI,
        "source": "crossref",
        "source_type": "journal",
        "url": f"https://doi.org/{PARENT_DOI}",
        "available_online": DATE,
        "published_online": DATE,
        "issue_date": DATE,
        "detected_at": f"{DATE}T01:00:00+00:00",
    }


def _child_records() -> list[dict]:
    rows = []
    for doi in CHILD_DOIS:
        rows.append(
            {
                "title": f"Book Review {doi.rsplit('.', 1)[-1]}",
                "journal": "Journal of Economic Literature",
                "journal_id": "journal-of-economic-literature",
                "doi": doi,
                "source": "crossref",
                "source_type": "journal",
                "url": f"https://doi.org/{doi}",
                "available_online": DATE,
                "issue_date": DATE,
            }
        )
    return rows


def test_covered_by_derived_doi_matches_child_prefix() -> None:
    children = _child_records()
    assert dedupe.covered_by_derived_doi({"doi": PARENT_DOI}, children)
    assert not dedupe.covered_by_derived_doi({"doi": "10.1257/jel.64.3.9999"}, children)
    assert not dedupe.covered_by_derived_doi({"doi": PARENT_DOI}, [])
    assert not dedupe.covered_by_derived_doi({"doi": None}, children)
    assert not dedupe.covered_by_derived_doi({"doi": ""}, children)


def test_audit_ingestion_parent_covered_by_children(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audit_ingestion, "DATA_DIR", tmp_path)
    monkeypatch.setattr(audit_ingestion, "record_source", lambda *a, **k: None)
    monkeypatch.setattr(audit_ingestion, "load_status", lambda *a, **k: {})
    _write_json(tmp_path / "seen.json", {"papers": {}})
    _write_json(tmp_path / "raw" / f"{DATE}.json", [_parent_record()])
    _write_json(tmp_path / "daily" / f"{DATE}.json", _child_records())

    out = tmp_path / "ingestion_audit.json"
    ledger = tmp_path / "ingestion_exclusion_ledger.json"
    argv = [
        "audit_ingestion.py",
        "--date", DATE,
        "--raw-dir", str(tmp_path / "raw"),
        "--daily-dir", str(tmp_path / "daily"),
        "--output", str(out),
        "--ledger-output", str(ledger),
    ]
    old = sys.argv
    sys.argv = argv
    try:
        audit_ingestion.main()
    finally:
        sys.argv = old

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["new_today_candidates"] == 1
    assert report["new_today_missing_candidates"] == 0


def test_audit_formal_parent_covered_by_children(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audit_formal_journal_coverage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(audit_formal_journal_coverage, "record_source", lambda *a, **k: None)
    _write_json(tmp_path / "seen.json", {"papers": {}})
    _write_json(tmp_path / "source_registry.json", {"journals": {}})
    journals_yml = (
        "  - id: \"journal-of-economic-literature\"\n"
        "    title: \"Journal of Economic Literature\"\n"
        "    aliases:\n"
        "      - \"JEL\"\n"
    )
    (tmp_path / "journals.yml").write_text(journals_yml, encoding="utf-8")
    _write_json(tmp_path / "raw" / f"{DATE}.json", [_parent_record()])
    _write_json(tmp_path / "daily" / f"{DATE}.json", _child_records())

    out = tmp_path / "formal_journal_audit.json"
    argv = [
        "audit_formal_journal_coverage.py",
        "--date", DATE,
        "--raw-dir", str(tmp_path / "raw"),
        "--daily-dir", str(tmp_path / "daily"),
        "--output", str(out),
    ]
    old = sys.argv
    sys.argv = argv
    try:
        audit_formal_journal_coverage.main()
    finally:
        sys.argv = old

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["suspected_missed_journals"] == 0
    jel = next(row for row in report["journals"] if row["journal_id"] == "journal-of-economic-literature")
    assert jel["missing_today"] == 0
