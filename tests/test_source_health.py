from datetime import date, datetime, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from scripts.audit_source_health import inspect_journal


def now():
    return datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def journal():
    return {"id": "j1", "title": "Test Journal", "publisher": "Test"}


def test_crossref_only_is_degraded_but_usable():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["level"] == "degraded"
    assert result["coverage"] == "crossref_only"
    assert result["usable_paths"] == ["crossref"]


def test_openalex_recall_does_not_upgrade_crossref_only_to_healthy():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"sources": {"openalex-recall": {
            "ok": True,
            "updated_at": "2026-07-27T11:30:00+00:00",
            "details": {"per_journal": {"j1": {"ok": True, "count": 2}}},
        }}},
    )
    assert result["level"] == "degraded"
    assert result["coverage"] == "supplemental"
    assert result["usable_paths"] == ["crossref", "openalex-recall"]


def test_openalex_failed_journal_is_not_marked_as_covered():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"sources": {"openalex-recall": {
            "ok": True,
            "updated_at": "2026-07-27T11:30:00+00:00",
            "details": {"per_journal": {"j1": {"ok": False, "count": 0}}},
        }}},
    )
    assert result["usable_paths"] == ["crossref"]
    assert result["coverage"] == "crossref_only"


def test_both_paths_are_healthy():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "official-generated", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["level"] == "healthy"


def test_no_paths_are_unavailable():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "error", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["level"] == "unavailable"


def test_old_registry_is_stale_even_when_paths_are_configured():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-25T00:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["level"] == "stale"


def test_aea_toc_counts_as_a_real_path():
    result = inspect_journal(
        {"id": "american-economic-review", "title": "AER", "publisher": "AEA"},
        {"journals": {"american-economic-review": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"sources": {"aea-toc": {"ok": True, "updated_at": "2026-07-27T11:30:00+00:00"}}},
    )
    assert result["level"] == "healthy"
    assert "aea-toc" in result["usable_paths"]


def test_failed_chinese_journal_does_not_count_as_a_path():
    result = inspect_journal(
        {"id": "journal-edcb877d78", "title": "数量经济技术经济研究", "publisher": "CN"},
        {"journals": {"journal-edcb877d78": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"source_groups": {"cn-journals": {"ok": True, "updated_at": "2026-07-27T11:30:00+00:00", "journals": [{"journal_id": "journal-edcb877d78", "ok": False}]}}},
    )
    assert result["usable_paths"] == ["crossref"]
    assert result["failed_paths"][0]["path"] == "cn-journals"


def test_partial_group_failure_does_not_hide_successful_chinese_sibling():
    result = inspect_journal(
        {"id": "journal-edcb877d78", "title": "数量经济技术经济研究", "publisher": "CN"},
        {"journals": {"journal-edcb877d78": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"source_groups": {"cn-journals": {
            "ok": False,
            "updated_at": "2026-07-27T11:30:00+00:00",
            "journals": [{"journal_id": "journal-edcb877d78", "ok": True, "count": 8}],
        }}},
    )
    assert "cn-journals" in result["usable_paths"]
    assert result["failed_paths"] == []


def test_failed_aea_child_does_not_hide_successful_sibling():
    result = inspect_journal(
        {"id": "american-economic-review", "title": "AER", "publisher": "AEA"},
        {"journals": {"american-economic-review": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"sources": {"aea-toc": {
            "ok": False,
            "updated_at": "2026-07-27T11:30:00+00:00",
            "journals": {"american-economic-review": {"ok": True, "count": 44}},
        }}},
    )
    assert result["level"] == "healthy"
    assert result["coverage"] == "official_or_specialized"
    assert "aea-toc" in result["usable_paths"]


def test_rss_error_does_not_count_as_a_healthy_path():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {
            "last_rss_status": "configured",
            "last_rss_error": "HTTPError: 403",
            "last_crossref_status": "ok",
            "updated_at": "2026-07-27T11:00:00+00:00",
        }}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["usable_paths"] == ["crossref"]


def test_partial_specialized_source_with_records_is_usable():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
        36,
        {"source_groups": {"cn-journals": {"ok": True, "updated_at": "2026-07-27T11:00:00+00:00", "journals": [{"journal_id": "j1", "ok": False, "count": 12}]}}},
    )
    assert result["level"] == "healthy"
    assert result["coverage"] == "official_or_specialized"
    assert "cn-journals" in result["usable_paths"]


def test_blocked_priority_publisher_does_not_count_crossref_fallback_as_specialized():
    result = inspect_journal(
        {"id": "quarterly-journal-of-economics", "title": "QJE", "publisher": "OUP"},
        {"journals": {"quarterly-journal-of-economics": {
            "last_rss_status": "none",
            "last_crossref_status": "ok",
            "updated_at": "2026-07-27T11:00:00+00:00",
        }}},
        date(2026, 7, 27),
        datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
        36,
        {"sources": {"priority-toc": {
            "ok": True,
            "updated_at": "2026-07-27T11:30:00+00:00",
            "journals": {
                "quarterly-journal-of-economics": {
                    "ok": True,
                    "publisher_ok": False,
                    "count": 3,
                    "fallback_count": 3,
                }
            },
        }}},
    )
    assert result["usable_paths"] == ["crossref"]
    assert result["coverage"] == "crossref_only"


def test_single_path_degradation_reason_is_single_path():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["level"] == "degraded"
    assert result["degradation_reason"] == "single_path"


def test_failed_path_degradation_reason_is_failed_path():
    result = inspect_journal(
        {"id": "journal-edcb877d78", "title": "数量经济技术经济研究", "publisher": "CN"},
        {"journals": {"journal-edcb877d78": {"last_rss_status": "none", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
        {"source_groups": {"cn-journals": {"ok": True, "updated_at": "2026-07-27T11:30:00+00:00", "journals": [{"journal_id": "journal-edcb877d78", "ok": False}]}}},
    )
    assert result["level"] == "degraded"
    assert result["degradation_reason"] == "failed_path"


def test_healthy_has_no_degradation_reason():
    result = inspect_journal(
        journal(),
        {"journals": {"j1": {"last_rss_status": "official-generated", "last_crossref_status": "ok", "updated_at": "2026-07-27T11:00:00+00:00"}}},
        date(2026, 7, 27),
        now(),
        1.5,
    )
    assert result["level"] == "healthy"
    assert result["degradation_reason"] is None
