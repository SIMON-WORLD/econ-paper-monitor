# Architecture Ownership

## Production boundary

The paper monitor has two independent production lines:

1. The data monitoring line owns source fetching, cleaning, deduplication,
   canonical daily archives, audits, ledgers, health state, and commits under
   `data/**`.
2. The display line owns static page generation, feeds, browser validation, and
   commits under `docs/**`.

The data line must never call a display generator or stage `docs/**`. The
display line must never fetch sources or modify `data/**`.

## Ownership table

| Path | Owner | Production rule |
| --- | --- | --- |
| `data/raw/**` | Data line | Candidate source output |
| `data/daily/**` | Data line | Canonical Beijing-date daily archive for current and daily views |
| `data/seen.json` | Data line | Canonical historical ledger; secondary search/list pages may restore only records absent from a daily archive |
| `data/*audit*.json` and ledgers | Data line | Quality and provenance artifacts |
| `docs/index.html` | `scripts/build_daily_vnext.py` | Sole homepage writer |
| `docs/daily-vnext/**` | Display line | Same generator, template, and data as root |
| `docs/classic/**` | Classic surface | Preserved and never written by the legacy renderer |
| Other `docs/**` | Display line | Secondary pages and feed outputs |

## Production call chain

```text
data workflow -> data/** commit -> render-site workflow -> docs/** commit -> Pages
```

The display workflow is triggered by `data/**` changes only. Its generated
`docs/**` commit does not match that trigger, so the two workflows cannot form
a push loop. Both workflows share a main-writer concurrency group.

## Refresh and quality contract

The service is near-real-time, not a continuous stream: light monitoring wakes
every 15 minutes, while full monitoring runs four times per Beijing day. The
local CNKI supplement is an independent batch publisher and reports its last
successful timestamp under `data/local_cnki_status.json`.

Public discovery pages may display records only from `data/daily/**` and the
canonical `data/seen.json` ledger. The ledger can restore historical search
records but must never manufacture a daily archive. Source-health levels
(`healthy`, `degraded`, `stale`, `unavailable`) and metadata completeness
are data-line facts: degraded and Crossref-only coverage are explicit warnings,
never evidence of continuous or fully independent source coverage.

## Legacy and non-production entries

`scripts/render_site.py`, `scripts/build_feed.py`, and local/admin status
scripts remain available for secondary or local uses. They are not permitted
to write `docs/index.html` or to be called by the data monitoring workflow.

`.maturity` is the integration source for the current architecture until its
changes are merged. `.codex-*` worktrees and `.local-cnki-standalone` are
non-production copies and must not be used for Pages deployment.

## Failure policy

- Missing or malformed canonical input fails the display workflow before any
  generated site commit.
- A valid empty daily archive renders an explicit empty state.
- A rendering failure leaves the previous committed Pages output unchanged.
- Classic is checked as a preserved surface on every display validation.
