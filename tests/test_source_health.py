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
    assert result["usable_paths"] == ["crossref"]


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
