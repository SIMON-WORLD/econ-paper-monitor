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
