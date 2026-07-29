from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_only_homepage_generator_can_target_root_homepage():
    renderer = (ROOT / "scripts" / "render_site.py").read_text(encoding="utf-8")
    homepage = (ROOT / "scripts" / "build_daily_vnext.py").read_text(encoding="utf-8")
    assert 'args.docs_dir / "index.html"' not in renderer
    assert 'ROOT / "docs" / "index.html"' in homepage


def test_display_workflow_reads_data_and_commits_docs_only():
    workflow = (ROOT / ".github" / "workflows" / "render-site.yml").read_text(encoding="utf-8")
    assert 'paths:\n      - "data/**"' in workflow
    assert "scripts/render_site.py" in workflow
    assert "scripts/build_daily_vnext.py" in workflow
    assert "scripts/build_feed.py" in workflow
    assert "git add docs" in workflow
    assert "git add data" not in workflow
    assert "git push origin HEAD:main" in workflow


def test_monitor_and_display_workflows_cannot_form_a_push_loop():
    monitor = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
    display = (ROOT / ".github" / "workflows" / "render-site.yml").read_text(encoding="utf-8")
    assert "git add data docs" not in monitor
    assert "git add data" in monitor
    assert 'paths:\n      - "data/**"' in display
    assert '      - "docs/**"' not in display
