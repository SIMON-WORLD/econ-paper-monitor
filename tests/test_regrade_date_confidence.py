"""Tests for the Issue #22 date-confidence regrade policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from regrade_date_confidence import confidence_for, regrade_daily_and_seen  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


RUN_DATE = "2026-08-05"


def test_confidence_mapping_follows_policy_a():
    cases = [
        ({"date_source": "publisher_published_online", "available_online": "2026-08-01"}, "A"),
        ({"date_source": "publisher_meta:dc.date", "available_online": "2026-08-01"}, "A"),
        ({"date_source": "rss_description_online", "published_online": "2026-08-01"}, "A"),
        ({"date_source": "rss_published", "published_online": "2026-08-01"}, "A"),
        ({"date_source": "elsevier_article_api", "available_online": "2026-08-01"}, "A"),
        ({"date_source": "cnki_rss_pubdate", "available_online": "2026-08-01"}, "A"),
        ({"date_source": "aea_forthcoming", "available_online": "2026-08-01"}, "A"),
        ({"date_source": "official_first_publish", "available_online": "2026-08-01"}, "A"),
        ({"date_source": "tandf_issue_date_fallback", "available_online": "2026-08-01"}, "B"),
        ({"date_source": "iza_detail_month", "available_online": "2026-08-01"}, "B"),
        ({"date_source": "crossref_doi_published_online", "published_online": "2026-08-01"}, "C"),
        ({"date_source": "crossref_doi_elsevier_created_online", "available_online": "2026-08-01"}, "C"),
        ({"date_source": "openalex", "available_online": "2026-08-01"}, "C"),
        ({"date_source": "crossref_doi_issue", "issue_date": "2026-08-01"}, "D"),
        ({"date_source": "nep_issue", "issue_date": "2026-08-01"}, "D"),
        ({"date_source": "rss_description_online", "available_online": "September "}, "F"),
        ({"date_source": "publisher_published_online"}, "F"),
        ({}, "F"),
    ]
    for record, expected in cases:
        assert confidence_for(record, RUN_DATE) == expected, (record, expected)


def test_future_official_date_is_first_seen_until_it_arrives():
    record = {"date_source": "publisher_published_online", "available_online": "2026-08-10"}
    assert confidence_for(record, RUN_DATE) == "F"


def test_regrade_is_idempotent_and_writes_only_changes(tmp_path: Path):
    data_dir = tmp_path / "data"
    daily = data_dir / "daily"
    daily.mkdir(parents=True)
    write_json(
        daily / "2026-08-05.json",
        [
            {"date_source": "publisher_published_online", "available_online": "2026-08-01", "date_confidence": "B"},
            {"date_source": "crossref_doi_published_online", "published_online": "2026-08-01", "date_confidence": "C"},
            {"date_source": "publisher_published_online", "available_online": "2026-08-10", "date_confidence": "A"},
        ],
    )
    write_json(
        data_dir / "seen.json",
        {
            "papers": {
                "k1": {"date_source": "rss_description_online", "published_online": "2026-08-01", "date_confidence": "B"}
            }
        },
    )

    first = regrade_daily_and_seen(data_dir, run_date=RUN_DATE, write=True)
    assert first["daily_files_changed"] == 1
    assert first["daily_records_changed"] == 2  # B->A and future A->F
    assert first["seen_records_changed"] == 1

    second = regrade_daily_and_seen(data_dir, run_date=RUN_DATE, write=True)
    assert second["daily_files_changed"] == 0
    assert second["daily_records_changed"] == 0
    assert second["seen_records_changed"] == 0

    payload = json.loads((daily / "2026-08-05.json").read_text(encoding="utf-8"))
    assert payload[0]["date_confidence"] == "A"
    assert payload[2]["date_confidence"] == "F"