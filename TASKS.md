# 每日之门 · 建设收尾任务清单（TASKS.md）

更新时间：2026-08-05
说明：这是「每日之门建设收尾」的单一事实来源。每完成一项，把 `[ ]` 改为 `[x]` 并在 PR 说明里引用对应行。完成定义见底部。

## Phase 0 — 收尾启动
- [x] 导入剩余补录包 `2026-08-04-nodoi-1`、`2026-08-05-nodoi-3`（PR #89，幂等复跑零写回）
- [x] 关闭遗留 PR #75（内容已由历史导入覆盖）
- [ ] 本清单（TASKS.md）建立并登记全部阶段 —— 本文件即交付物

## Phase 1 — 日期口径 A（Issue #22）
- [ ] 数据判定：官方渠道（详情页或官方 RSS）明确 online/published 日期一律 A；B 收窄为官方渠道备选/推断
- [ ] 解析失败（如 `"September "`）降 D/F；未来日期禁止入当日桶（现存 5 条修复）
- [ ] 展示线同步可信度标签/筛选文案；PRODUCT.md 措辞对齐
- [ ] 验收：A 占比 ≥50%；quality_report 断言固化（解析失败降级、未来日期不入桶）

## Phase 2 — 结构债收敛（Issue #20）
- [ ] OUP 组：QJE / EJ / JEEA / JLEO 等接官方 RSS/TOC/advance 或独立 fallback
- [ ] UChicago 组：JPE / JLE / JOLE / EDCC 等
- [ ] Springer 组：IJGT / ET / RED / SCW / PC / ITPF 等
- [ ] MIT 及其余：REStat、RFS、JEG、JPubE 等
- [ ] 每批复测 source_health degraded 计数与 release_gate 警告；确无官方 feed 的期刊写 triage 清单（补充源口径）
- [ ] 验收：degraded 23 → ≤8（≤10%）；JPE/QJE/EJ/JEEA/RFS/REStat 脱离名单

## Phase 3 — 数据债清零/封口
- [ ] 150/批恢复持续运行（SS 1 RPS + Elsevier API + Crossref/OpenAlex 双源互证）
- [ ] 缺摘要近期（30 天）=0；全库收敛到"仅上游真实缺失"清单（not_found/无官方日期名单化，不伪造）
- [ ] 缺作者=0、future_official_date_in_bucket=0
- [ ] quality_report 相关断言固化为测试

## Phase 4 — 渠道策略与交接文档
- [ ] PRODUCT.md / AGENTS.md 增加"渠道策略"：RSS/官方=实时主通道；Elsevier API 仅兜底 SD 搜索+补摘要；SS 仅历史补全；配额纪律（SS 1 RPS/60 天保活、Elsevier 7 天重置/16,000 预警）
- [ ] PROJECT_HANDOFF.md 更新到 2026-08-05 状态，附 Academic Door Journal 线对接链接

## Phase 5 — 仓库清理
- [ ] 清理 57 个已合并 codex/* 远程分支（保留活跃分支）
- [ ] 删除 in-repo 遗留目录（.codex-* 系列、worktrees/ 旧 worktree、.maturity 评估去留）
- [ ] 清理 local_admin/scratch（含 usage-preview）
- [ ] C 盘 .codex/sessions 归档一次（保留最近 2 周）
- [ ] 删除前按 AGENTS.md §5 列清单确认

## Phase 6 — 运营验证与收尾验收
- [ ] 健康告警闭环演练（失败→自动开 Issue→恢复→自动关）
- [ ] 10 入口线上回归 + Lighthouse ≥ #68 基线（Mobile performance ≥90、TBT ≤400ms）
- [ ] 用量页/配额监测、SS 保活、CNKI 本地 runner 复核
- [ ] 关闭 Issue #20、#22

## 完成定义（Definition of Done）
- degraded ≤ 8（≤10%）且 TOP 刊（JPE/QJE/EJ/JEEA/RFS/REStat）脱离名单
- A 级日期占比 ≥50%；解析失败不标 B；未来日期不入当日桶
- 缺摘要近期=0、缺作者=0、future_official_date_in_bucket=0；上游真实缺失清单化
- release gate 仅剩可接受警告；CI 全绿；线上 10 入口 200；Lighthouse 达标
- 遗留 PR/分支/worktree/临时目录清理完成；PROJECT_HANDOFF/TASKS.md 更新并由总控确认