# 如何新增监测期刊

新增期刊主要改 `data/journals.yml`。

## 最小字段

```yaml
  - id: "journal-slug"
    title: "Journal Full Name"
    short_name: "JFN"
    aliases:
      - "JFN"
    chinese_name: "中文名"
    fields:
      - "general"
    public_group: "综合"
    priority_private: ""
    issn: "0000-0000"
    publisher: "Publisher Name"
    sources:
      - type: crossref
        issn: "0000-0000"
```

## 推荐流程

1. 在 `data/journals.yml` 末尾新增一条期刊。
2. 尽量填写 ISSN；如果没有 ISSN，Crossref 抓取通常无法稳定工作。
3. 如果出版社提供 RSS，可以在 `sources` 中再加：

```yaml
      - type: rss
        url: "https://example.com/rss"
```

4. 本地运行：

```powershell
python scripts/enrich_journals.py
python scripts/fetch_crossref.py --days 14 --rows 20
python scripts/dedupe.py
python scripts/render_site.py
```

5. 确认 `docs/` 页面正常后提交并推送。
