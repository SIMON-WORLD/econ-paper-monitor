# Architecture Ownership

## Production boundary

The paper monitor has two independent **production workflow lines** inside the Daily Door subsystem:

1. The **data monitoring line** owns source fetching, cleaning, deduplication, first-discovery daily archives, audits, ledgers, health state and commits under `data/**`.
2. The **display line** owns static page generation, feeds, browser validation and commits under `docs/**`.

These are workflow responsibilities, not separate product authorities. Repo-local product/engineering authority remains with **② 每日之门 | 总控** under current Academic Door Parent/Child governance.

The data line must never call a display generator or stage `docs/**`. The display line must never fetch sources or modify `data/**`.

## Ownership table

| Path | Owner | Production rule |
| --- | --- | --- |
| `data/raw/**` | Data line | Candidate source output |
| `data/daily/**` | Data line | Canonical Beijing-date **first-discovery** daily archive; never reconstructed from publication/archive dates |
| `data/seen.json` | Data line | Canonical historical ledger; search/list surfaces may restore records absent from a daily archive, but must not manufacture a daily bucket |
| `data/*audit*.json`, source-health artifacts and ledgers | Data line | Quality, coverage and provenance facts |
| `data/local_cnki_status.json` / `data/local_uchicago_status.json` | Local supplement runtime → data line | Durable publication/freshness evidence from the Windows local runner |
| `docs/index.html` | `scripts/build_daily_vnext.py` | Sole homepage writer |
| `scripts/templates/daily_vnext.html` | Display line | Shared production template for root and Daily vNext |
| `docs/daily-vnext/index.html` | Display line | Same generator/template/data contract as root |
| `docs/classic/**` | Classic surface | Preserved compatibility surface |
| `docs/paper.html` and `docs/paper-data/**` | `scripts/render_site.py` | Generated detail shell and canonical detail payloads |
| Other `docs/**` | Display line | Secondary pages and feed outputs; internal admin/quality diagnostics are not public navigation |

## Production call chain

```text
acquisition / local supplement
        ↓
data/** commit on GitHub main
        ↓
render-site workflow
        ↓
docs/** commit
        ↓
GitHub Pages
```

The display workflow is triggered by data changes; generated `docs/**` commits do not recursively invoke the data acquisition line. Main-writer concurrency protects publication ordering.

## First-discovery and date contract

Daily Door is a **first-discovery product**. `firstSeenAt` / first discovery defines the timeline and Beijing daily buckets.

Publisher online dates, publication dates, accepted dates, issue dates, RSS timestamps, Crossref dates and detection timestamps are separate evidence. They may enrich a record, but publication/archive dates must never back-write `firstSeenAt` or manufacture historical Daily Door archives.

## Source-health contract

Source health and coverage are data-line facts, not marketing claims.

Current health vocabulary includes:

- `healthy` — current usable evidence satisfies the health model;
- `supplemental-closed` — no unexplained active incident, but coverage is intentionally closed with supplemental/recall paths rather than a fully independent official path;
- `degraded` — an active or material path failure/redundancy problem remains;
- `stale` — evidence is older than the accepted freshness window;
- `unavailable` — no usable production path is currently available.

Coverage fields such as `official_or_specialized` and `supplemental` are distinct from the health label. Crossref/OpenAlex recall can keep discovery useful, but they are not evidence that independent official coverage exists. Failed official/specialized paths remain auditable even when another path keeps the overall journal healthy.

## Local supplement runtime

CNKI and UChicago supplements are produced by the Windows local runtime because some sources are not reliably reachable from GitHub-hosted CI.

Current topology:

```text
E: pinned project / runtime-adjacent inspection-control path
        ↓ launcher + local_admin/logs
C: production runner checkout (production-only)
        ↓ CNKI + UChicago local acquisition
GitHub main data/** publication
        ↓ normal render / Pages pipeline
```

E: remains pinned; C: is not a human development workspace. Mutation-heavy development, when local execution is required, uses disposable non-sync task clones outside the production runner.

`scripts/audit_local_supplement_runtime.py` is the read-only operator observer for scheduler / launcher / C-runner / source-fetch / Git-publication / watchdog evidence. It diagnoses and reports bounded recovery guidance; it does not relocate or mutate the runtime.

## Refresh and quality contract

The service is near-real-time, not a continuous stream. Scheduled GitHub monitoring and the independent Windows local supplement publish bounded batches. Release/monitor gates treat recent coverage, duplicates, metadata completeness, source health and local-runtime freshness as operational evidence.

Public discovery pages read canonical Daily Door data. Historical search may restore ledger records, but completeness of journal **issues** is not inferred from Daily discovery counts; authoritative issue identity/completeness belongs to the Journal System.

## Legacy and non-production entries

Local/admin scripts, historical worktrees and archived evidence may remain for operations or audit. They are not Pages deployment authorities and must not be treated as current-code SSOT. GitHub `main` is the current code authority.

## Failure policy

- Missing or malformed canonical input fails the display workflow before a generated site commit.
- A valid empty daily archive renders an explicit empty state.
- A rendering failure leaves the previous committed Pages output unchanged.
- Classic remains a preserved compatibility surface where still referenced by production checks.
- Source/runtime degradation must be reported as evidence; do not fabricate health or metadata to keep a gate green.
