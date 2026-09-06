# 来源覆盖说明 / Source Coverage Notes

> 本文档记录某些期刊在“官方/专门采集路径”上的预期覆盖债务，用于审计与人工核对。
> 这里只做证据化分类，不改写 `data/journals.yml` 的 source 语义，不伪造 source-health，
> 也不改 `firstSeenAt` / 日桶 / 日期 / dedupe 语义。

---

## 数量经济技术经济研究（journal-edcb877d78）

**分类：官方 `jqte.net` 路径存在 CI 可达性债务；整体 source-health 可随其它路径状态在 healthy / degraded 之间变化。**

### 已验证事实

- 官方站点：`https://www.jqte.net/sljjjsjjyj/ch/index.aspx`。
- 本机住宅/代理网络可访问并解析：
  - `index.aspx`；
  - `reader/issue_list.aspx`（期次/目录，稳定 `file_no`）；
  - `reader/view_abstract.aspx?file_no=<id>&flag=1`（作者、中英文摘要、关键词、年/期/页码）。
- 官方站未发现可直接复用的 RSS/Atom 或 DOI 路径；接入需要专门的 TOC / article parser。
- GitHub-hosted production acquisition 中，`cn-journals` 路径曾对本刊记录
  `HTTPError: HTTP Error 502: Bad Gateway`。本机 200 与 CI 502 的差异说明：
  **当前不能把本机可达性等同于 GitHub-hosted CI 上的可靠生产可达性。**
- `.github/workflows/update.yml` 中关于 HTTP 418 的注释专门描述 **CNKI RSS** 的 GitHub runner 行为；
  它不是 `jqte.net` 502 的因果证据，因此不据此推断两者具有相同的网络阻断机制。

### Source-health 解释

- 2026-09-06 早一轮 health snapshot 中，本刊曾进入 `single_path_degraded`，同时
  `cn-journals` 路径记录 502。
- 后续 main snapshot（`checked_at=2026-09-06T14:32:43Z`）已恢复为：
  `degraded=0`、`single_path_degraded=[]`，本刊 `level=healthy`；但该刊条目仍保留
  `cn-journals` 的 502 failed-path evidence。
- 因此这里记录的是**独立官方路径的可靠性/冗余债务**，而不是声明本刊永久处于 degraded，
  也不是 parser 或本地 CNKI runtime 事故。

### 结论

- 现阶段不把 `jqte.net` 直接新增为依赖 GitHub-hosted CI 的生产独立路径；缺少 CI 稳定性证据。
- 不做 source-health “硬升/硬降”；由真实运行证据决定 `healthy / degraded`。
- 不改 `data/journals.yml`、`firstSeenAt`、日期或 dedupe 语义。
- 当前可继续依赖已有 Crossref / 本地 `cnki-rss` / `openalex-recall` 组合，并保留
  `cn-journals` 官方站失败证据供后续诊断。

### 后续选项

若未来要增强独立官方路径，可优先验证以下任一方案后再接入：

- 将 `jqte.net` 作为 machine-local official-site supplement（需单独评估是否值得增加本地 runtime 复杂度）；
- 寻找另一个正式/权威索引来源，并先验证 GitHub-hosted CI 可达性与字段质量；
- 若 `jqte.net` 在后续多个 CI 周期稳定恢复，再重新评估专门 parser，而不是基于单次本地成功上线。
