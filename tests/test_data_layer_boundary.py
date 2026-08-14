import json
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_metadata_recovery import audit_metadata_recovery  # noqa: E402
from clean_nonpaper_records import clean_nonpaper_records  # noqa: E402
from reconcile_retry_queues import reconcile_retry_queue  # noqa: E402


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_github_monitor_workflow_does_not_generate_or_commit_pages():
    workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")

    for forbidden in (
        "scripts/render_site.py",
        "scripts/build_daily_vnext.py",
        "scripts/build_feed.py",
        "scripts/render_local_status.py",
        "git add data docs",
    ):
        assert forbidden not in workflow
    assert "git add data" in workflow


def test_full_and_single_crossref_fetch_include_created_days():
    workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
    # Priority already passes created-days; full and single now must too so
    # in-press records without a published date are not skipped by deep runs.
    assert workflow.count("--created-days 7") >= 3


def test_local_cnki_monitor_does_not_generate_or_commit_pages():
    script = (ROOT / "scripts" / "local_cnki_update.py").read_text(encoding="utf-8")

    for forbidden in (
        'run_step([python, "scripts/render_site.py"])',
        'run_step([python, "scripts/build_feed.py"',
        'run_step([python, "scripts/render_local_status.py"])',
        'run_step([python, "scripts/render_cnki_status.py"])',
        '["git", "add", "data", "docs"]',
    ):
        assert forbidden not in script
    assert '["git", "add", "data"]' in script


def test_canonical_daily_interface_has_schema_and_beijing_bucket():
    schema = json.loads((ROOT / "data" / "daily.schema.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "data" / "pipeline_output_policy.json").read_text(encoding="utf-8"))

    assert schema["type"] == "array"
    assert "data/daily.schema.json" in policy["required_supporting_artifacts"]
    assert policy["canonical_interface"] == "data/daily/YYYY-MM-DD.json"


def test_data_repair_tasks_leave_docs_tree_unchanged(tmp_path: Path):
    data_dir = tmp_path / "data"
    daily_dir = data_dir / "daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "2026-07-31.json").write_text("[]", encoding="utf-8")
    for name, payload in {
        "seen.json": {"papers": {}},
        "pending_date_records.json": [],
        "ingestion_retry_queue.json": {"records": []},
        "ingestion_exclusion_ledger.json": {"records": []},
        "metadata_retry_queue.json": {"records": []},
        "source_health.json": {"counts": {}, "coverage_counts": {}},
        "historical_backfill_pending.json": {"records": []},
    }.items():
        (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    before = tree_hash(ROOT / "docs")
    clean_nonpaper_records(
        daily_dir,
        data_dir / "seen.json",
        data_dir / "ingestion_exclusion_ledger.json",
    )
    reconcile_retry_queue(data_dir)
    audit_metadata_recovery(data_dir)
    after = tree_hash(ROOT / "docs")

    assert after == before
