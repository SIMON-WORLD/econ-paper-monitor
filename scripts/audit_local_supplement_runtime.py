"""Audit the Windows CNKI/UChicago local supplement runtime chain.

The local supplement runs on the machine from a scheduled entry point
(historically Task Scheduler) -> launcher ``local_admin/runner/run_local_supplements.ps1``
on canonical E: -> the C: production runner checkout
``C:\\Users\\Administrator\\Work\\econ-paper-monitor\\runner-worktree``, where
``scripts/local_cnki_update.py`` and ``scripts/fetch_uchicago_local.py`` capture
CNKI / UChicago data and (on success) push to ``origin/main`` and trigger the
``watchdog.yml`` workflow.

This tool is read-only. It never reads or prints credentials; the launcher log
already redacts ``Authorization: Basic ...`` lines, and this module re-redacts
any credential-looking fragment defensively.

Verdicts
--------
* ``healthy``   - both CNKI and UChicago durable status are published/fresh AND
                  (when the launcher log is available) the last run ended ``ok``.
* ``degraded``  - data was captured but remote sync/publication is unconfirmed
                  (``end degraded``, a stale-but-present status, an incomplete
                  source-health set, a skipped push).
* ``blocked``   - health cannot be confirmed or an active failure occurred
                  (missing/invalid status, ``FAIL:`` in the launcher log, an
                  unrecovered source fetch error).

Layers (each real, bounded, read-only)
--------------------------------------
* ``scheduler``  - attempts a read-only Task Scheduler probe (Windows) and reports
                   registration / trigger / last-result evidence; only when the
                   probe is unavailable or permission-limited is it classified as
                   a visibility limitation. It never guesses absence.
* ``launcher``   - the E: ``local-admin/runner`` launcher log outcome (last run block).
* ``c_runner``   - bounded read-only evidence for the production runner checkout
                   (existence, branch, HEAD, clean/dirty) or an unobservable/error
                   classification when the path is absent / not readable.
* ``source_fetch`` / ``git_publication`` / ``watchdog`` - parsed from the last run
                   block of the launcher log.

Recovery
--------
``--recovery`` prints a bounded, credential-free recovery procedure for the
localized (or unknown) layer.

Usage
-----
    python scripts/audit_local_supplement_runtime.py [--cnki PATH] [--uchicago PATH]
        [--log PATH] [--runner PATH] [--scheduler-task NAME] [--max-age-hours 30]
        [--recovery]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CNKI = ROOT / "data" / "local_cnki_status.json"
DEFAULT_UCHICAGO = ROOT / "data" / "local_uchicago_status.json"
DEFAULT_LOG = ROOT / "local_admin" / "logs" / "local-supplements.log"
DEFAULT_RUNNER = r"C:\Users\Administrator\Work\econ-paper-monitor\runner-worktree"
DEFAULT_TASK_NAME = "Econ Papers Daily - Local Supplement"

# Credential-ish fragments we refuse to echo even if they ever appear in input.
_CRED_RE = re.compile(
    r"(Authorization: Basic [A-Za-z0-9+/=]+|x-access-token:[^\s]+|ghp_[A-Za-z0-9]+|"
    r"github_pat_[A-Za-z0-9_]+|token[:=]\s*[^\s]+)",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Return text with credential-looking fragments replaced by a marker."""
    return _CRED_RE.sub("<redacted>", text or "")


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _run_cmd(cmd: list[str], *, cwd: str | None = None, timeout: int = 20) -> tuple[int, str, str]:
    """Run a bounded read-only command, returning (rc, stdout, stderr)."""
    env = dict(os.environ)
    env.setdefault("GIT_NO_LAZY_FETCH", "1")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
            encoding="utf-8", errors="replace",
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except OSError as exc:
        return 1, "", str(exc)[:120]


def _status_verdict(payload: object, *, now: datetime, max_age_hours: float) -> dict:
    """Classify a single durable status object (CNKI or UChicago)."""
    if not isinstance(payload, dict):
        return {"ok": False, "code": "invalid_shape", "message": "status must be an object"}
    state = payload.get("state")
    ok = payload.get("ok") is True
    if state != "published" or not ok:
        return {
            "ok": False,
            "code": "not_published",
            "state": state,
            "message": payload.get("message", "status is not published"),
        }
    counts = {
        key: payload.get(key)
        for key in ("selected_sources", "successful_sources", "failed_sources")
        if key in payload
    }
    if counts:
        selected = int(counts.get("selected_sources") or 0)
        successful = int(counts.get("successful_sources") or 0)
        failed = int(counts.get("failed_sources") or 0)
        if selected <= 0 or failed != 0 or successful != selected:
            return {"ok": False, "code": "incomplete_source_health", "source_health": counts}
    timestamp = parse_timestamp(payload.get("last_success_at"))
    if timestamp is None:
        return {"ok": False, "code": "missing_success_timestamp"}
    age_hours = (now - timestamp).total_seconds() / 3600.0
    if age_hours < -1:
        return {"ok": False, "code": "future_timestamp", "age_hours": round(age_hours, 2)}
    if age_hours > max_age_hours:
        return {"ok": False, "code": "stale", "age_hours": round(age_hours, 2),
                "last_success_at": timestamp.isoformat()}
    return {
        "ok": True,
        "code": "fresh",
        "age_hours": round(max(age_hours, 0.0), 2),
        "last_success_at": timestamp.isoformat(),
        "count": payload.get("count"),
        "source_health": counts or None,
    }


def inspect_status(path: Path, *, now: datetime | None = None, max_age_hours: float = 30.0) -> dict:
    """Read and classify one durable status file."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "code": "missing_or_invalid", "message": str(exc)}
    verdict = _status_verdict(payload, now=now, max_age_hours=max_age_hours)
    verdict["layer"] = "source_fetch"
    return verdict


def inspect_runner(runner_path: str = DEFAULT_RUNNER, *, run_cmd: object = _run_cmd) -> dict:
    """Collect bounded read-only evidence for the production runner checkout.

    Returns ``observable`` + ``branch`` / ``head`` / ``clean`` / ``dirty`` when the
    checkout exists and is readable, or ``unobservable`` with a reason
    (``path_missing`` / ``git_error``) when it cannot be observed.
    """
    path = str(runner_path)
    if not Path(path).exists():
        return {"observable": False, "reason": "path_missing", "status": "unobservable", "path": path}
    rc_b, branch, err_b = run_cmd(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"])
    if rc_b != 0:
        return {"observable": False, "reason": "git_error", "status": "unobservable",
                "path": path, "error": redact(err_b)[:120]}
    rc_h, head, _ = run_cmd(["git", "-C", path, "rev-parse", "HEAD"])
    rc_s, status, _ = run_cmd(["git", "-C", path, "status", "--porcelain"])
    dirty = rc_s == 0 and bool(status)
    return {
        "observable": True,
        "status": "ok",
        "path": path,
        "branch": branch,
        "head": head,
        "clean": rc_s == 0 and not dirty,
        "dirty": dirty,
    }


def probe_scheduler(task_name: str = DEFAULT_TASK_NAME, *,
                    platform_name: str | None = None, run_cmd: object = _run_cmd) -> dict:
    """Attempt a read-only scheduler probe (Windows).

    Reports ``observable`` + registration/trigger/last-result evidence when the
    environment permits; otherwise classifies the limitation reason
    (``platform_unsupported`` / ``permission_limited`` / ``registration_not_found`` /
    ``probe_error``). It never asserts absence.
    """
    pname = (platform_name or platform.system()).lower()
    if pname != "windows":
        return {"observable": False, "status": "unobservable", "task_name": task_name,
                "limitation": "platform_unsupported",
                "note": "Task Scheduler probe is Windows-only; not attempted on this platform."}

    # Try the exact task name first.
    rc, out, err = run_cmd(["schtasks", "/query", "/tn", task_name, "/v", "/fo", "LIST"])
    if rc == 0 and out.strip():
        return {"observable": True, "status": "registered", "task_name": task_name,
                "registered": True, "evidence": redact(out)[:1200],
                "note": "Task found; registration/trigger/last-result evidence captured."}

    # Fall back to a full listing and search for the launcher/runner reference.
    rc2, out2, err2 = run_cmd(["schtasks", "/query", "/fo", "CSV"])
    if rc2 == 0 and out2:
        lower = out2.casefold()
        if "econ-paper-monitor" in lower or "run_local_supplements" in lower or "econ papers" in lower:
            return {"observable": True, "status": "registered", "task_name": task_name,
                    "registered": True, "evidence": redact(out2)[:1200],
                    "note": "Task referenced in scheduler listing; evidence captured."}
        return {"observable": False, "status": "unobservable", "task_name": task_name,
                "limitation": "registration_not_found",
                "note": ("No matching scheduler entry found by this name; periodic launcher "
                         "runs in the log prove the chain is scheduled, so this is a "
                         "registration/name visibility limitation, not an absence.")}

    combined = (out + " " + err).casefold()
    if "access is denied" in combined or "access denied" in combined or "error: access" in combined:
        return {"observable": False, "status": "unobservable", "task_name": task_name,
                "limitation": "permission_limited",
                "note": "Task Scheduler probe failed due to insufficient privilege; visibility limitation."}
    return {"observable": False, "status": "unobservable", "task_name": task_name,
            "limitation": "probe_error", "detail": redact(err)[:120],
            "note": "Task Scheduler probe errored; visibility limitation."}


def inspect_launcher_log(text: str, *, now: datetime | None = None) -> dict:
    """Judge the LAST run block, plus per-layer markers within that block.

    The launcher appends every round to one file. Scrolling the whole file for
    markers mis-labels the current state (historical ``FAIL:`` lines would mark a
    later successful round as failed). So we split into run blocks on explicit
    ``[ts] start`` boundaries and terminal ``end ok`` / ``end degraded`` /
    ``FAIL:`` markers, then classify only the most recent block.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    line_re = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$")
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        m = line_re.match(raw)
        content = m.group(2) if m else raw
        if content.strip() == "start":
            if current is not None:
                blocks.append(current)
            current = [content]
        elif current is not None:
            current.append(content)
            if re.search(r"\b(end ok|end degraded|FAIL:)\b", content):
                blocks.append(current)
                current = None
    if current is not None:
        blocks.append(current)

    last = blocks[-1] if blocks else (text.splitlines() if text else [])
    low = "\n".join(last).casefold() if last else ""

    def has(needle: str) -> bool:
        return needle in low

    result: dict = {
        "available": True,
        "run_count": len(blocks),
        "markers": {
            "lock_acquired": has("acquired runner lock"),
            "lock_released": has("released runner lock"),
            "lock_stale": has("removing stale runner lock"),
            "lock_collision": has("another round is running"),
            "started": has("start"),
            "fetch_failed": has("fetch failed"),
            "fetch_skipped": has("fetch skipped"),
            "reset_failed": has("reset failed"),
            "cnki_reported_failure": has("cnki update reported failure"),
            "cnki_capture_error": has("cnki capture reported error"),
            "uchicago_failed": has("uchicago fetch failed"),
            "pushed_uchicago": has("pushed uchicago supplement"),
            "uchicago_no_change": has("uchicago: no changes"),
            "degraded_end": has("end degraded"),
            "ok_end": has("end ok"),
            "fail_marker": has("fail:"),
            "watchdog_triggered": has("workflow run watchdog.yml"),
            "action_run": has("actions/runs/"),
            "push_skipped": has("push/watchdog skipped"),
            "remote_sync_deferred": has("remote sync deferred"),
        },
        "layers": {},
        "last_run_ts": None,
        "age_hours": None,
        "outcome": "unknown",
    }

    last_ts = None
    for raw in text.splitlines():
        m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", raw)
        if m:
            last_ts = m.group(1)
    if last_ts:
        try:
            ts = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            result["last_run_ts"] = ts.isoformat()
            result["age_hours"] = round((now - ts).total_seconds() / 3600.0, 2)
        except ValueError:
            pass

    m = result["markers"]
    if m["fail_marker"]:
        result["outcome"] = "failed"
    elif m["degraded_end"]:
        result["outcome"] = "degraded"
    elif m["ok_end"]:
        result["outcome"] = "ok"
    elif m["started"]:
        result["outcome"] = "incomplete"
    else:
        result["outcome"] = "unknown"

    result["layers"] = {
        "launcher": "fail" if m["fail_marker"] else "ok",
        "source_fetch": "fail" if (m["fetch_failed"] or m["reset_failed"]
                                   or m["cnki_capture_error"] or m["uchicago_failed"]) else "ok",
        "git_publication": "fail" if (m["remote_sync_deferred"] or m["push_skipped"]
                                      or m["cnki_reported_failure"]) else "ok",
        "watchdog": "ok" if (m["watchdog_triggered"] or m["action_run"]) else "unknown",
    }
    return result


_DEFAULT_SCHEDULER = {
    "observable": False,
    "status": "unobservable",
    "limitation": "not_probed",
    "note": "Scheduler probe not attempted (default); visibility limitation.",
}


def assess(*, cnki_path: Path = DEFAULT_CNKI, uchicago_path: Path = DEFAULT_UCHICAGO,
           log_text: str | None = None, runner_path: str | None = None,
           runner: dict | None = None, scheduler: dict | None = None,
           now: datetime | None = None, max_age_hours: float = 30.0) -> dict:
    """Combine status + launcher log + C-runner evidence + scheduler into one verdict."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cnki = inspect_status(cnki_path, now=now, max_age_hours=max_age_hours)
    uchi = inspect_status(uchicago_path, now=now, max_age_hours=max_age_hours)
    log = inspect_launcher_log(log_text, now=now) if log_text else {"available": False}
    runner_result = runner if runner is not None else inspect_runner(runner_path) if runner_path else _DEFAULT_SCHEDULER_RUNNER()
    sched_result = scheduler if scheduler is not None else _DEFAULT_SCHEDULER

    status_ok = (["cnki", "uchicago"] if (cnki["ok"] and uchi["ok"]) else
                 (["cnki"] if cnki["ok"] else (["uchicago"] if uchi["ok"] else [])))
    hard_fail_status = (not cnki["ok"] and cnki.get("code") != "stale") or \
                       (not uchi["ok"] and uchi.get("code") != "stale")
    stale_any = (cnki.get("code") == "stale") or (uchi.get("code") == "stale")
    both_ok = cnki["ok"] and uchi["ok"]

    out = log.get("outcome")
    if hard_fail_status:
        verdict = "blocked"
    elif out == "failed":
        verdict = "blocked"
    elif out in ("degraded", "incomplete"):
        verdict = "degraded"
    elif both_ok:
        verdict = "healthy"
    elif stale_any:
        verdict = "degraded"
    elif not (cnki["ok"] or uchi["ok"]):
        verdict = "blocked"
    else:
        verdict = "degraded"

    failing_layers = [layer for layer, status in log["layers"].items() if status == "fail"]
    if runner_result.get("status") == "error":
        failing_layers.append("c_runner")

    result = {
        "verdict": verdict,
        "cnki_status": cnki,
        "uchicago_status": uchi,
        "launcher": log,
        "runner": runner_result,
        "scheduler": sched_result,
        "failing_layers": failing_layers,
        "recovery": recovery_for(verdict, failing_layers),
    }
    return result


def _DEFAULT_SCHEDULER_RUNNER() -> dict:
    return {"observable": False, "status": "unobservable", "reason": "runner_not_configured"}


def recovery_for(verdict: str, failing_layers: list[str]) -> list[str]:
    """Return a bounded, credential-free recovery procedure for the verdict."""
    steps: list[str] = []
    if verdict == "healthy":
        return ["No action required; local supplement runtime is healthy."]
    layers = failing_layers or ["unknown"]
    for layer in layers:
        if layer == "launcher":
            steps.append("Launcher: re-run locally `local_admin/runner/run_local_supplements.ps1` once the"
                         " runner lock is clear; verify the last log line reaches 'end ok'.")
        elif layer == "c_runner":
            steps.append("C-runner: confirm the production runner checkout exists, is on `main`, and is not"
                         " mid-run (clear the runner lock); verify `git status` is clean after the round.")
        elif layer == "source_fetch":
            steps.append("Source fetch: confirm the failing CNKI/UChicago source is reachable from this machine's"
                         " residential IP; re-run the affected `scripts/local_cnki_update.py` or"
                         " `scripts/fetch_uchicago_local.py`.")
        elif layer == "git_publication":
            steps.append("Git publication: verify connectivity to origin (`git ls-remote origin refs/heads/main`);"
                         " a single retry usually clears transient SSL-EOF/push stalls. Do not reset/rebase.")
        elif layer == "watchdog":
            steps.append("Watchdog: confirm the workflow run id printed after 'pushed UChicago supplement'; if"
                         " absent, trigger `gh workflow run watchdog.yml` on the repo manually.")
        else:
            steps.append(f"Unknown layer '{layer}': re-read the launcher log tail and the two durable status JSONs.")
    steps.append("If a status timestamp is stale but no hard error is present, treat as DEGRADED (backfill on"
                 " next scheduled round) rather than BLOCKED.")
    steps.append("Never re-author credentials or inspect token files manually; the launcher injects the machine"
                 " token itself. Task Scheduler registration, if unobservable, is a visibility limitation."
                 " Confirm it from an elevated session if registration accuracy is required.")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the CNKI/UChicago local supplement runtime chain")
    parser.add_argument("--cnki", type=Path, default=DEFAULT_CNKI)
    parser.add_argument("--uchicago", type=Path, default=DEFAULT_UCHICAGO)
    parser.add_argument("--log", type=Path, default=None,
                        help="Launcher log path (default: <repo>/local_admin/logs/local-supplements.log if present)")
    parser.add_argument("--runner", type=str, default=DEFAULT_RUNNER,
                        help="Production runner checkout path to observe")
    parser.add_argument("--scheduler-task", type=str, default=DEFAULT_TASK_NAME,
                        help="Candidate Task Scheduler task name to probe")
    parser.add_argument("--max-age-hours", type=float, default=30.0)
    parser.add_argument("--recovery", action="store_true", help="Print the bounded recovery procedure only")
    parser.add_argument("--no-scheduler-probe", action="store_true",
                        help="Skip the read-only Task Scheduler probe (treat as visibility limitation)")
    args = parser.parse_args()

    log_text = None
    log_path = args.log or DEFAULT_LOG
    if log_path.exists():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = None

    scheduler_res = _DEFAULT_SCHEDULER if args.no_scheduler_probe else probe_scheduler(args.scheduler_task)
    runner_res = inspect_runner(args.runner)

    result = assess(cnki_path=args.cnki, uchicago_path=args.uchicago, log_text=log_text,
                    runner_path=None, runner=runner_res, scheduler=scheduler_res,
                    max_age_hours=args.max_age_hours)
    if args.recovery:
        for step in result["recovery"]:
            print("- " + step)
        return 0 if result["verdict"] == "healthy" else 1

    out = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(redact(out))
    return {"healthy": 0, "degraded": 1, "blocked": 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
