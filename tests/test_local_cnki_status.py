from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.audit_local_cnki_status import inspect_status


def test_local_cnki_status_is_fresh(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "state": "published",
                "ok": True,
                "count": 101,
                "last_success_at": "2026-07-27T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    result = inspect_status(path, now=datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc))
    assert result["ok"] is True
    assert result["code"] == "fresh"


def test_local_cnki_status_stale(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "state": "published",
                "ok": True,
                "last_success_at": "2026-07-25T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    result = inspect_status(path, now=datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc))
    assert result["ok"] is False
    assert result["code"] == "stale"


def test_local_cnki_status_requires_published_state(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"state": "running", "ok": False}), encoding="utf-8")
    result = inspect_status(path)
    assert result["ok"] is False
    assert result["code"] == "not_published"
