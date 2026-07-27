from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_cnki_rss  # noqa: E402


def test_cnki_health_accepts_partial_source_success():
    result = fetch_cnki_rss.source_health_counts(
        [{"ok": True}, {"ok": False}, {"ok": True}]
    )

    assert result == {
        "ok": True,
        "selected_sources": 3,
        "successful_sources": 2,
        "failed_sources": 1,
    }


def test_cnki_health_rejects_all_source_failure():
    result = fetch_cnki_rss.source_health_counts([{"ok": False}, {"ok": False}])

    assert result == {
        "ok": False,
        "selected_sources": 2,
        "successful_sources": 0,
        "failed_sources": 2,
    }


def test_cnki_health_is_empty_when_no_sources_are_selected():
    result = fetch_cnki_rss.source_health_counts([])

    assert result == {
        "ok": False,
        "selected_sources": 0,
        "successful_sources": 0,
        "failed_sources": 0,
    }


def test_authoritative_local_runner_requires_every_source():
    assert "--require-all-sources" in (
        Path(fetch_cnki_rss.__file__).resolve().parents[1]
        / "scripts"
        / "local_cnki_update.py"
    ).read_text(encoding="utf-8")


def test_public_workflow_does_not_overwrite_local_cnki_status():
    workflow = (
        Path(fetch_cnki_rss.__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "update.yml"
    ).read_text(encoding="utf-8")

    assert "Fetch CNKI RSS feeds" not in workflow
    assert "CNKI RSS is intentionally absent" in workflow


def test_local_cnki_publish_pulls_are_fail_closed():
    script = (
        Path(fetch_cnki_rss.__file__).resolve().parents[1]
        / "scripts"
        / "local_cnki_update.py"
    ).read_text(encoding="utf-8")

    assert 'run_step(["git", "pull", "--ff-only", "origin", "main"])' in script
    assert 'run_step(["git", "pull", "--rebase", "origin", "main"])' in script
    assert '"-X", "theirs"' not in script
