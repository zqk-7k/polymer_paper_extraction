# Demo 5 Stage 5 分片审阅结果

生成日期：2026-08-23

对应代码快照：`6d34d06a2679c67d628c950367c55714e7a2c835`

用途：人工审阅 Stage 4T 表格候选、Stage 4R unified 合并和 Stage 5 表征分片结果。

本目录不是正式生产批次，只提供 `REVIEW_INDEX.json`，不提供 `RESULT_INDEX.json`。生产 API 不会自动选择本目录。原因是 5 篇中 4 篇的 `candidate.publication.status` 为 `partial`，不满足正式批次必须全部为 `complete` 的发布规范。

| 文献 | Candidate | Stage 5 | 分片数 | Characterization | Property | Stage 6 errors | 阻断原因 |
|---|---|---|---:|---:|---:|---:|---|
| `reference_no_0020284` | partial | candidate_partial | 6 | 5 | 50 | 0 | series subject 未解析；部分 Stage 5 分片失败或隔离对象 |
| `reference_no_0038527` | partial | success | 6 | 5 | 6 | 0 | series subject 未解析 |
| `reference_no_0038813` | partial | candidate_partial | 10 | 8 | 36 | 0 | series subject 未解析；部分 Stage 5 分片失败或隔离对象 |
| `reference_no_0043541` | complete | success | 2 | 3 | 0 | 0 | 无 blocking warning |
| `reference_no_0043590` | partial | success | 3 | 2 | 5 | 0 | series subject 未解析 |

说明：

- `Stage 6 errors = 0` 只表示当前 Preview-relaxed 校验没有 error，不等于 Candidate 完整或科学语义已人工确认。
- `stage4t_shadow.json` 是非权威表格候选；未通过样品、语义、条件和证据门控的内容不直接发布。
- `stage4r_unified_audit.json` 保存 4N/4T 合并、拒绝和未解析原因。
- `stage5_shards.json` 保存分片状态和解析诊断；`candidate_partial` 不应改写为 success。
- 本集合保留每个 Stage 的 JSON 和 HTML，供逐篇、逐对象和逐证据审阅。
