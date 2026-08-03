# manual-* 来源导入约定

更新时间：2026-08-02

人工补录包（例如 CNKI 期刊期次摘要）由数据质量线通过
`scripts/import_manual_supplement.py` 导入，只写入 `data/**`：

1. 包文件放在 gitignored 的 `local_admin/manual-supplements/<slug>.json`，
   结构为 `{journal, journal_id, issn, issue, source, records: [...]}`。
   多期刊单文件包允许 `package.journal` 为 null，由每条 `records[].journal` /
   `records[].journal_id` 指定期刊；记录级字段优先，缺失时回退到包级字段。
2. `source` 必须为 `manual-*`（如 `manual-cnki`），否则拒绝导入。
3. 每条记录所属期刊必须能在 `data/journals.yml` 中解析（按标题或 id），
   清单外不导入；无法解析的记录如实计入 `unresolved_journal_count` 并跳过。
4. 每条 `records`：
   - `title` 必填；用 NFKC + 去标点空白后的规范化标题匹配 `seen.json`。
   - 有 `doi` 时，DOI 精确匹配优先（含 `identity_aliases`），匹配命中后
     同步回写 `data/daily/*.json` 中同 DOI 的 canonical 记录；
     无 DOI 时按规范化标题 + 期刊范围匹配 daily 回写。
   - 匹配成功且摘要缺失或仅为预览时，回填/升级为完整摘要，
     `abstract_source=manual-cnki`、`abstract_completeness=full`；
   - 无匹配时新增 canonical 记录（`source_type=journal`、`source=manual-*`）；
   - `doi` 缺失时**不编造**，保持缺省并计入 `missing_doi`；
   - 作者解析为“去除序号与分隔符”的 best-effort 列表；
   - `manual-publisher` 摘要会去除 ScienceDirect Highlights 段与
     `Abstract` 标签后再落盘，避免样板文字进入公开摘要。
   - 期次日期写入 `issue_date`，`date_confidence=D`、`date_source=manual_issue`，
     不把 `accepted_date` / 首次发现时间当作官方在线日期。
5. 幂等：同一 `manual-*` 源 + 规范化标题已存在时跳过；重复导入不会重复新增。
6. 每次导入追加一条审计到 `data/manual_supplement_imports.json`（保留最近 50 次），
   报告中记录 matched_by_doi / matched_by_title / daily_backfilled /
   daily_files_changed 实测数字。
