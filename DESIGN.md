# Design

## Design Read

Econ Papers Daily is a research-monitoring product. The interface should feel like a daily scholarly intelligence desk: dense enough for scanning, restrained enough to trust, and explicit about evidence.

## Visual System

### Color Tokens

- `--ink`: `#1f2328`, primary text
- `--muted`: `#667085`, secondary text
- `--line`: `#d9dee7`, dividers and quiet borders
- `--page`: `#f7f8fa`, page background
- `--panel`: `#ffffff`, content panels
- `--blue`: `#155da9`, links, focus, active state
- `--blue-soft`: `#e8f1fb`, source and journal chips
- `--red`: `#c62828`, China-related emphasis only
- `--red-soft`: `#fdeaea`, China-related chip background
- `--yellow`: `#8a6100`, needs-attention date state
- `--yellow-soft`: `#fff4d6`, needs-attention date chip background
- `--green`: `#2f6f4e`, high-confidence positive state
- `--green-soft`: `#e7f4eb`, high-confidence chip background

Use one primary accent, blue, plus one semantic emphasis, red for China-related records. Avoid gradients, glass effects, heavy shadows, and decorative color.

### Typography

Use the system UI stack for all public UI:

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "Noto Sans SC", sans-serif;
```

Use tabular numeric rendering for dates, counts, and DOI-like identifiers:

```css
font-variant-numeric: tabular-nums;
```

Avoid display fonts in data lists. The product's quality comes from hierarchy and labels, not decorative typography.

### Layout

- Public pages use a stable app shell: left navigation plus a main content area.
- Homepage has two primary sections: TOP journal articles and working papers.
- Related pages keep the same article-card vocabulary.
- Avoid nested cards. Use panels for major areas and rows for records.
- Use 8px radius for panels and records. Pills are allowed only for small tags.

## Information Architecture

Public navigation:

- Today
- China-related
- Full-site search
- Archive
- Monitored journals
- Working paper sources
- RSS

Do not include backend status, quality audit, beta labels, or internal diagnostics in public navigation.

## Record Card

Each record card must prioritize:

1. First monitored date
2. English title
3. Chinese title, when available
4. Authors
5. Journal or source
6. Official date label and date
7. Evidence source
8. DOI or article link
9. Topic tags
10. China-related tag, when applicable

Date labels:

- `First monitored`: monitor discovery date in Beijing time
- `Official online`: publisher online date
- `Official published`: publisher publication date
- `Accepted`: accepted date
- `Issue date`: volume/issue date, never treated as online date
- `Official date pending`: no reliable official date yet

Public copy should use Chinese labels:

- `首次监测`
- `官方在线`
- `官方发布`
- `接受日期`
- `卷期日期`
- `官方日期待补`
- `来源：出版社网页 / RSS / Crossref / 本地中文补充 / 聚合源`

## States

- China-related: red chip, fixed wording `与中国相关`
- Official date pending: yellow chip, fixed wording `官方日期待补`
- Publisher or RSS evidence: blue-soft chip
- High-confidence publisher/PDF evidence: green-soft chip

## Public Copy Rules

- Use plain Chinese labels.
- Avoid internal phrases: `后台`, `质量抽检`, `Beta`, `失败`, `人工确认`, `待核`.
- If a source is experimental, say `来源说明` or hide the source from public prominence.
- Keep public explanations short; detailed diagnostics belong in admin pages.

## Backend Pages

Backend pages may show operational detail:

- Fast monitor and full monitor status
- Source success rates
- Date pending counts
- China-related quality checks
- CNKI RSS / local supplement / GitHub source counts
- Publisher detail failures

Backend pages should not be linked from public navigation unless access protection is added.
