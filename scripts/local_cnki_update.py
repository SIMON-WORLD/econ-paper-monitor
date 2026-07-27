"""Run the local-only Chinese journal supplement pipeline.

This entrypoint is intended for a Windows scheduled task. It keeps CNKI RSS on
the user's local network, then publishes only normalized site data to GitHub.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

from common import ROOT, today_str
from status import now, record_source, record_workflow_run


LOG_DIR = ROOT / "local_admin" / "logs"
LOG_PATH = LOG_DIR / "local-cnki-update.log"
RUNTIME_DIR = ROOT / "local_admin" / "runtime"
MAX_LOG_BYTES = 2_000_000
KEEP_LOG_BYTES = 400_000


def configure_console() -> None:
    """Keep scheduled-task logging alive on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def log_path_for_status() -> str:
    """Return a repository-relative log path for public status metadata."""
    return str(LOG_PATH.relative_to(ROOT)).replace("\\", "/")


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rotate_log(LOG_PATH)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")
    print(message)


def rotate_log(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= MAX_LOG_BYTES:
        return
    payload = path.read_bytes()[-KEEP_LOG_BYTES:]
    path.write_bytes(payload)


def prune_old_files(directory: Path, *, older_than_days: int) -> int:
    if not directory.exists():
        return 0
    cutoff = datetime.now().timestamp() - older_than_days * 24 * 60 * 60
    removed = 0
    for path in directory.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def run_step(
    command: list[str],
    *,
    allow_failure: bool = False,
    extra_env: dict[str, str] | None = None,
    display_command: list[str] | None = None,
) -> int:
    log("$ " + " ".join(display_command or command))
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.stdout:
        for line in completed.stdout.splitlines():
            log("  " + line)
    if completed.returncode and not allow_failure:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")
    return completed.returncode


def git_has_staged_changes() -> bool:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode != 0


def push_command() -> tuple[list[str], dict[str, str]]:
    """Return a push command and private environment additions.

    Interactive Git Credential Manager remains the default. A scheduled task
    can instead provide GITHUB_PUBLISH_TOKEN without putting the token in the
    remote URL or command-line log.
    """
    token = os.environ.get("GITHUB_PUBLISH_TOKEN", "").strip()
    if not token:
        return ["git", "push"], {}
    encoded = base64.b64encode(f"x-access-token:{token}".encode("ascii")).decode("ascii")
    count = int(os.environ.get("GIT_CONFIG_COUNT", "0") or 0)
    return ["git", "-c", "http.sslbackend=openssl", "push"], {
        "GIT_CONFIG_COUNT": str(count + 1),
        f"GIT_CONFIG_KEY_{count}": "http.https://github.com/.extraheader",
        f"GIT_CONFIG_VALUE_{count}": f"AUTHORIZATION: basic {encoded}",
    }


def push_with_retries(attempts: int = 4) -> None:
    last_code = 0
    for attempt in range(1, attempts + 1):
        command, extra_env = push_command()
        last_code = run_step(
            command,
            allow_failure=True,
            extra_env=extra_env,
            display_command=["git", "push"],
        )
        if last_code == 0:
            return
        wait_seconds = min(120, attempt * 30)
        log(f"git push failed; retrying in {wait_seconds} seconds ({attempt}/{attempts}).")
        import time

        time.sleep(wait_seconds)
    raise RuntimeError(f"git push failed after {attempts} attempts; last exit code={last_code}")


def prepare_cnki_raw_input(temp_output: Path) -> tuple[Path, int]:
    input_dir = RUNTIME_DIR / "raw-input"
    input_feed_dir = input_dir / "cnki-rss"
    input_feed_dir.mkdir(parents=True, exist_ok=True)
    for old_file in input_feed_dir.glob("*.json"):
        old_file.unlink()

    records = json.loads(temp_output.read_text(encoding="utf-8-sig")) if temp_output.exists() else []
    target = ROOT / "data" / "raw" / "cnki-rss" / f"{today_str()}.json"
    target_status = target.with_suffix(".status.json")
    if not isinstance(records, list) or not records:
        log("CNKI RSS fetch produced no records; preserving existing raw cache.")
        if target.exists():
            cached = json.loads(target.read_text(encoding="utf-8-sig"))
            if isinstance(cached, list) and cached:
                shutil.copyfile(target, input_feed_dir / target.name)
                log(f"Using preserved CNKI RSS cache with {len(cached)} records for dedupe input.")
                return input_dir, len(cached)
        return input_dir, 0
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(temp_output, target)
    shutil.copyfile(temp_output, input_feed_dir / target.name)
    temp_status = temp_output.with_suffix(".status.json")
    if temp_status.exists():
        shutil.copyfile(temp_status, target_status)
    log(f"Promoted {len(records)} CNKI RSS records to {target}")
    return input_dir, len(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-push", action="store_true", help="Run pipeline without committing/pushing generated updates.")
    parser.add_argument("--max-age-days", type=int, default=90)
    args = parser.parse_args()
    configure_console()

    python = sys.executable
    start = datetime.now().isoformat(timespec="seconds")
    log("=" * 72)
    log(f"Local CNKI update started at {start}")
    removed_runtime = prune_old_files(RUNTIME_DIR, older_than_days=14)
    removed_raw = prune_old_files(ROOT / "data" / "raw" / "cnki-rss", older_than_days=60)
    if removed_runtime or removed_raw:
        log(f"Pruned old local artifacts: runtime={removed_runtime}, cnki_raw={removed_raw}")
    record_source("local-cnki-run", ok=False, count=0, message="running")
    record_source("local-cnki-publish", ok=False, count=0, message="not attempted")
    final_status_recorded = False

    try:
        if not args.no_push:
            run_step(["git", "pull", "--ff-only", "origin", "main"], allow_failure=True)

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        cnki_temp = RUNTIME_DIR / f"cnki-rss-{today_str()}.json"
        run_step(
            [
                python,
                "scripts/fetch_cnki_rss.py",
                "--max-age-days",
                str(args.max_age_days),
                "--output",
                str(cnki_temp),
            ]
        )
        cnki_raw_input, cnki_count = prepare_cnki_raw_input(cnki_temp)
        if cnki_count:
            run_step([python, "scripts/dedupe.py", "--raw-dir", str(cnki_raw_input)])
        else:
            log("No CNKI RSS records available for dedupe input; skipping dedupe.")
        run_step([python, "scripts/clean_historical_working_papers.py"])
        run_step([python, "scripts/clean_cn_noise.py"])
        run_step([python, "scripts/apply_overrides.py"])
        run_step([python, "scripts/normalize_records.py"])
        # Dedupe can restore records from seen.json. Re-run the same public
        # discovery cleanup used by GitHub Actions after that restore point.
        run_step([python, "scripts/clean_historical_working_papers.py"])
        run_step([python, "scripts/clean_nonpaper_records.py"])
        run_step([python, "scripts/clean_rss_backfill.py"])
        run_step([python, "scripts/remove_seen_backflow.py"])
        run_step([python, "scripts/enrich_china_relevance.py", "--all"])
        run_step([python, "scripts/product_audit.py"])
        run_step([python, "scripts/audit_recent72_coverage.py"])
        run_step([python, "scripts/audit_formal_journal_coverage.py"])
        run_step([python, "scripts/release_gate.py"])
        finished_at = now()
        record_source("local-cnki-run", ok=True, count=1, message=f"finished; log={log_path_for_status()}")
        record_workflow_run(
            {
                "mode": "light",
                "mode_label": "本地中文补充",
                "event": "local-cnki",
                "schedule": "",
                "run_id": "",
                "run_url": "",
                "date": today_str(),
                "finished_at": finished_at,
                "updated_at": finished_at,
            }
        )
        final_status_recorded = True
        run_step([python, "scripts/render_site.py"])
        run_step([python, "scripts/build_feed.py", "--site-url", "https://academic-door.github.io/econ-paper-monitor/"])
        run_step([python, "scripts/render_local_status.py"])
        run_step([python, "scripts/render_cnki_status.py"])

        if not args.no_push:
            record_source("local-cnki-publish", ok=False, count=0, message="pending")
            run_step(["git", "add", "data", "docs"])
            if git_has_staged_changes():
                run_step(["git", "commit", "-m", "Update local CNKI supplement"])
                run_step(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"], allow_failure=True)
                push_with_retries()
                record_source("local-cnki-publish", ok=True, count=1, message="published to origin/main")
            else:
                log("No generated changes to commit.")
                record_source("local-cnki-publish", ok=True, count=0, message="no generated changes")

        log("Local CNKI update finished successfully.")
    except Exception as exc:  # noqa: BLE001
        if not final_status_recorded:
            record_source("local-cnki-run", ok=False, count=0, message=f"{type(exc).__name__}: {exc}; log={log_path_for_status()}")
        log(f"FAILED: {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
