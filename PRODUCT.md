# Product

## Register

product

## Users

Econ Papers Daily serves economics researchers, graduate students, policy readers, and the Academic Portal editorial workflow. Users arrive with limited time and need to know what new papers appeared today, which ones relate to China, and whether the date shown is trustworthy enough for follow-up reading or public sharing.

## Product Purpose

The product tracks first discoveries of top economics journal articles and important economics working papers. Success means a user can quickly answer:

- What did the monitor first discover today?
- Which records are related to China?
- Is this a journal article or a working paper?
- What is the official online or publication date?
- Which source supports that date?

"Today" always means the monitor's first discovery date in Beijing time, not necessarily the publisher's official online date. Official online, published, accepted, and issue dates must be displayed separately when available.

## Brand Personality

Credible, restrained, and useful. The voice should feel like a calm research desk: specific labels, no promotional filler, no internal chatter, no vague system language.

## Anti-references

- Do not look like a generic SaaS landing page with oversized cards, decorative gradients, or self-promotional copy.
- Do not expose internal operations such as quality review, backend status, beta labels, failure logs, or manual audit pages in public navigation.
- Do not mix journal articles and working papers without clear labels.
- Do not call issue dates or Crossref fallback dates "online dates" unless the evidence supports it.
- Do not use verbose explanatory text on public pages when a short label can do the job.

## Design Principles

1. First discovery is the product's timeline.
2. Official dates are evidence, not decoration.
   - 日期证据分级：A=官方渠道明确 online/published 日期（出版社详情/API、官方 RSS 解析日期、CNKI 明确日期、AEA forthcoming、PDF）；B=官方渠道备选/推断日期；C=Crossref/OpenAlex 登记日期；D=卷期/期次日期；F=仅首次监测或未来官方日期未到（按首次监测展示）。数据层与展示层共用此口径。
3. China-related records should be visually unmistakable but not over-labeled.
4. Public pages stay calm and readable; backend pages carry operational detail.
5. Search and archive must preserve everything, even records excluded from today's first-discovery stream.

## Accessibility & Inclusion

The public site should meet WCAG AA contrast for text and controls. It should remain usable without JavaScript for reading core records, while JavaScript may enhance filtering. Motion should be limited to short state transitions and respect reduced-motion preferences.
