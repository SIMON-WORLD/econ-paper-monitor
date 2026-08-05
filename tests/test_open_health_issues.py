from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from open_health_issues import build_anomalies, sync_issues  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    write_json(data_dir / "release_gate.json", {"ok": True, "failures": [], "warnings": []})
    write_json(
        data_dir / "source_health.json",
        {"counts": {"degraded": 0, "unavailable": 0}, "degraded": [], "unavailable": []},
    )
    write_json(
        data_dir / "local_cnki_status.json",
        {
            "ok": True,
            "last_success_at": "2026-08-03T10:00:00+00:00",
            "state": "success",
            "count": 1,
        },
    )
    write_json(
        data_dir / "semantic_scholar_keepalive.json",
        {
            "checked_at": "2026-08-04T10:00:00+00:00",
            "ok": True,
            "status_code": 200,
            "reason": "ok",
            "detail": "paperId=test",
        },
    )
    return data_dir


def test_release_gate_failure_creates_anomaly(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    write_json(data_dir / "release_gate.json", {"ok": False, "failures": [{"code": "x", "count": 2}]})

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, tzinfo=timezone.utc))

    slugs = {item["slug"] for item in anomalies}
    assert "release-gate" in slugs
    release = next(item for item in anomalies if item["slug"] == "release-gate")
    assert "x count=2" in release["body"]


def test_degraded_threshold_and_unavailable(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    write_json(
        data_dir / "source_health.json",
        {
            "counts": {"degraded": 30, "unavailable": 1},
            "degraded": [{"journal": "Journal A"}, {"journal": "Journal B"}],
            "unavailable": [{"journal": "Journal C"}],
        },
    )

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, tzinfo=timezone.utc))

    slugs = {item["slug"] for item in anomalies}
    assert "degraded-sources" in slugs
    assert "source-unavailable" in slugs
    degraded = next(item for item in anomalies if item["slug"] == "degraded-sources")
    assert "Journal A" in degraded["body"]
    unavailable = next(item for item in anomalies if item["slug"] == "source-unavailable")
    assert "Journal C" in unavailable["body"]


def test_cnki_stale_only_when_older_than_window(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    write_json(
        data_dir / "local_cnki_status.json",
        {"ok": True, "last_success_at": "2026-08-02T10:00:00+00:00", "state": "success"},
    )

    anomalies = build_anomalies(data_dir, cnki_max_age_hours=30.0, now=now)

    assert any(item["slug"] == "local-cnki-stale" for item in anomalies)

    write_json(
        data_dir / "local_cnki_status.json",
        {"ok": True, "last_success_at": "2026-08-04T10:00:00+00:00", "state": "success"},
    )
    anomalies_fresh = build_anomalies(data_dir, cnki_max_age_hours=30.0, now=now)
    assert not any(item["slug"] == "local-cnki-stale" for item in anomalies_fresh)


def test_sync_issues_creates_when_absent(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    anomalies = [
        {
            "slug": "degraded-sources",
            "title": "Degraded sources (2)",
            "body": "body",
        }
    ]
    calls = []

    def fake_request(method, url, token, payload=None):
        calls.append((method, url, token, payload))
        if method == "GET":
            return []
        return {"number": 1}

    with patch("open_health_issues._request", side_effect=fake_request):
        report = sync_issues(anomalies, repo="academic-door/econ-paper-monitor", issue_prefix="[Monitor Health]", token="tok", dry_run=False)

    assert report["created"] == ["degraded-sources"]
    post = next(call for call in calls if call[0] == "POST")
    assert post[3]["title"].startswith("[Monitor Health] degraded-sources")


def test_sync_issues_updates_existing_and_closes_recovered(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    anomalies = [
        {
            "slug": "degraded-sources",
            "title": "Degraded sources (2)",
            "body": "body v2",
        }
    ]
    calls = []

    def fake_request(method, url, token, payload=None):
        calls.append((method, url, token, payload))
        if method == "GET":
            return [
                {
                    "number": 7,
                    "title": "[Monitor Health] degraded-sources: Degraded sources (2)",
                }
            ]
        return {"number": 7}

    with patch("open_health_issues._request", side_effect=fake_request):
        report = sync_issues(anomalies, repo="academic-door/econ-paper-monitor", issue_prefix="[Monitor Health]", token="tok", dry_run=False)

    assert report["updated"] == ["degraded-sources"]
    assert report["created"] == []
    patch_call = next(call for call in calls if call[0] == "PATCH" and call[1].endswith("/issues/7"))
    assert patch_call[3]["body"] == "body v2"

    calls.clear()
    with patch("open_health_issues._request", side_effect=fake_request):
        recovered = sync_issues([], repo="academic-door/econ-paper-monitor", issue_prefix="[Monitor Health]", token="tok", dry_run=False)

    assert recovered["closed"] == ["degraded-sources"]
    close_call = next(call for call in calls if call[0] == "PATCH" and call[1].endswith("/issues/7"))
    assert close_call[3]["state"] == "closed"


def test_semantic_scholar_key_not_configured_creates_anomaly(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    write_json(
        data_dir / "semantic_scholar_keepalive.json",
        {
            "checked_at": "2026-08-04T10:00:00+00:00",
            "ok": False,
            "status_code": None,
            "reason": "not_configured",
        },
    )

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))

    key_issue = next(item for item in anomalies if item["slug"] == "semantic-scholar-key")
    assert "not configured" in key_issue["title"]


def test_semantic_scholar_key_invalid_creates_anomaly(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    write_json(
        data_dir / "semantic_scholar_keepalive.json",
        {
            "checked_at": "2026-08-04T10:00:00+00:00",
            "ok": False,
            "status_code": 401,
            "reason": "invalid_key",
        },
    )

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))

    key_issue = next(item for item in anomalies if item["slug"] == "semantic-scholar-key")
    assert "unhealthy" in key_issue["title"]


def test_semantic_scholar_key_stale_creates_anomaly(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    write_json(
        data_dir / "semantic_scholar_keepalive.json",
        {
            "checked_at": "2026-07-20T10:00:00+00:00",
            "ok": True,
            "status_code": 200,
            "reason": "ok",
        },
    )

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))

    key_issue = next(item for item in anomalies if item["slug"] == "semantic-scholar-key")
    assert "idle" in key_issue["title"]


def test_semantic_scholar_key_fresh_has_no_anomaly(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))

    assert not any(item["slug"] == "semantic-scholar-key" for item in anomalies)


def test_semantic_scholar_key_missing_keepalive_creates_idle_anomaly(tmp_path: Path):
    data_dir = make_data_dir(tmp_path)
    (data_dir / "semantic_scholar_keepalive.json").unlink()

    anomalies = build_anomalies(data_dir, now=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))

    key_issue = next(item for item in anomalies if item["slug"] == "semantic-scholar-key")
    assert "idle" in key_issue["title"]