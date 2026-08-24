# 九类性质归属 Agent 与受控自进化小试验

完整方案、5 篇试验结果、费用和结论见 [方案与试验结果.md](方案与试验结果.md)。

本目录实现 0824 目标架构中的两个非生产能力：

1. 九类性质归属核验 Agent：只核验表头语义、样品归属和证据引用；
2. 专家审核驱动的受控自进化：从 development gold 生成记忆候选，经人工门禁后，
   在冻结小测试上比较基线与进化版本。

## 安全边界

- 不重新运行 MinerU，直接复用已有 Stage 0–5 产物；
- 不向 Agent 提供性质数值，数据格在输入中被替换为占位符；
- 不修改原始 evidence、`final.json`、`candidate.json` 或生产 YAML；
- Agent 输出恒为 `candidate_only`；
- frozen test 的答案不进入记忆；
- 本轮只有 5 张表，属于工程可行性验证，不是正式统计结果。

## 执行顺序

```text
baseline Agent（5张表）
-> development 误差与已验证模式
-> update_proposals.json
-> 人工门禁
-> approved_memory_v1.yaml
-> evolved Agent（3张冻结表）
-> evaluation.json / evaluation.md
```
