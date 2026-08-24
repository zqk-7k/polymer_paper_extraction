# Demo 30 Preview 审阅结果

生成日期：2026-08-24

对应代码快照：`31f0b55740e0deb7ca31ddfbfa14c5f8abaf40af`

用途：人工审阅 32 篇文献的 Stage 4T 表格候选、Stage 4R unified 合并、Stage 5 表征分片和 Stage 6 校验结果。

本目录不是正式生产批次，只提供 `REVIEW_INDEX.json`，不提供 `RESULT_INDEX.json`。生产 API 不会自动选择本目录。原因是 32 篇中 21 篇的 `candidate.publication.status` 为 `partial`，不满足正式批次必须全部为 `complete` 的发布规范。

**关于 Stage 5 分片状态的说明：** 部分文献的 `stage5_shards.json` 顶层 `status` 字段停留在 `running`，但对应分片均已完成或明确失败。这是流水线写回步骤缺失的中间态遗留，不代表实际执行失败。下表中 Stage 5 状态列已按各分片实际结果重新归纳：`success` 表示所有分片均 `complete`，`partial_shards` 表示存在未完成分片，`candidate_partial` 与 demo5 一致（分片层已写回该状态）。

| 文献 | Candidate | Stage 5 | 分片数 | Characterization | Property | Stage 6 errors |
|---|---|---|---:|---:|---:|---:|
| `reference_no_0020284` | partial | success | 6 | 5 | 84 | 0 |
| `reference_no_0021296` | partial | partial_shards | 7 | 11 | 0 | 0 |
| `reference_no_0022895` | complete | success | 2 | 0 | 0 | 0 |
| `reference_no_0024941` | partial | partial_shards | 4 | 1 | 11 | 0 |
| `reference_no_0025452` | partial | success | 3 | 1 | 13 | 0 |
| `reference_no_0026548` | partial | success | 1 | 0 | 0 | 0 |
| `reference_no_0026714` | complete | partial_shards | 7 | 4 | 4 | 0 |
| `reference_no_0027435` | partial | candidate_partial | 5 | 4 | 32 | 0 |
| `reference_no_0028883` | complete | success | 3 | 7 | 8 | 0 |
| `reference_no_0028993` | complete | partial_shards | 4 | 1 | 4 | 0 |
| `reference_no_0033493` | partial | candidate_partial | 2 | 1 | 15 | 0 |
| `reference_no_0033617` | partial | partial_shards | 4 | 2 | 7 | 0 |
| `reference_no_0033940` | partial | partial_shards | 9 | 0 | 10 | 0 |
| `reference_no_0036922` | complete | partial_shards | 5 | 0 | 12 | 0 |
| `reference_no_0037268` | complete | success | 3 | 1 | 26 | 0 |
| `reference_no_0037607` | partial | candidate_partial | 6 | 12 | 70 | 0 |
| `reference_no_0037645` | partial | candidate_partial | 4 | 5 | 16 | 0 |
| `reference_no_0037886` | complete | success | 1 | 1 | 4 | 0 |
| `reference_no_0037921` | complete | partial_shards | 7 | 0 | 6 | 0 |
| `reference_no_0038527` | partial | success | 6 | 2 | 23 | 0 |
| `reference_no_0038813` | partial | candidate_partial | 10 | 8 | 67 | 0 |
| `reference_no_0039705` | partial | partial_shards | 7 | 1 | 18 | 0 |
| `reference_no_0041326` | complete | success | 2 | 3 | 52 | 0 |
| `reference_no_0041387` | partial | partial_shards | 7 | 3 | 35 | 0 |
| `reference_no_0042246` | partial | partial_shards | 3 | 1 | 21 | 0 |
| `reference_no_0042367` | complete | partial_shards | 2 | 0 | 14 | 0 |
| `reference_no_0042480` | partial | candidate_partial | 4 | 2 | 40 | 0 |
| `reference_no_0043541` | partial | success | 2 | 0 | 4 | 0 |
| `reference_no_0043590` | partial | success | 3 | 1 | 21 | 0 |
| `reference_no_0043955` | complete | success | 5 | 0 | 2 | 0 |
| `reference_no_0073324` | partial | success | 1 | 1 | 5 | 0 |
| `reference_no_0101911` | partial | success | 4 | 1 | 10 | 0 |

说明：

- `Stage 6 errors = 0` 只表示当前 Preview-relaxed 校验没有 error，不等于 Candidate 完整或科学语义已人工确认。
- `stage4t_shadow.json` 是非权威表格候选；未通过样品、语义、条件和证据门控的内容不直接发布。
- `stage4r_unified_audit.json` 保存 4N/4T 合并、拒绝和未解析原因。
- `stage5_shards.json` 保存分片状态和解析诊断；`candidate_partial` 不应改写为 success。
- 本集合保留每个 Stage 的 JSON 和 HTML，供逐篇、逐对象和逐证据审阅。
- `_assets/mathjax-3.2.2/` 提供 `report_candidate.html` 离线渲染所需的 MathJax。
