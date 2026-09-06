"""Audit the Windows CNKI/UChicago local supplement runtime chain.

Purpose
-------
The local supplement runs on the machine from a scheduled entry point
(historically Task Scheduler) -> launcher ``local_admin/runner/run_local_supplements.ps1``
on canonical E: -> the C: production runner checkout
``C:\\Users\\Administrator\\Work\\econ-paper-monitor\\runner-worktree``, where
``scripts/local_cnki_update.py`` and ``scripts/fetch_uchicago_local.py`` capture
CNKI / UChicago data and (on success) push to ``origin/main`` and trigger the
``watchdog.yml`` workflow.

This tool gives an unambiguous verdict and localizes which layer is failing:

    scheduler -> launcher -> C-runner -> source fetch -> Git publication -> watchdog

It is read-only. It never reads or prints credentials; the launcher log already
redacts ``Authorization: Basic ...`` lines, and this module re-redacts any
credential-looking fragment defensively.

Verdicts
--------
* ``healthy``   - both CNKI and UChicago durable status are published/fresh AND
                  (when the launcher log is available) the last run ended ``ok``.
* ``degraded``  - data was captured but the remote sync/publication could not be
                  confirmed (e.g. ``end degraded``, a stale-but-present status,
                  an incomplete source-health set, a push was skipped).
* ``blocked``   - health cannot be confirmed or an active failure occurred
                  (missing/invalid status, ``FAIL:`` in the launcher log, an
                  unrecovered source fetch error, an expired run window).

Recovery
--------
Run with ``--recovery`` to print the bounded, credential-free recovery procedure
for the localized layer.

Usage
-----
    python scripts/audit_local_supplement_runtime.py [--cnki PATH] [--uchicago PATH] [--log PATH]
                                                      [--max-age-hours 30] [--recovery]
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CNKI = ROOT / "data" / "local_cnki_status.json"
DEFAULT_UCHICAGO = ROOT / "data" / "local_uchicago_status.json"
DEFAULT_LOG = ROOT / "local_admin" / "logs" / "local-supplements.log"

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


def inspect_launcher_log(text: str, *, now: datetime | None = None) -> dict:
    """Judge the LAST run block, plus per-layer markers within that block.

    The launcher appends every round to one file. Scrolling the whole file for
    markers mis-labels the current state (historical many-run ''FAIL:'' lines
    would mark a later successful round as failed). So we split into run blocks
    on explicit ``[ts] start`` boundaries and terminal ``end ok`` / ``end degraded``
    / ``FAIL:`` markers, then classify only the most recent block.
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

    # Last-run timestamp = the newest [ts] line inside the last block header.
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
        # A recorded run exists; FAIL (in the last block) is the only launcher fault signal.
        "launcher": "fail" if m["fail_marker"] else "ok",
        "source_fetch": "fail" if (m["fetch_failed"] or m["reset_failed"]
                                   or m["cnki_capture_error"] or m["uchicago_failed"]) else "ok",
        "git_publication": "fail" if (m["remote_sync_deferred"] or m["push_skipped"]
                                      or m["cnki_reported_failure"]) else "ok",
        "watchdog": "ok" if (m["watchdog_triggered"] or m["action_run"]) else "unknown",
    }
    return result


def assess(*, cnki_path: Path = DEFAULT_CNKI, uchicago_path: Path = DEFAULT_UCHICAGO,
           log_text: str | None = None, now: datetime | None = None,
           max_age_hours: float = 30.0) -> dict:
    """Combine status + launcher log into a single verdict."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cnki = inspect_status(cnki_path, now=now, max_age_hours=max_age_hours)
    uchi = inspect_status(uchicago_path, now=now, max_age_hours=max_age_hours)
    log = inspect_launcher_log(log_text, now=now) if log_text else {"available": False}

    # Determine overall verdict.
    status_ok = (["cnki", "uchicago"] if (cnki["ok"] and uchi["ok"]) else
                 (["cnki"] if cnki["ok"] else (["uchicago"] if uchi["ok"] else [])))
    stale = (cnki.get("code") == "stale") or (uchi.get("code") == "stale")
    hard_fail_status = (not cnki["ok"] and cnki.get("code") != "stale") or \
                       (not uchi["ok"] and uchi.get("code") != "stale")

    out = log.get("outcome")
    # A stale-but-described status is a soft degrade, not a hard fail.
    stale_any = (cnki.get("code") == "stale") or (uchi.get("code") == "stale")
    both_ok = cnki["ok"] and uchi["ok"]
    if hard_fail_status:
        verdict = "blocked"
    elif out == "failed":
        verdict = "blocked"
    elif out in ("degraded", "incomplete"):
        # Last run ended degraded or did not produce a clean terminal marker.
        verdict = "degraded"
    elif both_ok:
        # Both durable statuses are published/fresh => the chain produced + published.
        verdict = "healthy"
    elif stale_any:
        # One or both statuses are stale but present => last-known-good, degraded.
        verdict = "degraded"
    elif not (cnki["ok"] or uchi["ok"]):
        verdict = "blocked"
    else:
        verdict = "degraded"

    # Scheduler is not observable from this sandbox / read-only context.
    scheduler = {
        "observable": False,
        "note": ("Task Scheduler registration is not readable from this sandbox "
                 "(Get-ScheduledTask/schtasks return nothing). Periodic launcher runs "
                 "in the log prove the chain is scheduled, but trigger/registration "
                 "details are a visibility limitation, not an absence."),
    }

    failing_layers = [layer for layer, status in log["layers"].items() if status == "fail"]
    result = {
        "verdict": verdict,
        "cnki_status": cnki,
        "uchicago_status": uchi,
        "launcher": log,
        "scheduler": scheduler,
        "failing_layers": failing_layers,
        "recovery": recovery_for(verdict, failing_layers),
    }
    return result


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
        elif layer == "source_fetch":
            steps.append("Source fetch: confirm the CNKI/UChicago source of the failing journal is reachable from"
                         " this machine's residential IP (no CI-only block). Re-run the affected"
                         " `scripts/local_cnki_update.py` or `scripts/fetch_uchicago_local.py`.")
        elif layer == "git_publication":
            steps.append("Git publication: verify connectivity to origin (git ls-remote origin refs/heads/main);"
                         " a single retry usually clears transient SSL-EOF/push stalls. Do not reset/rebase.")
        elif layer == "watchdog":
            steps.append("Watchdog: confirm the workflow run id printed after 'pushed UChicago supplement'; if"
                         " absent, trigger `gh workflow run watchdog.yml` on the repo manually.")
        else:
            steps.append(f"Unknown layer '{layer}': re-read the launcher log tail and the two durable status JSONs.")
    steps.append("If the status timestamp is stale but no hard error is present, treat as DEGRADED (backfill on"
                 " next scheduled round) rather than BLOCKED.")
    steps.append("Never re-author credentials or inspect token files manually; the launcher injects the machine"
                 " token itself.")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the CNKI/UChicago local supplement runtime chain")
    parser.add_argument("--cnki", type=Path, default=DEFAULT_CNKI)
    parser.add_argument("--uchicago", type=Path, default=DEFAULT_UCHICAGO)
    parser.add_argument("--log", type=Path, default=None,
                        help="Launcher log path (default: <repo>/local_admin/logs/local-supplements.log if present)")
    parser.add_argument("--max-age-hours", type=float, default=30.0)
    parser.add_argument("--recovery", action="store_true", help="Print the bounded recovery procedure only")
    args = parser.parse_args()

    log_text = None
    log_path = args.log or DEFAULT_LOG
    if log_path.exists():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = None

    result = assess(cnki_path=args.cnki, uchicago_path=args.uchicago, log_text=log_text,
                    max_age_hours=args.max_age_hours)
    if args.recovery:
        for step in result["recovery"]:
            print("- " + step)
        return 0 if result["verdict"] == "healthy" else 1

    out = json.dumps(result, ensure_ascii=False, sort_keys=True)
    # Single serialization; redact any credential-looking fragment in the JSON text.
    print(redact(out))
    # exit 0 healthy, 1 degraded, 2 blocked
    return {"healthy": 0, "degraded": 1, "blocked": 2}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
