# econ-paper-monitor

An economics paper monitor for tracking latest journal articles, working papers,
preprints, public archive pages, and feeds.

The public site should use neutral source, field, journal, and update-time
grouping. Private priority labels may be kept in local data for fetch cadence
and personal ranking, but should not be shown on public pages.

## MVP Pipeline

```powershell
python .\scripts\enrich_journals.py --rows 3 --timeout 8 --sleep 0.05
python .\scripts\fetch_rss.py
python .\scripts\fetch_crossref.py --days 14 --rows 20 --sleep 0.2
python .\scripts\dedupe.py
python .\scripts\render_site.py
python .\scripts\build_feed.py
```

Generated public files live under `docs/`. Daily canonical records live under
`data/daily/`, and `data/seen.json` stores dedupe state for scheduled runs.

Review remaining uncertain journal matches in `data/journal_match_review.yml`.

## Local CNKI RSS Supplement

GitHub-hosted Actions may be blocked by CNKI RSS (`HTTP 418`). Keep international
sources on GitHub Actions, and run the CNKI RSS supplement on a local Windows
machine or a domestic self-hosted runner. The installed task runs four times
per day and publishes only generated data and pages.

The scheduled task uses a dedicated checkout under
`%LOCALAPPDATA%\AcademicDoor\econ-paper-monitor-cnki-runner`. It must not use a
development worktree: the runner always follows the public `origin/main`, while
the main development checkout may contain unpublished commits.

> Note (Phase 0): the ACTIVE registered task is `Econ Papers Daily - Local Supplement`, which runs `<checkout>\local_admin\runner\run_local_supplements.ps1` (see `Runtime Ownership & Path Dependency (Phase 0)`). The `%LOCALAPPDATA%` dedicated runner documented here is a separate/alternate install.

Run once manually without pushing from the dedicated runner:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_cnki_update.ps1 -NoPush
```

Install or refresh a silent Windows scheduled task at 00:10, 06:10, 12:10 and
18:10 local time (set the machine timezone to Beijing time if those should be
Beijing times). The installer creates and updates the dedicated runner first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_local_cnki_task.ps1
```

For a custom runner location, pass `-RunnerPath` explicitly. Never point it at
the development checkout unless that checkout is intentionally kept identical
to the public `main` branch.

The local supplement writes a durable owner status to
`data/local_cnki_status.json`. The public watchdog checks that status and
fails when the last successful six-source run is older than 30 hours:

```powershell
python .\scripts\audit_local_cnki_status.py --max-age-hours 30
```

This keeps the local CNKI network requirement separate from the GitHub-hosted
publisher monitor while making a stopped local task visible to the release
process.

The scheduled task uses `-WindowStyle Hidden`. Logs and local-only dashboards are
written under:

- `local_admin\logs\local-cnki-update.log`
- `local_admin\logs\local-cnki-scheduled-task.log`
- `local_admin\status.html`
- `local_admin\cnki_status.html`

## Metadata Retry Queue

The full monitor writes `data/metadata_retry_queue.json` after each quality
audit. It ranks recent records with missing abstracts, missing authors, or weak
date evidence for automatic retries and independent review. The queue is an
internal operational artifact: it never invents metadata and it is not shown
as a public navigation surface.

OpenAlex is configured as an independent recall source for journals whose
publisher pages are currently inaccessible to hosted runners. Recall records
are retained for audit and enrichment, but are explicitly excluded from the
public daily first-discovery archive until an authoritative source confirms
the online date.

If Windows Credential Manager is unavailable to a non-interactive scheduled
task, provide a repository-scoped fine-grained GitHub token through the user
environment variable `GITHUB_PUBLISH_TOKEN`. The runner passes it through an
in-memory Git header and never writes it to the remote URL or task log.

The local runner prunes temporary runtime files older than 14 days and CNKI raw
cache files older than 60 days. The main log is automatically trimmed after it
exceeds 2 MB.

## Formal Source Health

Each scheduled run audits every journal in `data/journals.yml`. The internal
report `data/source_health.json` distinguishes the release level (healthy,
degraded, stale, unavailable) from the acquisition coverage: official or
specialized, supplemental, Crossref-only, or unavailable. This makes a
Crossref fallback visible to maintainers without exposing transport errors on
the public homepage. A run stops before publishing when a formal journal has
no usable RSS, specialized, or Crossref path; a publisher block is acceptable
only when another path remains usable.

The anonymous presence Worker is deployed separately from paper monitoring. Its
endpoint is smoke-tested by `.github/workflows/verify-presence.yml`, so a
Cloudflare deployment failure cannot be mistaken for a paper-monitor failure.

## Coverage Debt And Release Checks

`data/source_health.json` contains an internal `coverage_debt` section. It lists
formal journals that currently rely only on Crossref or have one degraded
acquisition path, with the next action for the maintainer. These records are
not shown as transport errors on the public site. The release gate blocks only
when a formal journal is unavailable or its source audit is stale; Crossref-only
coverage remains usable but is recorded as an explicit improvement task.

The normal verification sequence is:

```powershell
python -m pytest -q
python .\scripts\audit_source_health.py
python .\scripts\audit_recent72_coverage.py
python .\scripts\audit_formal_journal_coverage.py
python .\scripts\product_audit.py
python .\scripts\release_gate.py
python .\scripts\monitor_health.py
```

`data/monitor_health.json` is the consolidated internal handoff for the main
workflow, the local CNKI task, and independent source audits. Its `failures`
list is release-blocking; its `warnings` list is tracked improvement debt.

For the local Chinese supplement, verify the Windows task itself rather than
inferring health from the public page: confirm the task is `Ready`, its last
result is `0`, and its next run is one of the four configured times. A successful
CNKI fetch is published only after all six configured feeds succeed.

## Runtime Ownership & Path Dependency (Phase 0)

- **Active Windows scheduled task**: `Econ Papers Daily - Local Supplement` (TaskPath `\`, State `Ready`). It runs `powershell.exe ... -File "<canonical-checkout>\local_admin\runner\run_local_supplements.ps1"` with `WorkingDirectory` = that `local_admin\runner` folder (the launcher file is gitignored/local).
- **Launcher** (`<canonical-checkout>\local_admin\runner\run_local_supplements.ps1`, local/gitignored) runs CNKI (`scripts\local_cnki_update.py`) and UChicago (`scripts\fetch_uchicago_local.py`) inside `C:\Users\Administrator\Work\econ-paper-monitor\runner-worktree` (a hardcoded local checkout; verified: branch `main`, remote = `academic-door/econ-paper-monitor.git`, clean). It fetches `origin/main` -> resets `--hard` -> runs both supplements -> commits/pushes `data/raw/uchicago-local` + `data/local_uchicago_status.json` to `origin/main` (UChicago), then dispatches `watchdog.yml` via `gh` resolved from `PATH`/`GH_EXE` (the fixed `D:\Software\GitHub CLI\gh.exe` dependency was removed; original preserved at `local_admin\runner\run_local_supplements.ps1.bak.20260830`).
- **CURRENT_CHECKOUT_PATH_PINNED**: the canonical `E:` checkout is pinned — the active task entrypoint lives in its `local_admin\runner` folder, and the launcher hardcodes the `C:\...\runner-worktree`. **Do NOT move the canonical `E:` checkout before this pinned runtime is deliberately migrated.**
- **Watchdog** itself runs on GitHub Actions (`watchdog.yml`: `workflow_dispatch` + cron `*/15`); the local `scripts/trigger_watchdog.{cmd,ps1}` are optional manual triggers, path-hardened (repo-root + PATH `gh`), and are NOT used by the active task.
- The documented `%LOCALAPPDATA%\AcademicDoor\econ-paper-monitor-cnki-runner` (see "Local CNKI RSS Supplement") is a separate/alternate install; the ACTIVE registered task is the `run_local_supplements.ps1` one above.

> Execution-env note: this sandbox runs as a non-Administrator user and cannot enumerate the real Task Scheduler registrations; the facts above were confirmed from the real Windows account (`Get-ScheduledTask`/`schtasks`) and by reading the gitignored launcher.