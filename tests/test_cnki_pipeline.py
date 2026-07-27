from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_cnki_rss  # noqa: E402
import fetch_rss  # noqa: E402
import dedupe  # noqa: E402


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

    assert 'run_step(["git", "-c", "http.sslbackend=openssl", "pull", "--ff-only", "origin", "main"])' in script
    assert 'run_step(["git", "-c", "http.sslbackend=openssl", "pull", "--rebase", "origin", "main"])' in script
    assert '"-X", "theirs"' not in script


def test_local_cnki_has_durable_owner_status():
    root = Path(fetch_cnki_rss.__file__).resolve().parents[1]
    script = (root / "scripts" / "local_cnki_update.py").read_text(encoding="utf-8")
    renderer = (root / "scripts" / "render_cnki_status.py").read_text(encoding="utf-8")
    assert "local_cnki_status.json" in script
    assert 'write_local_status("published"' in script
    assert "local_status = read_json(DATA_DIR / \"local_cnki_status.json\"" in renderer


def test_local_cnki_publishes_final_status_after_push():
    script = (
        Path(fetch_cnki_rss.__file__).resolve().parents[1]
        / "scripts"
        / "local_cnki_update.py"
    ).read_text(encoding="utf-8")

    assert "def publish_final_status()" in script
    assert 'record_source("local-cnki-publish", ok=True' in script
    assert "publish_final_status()" in script


def test_local_task_prefers_powershell_7_with_windows_fallback():
    root = Path(fetch_cnki_rss.__file__).resolve().parents[1]
    script = (root / "scripts" / "install_local_cnki_task.ps1").read_text(encoding="utf-8")
    assert "Get-Command pwsh.exe" in script
    assert "Get-Command powershell.exe" in script
    assert "-Execute $shell" in script


def test_aggregate_source_status_does_not_hide_partial_failures():
    root = Path(fetch_cnki_rss.__file__).resolve().parents[1]
    preprints = (root / "scripts" / "fetch_preprints.py").read_text(encoding="utf-8")
    rss = (root / "scripts" / "fetch_rss.py").read_text(encoding="utf-8")
    assert "ok=failures == 0" in preprints
    assert "successful_feeds == attempted_feeds" in rss


def test_local_cnki_does_not_recompute_global_formal_source_health():
    root = Path(fetch_cnki_rss.__file__).resolve().parents[1]
    script = (root / "scripts" / "local_cnki_update.py").read_text(encoding="utf-8")
    assert 'run_step([python, "scripts/audit_source_health.py"])' not in script
    assert "GitHub full workflow owns data/source_health.json" in script


def test_rss_parser_does_not_truncate_unparseable_date_labels():
    assert fetch_rss.parse_date("September 2026") is None
    assert fetch_rss.parse_month_date("September 2026") == "2026-09-01"


def test_rss_parser_repairs_bare_ampersands_but_keeps_structure_strict():
    xml = "<rss><channel><item><title>Trade & Growth</title><link>https://example.org/paper</link></item></channel></rss>"
    records = fetch_rss.parse_feed(xml, {"id": "test-journal", "title": "Test Journal"}, "https://example.org/feed")
    assert records[0]["title"] == "Trade & Growth"


def test_rss_helpers_extract_doi_and_reject_concatenated_affiliation_blob():
    assert fetch_rss.extract_doi("doi:10.1086/740172") == "10.1086/740172"
    assert fetch_rss.normalize_authors(["Bård HarstadKatinka HoltsmarkStanford University"]) == []


def test_rss_identity_guard_rejects_a_valid_but_wrong_chicago_feed():
    xml = "<rss><channel><title>The Journal of Law and Economics</title></channel></rss>"
    assert fetch_rss.feed_identity_matches(xml, {"title": "Journal of Labor Economics"}) is False
    assert fetch_rss.feed_identity_matches(xml, {"title": "Journal of Law & Economics"}) is True


def test_chicago_journal_codes_are_kept_distinct():
    journals = {item["id"]: item for item in fetch_rss.load_journals()}
    jole = journals["journal-of-labor-economics"]["sources"][0]["url"]
    jle = journals["journal-of-law-and-economics"]["sources"][0]["url"]
    assert "jc=jole" in jole
    assert "jc=jle" in jle


def test_chicago_official_feed_codes_cover_verified_journals():
    from sources.registry import UCHICAGO_JOURNAL_CODES, generated_official_rss_urls

    assert UCHICAGO_JOURNAL_CODES["journal-of-political-economy"] == "jpe"
    journals = {item["id"]: item for item in fetch_rss.load_journals()}
    urls = [item["url"] for item in generated_official_rss_urls(journals["journal-of-political-economy"])]
    assert any("jc=jpe" in url for url in urls)


def test_rss_forthcoming_date_is_not_published_as_a_future_archive():
    record = {"source": "rss", "available_online": "2026-08-01", "date_source": "rss_published"}
    assert dedupe.archive_date_for_new_record(record, "2026-07-27") is None


def test_undated_rss_backfill_is_not_published_as_today():
    record = {"source": "rss", "url": "https://example.org/paper", "date_source": "", "title": "Undated feed item"}
    assert dedupe.archive_date_for_new_record(record, "2026-07-27") is None


def test_policy_commentary_has_a_distinct_public_label():
    import render_site

    assert render_site.source_type_label({"source": "working_papers", "source_type": "policy_commentary"}) == "研究评论"


def test_known_wrong_journal_doi_is_quarantined():
    assert dedupe.is_source_navigation_noise({"doi": "10.56347/jle.v5i1.421", "title": "Unrelated paper"}) is True


def test_local_pipeline_normalizes_after_metadata_enrichment():
    root = Path(fetch_cnki_rss.__file__).resolve().parents[1]
    local_script = (root / "scripts" / "local_cnki_update.py").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
    assert local_script.index('"scripts/enrich_metadata.py"') < local_script.rfind('"scripts/normalize_records.py"]')
    assert workflow.index("Enrich publisher detail pages") < workflow.index("Normalize enriched metadata")
