# 九类性质归属 Agent 与受控自进化小试验

> 该结果只覆盖 5 张表，其中 3 张为冻结小测试，不能外推为总体性能。

| 指标 | 基线 | 进化后 | 变化 |
|---|---:|---:|---:|
| 语义 Precision | 100.0% | 100.0% | +0.0% |
| 语义 Recall | 100.0% | 100.0% | +0.0% |
| 语义 F1 | 100.0% | 100.0% | +0.0% |
| 样品绑定准确率 | 90.9% | 90.9% | +0.0% |

## 门禁

- 通过：semantic_f1_not_worse
- 通过：sample_binding_not_worse
- 通过：no_failed_agent_runs
- 通过：negative_control_false_positive_guardrail

无论门禁是否通过，本轮均不会自动修改生产词表或发布数据。
