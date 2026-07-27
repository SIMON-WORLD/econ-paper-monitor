# Claude Collaboration Guide

## Project Boundary

This repository powers **每日之门**, the economics paper-monitoring product
under the Academic Door brand. The brand homepage and this product are separate
surfaces. Keep changes scoped to this repository unless a task explicitly says
otherwise.

Claude may also inspect the companion repository
`academic-door/nber-working-papers-cn` when access is enabled. Cross-repository
findings should improve this product's monitoring logic, not expand its journal
scope without an explicit product decision.

## Collaboration Roles

- Claude may audit data sources, coverage, freshness, duplicates, date evidence,
  and metadata quality. Small, low-risk fixes may be applied directly; major,
  cross-cutting, uncertain, or explicitly requested changes should be proposed
  in a focused PR with evidence.
- The main Codex line owns product direction, merge decisions, public wording,
  release verification, changes to the monitoring contract, and final delivery.
- A PR is advice and evidence, not an automatic product decision. Keep it small
  enough to review and avoid unrelated generated-data churn.

## Non-negotiable Product Rules

1. The product goal is first discovery of new papers, not historical backfill.
2. Never fabricate authors, abstracts, translations, online dates, or China
   relevance. Mark missing evidence internally and preserve the original field.
3. Keep journal articles, working papers, commentary, and aggregators distinct.
4. Deduplicate by DOI first, then stable URL/title identity. Historical records
   remain searchable even when excluded from today's first-discovery stream.
5. Publisher dates, Crossref dates, issue dates, RSS dates, and detection dates
   must remain separate fields with their evidence source.
6. Public pages should remain calm and lightweight. Do not expose raw transport
   errors, stack traces, internal audit labels, or source credentials in public
   navigation. Detailed source health belongs in admin artifacts.
7. Prefer a reliable existing source and a small fallback over a large new
   dependency or a broad scraper that increases failure surface.

## PR Expectations

Every source-related PR should state:

- which configured sources it covers;
- observed official date and first-detection evidence;
- duplicate/backfill behavior;
- what happens when the source is blocked or empty;
- focused verification results and remaining limitations.

Do not expand the monitored journal scope merely because another site has more
records. Scope changes require an explicit product decision.
