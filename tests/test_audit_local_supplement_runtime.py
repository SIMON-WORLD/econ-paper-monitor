from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.audit_local_supplement_runtime import assess


def _write_status(path, *, state="published", ok=True, count=99, sel=6, succ=6, failed=0, ts="2026-09-06T04:11:57+00:00"):
    path.write_text(
        json.dumps(
            {
                "state": state,
                "ok": ok,
                "count": count,
                "selected_sources": sel,
                "successful_sources": succ,
                "failed_sources": failed,
                "last_success_at": ts,
                "message": "ok",
            }
        ),
        encoding="utf-8",
    )


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

LOG_OK = (
    "[2026-09-06 00:12:18] pushed UChicago supplement 2026-09-06\n"
    "https://github.com/academic-door/econ-paper-monitor/actions/runs/34010973047\n"
    "[2026-09-06 00:12:22] end ok\n"
    "[2026-09-06 00:12:22] released runner lock\n"
)

LOG_DEGRADED = (
    "[2026-09-06 00:00:00] start\n"
    "[2026-09-06 00:00:10] fetch failed; continuing local capture without remote sync\n"
    "[2026-09-06 00:05:00] fetch failed; CNKI local capture completed, push skipped\n"
    "[2026-09-06 00:10:00] fetch failed; local capture committed to local-supplements-backup, push/watchdog skipped\n"
    "[2026-09-06 00:10:01] end degraded (local capture ok, remote sync deferred)\n"
)

LOG_FAIL = (
    "[2026-09-06 00:00:00] start\n"
    "[2026-09-06 00:00:01] FAIL: launcher exception\n"
)

# --------------------------------------------------------------------------- health

def test_healthy_when_both_published_and_run_ok(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, now=NOW)
    assert res["verdict"] == "healthy"
    assert res["cnki_status"]["ok"] is True
    assert res["uchicago_status"]["ok"] is True


def test_degraded_when_run_end_degraded(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_DEGRADED, now=NOW)
    assert res["verdict"] == "degraded"
    assert "git_publication" in res["failing_layers"]


def test_blocked_when_status_missing(tmp_path):
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, now=NOW)
    assert res["verdict"] == "blocked"
    assert res["cnki_status"]["ok"] is False
    assert res["cnki_status"]["code"] == "missing_or_invalid"


def test_blocked_when_launcher_log_failed(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_FAIL, now=NOW)
    assert res["verdict"] == "blocked"
    assert res["launcher"]["outcome"] == "failed"


def test_stale_status_degrades(tmp_path):
    _write_status(tmp_path / "cnki.json", ts="2026-09-01T00:00:00+00:00")
    _write_status(tmp_path / "uchi.json", ts="2026-09-01T00:00:00+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, now=NOW)
    assert res["verdict"] == "degraded"
    assert res["cnki_status"]["code"] == "stale"


# --------------------------------------------------------------------------- layers

def test_layer_localization_source_fetch_and_publication(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_DEGRADED, now=NOW)
    layers = res["launcher"]["layers"]
    assert layers["source_fetch"] == "fail"
    assert layers["git_publication"] == "fail"


def test_watchdog_marker_detected(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, now=NOW)
    assert res["launcher"]["layers"]["watchdog"] == "ok"


# --------------------------------------------------------------------------- scheduler + recovery

def test_scheduler_is_classified_as_visibility_limitation(tmp_path):
    _write_status(tmp_path / "cnki.json")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, now=NOW)
    assert res["scheduler"]["observable"] is False
    note = res["scheduler"]["note"]
    assert "not readable" in note or "visibility limitation" in note


def test_recovery_procedure_is_bounded_and_credential_free(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_DEGRADED, now=NOW)
    assert isinstance(res["recovery"], list) and len(res["recovery"]) >= 1
    joined = " ".join(res["recovery"])
    assert "token" not in joined.lower() or "machine token" in joined.lower()


def test_healthy_recovery_is_noop(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, now=NOW)
    assert res["recovery"][0].startswith("No action")
