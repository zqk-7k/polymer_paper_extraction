# PoLyInfo 锚点召回自进化试验

本目录是独立于生产流水线的实验模块，位于分支
`experiment/polyinfo-recall-evolution`。它不修改 `main`，也不自动更新生产提示词。

## 科学问题

当前目标不是让模型尽可能多报数值，而是在证据和样品绑定约束下，提高
PoLyInfo 已记录性质的恢复率。主指标为 PoLyInfo 锚点 Recall：

`Recall = matched / (matched + value_diff + polyinfo_only)`

同时设置三条护栏：Precision 相对基线下降不超过 5 个百分点；每篇论文的证据
定位率不低于 95%；样品绑定率不低于 95%。这些仍是 PoLyInfo 锚点评价，不等于
人工全文 gold accuracy。

## 冻结设计

- 开发集：`reference_no_0037921`、`reference_no_0038527`
- 冻结测试集：`reference_no_0037886`、`reference_no_0037268`、
  `reference_no_0043955`
- 基线：`batch_results/demo20_types_preview_20260814`
- 自变量：只增加经开发集归纳的 `recall_memory.md`
- 主干模型、Schema、词表、Stage 4R 和评价器保持不变

测试集的 PoLyInfo 数值不会进入提示词。只有实验结束后，评价器才读取 PoLyInfo
记录计算指标。

## 运行

只使用现成 Stage 0–3 结果，不需要 MinerU：

```powershell
$env:DMX_API_KEY = "<DMX key>"
python experiments/self_evolution_recall/recall_evolution.py all
```

分步执行：

```powershell
python experiments/self_evolution_recall/recall_evolution.py prepare
python experiments/self_evolution_recall/recall_evolution.py run
python experiments/self_evolution_recall/recall_evolution.py evaluate
```

输出位于 `runs/trial_v1/`，该目录已被 Git 忽略。任何候选升级都必须经过人工审核，
不能由本模块自动写回生产提示词。

