# econ-paper-monitor 项目规范（AGENTS.md）

更新时间：2026-08-02

本项目是**每日之门 / economics paper monitor** 的正式仓库。任何进入本仓库工作的 Agent（Codex 数据质量线、Codex 网站展示线、总控、Claude）必须先读本文件与 `PROJECT_HANDOFF.md`、`CLAUDE.md`，并遵守以下目录命名、文件生命周期与边界规则。

## 1. 项目结构与职责

本项目分两条业务线，由总控负责架构与集成：

- **数据质量线（A）**：抓取、清洗、去重、canonical、audit、ledger、元数据恢复、来源健康。只允许产出 `data/**` + 数据脚本 + 数据测试。
- **网站展示线（B）**：读取 canonical 数据，生成 `docs/**`、前端测试、Pages 部署。只允许修改展示脚本/模板/测试/workflow。
- **总控**：架构所有权、PR 审查合并、部署验收、清理规程执行。不直接修改抓取规则或视觉设计（除接口/集成冲突）。

## 2. 顶层目录规范（每个目录只放该放的东西）

| 目录/文件 | 用途 | 是否进 git |
|---|---|---|
| `data/` | 监测数据（canonical、daily、seen、ledger、retry、source health、审计）。只由数据线写入 | 是 |
| `docs/` | 公开站点生成物。**只由 render-site workflow 生成，人手不直接编辑** | 是 |
| `scripts/` | 正式生产脚本，按职责前缀命名（见 §3） | 是 |
| `tests/` | 自动化测试，`test_<模块>.py` | 是 |
| `.github/workflows/` | 一个 concern 一个文件（见 §3） | 是 |
| `infra/` | 基础设施/部署相关配置 | 是 |
| `.maturity/` | 实验/原型实现。成熟后提升到 `scripts/`，未提升的不进生产链路 | 是 |
| `local_admin/` | **gitignored 本地工作区**：`manual-supplements/`（跨线交付）、`scratch/`（临时）、`archives/`（备份归档） | 否（.gitignore） |
| `README.md / PRODUCT.md / DESIGN.md / PROJECT_HANDOFF.md / AGENTS.md / CLAUDE.md` | 项目文档 | 是 |

**禁止在根目录新建的目录**：`.codex-*`、`.integration-*`、`worktrees/`、`homepage-redesign/`、`.local-*`、`.codex-fix-*` 等任何散落的一次性目录（历史遗留已加入 .gitignore，见 §5 清理规程）。

## 3. 命名规范

- **脚本**：`fetch_*.py`（抓取）、`clean_*.py` / `dedupe.py`（清洗去重）、`build_*.py` / `render_*.py`（生成）、`audit_*.py` / `triage_*.py`（审计）、`recover_*.py`（元数据恢复）、`enrich_*.py`（富化）。
- **测试**：`test_<被测模块名>.py`，与脚本一一对应；不建 `tests/helpers` 之外的散落工具。
- **workflow**：`update.yml`（数据线）、`render-site.yml`（展示线）、`daily_vnext_public_smoke.*`、`daily_vnext_browser_smoke.*`（验收）。一个 workflow 只做一件事，不做循环触发。
- **data 子目录**：保持现有结构（`canonical`、`daily`、`seen`、`ledger`、审计与重试队列、来源健康）。新增数据文件必须位于 `data/**` 并兼容 `data/daily.schema.json`。
- **临时/一次性目录**：一律进 `local_admin/scratch/<YYYY-MM-DD>-<slug>/`，任务结束即删。
- **跨线交付物**（人工补录包、审计交付）：`local_admin/manual-supplements/<YYYY-MM-DD>-<slug>.json`，不用系统 Temp。
- **归档**：`local_admin/archives/<YYYY-MM-DD>-<slug>/`。
- **集成 worktree**：放到项目目录之外（如 `E:\BaiduSyncdisk\Work\Agent_automation\vibe_coding\econ-paper-monitor-worktrees\<name>`），**禁止**放进项目根目录。

## 4. 文件生命周期规则（防堆积）

1. **跨线交付物** → `local_admin/manual-supplements/`，不写系统 Temp，不进 git。
2. **临时/实验** → `local_admin/scratch/<date>/`，任务结束后由执行者删除。
3. **集成 worktree**：PR 合并后 3 天内由总控确认删除；不保留多个历史 `.integration-*` 副本。
4. **根目录禁止散落新目录**；发现 `.codex-*`、`.integration-*`、`worktrees/` 等遗留目录，列入清理清单，经确认后归档或删除。
5. **C 盘会话文件**（`C:\Users\Administrator\.codex\sessions\*.jsonl`）：每两周归档一次到 `local_admin/archives/codex-sessions/`，只保留最近 2 周活跃会话。
6. **docs 生成物**：展示线持续控制体积（索引/shards/路由瘦身），禁止无上限堆积生成页。
7. **.maturity 提升**：实验实现验证成熟后提升到 `scripts/` 并移除/标注 .maturity 副本，避免双份维护。

## 5. 清理规程（总控执行）

- 每次合并后：检查是否产生新的 worktree/临时目录；确认后删除。
- 每周：检查根目录是否出现违规目录、`local_admin/scratch` 是否残留、git 工作区是否干净。
- 删除前：先列清单（路径+体积+是否可恢复），用户确认后执行；不 `rm` 未确认路径。

## 6. 边界红线（不可违反）

- 数据线只写 `data/**` + 数据脚本 + 数据测试；PR 不含 `docs/**` 生成页。
- 展示线不写 `data/**`；只有正式首页生成器可以写 `docs/index.html`；Classic 保持不变。
- 正式期刊范围以 `data/journals.yml` 为准，清单外期刊不处理。
- 不编造作者/摘要/翻译/日期/中国相关性；缺失信息用显式状态标记。
- 发布前总控核对 release gate、完整性审计、PR diff 边界；发布后线上 10 入口验收。

## 7. 执行指令（给每个进入仓库的 Agent）

1. 进入仓库先读 `AGENTS.md` → `PROJECT_HANDOFF.md` → `CLAUDE.md`。
2. 任何新增文件先判断归属目录；拿不准放 `local_admin/scratch/<date>/` 并注明。
3. 不修改不属于自己业务线的文件（数据线不碰 docs/展示脚本，展示线不碰 data/抓取逻辑）。
4. 提交前 `git status` 确认没有混入生成页、临时文件或未授权目录。
5. 需要删除历史遗留目录时，提交清单给总控，不自行删除。
