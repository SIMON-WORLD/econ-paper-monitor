# Claude Collaboration Guide

## Project Boundary

This repository powers **每日之门**, the economics paper-monitoring product under the Academic Door brand. Keep changes scoped to this repository unless the current Controller explicitly authorizes cross-repository work.

Cross-repository inspection may be useful for evidence or compatibility checks, but it does not transfer product scope or ownership. Daily Door monitoring-scope decisions remain with **② 每日之门 | 总控**; journal issue identity / canonical issue completeness remain owned by the Journal System under the current Academic Door governance.

## Collaboration Roles

- **② 每日之门 | 总控** is the repo-local product/engineering authority for Daily Door. It owns product direction, monitoring-contract decisions, acceptance, merge/release decisions and final delivery within this subsystem.
- Claude, Codex and other execution agents are **Executors / capabilities**, not product authorities. Within an authorized task they may inspect, diagnose, edit, test, debug, retry, commit and open/update PRs.
- A PR, agent report or recommendation is implementation evidence, not an automatic product decision. The Controller independently verifies GitHub/CI/production evidence before accepting material outcomes.
- Current Parent governance is inherited from `academic-door/academic-door-main-control` current `main`. Routine compatible implementation is autonomous under②; material semantics, ownership/cross-subsystem changes, shared capability, breaking contracts or major migration/runtime relocation cross the Parent boundary.

## Non-negotiable Product Rules

1. The product goal is **first discovery of new papers**, not a publication-date or historical-backfill archive.
2. Never fabricate authors, abstracts, translations, online dates, China relevance or other metadata. Preserve missing/uncertain evidence explicitly.
3. Keep journal articles, working papers, commentary and aggregators distinct.
4. Deduplicate by DOI first, then stable URL/title identity. Historical records may remain searchable even when absent from today's first-discovery stream.
5. `firstSeenAt` / first discovery is the Daily Door timeline. Publisher dates, Crossref dates, issue dates, RSS dates and detection timestamps remain separate evidence fields and must never back-write first discovery.
6. Public pages should remain calm and lightweight. Do not expose raw transport errors, stack traces, internal audit labels or source credentials in public navigation. Detailed source health belongs in data/admin artifacts.
7. Prefer a reliable existing source and a small fallback over a broad scraper or dependency that increases failure surface.
8. Source-health labels must reflect real evidence. Never force `healthy` to hide a blocked/failed official path, and do not treat supplemental/recall coverage as equivalent to independent official coverage.

## Execution Routing

Use the current Parent execution policy: **Evidence first → Decision → Capability Routing → Execute → Verify**.

- Prefer ChatGPT Web / GitHub / Actions when the current session can reliably close the bounded outcome end-to-end.
- Use Codex when the task materially needs local machine/runtime access, sustained shell/debug context, large mutation loops or other capability not reliably exposed in the current ChatGPT session.
- When Codex is used, delegate an outcome-sized scope rather than microtasks; GitHub-visible facts should still be independently verified by the Controller.

## PR Expectations

Every source-related PR should state:

- which configured sources it covers;
- observed official-date and first-detection evidence;
- duplicate/backfill behavior;
- what happens when the source is blocked or empty;
- focused verification results and remaining limitations.

Do not expand monitored journal scope merely because another site has more records. Scope changes require a Daily Door product decision; issue-history/completeness ownership remains separate.
