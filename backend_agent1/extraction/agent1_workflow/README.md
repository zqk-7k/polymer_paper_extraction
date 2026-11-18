# agent1 单路正式入口（20261109）

正式接入已完成迁移。推荐使用项目根目录 `agent1_runner.py`，只运行 agent1。旧批处理入口保持兼容，显式选择 `--directory-source agent1` 后，使用同一实现：目录导入 → Stage3 原生状态/工艺补充及缺口任务 → 分组4N＋完整表4T → 限权4R → Stage5 → 原值导出。

不运行模型质检、数值/单位转换、性质计算或图中数据抽取。Stage6 这里只做引用守恒、目录成员等工程检查，输出 `raw_sample_information.v1`；不能将它冒充旧的归一化 FinalDocument。

## 输入与运行

使用 `agent1_runner.py prepare / run / resume / status`；也可使用 `extraction/batch_runner.py` 或上层 `pipeline_runner.py` 的 agent1 选项。保留现有 `--config`，不在本模块保存密钥，也不自动换模型。

在 `D:\work_2026\polymer\testcode` 下可执行以下状态查询（不调用模型）：

```powershell
.venv\Scripts\python.exe -B -X utf8 agent1_runner.py status --output reports/agent1_mainline_rollout_20261109/acceptance/full_verified
```

新任务：`prepare --documents <一个或多个原文JSON> --bundle-root <已转换目录根路径> --config <配置路径> --output <新目录>`。准备后执行 `run --output <同一目录> --workers 3`；中断后执行 `resume --output <同一目录> --workers 3`。这些子命令均接在 `agent1_runner.py` 后；模型配置和目录必须由调用者明确指定。运行代码位于主流程 `extraction/agent1_workflow`，不依赖历史报告中的脚本。

- `--directory-source agent1`：显式启用；省略则 native。
- `--agent1-bundle-root <目录>`：按文献分目录，例如 `reference_no_0021296` 内必须含 `agent1_entities.json`、`agent1_directory_samples.json`、`agent1_handoff.json`。可附 `stage0_blocks.json` 做原文版本锁定。
- `--agent1-compare-native` 已停用，传入会报错；agent1 只运行单路。
- `--workers 4 --llm-workers 4`：最多四个文献/分支进程同时执行，每个进程顺序调用模型。
- `--ref-no reference_no_0021296`：沿用主程序的完整编号格式。
- `--output-dir <新的空目录>`：原输出不覆盖。原样重启同一命令可续跑。
- `--status`：读取进程锁、失败任务和导出完整性，显示真实运行状态，不仅仅读取旧状态快照。`--dry-run` 只显示计划，不调用模型。

输入三件套来自此前已核对的 agent1 转换结果。`unified_directory.convert()` 保留原导出转换函数；此入口不自动从任意 Excel 猜工作表、列或论文对应关系。扩大到新论文前先准备并核对三件套。

## 输出与回退

每篇输出位于 `runs/B/reference_no_*/`（B 为兼容已有产物的目录名，只运行 agent1）：`report.html`、`final.json`、`sample_information.json`（采用）、`review.json`（待核）、`uncategorized_properties.json`（未分类/单体标注）、`candidate_ledger.json`（逐引用去向）。`extracted_uncategorized` 不等于采用，不应计入采用率。

`production_contract.json` 和 `frozen_manifest.json` 锁定原文、目录、配置、模块及共享 Stage3/提示词。代码或输入变化需新输出目录。模型失败原响应留存，续跑成功后活动失败标志归档到 `failure_history`。运行锁由操作系统持有；进程退出后释放，恢复时自动归档残留标记。无需人工删锁；活跃工作进程会拒绝重复启动。成功任务从检查点恢复，不重复请求。存在未解决任务失败时不得报完成，导出损坏可从结果重建。只有任务完成且导出完整性通过才显示 completed。

回退时省略 agent1 参数并使用独立输出目录，原生行为不受本模块影响。旧预览/数据库工具不能自动把新 raw JSON 当旧 schema 使用；新入口使用自己的状态和 HTML 导出。历史 source-workflow、旧校验/强制覆盖参数不与此模式混用。

## 表内作用范围与失败恢复

Stage4T 的主体轴可携带 `region: {rows: [...], columns: [...]}`，下游同时限制行列；多级父子表头不按并排列组裁剪。整表主体须有唯一目录身份及命名原文证据。范围接收不等于独立确认物理状态语义。

全空结果需提供 `completion_explanation`，明确已覆盖全部所给来源及无结果原因；无说明则限次重试并保留失败。连接／读取超时设置为 1200 秒，不是整篇总时限。请求错误、响应流中断和读取超时最多重试一次；单任务总尝试上限仍为 3。4N/5 的初始预算不变，截断后可升至 65536；其余阶段仍使用通用 32768 上限。阶段覆盖配置为 stage_output_truncation_fallback_tokens，不改变默认 native 入口。

输出字段逐次减半直至单字段；来源分组有独立额度，最多再分三层（每个字段最多八个来源输出组）。每组保留完整输入，只划分输出职责。不能再分的任务继续截断时明确保留失败。混合错误按本次最终失败类型判断是否分组，旧失败文件不参与判断。续跑可恢复已建立的分组，各子任务仍按完整请求签名验证缓存；失败不会被解释成原文无数据。模型、代码或输入变动后的跨版本缓存迁移必须另有逐请求证据，本模块不自动绕过版本锁。

## 验收边界

本版迁入已验收的 `agent1_single_candidate_20261109`，包括此前固定的空值条件和表内组成端点修复。历史实验脚本、标准集与评估逻辑不进入运行模块。每个 worker 独立进程，兼容接收器的安装不污染原生进程。

迁入验收位于 `reports/agent1_mainline_rollout_20261109`：主流程批处理入口三篇并发冻结回放、真实进程中断/恢复、状态读取和导出重建。冻结回放证明工程链路与结果保全，不代表重新验证线上模型服务，也不把原有待核歧义视为已解决。此次没有重新做 A/B，没有新增质量规则。
