# Design

## Design Read

Econ Papers Daily / 每日之门 is a research-monitoring product centered on **first discovery**. The interface should feel like a daily scholarly intelligence desk: editorial, calm, dense enough for scanning, and explicit about evidence without exposing backend noise.

This document describes the current production direction; it is not a redesign brief.

## Current Visual System

The production homepage uses a warm paper/editorial system rather than the older cool-gray card shell.

Core tokens in the current template include approximately:

- paper background: `#f4f1ea`
- ink: `#202426`
- muted text: `#5f615e`
- line/divider: `#d8d3c9`
- soft surface: `#ece7dc`
- primary blue: `#1d5f83`
- deep blue: `#16445e`
- China-related red: `#a94236`
- light content surface: `#fbfaf7`

Typography deliberately mixes an editorial serif for headlines with a restrained sans-serif UI stack and monospace for dates/counts. Avoid gradients, glass effects, heavy shadows and decorative color. Motion should remain subtle and respect `prefers-reduced-motion`.

## Production Shell

Desktop uses a **sticky top header with horizontal navigation**, not a persistent left sidebar. On narrow screens the navigation collapses into a menu.

The homepage structure is:

1. Academic Door / Econ Papers Daily header
2. editorial hero with Beijing-date / discovery count context
3. compact overview statistics
4. first-discovery timeline
5. filters + search within the current timeline
6. footer / secondary links

The timeline is the primary reading surface. Do not reintroduce a split “TOP journals vs working papers” homepage as a documentation-only assumption; journal articles, working papers and commentary can coexist in the monitored discovery stream while retaining distinct source types.

## Information Architecture

Current primary navigation:

- 今日
- 最近72小时
- 中国研究
- 期刊
- 工作论文
- 搜索
- RSS

Archive/history and other secondary surfaces may be reachable from contextual/footer links, but they are not required to occupy the primary header.

Do not place backend status, quality audits, beta labels, raw source failures or internal diagnostics in public navigation.

## Timeline / Record Hierarchy

Each record should make the discovery chronology and paper identity easy to scan. Typical priority:

1. first-discovery time/date
2. source/journal context
3. title
4. translated/secondary title when available
5. authors
6. source/type/topic/China-related tags
7. detail/read link
8. expandable evidence/date detail when useful

The public timeline must never imply that publication date defines Daily Door chronology.

## Date Semantics

Public labels may include:

- `首次监测` — Daily Door first discovery in Beijing time
- `官方在线` — publisher online date
- `官方发布` — publisher publication date
- `接受日期` — accepted date
- `卷期日期` — issue/volume date
- `官方日期待补` — no reliable official date yet

These dates are evidence fields. `firstSeenAt` / first discovery remains the timeline anchor; archive/publication dates must not back-write it.

## Evidence and States

- China-related records may use the restrained red semantic accent.
- Publisher/RSS/official evidence should be visually distinct from recall/aggregator evidence without overwhelming the card.
- Missing official dates should be described plainly rather than fabricated.
- Source-health internals (`healthy`, `supplemental-closed`, degraded-path messages, transport errors) belong in operational artifacts, not record-card copy.

Use short Chinese labels in public UI. Avoid exposing stack traces, raw HTTP failures, credential names, internal audit statuses or implementation jargon.

## Interaction Rules

- Preserve keyboard focus states and minimum touch target sizing.
- Desktop hover may provide subtle affordances; core meaning cannot depend on hover.
- Mobile must preserve timeline chronology and readable metadata without horizontal overflow.
- Filters/search should not alter underlying first-discovery semantics.
- Empty states should be explicit and calm, not treated as errors when the daily bucket is validly empty.

## Public vs Operational Surfaces

Public pages are discovery/reading surfaces. Operational details belong in committed data artifacts, GitHub/Actions evidence or local operator tools.

Operational information may include:

- monitor/release health
- source-path success/failure and coverage debt
- metadata completeness
- CNKI/UChicago local supplement freshness
- scheduler/launcher/C-runner diagnostics
- publisher detail failures

These diagnostics should not be linked from public navigation unless a deliberate protected/admin product is introduced.

## Design Change Rule

Documentation must follow production reality; it must not silently redesign the product. Material navigation, product hierarchy or public semantic changes require a Daily Door product decision and normal implementation/verification. Routine responsive/accessibility refinements may evolve incrementally while preserving the first-discovery core.
