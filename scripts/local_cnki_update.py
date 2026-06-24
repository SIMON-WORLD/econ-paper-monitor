"""Run the local-only Chinese journal supplement pipeline.

This entrypoint is intended for a Windows scheduled task. It keeps CNKI RSS on
the user's local network, then publishes only normalized site data to GitHub.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common import ROOT, today_str
from status import record_source


LOG_DIR = ROOT / "local_admin" / "logs"
LOG_PATH = LOG_DIR / "local-cnki-update.log"
RUNTIME_DIR = ROOT / "local_admin" / "runtime"


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")
    print(message)


def run_step(command: list[str], *, allow_failure: bool = False) -> int:
    log("$ " + " ".join(command))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
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

    python = sys.executable
    start = datetime.now().isoformat(timespec="seconds")
    log("=" * 72)
    log(f"Local CNKI update started at {start}")
    record_source("local-cnki-run", ok=False, count=0, message="running")

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
        run_step([python, "scripts/clean_cn_noise.py"])
        run_step([python, "scripts/apply_overrides.py"])
        run_step([python, "scripts/normalize_records.py"])
        run_step([python, "scripts/enrich_china_relevance.py", "--all"])
        run_step([python, "scripts/product_audit.py"])
        run_step([python, "scripts/render_site.py"])
        run_step([python, "scripts/build_feed.py", "--site-url", "https://simon-world.github.io/econ-paper-monitor/"])
        run_step([python, "scripts/render_local_status.py"])
        run_step([python, "scripts/render_cnki_status.py"])

        if not args.no_push:
            run_step(["git", "add", "data", "docs"])
            if git_has_staged_changes():
                run_step(["git", "commit", "-m", "Update local CNKI supplement"])
                run_step(["git", "pull", "--rebase", "-X", "theirs", "origin", "main"], allow_failure=True)
                run_step(["git", "push"])
            else:
                log("No generated changes to commit.")

        record_source("local-cnki-run", ok=True, count=1, message=f"finished; log={LOG_PATH}")
        log("Local CNKI update finished successfully.")
    except Exception as exc:  # noqa: BLE001
        record_source("local-cnki-run", ok=False, count=0, message=f"{type(exc).__name__}: {exc}; log={LOG_PATH}")
        log(f"FAILED: {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
