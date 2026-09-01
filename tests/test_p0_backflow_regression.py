"""Regression: already-seen backflow must not be re-archived into today's daily bucket.

P0 2026-09-01: RSS re-published old papers with issue_date == run_date were
re-archived by dedupe into the run-date bucket, then remove_seen_backflow moved
them back out, leaving the bucket empty and tripping ingestion gates at month
boundaries. dedupe must skip re-archiving a record whose seen first_seen
predates the run date.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dedupe


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")


def _run_dedupe(tmp_path: Path, date: str) -> None:
    argv = [
        "dedupe.py",
        "--raw-dir", str(tmp_path / "raw"),
        "--seen", str(tmp_path / "seen.json"),
        "--daily-dir", str(tmp_path / "daily"),
        "--date", date,
    ]
    old = sys.argv
    sys.argv = argv
    try:
        dedupe.main()
    finally:
        sys.argv = old


def test_backflow_record_not_rearchived_into_today_bucket(tmp_path: Path) -> None:
    date = "2026-09-01"
    record = {
        "title": "Old paper re-published",
        "journal": "Journal of Development Economics",
        "journal_id": "journal-of-development-economics",
        "doi": "10.1016/j.jdeveco.2026.100001",
        "source": "rss",
        "source_type": "journal",
        "url": "https://www.sciencedirect.com/science/article/pii/S0000000000000001",
        "issue_date": date,
        "available_online": None,
        "published_online": None,
        "detected_at": "2026-06-18T17:57:38+00:00",
        "first_seen": "2026-06-18T17:57:38+00:00",
    }
    _write_json(tmp_path / "seen.json", {"papers": {record["doi"]: dict(record)}})
    _write_json(tmp_path / "raw" / date / "rss.json", [record])

    _run_dedupe(tmp_path, date)

    daily_path = tmp_path / "daily" / f"{date}.json"
    assert not daily_path.exists(), "backflow record must not be re-archived into the run-date bucket"


def test_new_record_still_archived_into_today_bucket(tmp_path: Path) -> None:
    date = "2026-09-01"
    record = {
        "title": "Brand new paper",
        "journal": "Journal of Development Economics",
        "journal_id": "journal-of-development-economics",
        "doi": "10.1016/j.jdeveco.2026.100002",
        "source": "rss",
        "source_type": "journal",
        "url": "https://www.sciencedirect.com/science/article/pii/S0000000000000002",
        "issue_date": date,
        "available_online": date,
        "published_online": date,
        "detected_at": "2026-09-01T01:00:00+00:00",
    }
    _write_json(tmp_path / "seen.json", {"papers": {}})
    _write_json(tmp_path / "raw" / date / "rss.json", [record])

    _run_dedupe(tmp_path, date)

    daily_path = tmp_path / "daily" / f"{date}.json"
    assert daily_path.exists(), "new record must be archived into the run-date bucket"
    import json
    rows = json.loads(daily_path.read_text(encoding="utf-8"))
    assert any(str(r.get("doi")) == record["doi"] for r in rows)
