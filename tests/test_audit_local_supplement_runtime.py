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


from scripts.audit_local_supplement_runtime import inspect_runner, probe_scheduler


# ------------------------- C-runner observation (gap 1) ------------------------
# NOTE: runner path must exist on disk for the existence check; git output is faked.

def _git_fake(branch="main", head="abc1234deadbeef", status=""):
    def fake(cmd, **_kw):
        j = " ".join(cmd)
        if "--abbrev-ref" in j:
            return (0, branch, "")
        if j.endswith("HEAD") and "--abbrev-ref" not in j:
            return (0, head, "")
        if "status" in j:
            return (0, status, "")
        return (0, "", "")
    return fake


def test_inspect_runner_observable(tmp_path):
    r = inspect_runner(str(tmp_path), run_cmd=_git_fake())
    assert r["observable"] is True
    assert r["branch"] == "main"
    assert r["head"] == "abc1234deadbeef"
    assert r["clean"] is True
    assert r["dirty"] is False


def test_inspect_runner_path_missing():
    r = inspect_runner(r"C:\definitely\not\a\repo")
    assert r["observable"] is False
    assert r["reason"] == "path_missing"


def test_inspect_runner_git_error(tmp_path):
    def fake(cmd, **_kw):
        return (128, "", "fatal: not a git repository")
    r = inspect_runner(str(tmp_path), run_cmd=fake)
    assert r["observable"] is False
    assert r["reason"] == "git_error"


def test_inspect_runner_dirty(tmp_path):
    r = inspect_runner(str(tmp_path), run_cmd=_git_fake(status=" M data/foo.json"))
    assert r["dirty"] is True
    assert r["clean"] is False


# ------------------------- scheduler probe (gap 2) -----------------------------

def test_probe_scheduler_registered():
    out = "TaskName: Econ Papers Daily - Local Supplement\nStatus: Ready\nNext Run Time: 9/6/2026"
    def fake(cmd, **_kw):
        return (0, out, "") if "/tn" in " ".join(cmd) else (0, "", "")
    s = probe_scheduler(platform_name="Windows", run_cmd=fake)
    assert s["observable"] is True
    assert s["status"] == "registered"
    assert s["registered"] is True
    assert "Econ Papers" in s["evidence"]


def test_probe_scheduler_not_found_is_limitation_not_absence():
    csv = "TaskName,Status\nSomeOtherTask,Ready"
    def fake(cmd, **_kw):
        if "/tn" in " ".join(cmd):
            return (1, "", "ERROR: The system cannot find the file specified.")
        return (0, csv, "")
    s = probe_scheduler(platform_name="Windows", run_cmd=fake)
    assert s["observable"] is False
    assert s["limitation"] == "registration_not_found"
    assert "not an absence" in s["note"]


def test_probe_scheduler_permission_limited():
    def fake(cmd, **_kw):
        return (1, "", "ERROR: Access is denied.")
    s = probe_scheduler(platform_name="Windows", run_cmd=fake)
    assert s["observable"] is False
    assert s["limitation"] == "permission_limited"


def test_probe_scheduler_platform_unsupported():
    s = probe_scheduler(platform_name="Linux")
    assert s["limitation"] == "platform_unsupported"
    assert "not attempted" in s["note"]


# ------------------------- integrated assess() surfaces both -------------------

def test_assess_reports_c_runner_and_scheduler_when_observed(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    runner = {"observable": True, "status": "ok", "branch": "main",
              "head": "abc", "clean": True, "dirty": False}
    sched = {"observable": True, "status": "registered", "registered": True,
             "evidence": "TaskName: Econ Papers Daily - Local Supplement"}
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK, runner=runner, scheduler=sched, now=NOW)
    assert res["runner"]["observable"] is True
    assert res["scheduler"]["observable"] is True
    assert res["verdict"] == "healthy"


def test_unobservable_runner_and_scheduler_do_not_hard_fail(tmp_path):
    _write_status(tmp_path / "cnki.json")
    _write_status(tmp_path / "uchi.json", ts="2026-09-06T04:12:13+00:00")
    res = assess(cnki_path=tmp_path / "cnki.json", uchicago_path=tmp_path / "uchi.json",
                 log_text=LOG_OK,
                 runner={"observable": False, "reason": "path_missing", "status": "unobservable"},
                 scheduler={"observable": False, "limitation": "platform_unsupported",
                            "status": "unobservable"},
                 now=NOW)
    assert res["verdict"] == "healthy"
