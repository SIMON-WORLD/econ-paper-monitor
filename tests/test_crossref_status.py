from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_crossref_aggregate_status_is_fail_closed() -> None:
    source = (ROOT / "scripts" / "fetch_crossref.py").read_text(encoding="utf-8")
    assert "failures = 0" in source
    assert "failures += 1" in source
    assert "ok=failures == 0" in source


def test_source_health_publishes_actionable_coverage_debt() -> None:
    source = (ROOT / "scripts" / "audit_source_health.py").read_text(encoding="utf-8")
    assert '"coverage_debt"' in source
    assert '"crossref_only"' in source
    assert "next_action" in source
