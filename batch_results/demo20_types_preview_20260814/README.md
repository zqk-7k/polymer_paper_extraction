# 20 篇类型与性质归属 Preview 结果（2026-08-17 更新）

本目录覆盖发布同一组 20 篇文献的最新 Preview 结果。目录日期沿用原发布批次标识，实际生成与验收时间、代码提交和文件哈希以 `RESULT_INDEX.json` 为准。

## 本次更新

- Stage 2 实现版本：`1.6.1`；无直接证据时 `polymer_type` 保持 `null`，不默认填充 `homopolymer`；
- Stage 3 实现版本：`1.7.1`；无配方证据时 `material_type` 保持 `null`，不默认填充 `neat_resin`；
- HTML 的 Sample 主标题仅展示聚合物名称；类型未知时显示 `not specified`；
- Stage 4R 仅在 Sample 标签唯一匹配时迁移性质，不能唯一归属时保留 unresolved；
- 模式仅为 Preview，不声明 Strict 合规。

## 验收摘要

- 文献与正式文件：20/20，14 类结果文件均完整；
- Candidate 发布完成：20/20；
- Stage failures：0；Stage 6 errors：0；
- 聚合物实体：267；样品：208；
- Stage 4 正式性质：211；待归属性质：84；Candidate 合并后性质对象：289；
- Stage 4R 恢复候选：170；成功迁移到正式性质：102；歧义跳过：74；
- 代码提交：`b3abf4cab0c7a05661591387117e6843ed0bc5f3`。

## 文件说明

每篇目录包含 `candidate.json`、`final.json`、两份 HTML、Stage 0–6 JSON 以及 Stage 4R 审计产物。最终展示文件是 `report.html`，Preview 候选展示文件是 `report_candidate.html`。

本批次不包含 `_batch`、原始模型响应、失败响应、日志、SQLite、缓存、本机路径、密钥或新增 PDF。逐文件大小和 SHA-256 见 `RESULT_INDEX.json`，统计见 `validation_summary.json`。
