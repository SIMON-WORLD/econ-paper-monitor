# 来源覆盖说明 / Source Coverage Notes

> 本文档记录某些期刊在"官方/专门采集路径"上的**预期覆盖债务**，用于审计与人工核对。
> 这里只做证据化分类，**不**改写 `data/journals.yml` 的 `sources` 语义，**不**把 source-health 伪升为
> `healthy`，也**不**改 `firstSeenAt` / 日桶 / 日期 / dedupe 语义。

---

## 数量经济技术经济研究（journal-edcb877d78）

**状态：`single_path_degraded`（预期覆盖债务，非解析器 / 运行时事故）。**

### 根因

- 本刊唯一官方站点 `https://www.jqte.net/sljjjsjjyj/ch/index.aspx`（技术支持：**北京勤云科技发展有限公司**）
  在 **GitHub-hosted CI（`ubuntu-latest`）上无法可靠访问**。
- 生产 `cn-journals` 采集路径对本刊在 CI 上返回
  **`HTTPError: HTTP Error 502: Bad Gateway`**，记录于
  `data/source_health.json`：`failed_paths=[{path: cn-journals, message: "HTTPError: HTTP Error 502: Bad Gateway"}]`，
  `last_checked_at=2026-09-06T12:52:12Z`。
- 该平台与 CNKI 属同一类勤云系站点；`update.yml` 已明确注明"GitHub runner IP 会被间歇性拒绝 (HTTP 418)"。
  因此本刊官方站在 CI 上是**结构性不可达/不可用**，不是本地抓取或解析器缺陷。
- 官方站**无 RSS/Atom feed**，页面**无 DOI**；文章信息仅由
  `reader/issue_list.aspx`（当期目录：`<a href="view_abstract.aspx?file_no=<id>&flag=1">标题</a>` + 稳定 `file_no`）
  与 `reader/view_abstract.aspx?file_no=<id>&flag=1`（作者、中英文摘要、关键词、`[J].数量经济技术经济研究,年,(期):页`）暴露。
  即便可达，也需要一个 bespoke TOC + abstract 解析器，并需在 GitHub-hosted CI 上验证。

### 本机可达性（仅住宅/代理网络，不等于 CI 可用）

- 本机（住宅/代理网络）访问均 200：`index.aspx`、`reader/issue_list.aspx`（当期目录）、
  `reader/view_abstract.aspx?file_no=<id>&flag=1`（完整文章记录）。
- 可解析字段：标题、`file_no`、作者（含单位）、中英文摘要、关键词、年/期/页码。
- **这只是本机/住宅网络可达；真实 CI 证据为 502，不能作为生产独立路径的依据。**

### 结论 / 分类

- 官方 `jqte.net` 站**不能**作为生产独立采集路径（GitHub-hosted CI 返回 502）。
- 本刊当前 `single_path_degraded` 分类为**预期覆盖债务**，非解析器/运行时事故。
- 未做 source-health 健康级"硬升/伪造"；未改 `data/journals.yml` 的 `sources` 语义；未改任何日期语义。
- 当前路径：`crossref`（限流时不可用，正常时可靠）+ 本地 `cnki-rss`（仅本机 supplement）；
  `openalex-recall` 为补充路径。release gate 与 monitor health 当前均为 `ok=true`（非阻塞）。

### 后续选项（供 ② Brain 决定）

- 若要恢复真正独立的路径，可考虑：
  - 为本刊增加**本机**官方站 local supplement runner（与现有 CNKI 本地 supplement 同类，仅本机，需在 CI 之外运行）；
  - 或改用其它官方/索引来源（如国家哲学社会科学文献中心）并先做 CI 可达性验证；
  - 在此之前，保持本文档记录，**不伪造健康**。
