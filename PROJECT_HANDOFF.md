# econ-paper-monitor 项目交接说明

更新时间：2026-06-14

## 1. 项目目标

建立一个面向经济学研究者和读者的“经济学论文雷达”：根据一组重点经济学期刊和 working paper / preprint 来源，自动追踪每天或更高频更新的最新论文，生成公开网页、RSS/订阅源和历史归档。

核心目标不是 Zotero 式文献管理，而是“最快发现新增论文”：

- 追踪期刊 latest articles / online first / articles in press / issue ahead of print。
- 追踪 working papers / preprints，例如 NBER、CEPR、SSRN、RePEc、arXiv econ 等。
- 自动去重，避免同一 DOI 或同一论文重复推送。
- 每天或每小时自动更新网页。
- 支持后续邮件、RSS、Telegram、企业微信等推送。
- 支持中文标题/摘要翻译，但不能让模型编造摘要。

## 2. 用户偏好与重要决策

- 公开页面不要按 S/A/B 优先级分组，避免显得在公开评价或歧视期刊。
- 期刊优先级可以保留在本地私有配置中，只用于抓取频率、排序权重、翻译优先级或个人推送。
- 公开页面使用中性分类：按领域、期刊、来源类型、更新时间展示。
- 公开文案避免“顶刊/普通期刊”这类分级措辞，可使用“关注期刊”“核心关注”“扩展关注”等中性表达。
- Zotero RSS 可以作为阅读/收纳入口，但不作为主要监控入口，因为用户不想每天手动逐个浏览 Zotero feed。
- 项目应独立于旧的 Project Test，作为正式 repo 维护。

## 3. 已有素材

用户已有重点期刊清单：

D:\Desktop\journal_monitor_list.md

该文件包含：

- 期刊英文名
- 常用缩写
- 中文名
- 优先级
- 领域/分类

注意：读取时应使用 UTF-8 编码。之前 PowerShell 默认编码读取出现乱码，但 `Get-Content -Encoding UTF8` 可以正常显示。

下一步应把该 Markdown 转换为机器可读配置，例如：

```yaml
journals:
  - title: Quarterly Journal of Economics
    short_name: QJE
    chinese_name: 经济学季刊
    fields: [general]
    public_group: 综合
    priority_private: S
    issn: "0033-5533"
    publisher: Oxford University Press
    sources:
      - type: rss
        url: null
      - type: crossref
        issn: "0033-5533"
```

公开仓库中建议保留 `data/journals.yml`；如果含敏感/个人排序，可另建 `data/journals_private.yml` 并加入 `.gitignore`。

## 4. 公开检索结论

已经对 GitHub/Gitee/公开搜索做过初步检索，关键词包括：

- economics journal Crossref alert
- economics paper monitor
- NBER RePEc SSRN alert
- journal monitor Crossref RSS
- academic paper alert Crossref
- 经济学 期刊 论文 自动更新
- 论文雷达 经济学
- NBER 自动更新 周报

结论：没有发现成熟的、专门面向“经济学核心期刊每日最新论文 + online first + working papers/preprints + 公开网页 + 历史归档 + 中文辅助阅读”的开源项目。

找到的相邻项目：

- EconGeo/journal-digest: https://github.com/EconGeo/journal-digest
  - 描述：Automated weekly monitor for academic journals.
  - 技术：RSS + CrossRef fetch + Zotero dedup + Claude Code synthesis.
  - 原始方向：real estate and finance journals.
  - 判断：相邻项目，可参考技术路线，但不是公开经济学每日更新站。

可复用组件/相邻工具：

- RSSHub: https://github.com/DIYgod/RSSHub
  - 通用 RSS 生成器，可给没有 RSS 的网站补源。
- arxiv-sanity-preserver: https://github.com/karpathy/arxiv-sanity-preserver
  - 偏 arXiv 浏览/筛选/推荐。
- paperscraper: https://github.com/jannisborn/paperscraper
  - 偏 arXiv、bioRxiv、medRxiv、chemRxiv 等预印本元数据抓取。

## 5. 推荐项目结构

```text
econ-paper-monitor/
  data/
    journals.yml              # 公开期刊清单，不展示分级措辞
    journals_private.yml      # 本地私有优先级，可不提交 GitHub
    sources.yml               # NBER/CEPR/SSRN/RePEc/arXiv 等源配置
    seen.json                 # 已发现 DOI/URL，避免重复推送
  scripts/
    parse_journal_md.py       # 将 journal_monitor_list.md 转成 journals.yml
    fetch_rss.py              # 抓出版社 RSS/latest articles
    fetch_crossref.py         # Crossref 按 ISSN/DOI 补漏
    fetch_preprints.py        # 抓 NBER/CEPR/SSRN/RePEc/arXiv 等
    enrich_metadata.py        # 补作者、DOI、abstract、published date
    translate.py              # 中文标题/摘要翻译
    render_site.py            # 生成 docs 静态网页
    build_feed.py             # 生成总 RSS/Atom
  docs/
    index.html                # 首页：今日更新 + 最近更新
    daily/                    # 每日归档页面
    journals/                 # 按期刊归档
    fields/                   # 按领域归档
    archive/                  # 历史日历/月份页
    feed.xml                  # 总订阅源
  .github/workflows/
    update.yml                # 定时更新
  README.md
  .gitignore
```

## 6. 抓取优先级

为了尽量快，不要只靠 Crossref：

1. 出版社 RSS / Latest Articles / Articles in Press / Online First
   - 通常最快。
   - 优先抓正式上线和 online first。
2. Crossref 按 ISSN 查询
   - 统一补漏。
   - 适合 DOI、标题、作者、日期元数据补全。
3. OpenAlex / Semantic Scholar
   - 作为补充元数据和开放链接来源。
4. Working paper / preprint 来源
   - NBER、CEPR、SSRN、RePEc、arXiv econ、SocArXiv 等。
5. Zotero
   - 作为保存和阅读出口，不作为主监控器。

## 7. 页面设计

首页 `/`：

- 今日新增论文。
- 最近 7 天更新。
- 按更新时间倒序。
- 可筛选：期刊、领域、来源类型、是否有中文摘要。
- 不公开展示 S/A/B 分级。

每日页 `/daily/YYYY-MM-DD/`：

- 某一天全部新增论文。
- 支持按期刊/领域过滤。

期刊页 `/journals/qje/`：

- 某期刊历史新增论文。

领域页 `/fields/labor/`：

- 某领域历史新增论文。

归档页 `/archive/`：

- 按日期或月份浏览历史记录。

订阅：

- `/feed.xml`：总 RSS/Atom。
- 后续可增加按领域或按期刊的 feed。

## 8. 每篇论文建议字段

```yaml
id: doi-or-url-hash
title: original English title
title_zh: Chinese translated title, optional
abstract: original abstract, optional
abstract_zh: Chinese translated abstract, optional
authors: []
journal: Quarterly Journal of Economics
journal_short: QJE
source_type: journal | working_paper | preprint
publisher: Oxford University Press
published_online: 2026-06-14
detected_at: 2026-06-14T08:30:00+08:00
doi: null
url: https://...
pdf_url: null
fields: []
ai_tags: []
translation_status: translated | missing_abstract | skipped | failed
```

重要原则：

- 翻译只能基于真实标题/摘要。
- 如果没有 abstract，显示“暂无摘要”，不要让模型编造摘要。
- AI 可以做主题标签，但应标明为 AI tags。

## 9. 自动化建议

MVP 阶段：

- GitHub Actions 每 1-3 小时运行一次。
- 生成静态页面到 `docs/`。
- GitHub Pages 发布。

注意：GitHub Actions 的 schedule 支持 cron，但可能有延迟；极致时效阶段可以迁移到 VPS、Cloudflare Workers 或自建定时器。

MVP 流程：

```text
load journals.yml
fetch RSS feeds
fetch Crossref by ISSN
fetch preprint sources
dedupe by DOI/title/url
compare with seen.json
translate title/abstract if configured
write daily JSON/Markdown
render docs/index.html and archives
update feed.xml
commit generated files
```

## 10. 第一阶段任务清单

1. 初始化项目结构。
2. 从 `D:\Desktop\journal_monitor_list.md` 解析期刊表。
3. 生成 `data/journals.yml`。
4. 手动或半自动补充第一批 ISSN 和出版社。
5. 写 Crossref fetcher 原型。
6. 写 RSS fetcher 原型。
7. 写去重逻辑 `seen.json`。
8. 生成 `docs/index.html` 静态首页。
9. 生成 `/daily/YYYY-MM-DD/` 历史页。
10. 配 GitHub Actions 定时更新。
11. 配 GitHub Pages。
12. 后续再加翻译和推送。

## 11. 建议启动提示词

新项目对话中可以直接使用：

```text
我们要开发 econ-paper-monitor。请先阅读 PROJECT_HANDOFF.md，并据此初始化项目结构。目标是根据 D:\Desktop\journal_monitor_list.md 里的经济学期刊清单，自动追踪最新 online first/latest articles/working papers/preprints，生成公开网页、RSS 和历史归档。公开页面不要显示 S/A/B 期刊分级，分级只作为本地私有排序或抓取权重。第一步请创建项目骨架，并把 md 清单解析成 data/journals.yml。
```
