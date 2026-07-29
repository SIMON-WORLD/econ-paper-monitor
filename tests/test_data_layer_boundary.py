import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


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
