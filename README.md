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

Run once manually without pushing:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_cnki_update.ps1 -NoPush
```

Install a silent Windows scheduled task at 00:10, 06:10, 12:10 and 18:10 local
time (set the machine timezone to Beijing time if those should be Beijing times):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_local_cnki_task.ps1
```

The scheduled task uses `-WindowStyle Hidden`. Logs and local-only dashboards are
written under:

- `local_admin\logs\local-cnki-update.log`
- `local_admin\logs\local-cnki-scheduled-task.log`
- `local_admin\status.html`
- `local_admin\cnki_status.html`

If Windows Credential Manager is unavailable to a non-interactive scheduled
task, provide a repository-scoped fine-grained GitHub token through the user
environment variable `GITHUB_PUBLISH_TOKEN`. The runner passes it through an
in-memory Git header and never writes it to the remote URL or task log.

The local runner prunes temporary runtime files older than 14 days and CNKI raw
cache files older than 60 days. The main log is automatically trimmed after it
exceeds 2 MB.

## Formal Source Health

Each scheduled run audits every journal in `data/journals.yml`. The internal
report `data/source_health.json` distinguishes healthy dual-path coverage,
degraded single-path coverage, stale checks, and unavailable journals. A run
stops before publishing when a formal journal has no usable RSS or Crossref
path; a publisher block is acceptable only when another path remains usable.

The anonymous presence Worker is deployed separately from paper monitoring. Its
endpoint is smoke-tested by `.github/workflows/verify-presence.yml`, so a
Cloudflare deployment failure cannot be mistaken for a paper-monitor failure.
