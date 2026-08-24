# PolyInfo 性质覆盖分析与高分子数据库 Schema 扩展方案

> **版本**：v2.26（2026-08-23 修订）
> **修订依据**：本文 v1 的架构判断（§9 Stage 分工、§10 目标结构）经复核成立并保留；
> 涉及数字、口径、以及"已有能力待检查"的若干节已按对 GT 与批次产物的逐项核查结果改写。
> 原文备份见 `PolyInfo性质覆盖分析与高分子数据库Schema扩展方案.bak_20260821.md`。

> **当前结论（v2.26）**：保持 `Stage 4N=正文抽取`、`Stage 4T=表格候选抽取`、
> `Stage 4R=修复与整理` 的边界。4T 当前只运行非权威 Preview sidecar，采用“宽抽取、窄发布”：
> 先保留可定位候选，再由 4R 和发布门控决定是否进入正式 Schema。
>
> **当前状态**：numeric eligible 表的候选覆盖/语义覆盖/权威发布资格为 `51/51`、`51/51`、`0/51`；
> 5 张复杂数值表已将 100 个规则候选重绑定为 98 个语义候选，另有 2 张定性溶解性表新增 114 个候选；
> 目前共 7 张表、212 个候选，全部仍是 `candidate_only`。Preview 已接入 4R unified：5 篇试跑共消费
> 685 条 4T 候选，新增合入 69 条、合并同格重复 40 条，5/5 均通过 Stage 6 且为 0 errors；Strict 与
> legacy 4R 未改变。Stage 5 Preview 已按规范化表征方法分片，并内聚逐对象校验、有效对象保留、
> 确定性合并和 shard sidecar。定向重跑的 3 篇均不再为空壳，Stage 6 均为 0 errors；其中 0020284、
> 0038813 因局部语义/证据问题保留为 `candidate_partial`，0038527 为 `success`。下一步是扩展到 5 篇
> 人工审阅和 demo20 全流程重跑，不让 Stage 5 Preview 结果提前进入 Strict 权威路径。

<details>
<summary>历史修订记录（v2.0-v2.16）</summary>
>
> **v2 主要变更**
> 1. 新增 §4：Stage 4 稳定性缺陷先于 Schema 扩展修复（新 P0），含 `llm_client.py` 围栏缺陷等三项已定位代码问题。
> 2. 覆盖率改称**召回率**；数值型口径统一为 Legacy / Curated / Extended-numeric-all / Extended-numeric-locatable，定性信息单列，不再用"双指标"表述。
> 3. §7 原"Crystallinity 只需修输出链"的前提被证否：0817 产物与 GT **零重叠**，是真实缺口。
> 4. §7.3 morphology 目标结构删除：本批 13 条 GT 值全部不是尺寸型数值，改为暂缓对齐 + 信息改道。
> 5. §6.3 DP 的"必须区分 DPn/DPw"删除：GT 无 kind 字段；物理范围按实测 13~350 处理。
> 6. 实施顺序整体重排为 P0~P3，新增 8 条验收清单。
> 7. §6.4 A2 槽位定为 `thermal_mass_fraction_at_temperature` + `quantity_kind`：
>    21 组并非同一物理量（0020284/0021296 报残余质量，0037645 报失重量），抽取阶段不得做 `100−x` 换算。
>
> **v2.1 变更（2026-08-21 第二轮）**
> 8. **Curated 分母 547 → 526**：A2 的 21 组在旧 GT 中占 42 行，迁移后设定温度降级为 condition，
>    不再是独立性质点。可信 303/526=57.6%，严格 263/526=50.0%。Legacy 695 保持不可变。
> 9. **Extended 拆为 all(993) / locatable(822)**：旧值 1004 及位置分布 309/284 已失效
>    （含 morphology 的 11 条正则误抽），重算为 298/273，但重跑前不正式冻结。
> 10. **删除"召回率单调递增"门控**：修复错误匹配会使召回率合理下降，改为版本固化 + 变化可解释 + 三指标联合验收。
>
> **v2.2 增补（依赖与 Schema 收口）**
>
> 11. **解开 P0/P1/P2 依赖环**：黏度四分桶（原 P1-c）与匹配器回归 fixture（原 P2-d）提前为 **P0-g → P0-h**，
>     先建基线再改匹配器；P2-d 降级为"扩展 fixture"。
> 12. **Extended 加 `numeric` 限定词**：`Extended-numeric-all(993)` / `Extended-numeric-locatable(822)`，
>     另立 **Extended-qualitative(67)** 单独统计、不设分母；§3.2 标题由"三条"改为"四条数值口径 + 定性单列"。
> 13. **Observation 拆两层并补定性值**：`characteristic_name` + `variant` + `numeric_value` / `categorical_value`，
>     二者有且仅有一个非空，承接 23 条结晶状态。
> 14. **解析诊断显式承载**：`extract_json_object` 返回 `ParsedJSON`（含 `trailing_text` / `parse_source` / `warnings`）；
>     完整性关键词**只扫 JSON 之外**的前后文，不扫 `data` 内部。
> 15. **重试粒度分当前/目标架构**：当前 Stage 4 只能整篇重试 1 次；表级局部重试属 Stage 4T。
> 16. **§14.2 八项指标标注为尚不可执行**：门槛与公式须待 P1-a 产出人工复核 fixture 后冻结；
>     "零产出表"分母限定为 eligible tables。
> 17. **§14.1 第 4 条改为状态判据**：85 点是"重新具备参与评估的机会"，非"必须全部抽中"；
>     0817 三篇改称"未再复现"而非"已修复"。
> 18. **§4.2 解析算法改为五步固定顺序**（raw_decode 优先），新增 §4.2.2 完整性判定；
>     0043955 为 `finish_reason=end_turn` 的**主动省略**，非长度截断。
> 19. **新增 §4.3.1 空壳三态**与 §4.3.2 0814 四篇分类验收（0033617 属语义校验类，须单独验收）。
> 20. **黏度三分 → 四分**：η_inh/[η]/η_red/η_sp 为四个独立量，量纲与定义均不同。
> 21. **§12 统一为 `material_characteristic_observations[]`**：黏度、DP、结晶度同样存在多观测，不应保留单值字段。
> 22. **§14 验收清单重构**：拆为 P0(8 条) + Stage 4T 准确性(8 条) + 其余阶段。
>
> **v2.4 增补（Curated 实测口径收口）**
> 23. **区分冻结参考值与当前实测值**：Curated 分母仍为 526；文档原冻结参考为严格 263、可信 303，
>     v2.2 版本化 matcher 实测为严格 267、可信 307。新增的 4 条均为 0021296 的
>     `% residue (N2) at 800°C`，迁移为 `residual_mass_fraction` 后与 preview 表格序列 exact 命中，
>     属有效观察重新进入评估，不是放宽匹配或跨物理量误匹配。
>
> **v2.3 增补（实施边界收口）**
>
> 23. **单位状态显式化**：数值观测不再强制 `unit` 必填；区分原文已报告、物理量无量纲、原文未报告三种状态，禁止补造单位。
> 24. **解析器保留兼容入口**：新增 `parse_json_response() -> ParsedJSON`，原 `extract_json_object() -> dict` 保留为包装函数，避免一次改动 Stage 1~5 全部回放调用面。
> 25. **补全部分成功状态链**：Stage 4 的阻断性 warning 必须传递到 batch runner；后续 Stage 可继续运行，但最终不得被覆盖为 `candidate_complete`。
> 26. **P0 拆为六个可审查实施包**：先固化数据与基线，再分别提交解析、状态、重试、GT/匹配器和 Stage 4T 调研。

> **v2.5 增补（Stage 4T 冲突指标落地）**
> 27. “互斥性质映射冲突数”已由独立离线审计器按 cell/column/observation 三层计算；互斥关系从 fixture 的 `forbidden_pairs` 读取，`Char yield → thermal_decomposition_temperature` 仅作为热质量/分解温度类别的哨兵案例。
> 28. 新增 `extraction/tools/audit_stage4t_precision.py` 作为 Stage 4T Shadow 批量入口；仅在显式指定 `--output` 时生成独立报告，不覆盖历史 `stage4_properties.json`、Legacy GT 或批次结果。

> **v2.6 增补（P1-a 表结构调查落地）**
> 29. 已对 `demo20_preview_final_20260812` 的 59 张 Stage 0 表完成独立结构调查，报告见
>     `reports/stage4t_table_structure_survey_20260821.{json,md}`。实测方向为：逐行样品 38 张、
>     横向并列样品 2 张、混合 1 张、未知 18 张；54 张含数值，24 张可直接识别性质列。
> 30. 单位位置实测为：表头 27、单元格 7、caption 1、多位置 19、未发现 5。Stage 4T 不得只读取表头单位，
>     也不得把所有含数值表强行映射为性质表：30 张存在数值但未识别性质列，需保留为待复核/专用表型。
> 31. 方向检测采用“行样品 / 横向并列样品 / mixed / unknown”四态；未知表不得被默认降级为行样品，
>     后续 Shadow 抽取必须保留方向判定与原因，供人工复核和局部重试使用。
>
> **v2.7 增补（P1-b Stage 4T Shadow 落地）**
> 31. 新增 `extraction/stages/stage4t_table_property.py` 与
>     `extraction/tools/shadow_stage4t_tables.py`：仅对 Stage 0 表格做确定性 Shadow 绑定，
>     不调用 LLM、不生成最终 `Stage4Document`、不接管现有 Stage 4，也不修改 `batch_runner`。
> 32. Shadow 保留 `direction`、原始样品/性质文本、数值格 `cell_id`/行列坐标、单位位置、
>     `binding_status` 和 unresolved reason；`unknown` 方向只输出诊断，不静默按逐行表抽取。
> 33. demo20（59 张表）初版 Shadow 基线：325 个观测候选，298 个完整绑定，27 个未解析；
>     20 个为词表未承接的性质（Texo/ΔHexo、wt loss、λmax），7 个为样品轴未确定（空样品格的跨行热事件或条件轴），
>     均保留原始 cell 定位，不伪造 sample_id。
> 34. Shadow 层补充 LaTeX 表头规范化（Tg/Tm/Td/ΔHm 等）与单复数样品列识别；
>     `Char yield` 不映射为分解温度。报告输出为 `reports/stage4t_table_property_shadow_20260821.{json,md}`，
>     后续须先完成人工 fixture 与精度门槛，再进入 P3 全面接管。
>
> **v2.8 增补（P1-b 人工精度 fixture 与热分析语义）**
> 35. 新增 `stage4t_shadow_binding_fixture.v0.1`，人工复核 7 张代表表（6 张数值 eligible），
>     覆盖正置多级表头、转置、混合重复组、热分析/Char yield、空样品格跨行事件、条件轴和 unknown 安全保留，
>     共冻结 108 个数值格。
> 36. 新增 `stage4t_shadow_binding_audit.py` 与只读 CLI，明确计算方向准确率、数值格召回率、
>     输出精确率、性质映射准确率、样品绑定准确率、重复输出率和 eligible 零产出表数；
>     性质映射须同时核对规范名、`semantic_label`、variant 与条件，不能把两个 `None` 当作同一语义。
> 37. Shadow v0.2 补充 `Ti/T10/Tmax` 语义：只有同表存在 TGA/失重/Char yield 等降解上下文时，
>     `Ti` 才归入初始分解温度；液晶 DSC/HOPM 表中的 `Ti` 保留为
>     `transition_temperature_ti` unresolved，避免跨领域缩写误映射。
> 38. 当前 demo20 Shadow 为 369 候选、322 完整绑定、47 unresolved；代表 fixture 为 108/108 格命中，
>     方向、输出精确率、严格性质语义和可评估样品绑定均为 100%，重复率为 0。
>     该结果仅是代表 fixture 基线，尚未冻结 P3 接管阈值，也不代表全部 59 表已人工标注。
>
> **v2.9 增补（P1-b fixture 扩展与 characteristic 语义）**
> 39. `stage4t_shadow_binding_fixture.v0.2` 继承 v0.1，并把人工范围扩展到 13 张表
>     （12 张数值 eligible、260 个标注格）；新增黏度、Mn/Mw、分子量分布、结晶度、失重率、
>     泡孔密度、复杂分组表头和 OCR 列偏移案例。继承时按 `doc_id + table_id` 覆盖，避免复制旧答案。
> 40. Shadow v0.3 将 Sample 级 characteristic 先保留在中间语义层：`molecular_weight` +
>     number/weight-average variant、`molecular_weight_distribution`、`crystallinity`、
>     `mass_loss_fraction`、`cell_density`；尚未确定正式 Schema 槽位的不得强塞入 97 项性质桶。
> 41. 修复两类假映射：`Mw/Mn`、`Mn/Mw`、PDI、Đ 不再当作 Mw；`Cell Density` 不再当材料密度。
>     黏度保持当前兼容规范名 `intrinsic_viscosity`，同时用 variant 区分 inherent/intrinsic/reduced/specific。
> 42. `0073324/T_4_37` 存在 OCR 行数据相对表头右移一列。仅在“黏度列当前值全部 >50、
>     右邻列有至少 3 个 0–20 数值且出现 Insoluble 状态”同时满足时推断右移，并记录
>     `header_column_index` + `alignment_status=inferred_right_shift`；修复后删除 16 个 PMT 假黏度，恢复 11 个真实黏度。
> 43. v2.9 当时的 demo20 Shadow 基线为 528 候选、312 个规范性质完整绑定、216 unresolved；unresolved 的增长
>     来自 209 个未进入正式性质桶的候选（其中 195 个已有中间语义、14 个仍未归一）和 7 个样品轴未确定；
>     这批候选现已带 cell 定位保留，不代表精度下降。
>     v0.2 fixture 为 260/260 格命中，严格性质语义、可评估样品绑定与输出精确率均 100%，重复率 0。
>
> **v2.10 增补（当前 Shadow 输出表全覆盖与 sidecar 门槛）**
> 44. `stage4t_shadow_binding_fixture.v0.3` 继承 v0.2，覆盖当前全部 26 张有 Shadow 输出的表，
>     另保留 1 张 categorical unknown 非 eligible 表；共冻结 538 个数值格。审计报告见
>     `reports/stage4t_shadow_binding_audit_v03_20260821.{json,md}`。
> 45. v0.3 审计为 538/538 格命中；方向、输出精确率、严格性质语义和 528 个可评价格的样品绑定
>     均为 100%，重复输出率为 0。该结论仅覆盖当前有输出表，不代表其余无输出表已判定为非 eligible。
> 46. 修复 `rowspan` 稀释数值比例导致首两条数据被误判为表头的问题；多列 Sample 轴保留
>     “组标签 | 子标签”。补充 `Td^i`、`Td^10%/20%/...` variant/condition 与 `RM (%)`
>     的 `residual_mass_fraction` 中间语义。
> 47. 冻结“非权威 Stage 4T sidecar 随 Preview 运行”门槛，但不冻结 P3 全面接管门槛。
>     59 张表中仍有 30 张“含数值但未识别性质列”待逐表判定，Stage4N/Stage4T 合并准确率也尚未实现；
>     因此不得用本轮 538/538 直接替代现有 Stage 4/4R 输出。
>
> **v2.11 增补（Stage 4T 非权威 Preview sidecar 接入）**
> 48. precision 审计新增当前 Shadow 输入模式：用通用 `forbidden_pairs` 与 v0.3 binding fixture 的逐格答案
>     审计 538 个候选，其中 524 个已有性质/中间语义、14 个未归一。当前三类互斥冲突在
>     cell/column/observation 三层均为 0，报告见 `reports/stage4t_shadow_conflict_audit_v03_20260822.json`。
> 49. `batch_runner --preview` 默认在 Stage 0 后运行 `stage4t_preview_sidecar`，每篇独立输出
>     `stage4t_shadow.json`；该文件显式标记 `authoritative=false`，只依赖 `stage0_blocks.json`，
>     不进入 Stage 4、Stage 4R、Stage 5、Stage 6 或 candidate 发布输入。
> 50. sidecar 是 best-effort：失败会保留失败 attempt 和日志，但不触发 `candidate_partial`，不阻断正式流程；
>     `--no-stage4t-sidecar` 可显式关闭。Strict 流程不包含该步骤。
>
> **v2.12 增补（全批表格 eligibility 人工复核）**
> 51. `stage4t_table_eligibility_fixture.v0.4` 对“30 张无性质列数值表”和“18 张 unknown 方向表”的
>     41 张并集逐表复核（两者重叠 7 张）。分类为：16 张 `eligible_property`、19 张
>     `material_characteristic`、2 张 `condition_or_process`、2 张 `not_eligible`、2 张 `ambiguous`。
> 52. v0.3 binding fixture 与 v0.4 eligibility fixture 合并后，demo20 的 numeric eligible 表分母为 51 张；
>     当前仅 26 张有 Shadow 输出、25 张零输出，表级输出覆盖率为 26/51 = 50.98%。因此 v0.3 的
>     538/538 只证明“已有输出表”的格级精度，不能表述为全批表格召回率 100%。
> 53. 25 张 numeric eligible 零输出表中，14 张卡在 `unknown` 方向/样品轴识别，11 张已判为
>     `row_samples` 但缺性质词汇、复合数值或条件轴语义；按输出归属分为 12 张 PropertyObservation
>     与 13 张 material characteristic。报告见 `reports/stage4t_table_eligibility_audit_v04_20260822.{json,md}`。
> 54. 两张 MMX/FF 计算构象能量表保持 `ambiguous`，在 Schema 明确 calculated/experimental 区分前
>     不进入 numeric eligible 分母；两张纯定性溶解性表单独计 categorical eligible。
>
> **v2.13 增补（Stage 4T unknown 方向与条件轴修复）**
> 55. 新增 `stage4t_unknown_direction_fixture.v0.1`，冻结 14 张 numeric eligible unknown 表的方向、
>     轴角色和表头行：9 张 `row_samples`、3 张 `column_samples`、2 张 `condition_series`；轴角色区分
>     `named_sample`、`composition`、`grouped_sample` 与 `condition`，频率/温度条件不得伪装为样品轴。
> 56. Shadow v0.4 统一 survey/抽取器的表头判断，支持数值组成轴、跨行样品组继承、样品 colspan 分组列、
>     `Ox/Red = number` 复合值及频率/温度条件序列。14 张方向 fixture 均有输出，共 376 个候选，
>     `sample_label_not_found=0`；条件序列保持 `sample_label_raw=null`，条件写入 `conditions`。
> 57. demo20 runtime Shadow v0.4 为 59 表 / 935 候选 / 41 张有输出。与 v0.3 人工 fixture 回归时，
>     旧 538 格仍为 538/538，严格性质语义 538/538，可评价样品绑定 528/528，重复为 0；新增 15 张、
>     397 个候选尚需扩展人工格级 fixture，不得直接宣称为 100% 准确。
> 58. 固定 numeric eligible 分母仍为 51 张；当前 41 张有输出、10 张零输出，表级输出覆盖为
>     41/51 = 80.39%。两张 categorical eligible 表仍为 0/2，本轮没有实现定性值抽取。
>     新报告见 `reports/stage4t_table_structure_survey_v02_20260822.*`、
>     `reports/stage4t_table_property_shadow_v04_20260822.*` 与
>     `reports/stage4t_table_eligibility_audit_v04_runtime_20260822.*`。
>
> **v2.14 增补（Stage 4T 三层架构与结构解释契约）**
> 59. Stage 4T 改为“**宽抽取、窄发布**”：Stage 0 原始表格层保留单元格和表头结构；
>     Shadow 宽松候选层允许正式性质、material characteristic、未映射语义、定性值及条件状态；
>     权威发布层必须通过语义、样品、条件、值结构和 evidence 门控。97 项是规范化正式性质集合，
>     不是候选抽取上限。
> 60. Shadow v0.5 在 demo20 的 59 张表中生成 1602 条宽松候选：419 条正式性质、853 条
>     material characteristic、330 条 unmapped；55 张表有候选。全部候选均为
>     `candidate_only`，因为当前 sidecar 尚未解析稳定 `sample_id`，这是门控按设计生效，不是失败。
> 61. numeric eligible 的三层表级结果为：宽松候选 51/51（100%）、已有映射语义 46/51
>     （90.20%）、权威发布资格 0/51（0%）。候选覆盖只说明没有整表静默丢失，不能解释为性质准确率。
> 62. 新增独立 LLM 表结构解释契约：仅输出方向、轴角色、样品绑定策略、表头树/角色和列语义；
>     数据格数值以占位符脱敏，输出 Schema 禁止任何 value 字段。数值、单位和 cell provenance
>     仍由确定性代码从 Stage 0 读取。当前已接入默认关闭的 Preview 显式开关，尚未调用真实 LLM。
> 63. 首批复杂表 fixture 为 5 张 semantic-zero 表：`0021296/T_8_91`、`0038527/T_5_69`、
>     `0039705/T_6_84`、`0043541/T_4_49`、`0043590/T_1_19`。人工结构答案已冻结为
>     `stage4t_table_interpretation_fixture.v0.1`；完整性检查、fallback 状态和显式开关完成前，
>     不允许自动调用 LLM。
>
> **v2.15 增补（受控 LLM 结构解释路径）**
> 64. Preview sidecar 已接入 `--stage4t-llm-interpretation` 显式开关，默认关闭；该开关只能与
>     `--preview` 同用，且不能与 `--no-stage4t-sidecar` 同用。启用后解释调用受现有 LLM 并发槽约束，
>     仍不进入 Stage 4/4R 或权威发布输入。
> 65. `pipeline.yaml` 冻结首批 5 张人工 fixture 表的 allowlist 和 `max_tokens=4096`；即使显式开启，
>     未在 allowlist 中的复杂表也只记录 `not_in_approved_fixture`，不调用模型。
> 66. 完整性检查覆盖输出长度 finish reason、JSON 外省略标记、输出 Schema、真实 cell 引用、
>     空 assignment、缺 subject 轴和缺语义 assignment。任一失败均进入 `fallback_candidate_only`，
>     保留规则候选，不阻断 Preview。
> 67. sidecar v0.3 在 provenance 中聚合调用数、token 和费用，并进入 batch runner 既有费用审计；
>     配置失败不计远程调用，已发起但 usage 缺失时费用标记为 unavailable。缓存绑定 Stage 0 哈希、
>     配置哈希和解释器版本。产物不保存请求正文、API key 或模型响应正文，仅保留 provider/model/finish reason。
> 68. 本轮仅完成 mock/fixture 验证，未实际调用远程 LLM；Stage 4T 测试为 86 项通过。
>
> **v2.16 增补（5 张复杂表远程试跑与人工审计）**
> 69. allowlist 中 5 张表已使用 `gpt-5.6-terra-2026-07-09` 完成受控远程试跑；最终解释器版本
>     `0.4.0`、prompt `1.3.0`，5/5 响应通过完整性、Schema、真实 cell 引用和结构完整性校验，
>     无 fallback。
> 70. 首轮试跑暴露两类契约缺口并已修正：DMA/XRD 被误归为 official property；接触角只在首行组
>     声明 property，依赖隐式继承且漏掉首个 static 模式。当前字段所有权已收紧，condition/metadata
>     必须有 canonical 名，接触角 7/7 模式 cell 均同时具备 property 与 mode condition。
> 71. 新增 `stage4t_interpretation_audit.v0.1` 离线审计。最终同版本结果为：顶层方向/轴/绑定 5/5，
>     人工必需 assignment 56/56，缺失 0，额外解释 6；额外项仅为过程、阈值/温度 condition 和
>     unknown 标题，不构成错误性质发布。报告见
>     `reports/stage4t_llm_interpretation_audit_v01_20260822.{json,md}`。
> 72. 最终同版本运行消耗 25,867 token、0.872927 CNY。该数字是当前可复现 sidecar 的费用，
>     不包含 prompt 调试期间被覆盖的早期试跑。
> 73. LLM 解释目前仍只写入非权威 `interpretations`，尚未驱动确定性数值候选生成；因此 deterministic
>     semantic coverage 仍按 v0.5 的 46/51 计算，publication eligibility 仍为 0/51。Stage 4T 测试
>     为 90 项通过，extraction 全量为 643 项通过、1 项既有旧断言排除。
>
>
</details>

> **v2.17 增补（结构解释确定性应用层）**
> 74. 新增 `stage4t_interpretation_apply.py`：只消费已校验的表头 assignments，按 `cell_id` 与
>     `rowspan/colspan` 将性质、material characteristic、样品轴、条件轴和 measurement role 投影到
>     既有规则候选；数值仍从 Stage 0 原 observation 读取，不允许 LLM 回写或补造数值。当前应用器版本
>     为 `0.1.2`。
> 75. 5 张复杂表共输入 100 个旧规则候选；排除 `0038527/T_5_69` 中误作 observation 的 5 个
>     reflection-index 二级表头后，得到 95 个已映射语义候选：16 + 25 + 18 + 21 + 15。全部保留
>     `candidate_only`，权威发布资格仍为 0；`0043541/T_4_49` 中旧规则本就漏掉的 3 个格值未在本轮补造。
> 76. Preview sidecar 升至 v0.4。应用后的 `observations` 与原 `rule_observations` 并存，记录 assignment
>     source cell、排除项和冲突状态；语义多重冲突时保留原候选并增加 blocker，不静默择一。
> 77. sidecar schema 升级可在 Stage 0 哈希、配置哈希和 interpreter 版本一致时复用 v0.3 成功解释。
>     5 张实表离线升级均命中复用，本轮远程调用、token 和新增费用均为 0。
> 78. 沿用同一 51 张 numeric eligible 分母重算后，候选覆盖 51/51、语义覆盖 51/51、权威发布资格
>     0/51。51/51 只表示表级不再 semantic-zero，不代表 95 条新增候选已达到逐格准确率门槛；
>     报告见 `reports/stage4t_table_eligibility_audit_v06_interpreted_20260822.{json,md}`。
> 79. v0.6 合并报告共 1597 条候选（较 v0.5 的 1602 条少 5 个条件表头），全部为 `candidate_only`。
>     最终 Stage 4T 测试 95 项通过；extraction 全量 648 项通过，另排除 1 项既有“词表必须恰好 97 项”
>     旧断言（当前词表 99 项）。

> **v2.18 增补（新增候选逐格 fixture 底稿）**
> 80. 新增 `stage4t_candidate_precision_fixture.v0.1`，覆盖 5 张复杂表的 95 条应用候选，逐条保留
>     `cell_id`、值原文、性质语义、样品、条件、单位、measurement role 和 candidate class。
>     当前状态是 `provisional_seed / pending_human_review`，自动种子只能作为人工标注底稿，不构成准确率结论。
> 81. 新增 `stage4t_candidate_precision_audit.py` 和只读审计报告。当前结构审计为：预期/实际 95/95，
>     缺格 0、多格 0、重复 0、值/语义/样品/条件/单位/角色不一致均为 0；5 张表的候选仍全部为
>     `candidate_only`。下一步是逐格人工复核并冻结 fixture，而不是直接放行 4T。

> **v2.19 增补（expected-cell 召回底稿）**
> 82. 新增 `stage4t_candidate_precision_fixture.v0.2`：在 v0.1 的 95 条实际候选之外，
>     将 `0043541/T_4_49` 已定位但尚未产出的 3 个 contact-angle cell 纳入 expected-cell 集合：
>     `r0002:c0002`（advancing，13°）、`r0003:c0002`（receding，<5°）和
>     `r0004:c0002`（sliding，15°）。这些记录来自 Stage 0 原始表格，只用于召回审计，
>     不伪造 Stage 4T 实际输出。
> 83. v0.2 **补抽前**结构审计结果为 expected 98、actual 95、matched 95、missing 3、extra 0、duplicate 0，
>     当时数值格结构召回底线为 `95/98 = 96.94%`；字段不一致暂为 0。该比例不是人工准确率，
>     仍须逐格确认预期语义、样品、条件、单位和值结构后才能冻结评测门槛。下一步优先补抽这 3 格，
>     并继续扩展其他新增表的 expected-cell 集合。

> **v2.20 增补（已知漏格确定性补抽）**
> 84. 修复 `_candidate_value_like` 对“数字 + 度数符号 + 单字母脚注”值的识别，承接
>     `0043541/T_4_49` 的 3 个 contact-angle cell（`13°`、`<5°`、`15°`），不放宽为任意含字母文本。
>     5 张复杂表实际候选由 95 增至 98，解释应用后仍全部为 `candidate_only`。
> 85. v0.2 审计现为 expected/actual/matched `98/98/98`，missing/extra/duplicate 均为 0，
>     结构召回为 `100%`。这只证明当前已知 expected-cell 集合均有可审计输出，不等于人工准确率；
>     仍需逐格确认语义、样品、条件、单位和值结构，并继续扩展其他新增表的 expected-cell 集合。

> **v2.21 增补（定性溶解性表与扩展 fixture）**
> 86. 对已复核为 categorical eligible 的两张溶解性表增加确定性列式抽取：
>     `0020284/T_5_74` 产生 66 条、`0038813/T_7_98` 产生 48 条 `solubility` 候选；
>     `+ / ++` 归为 soluble，`+− / ±` 归为 partially_soluble，`−` 归为 insoluble，
>     原始符号仍保留在 `value_raw`，溶剂列写入 `conditions.solvent`。两张表仍全部 `candidate_only`。
> 87. 新增 `stage4t_candidate_precision_fixture.v0.3`，覆盖 7 张表、212 条候选
>     （98 条数值 + 114 条定性溶解性）。当前 provisional 结构审计为 `212/212` 命中、
>     缺格/重复/字段不一致均为 0；该结果只说明当前底稿与 sidecar 一致，不能替代人工准确率。
>     下一步是逐格人工确认新增 114 条定性候选，并继续扩展其余新增表的人工 expected-cell 集合。

> **v2.22 增补（4N/4T 候选契约边界）**
> 88. Stage 4T 候选现在显式携带 `candidate_role`、`candidate_state=raw_candidate`、
>     `evidence_locator` 和 `warnings`。`evidence_locator` 至少包含 `source=table`、
>     `table_id`、`cell_id`、行列坐标、初始表头路径和轴角色；数值仍只来自 Stage 0 原始 cell。
> 89. 4T 可扩展语义范围，但不放宽证据和结构约束：温度/频率/配方/编号等不得仅因含数字
>     就成为性质候选；计算结果、未知数值、material characteristic 和定性值必须保留角色。
>     后续 4R 只允许在保留 raw、差异、规则/版本、理由、置信度和人工复核标记的前提下做有限修复，
>     不重新解释整篇正文或整张表，也不得创造原文没有的数值、样品或条件。

> **v2.23 增补（逐格完整性、证据关系与最终实施顺序）**
> 90. 完整性目标从“eligible 表有输出”提升为“Stage 0 已识别的 eligible data cell 均有明确去向”。
>     去向包括 observation candidate、condition、composition、identifier、calculated result、
>     candidate partial 或带原因拒绝；表头、样品轴和条件轴 cell 是证据节点，不进入观测分母。
> 91. 4N/4T 只统一输出契约，不统一抽取算法。4N 必须保留句子/段落位置，4T 必须保留
>     cell、表头路径和轴角色；允许放宽语义范围，不允许放宽证据真实性和来源约束。
> 92. 4R 限定为局部修复和规范化，并以 unified shadow 与 legacy 并行运行。正文/表格候选关系
>     明确分为 exact、rounded、summary_detail、condition_distinct、citation_only、source_conflict
>     和 independent；未解决冲突不得进入单值权威字段。

> **v2.24 增补（4R Preview 跑通与 Stage 5 全文分片）**
> 93. Preview 已接入 `stage4r_unified_preview.py`。5 篇真实试跑中，4T 共生成 685 条候选，4R 新合入
>     69 条、合并同格重复 40 条；5/5 生成 Stage 4T、4R、Stage 5、Stage 6 与 candidate 关键产物，
>     Stage 6 均为 0 errors。该结果证明接线可运行，不等于 4T 已满足权威接管门槛。
> 94. Stage 5 当前仍是每篇一次请求。5 篇中 3 篇因 `max_tokens` 截断、`source_text/source_sentence`
>     字段差异或单元素 `series_ids` 校验失败而生成 `preview_degraded_empty_shell`，说明整篇原子失败
>     会放大局部错误。所有文章统一改为证据路由、分片抽取、逐对象修复和确定性合并。
> 95. Stage 5 主分片键为“规范化表征方法 + 局部证据区域 + measurement instance”，不以 Sample
>     为首要拆分轴。每个 shard 独立保存输入清单、原始响应、解析诊断、校验结果和状态；只重试失败
>     shard，局部失败标记 `candidate_partial`，不得把空壳记为 success。

> **v2.25 增补（Stage 5 内部步骤收敛）**
> 96. 不再把路由、抽取、逐对象保留和合并命名为 `Stage 5I/5E/5S/5M`。外部仍只有一个 Stage 5，
>     内部收敛为 `plan_shards()`、`extract_shard()`、`merge_shards()`；逐 Characterization/Property
>     校验与有效对象保留属于 `extract_shard()`，不是独立 Stage，也不增加一次模型调用。
>
> **v2.26 增补（Stage 5 Preview 分片落地与定向验证）**
> 97. Preview 默认启用按规范化表征方法分片，目标/硬上限为 18k/30k 字符，单 shard 输出预算 12k token；
>     Strict 默认继续使用旧整篇路径。`source_text`、单元素 `series_ids` 已作确定性兼容，坏对象不再清空
>     同 shard 合法对象；`merge_shards()` 负责稳定重编号和引用修复。
> 98. `stage5_shards.json` 升至 v0.2，保存 raw response、解析/校验状态和对象数量。旧 v0.1 sidecar 仅在
>     文档级 `1.8.0` cache key 与 shard 的方法、block、大小信息全部匹配时允许离线回放；回放重新执行
>     当前校验，不调用模型，并写回当前 key/result。
> 99. 定向结果：0020284 为 6 shard、5 Characterization/50 Property、`candidate_partial`；0038527 为
>     6 shard、5/6、`success`；0038813 为 10 shard、8/36、`candidate_partial`。三篇 Stage 6 均为
>     0 errors，并已重建 candidate 人审报告。该结果解决整篇空壳，不代表局部语义问题已经修复。

---

# 1. 背景

当前高分子文献自动抽取系统以 PolyInfo 数据结构作为参考，对已有性质覆盖情况进行评估。

初始评价主要围绕已定义的核心 property、Stage 4/Stage 5 抽取能力、PropertyObservation 召回率。

近期对 PolyInfo 与当前 schema 进行逐项比对后发现：

> 当前缺失并不主要来自核心性能性质不足，而是来自 PolyInfo 中另一类挂载于 Sample 对象上的 specialized properties。

三方核查（自查 + GPT 批评 + GPT 反驳）新增结论：

> Stage 4 本身存在已定位的代码缺陷，导致 0814 批次约 12% 的 GT 点落在空壳文档中无法参与评估。Schema 扩展必须在稳定性修复之后推进。

因此需要重新审视：

1. Stage 4 稳定性缺陷的修复次序；
2. 召回率指标如何冻结与命名；
3. 哪些性质应该进入 property[]；
4. 哪些信息应该作为 Sample/PolymerEntity 的属性；
5. Stage 4、Stage 5、Stage 6 如何分工。

---

# 2. PolyInfo 性质缺口分析

## 2.1 核心性质（property_groups）覆盖情况

PolyInfo catalog 中通用性质共 33 项。经过 polymer_schema.yaml 比对、同义词映射、字段名称差异修正后确认：

> **33 项核心性质全部已有对应槽位。当前核心性能 ontology 不存在结构性缺失。**

例如 `tensile_stress_strength_at_break` → `tensile_stress_at_break`，`theta_temperature` → `theta_solvent_theta_temperature`。

---

## 2.2 真正缺失的 9 项 specialized_properties

缺失性质均来自 PolyInfo 的 specialized_properties，挂载于 **Sample 对象**而非 property[] 通道，因此从未进入 695 分母。

已对 19 篇文档（186 个样品，排除 reference_no_0025452）逐项核查 GT：

| # | 字段 | 中文 | GT 文档 | GT 样品 | 可定位数值 | 备注 |
|---:|---|---|---:|---:|---:|---|
|1|average_molecular_weight|Mw/Mn/Mv/Mp|7|59|87（72 在表格）|列表结构，见 §6.1|
|2|solution_viscosity|溶液黏度|5|42|42|全部为 η_inh|
|3|crystallinity|结晶度|5|43|20|另 23 个仅有 state_after_molding|
|4|degree_of_polymerization|聚合度 DP|2|20|20|实测范围 13~350|
|5|crystallographic_data|晶面间距 d|3|16|45 个 d_value|XRD 表|
|6|primary_structure_informations|一级结构|8|76|84 数值 + 38 描述|暂缓|
|7|morphology|形貌|3|13|**0**|见 §7.3|
|8|stereoregularity|立构规整性|0|0|无 GT|暂缓|
|9|characteristics_of_material|材料特征|16|186|0|纯描述型|

**位置分布（298 条数字型 GT）**：表格 273（91.6%）/ 正文 23（7.7%）/ 原文未定位 2（0.7%）。
源文可定位合计 296。另有 44 条纯描述型（primary_structure 38 + morphology 6），不计入数字型统计。

> 早前版本的 309/284 已失效：其中含 morphology 的 11 条，系 `locate_missing_props.py` 从
> `chi23=-0.15`、`core–shell ratio=6:4` 等字符串中正则误抽的数字，实际可抽取形貌数值为 0。

若全部并入分母：695 → 993，0817 召回率从 45.0% 降至约 31.5%。该下降不反映系统能力，故不建议直接并入。

---

# 3. 召回率指标冻结

## 3.1 为什么改称"召回率"

当前匹配逻辑为**非排他匹配**：一条预测行可被多条 GT 点同时声明，且没有精确率指标。因此该数字衡量的是"GT 点被命中的比例"，应称**召回率（Recall）**而非覆盖率（Coverage）。

原方案 §3.2 的 "Core Property Coverage" 命名不成立：695 分母中包含 A1（失重档位，属测量条件）与 B（互为倒数对），并非纯粹的核心性质集合。

---

## 3.2 四条数值口径（冻结状态见下）+ 定性口径单列

以下口径并行记录，互不取代。**四条均只统计数值型 GT 点**，定性信息另立一栏、不设总分母：

| 口径 | 分母 | 0817 严格 | 0817 可信 | v2.2 当前实测 | 说明 |
|---|---:|---:|---:|---:|---|
| **Legacy** | 695 | 265 / 38.1% | 313 / 45.0% | 265 / 38.1%；313 / 45.0% | 历史对齐口径，**不可变**（见下） |
| **Curated** | **526** | **263 / 50.0%** | **303 / 57.6%** | **267 / 50.76%；307 / 58.37%** | 剔 A1(76)+B(70)+D(2)+A2 配对设定温度(21)；左侧为文档冻结参考，右侧为当前实测 |
| **Extended-numeric-all** | 993 | — | — | — | Legacy + 全部数值型 specialized(298)，**未冻结** |
| **Extended-numeric-locatable** | 822 | — | — | — | Curated + 源文可定位 specialized(296)，**未冻结** |

### Curated 为何是 526 而非 547

A2 的 21 组在旧 GT 中占 **42 行**（每组 1 条设定温度 td + 1 条质量比例 td_wl）。迁移后应归并为
**21 条规范 Observation**，设定温度降级为 `condition.temperature`，不再是独立性质点：

```
旧 GT（2 行）                          迁移后（1 条 Observation）
td     = 600°C   ┐                    thermal_mass_fraction_at_temperature
td_wl  = 73%     ┘   ──────────►        quantity_kind = residual_mass_fraction
                                        value         = 27%
                                        condition.temperature = 600°C
```

已验证：这 21 条配对设定温度行（0020284×11 @600°C、0021296×4 @800°C、0037645×6 @800°C）
`match_tier` 与 `pred_value` **全部为空**；而同批其余 26 条 td 行全部 exact 命中，切分干净。
分子不变（本就 0 命中），故 526 的两个百分比均来自分母收缩。

547 - 21 = **526**

文档中的 **263/526、303/526** 是迁移口径确定时的冻结参考值；版本化 matcher
`curated_manifest_v2.2.json` 记录的当前实测为 **267/526（严格）、307/526（可信）**。两者差异为 4 条
`reference_no_0021296` 的 `% residue (N2) at 800°C` 观察在 A2 迁移后恢复为
`residual_mass_fraction`，并与 preview 表格序列 exact 命中。该差异已写入 manifest，后续对外报告
应同时给出 GT/matcher 版本与差异解释，不能将两套数字混写为同一批次结果。

### Extended 两条口径尚未冻结

993 / 822 为按修正后清单重算所得，但在 specialized GT 完成规范化重跑前**不正式冻结**，仅作规模参考。

### 为什么加 `numeric` 限定词

原名 `Extended-all` 会被读成"全部材料信息"，但它只统计**可定位数值**，把 PolyInfo 中大量定性信息
排除在外。这些信息不是噪声，只是不能进召回率分母（无数值可比对）：

| 定性项 | 条数 | 来源 |
|---|---:|---|
| crystallinity 结晶状态 | 23 | GT `crystallinity.state_after_molding`（Crystal / Amorphous / …，与 20 条数值结晶度互不重叠）|
| primary_structure 描述 | 38 | 纯文字结构描述 |
| morphology 描述 | 6 | χ23、core–shell 比等非数值表述 |
| **Extended-qualitative** | **67** | **单独统计，不并入任何召回率分母** |

上表 23 条已独立核验：19 篇评估文档 218 个样品文件中，`crystallinity` 非空且不含数字的共 23 条。
定性项的验收方式是**结构承接率**（能否被 §12 的 `categorical_value` 正确接住），不是召回率。

### 指标变动规则（替代原"单调递增"条款）

原"数字只能单调递增"的规则**已删除**——它会把修复错误匹配误判为回退。例如黏度错桶修复后，
现有 4 条假命中消失、召回率下降，这是修对了而不是退步。改为：

1. **GT 版本与匹配器版本必须固定**，任一变更需同时记录两个版本号；
2. **任何指标变化必须给出解释**，注明是能力变化还是口径/匹配逻辑变化；
3. **联合验收**：召回率、准确率、假匹配数三者同时呈报，不得仅以召回率作为门控；
4. 现有 4 条黏度命中须**逐条确认语义正确性**，不得为保住数字而保留错误匹配。

---

# 4. Stage 4 稳定性缺陷（P0 — 先于 Schema 扩展修复）

## 4.1 问题规模

0814 批次中有 4 篇文档因 Stage 4 降级产生空壳，涉及 85 个 GT 点，占 695 分母的 12%。0817 **未再复现**其中 3 篇（Pydantic schema 校验失败），但新增了 1 篇（`llm_client.py` 围栏解析触发）。（措辞谨慎：目前只能确认现象未复现，无证据表明是代码修复所致，也可能是模型输出随机性。）

| 批次 | 空壳文档 | 涉及 GT 点 | 占 695 |
|---|---|---:|---:|
| 0814 | 0021296 / 0037645 / 0043541 / 0033617 | 85 | 12% |
| 0817 | 0043955 | 12 | 2% |

---

## 4.2 缺陷一：`llm_client.py` JSON 围栏解析

**文件**：`testcode/extraction/llm_client.py:298`，函数 `extract_json_object`

**缺陷**：围栏正则 `` re.search(r"```(?:json)?\s*(.*?)\s*```", ...) `` 先于 `json.loads` 执行，且 `re.search` 在文本中**任意位置**匹配。当模型输出"裸 JSON 正文 + 尾部围栏注释"时，正则捕获的是尾部围栏内的中文注释（无 `{`），导致大括号切片失败并抛出 `LLMRequestError`。

**实物证据**（`demo20_preview_final_20260812/reference_no_0043955/stage4_llm_response.json`）：

- `raw_response.content` 长 18612 字符；JSON 正文到 18526 结束；末尾 85 字符为围栏注释。
- 离线重放 `extract_json_object` 复现 `LLMRequestError: LLM 响应中没有 JSON 对象`。
- 裸切片 `[0:18526]` 可解析出 `measurement_conditions=4, properties=10, property_series=1, points=1`。
- 注意：0043955 同时存在第二个独立问题——模型**主动省略**了表格序列（`finish_reason=end_turn`，
  `output_tokens=13630` 远低于 `max_tokens=128000`）。这不是长度截断，提高 max_tokens 无法修复。

### 4.2.1 修复算法（固定顺序）

"大括号切片 / 最外层围栏"仍会被尾随 `{}`、多个围栏干扰。改为固定五步：

```
1. json.loads(完整文本)                    ← 整体即合法 JSON，直接返回
2. JSONDecoder.raw_decode(从首个 "{" 起)   ← 取第一个完整对象，天然忽略尾随内容
3. 检查并记录尾随文本                       ← 非空则记入 warnings，供 4.2.2 判定
4. 遍历所有围栏块，逐个尝试解析，取首个可解析的 JSON 对象
5. 以上均失败 → 抛出，并保存 raw response
```

关键是第 2 步：`raw_decode` 只消费第一个完整对象并返回结束位置，尾部有什么都不影响解析结果。

**新增诊断接口，但保留原接口兼容性。** 现签名 `extract_json_object(text) -> dict[str, Any]`
（`llm_client.py:298`）只返回数据体，第 3 步记录的尾随文本无处存放，出函数即丢弃，
§4.2.2 的完整性判定就无从做起。但该函数同时被 Stage 1~5 的离线回放调用，直接改变
返回类型会扩大 P0 改动面。采用以下兼容结构：

```
ParsedJSON
    data           解析出的对象
    prefix_text    首个 "{" 之前的文本（围栏说明、前言）
    trailing_text  raw_decode 结束位置之后的文本
    parse_source   direct | raw_decode | fence[i]
    warnings       [has_trailing_text, multiple_fences, ...]

parse_json_response(text) -> ParsedJSON
extract_json_object(text) -> parse_json_response(text).data
```

在线调用路径使用 `parse_json_response`，并由 `LLMJSONResponse`（或等效载体）承接诊断字段；
旧回放调用可继续使用 `extract_json_object`。Stage 4 必须取得诊断字段并据此判定完整性，
其余 Stage 再按测试覆盖逐步迁移，不能因兼容包装而丢失 Stage 4 的完整性告警。

### 4.2.2 完整性判定（不可仅凭解析成功）

**解析出 10 条性质 ≠ 抽取成功。** 0043955 尾部写明：

> 注：因表格全量序列点数量过多，以上仅保留示例序列（series001）和首个点（pt001），完整输出需补全所有表格对应序列、点及属性。

必须检测此类"仅保留示例 / 需补全 / 完整输出应包含"表述，命中则判为**不完整响应**，
**禁止以成功状态发布**。否则残缺表格会被当作成功入库，比解析失败更危险——失败至少可见，残缺则静默。

**检测范围必须限定在 JSON 之外。** 只扫描 `prefix_text` 与 `trailing_text`，
**不得扫描 `data` 内部**。论文原文本身可能出现"完整数据见补充材料"之类措辞，
扫进去就是稳定误报，会把正常抽取打成不完整。

**判定后的动作分当前架构与目标架构，不可混写：**

| 架构 | 重试粒度 | 仍不完整时 |
|---|---|---|
| **当前 Stage 4** | 整篇单次请求，无表级子任务 → 只能整篇重试 1 次 | 标记 `candidate_partial` |
| **目标 Stage 4T** | 仅重试缺失的表格 / 列 | 该表标记 `candidate_partial`，其余表正常发布 |

原文写"触发局部重试"在当前架构下不可实现——Stage 4 一次请求覆盖整篇，没有可局部重发的单元。

**建议将 `0043955/stage4_llm_response.json` 固化为解析器回归测试 fixture**，
同时覆盖两个断言：能解析出 10 条性质，且被正确标记为不完整响应。

---

## 4.3 缺陷二：两条空壳降级路径

**文件**：`testcode/extraction/stages/stage4_property.py`

**路径 1（约 L6389）**：顶层解析或 Pydantic schema 校验失败后，preview 模式直接生成 `PropertyStageResponse()`（空壳），原因写入 `preview_degraded_reason`。0814 的 3 篇失败（0021296/0037645/0043541）均属此路径，`_validation_feedback(exc)` 已组装好反馈文本，单次重试大概率可修复。

**路径 2（约 L6420）**：物化失败且逐对象挽救也失败时，同样降级为空壳。

正常空路径（entities 为空）创建 `PropertyStageResponse()` 是正常业务分支，不是故障，不计入上述两条路径。

### 4.3.1 修复后的三态定义

仅写"修复两条路径"不足以约束实现，必须定义修复后的终态：

| 情形 | 终态 | 产物 |
|---|---|---|
| 部分对象可结构化 | `candidate_partial` | 保留全部有效对象，标记部分成功，记录被丢弃对象及原因 |
| 完全无法结构化 | **Stage 失败** | 保存 raw response 与 failure 详情，供离线复盘 |
| 响应被判为不完整（见 §4.2.2） | `candidate_partial` | 同上；当前架构整篇重试，Stage 4T 才允许表级局部重试 |

**禁止以成功状态发布 degraded 空壳。** 当前实现把空壳当成功输出，
下游无法区分"这篇确实没有性质"与"这篇抽取失败了"，是 0814 的 85 点长期未被发现的直接原因。

**状态必须跨 Stage 传递，不能只停留在 Stage 4 warning。** 当前 batch runner 只在某个 Stage
非零退出、随后发布候选结果时设置 `candidate_partial`；如果各 Stage 正常退出，流程末尾会固定写成
`candidate_complete`。因此实现必须满足以下状态链：

```text
Stage 4 输出有效部分 + 机器可识别的 blocking warning
    -> batch runner 记录文档级 partial 标志
    -> 继续运行 Stage 4R / 5 / 6
    -> 流程结束仍写 candidate_partial，不得被 candidate_complete 覆盖

Stage 4 完全无法结构化
    -> Stage 4 非零退出
    -> 保存 failure 与 raw response

failure replay 仅生成 degraded 空壳
    -> 不得标记为 recovered，也不得按成功结果发布
```

`blocking warning` 必须是结构化、可枚举的信号，batch runner 不应依赖自然语言字符串匹配。

### 4.3.2 0814 四篇的验收须分别列出

四篇故障并非同一类，不能用"三篇恢复"代表全部 85 点：

| 文档 | GT 点 | 故障类型 | 失败信息 |
|---|---:|---|---|
| 0021296 | 38 | Pydantic 校验 | `property_series.10.points.1.coordinates.0.evidence: Field required` |
| 0037645 | 30 | Pydantic 校验 | `aggregate series_ids 包含不兼容的 PropertySeries` |
| 0043541 | 15 | Pydantic 校验 | `property_series.1.points: List should have at least 1 item` |
| **0033617** | **2** | **语义校验** | `series point 至少关联 Sample 或 PolymerEntity` |

前三篇合计 83 点属 Pydantic 类，一次校验重试大概率可修复；**0033617 是语义校验失败，属另一类问题**，
须单独验收，否则 85 点无法闭环。

---

## 4.4 缺陷三：`max_validation_retries` 全局为 0

**文件**：`testcode/extraction/config/pipeline.yaml`，L59/64/70/77/84

所有五个 LLM Stage 均设 `max_validation_retries: 0`。网络重试（`max_retries`）与校验重试是**独立配置**（`max_retries: 2` 已有先例）。

**修复建议**：仅对 Stage 4 将 `max_validation_retries` 调为 1，观察 0814 三篇 schema 失败文档恢复情况后再决定是否推广到其他 Stage。

---

# 5. 9 项性质分类

| 类别 | 内容 |
|---|---|
| 第一类（立即支持） | Mw/Mn、η_inh、DP、thermal_mass_fraction（A2 21 组） |
| 第二类（优先检查） | crystallinity、crystallographic_data |
| 第三类（暂缓） | morphology 对齐、primary_structure、stereoregularity、characteristics_of_material |

---

# 6. 第一类：立即支持

## 6.1 Molecular weight — 用可重复 Observation 表达

GT 中 `average_molecular_weight` 是**列表**：len=1 的 31 个样品，len=2 的 28 个样品（多值集中在 0037645×6、0038527×14、0038813×8）。条目 kind 分布 Mn 41 / Mw 40 / Unknown 6，数值范围 2000~6.6×10⁶，每条目自带 `average_molecular_weight_measurement_method`。

因此**不应用固定字段**（原方案 §4.1 的 Mn/Mw/Mv/Mp/PDI 各一槽），应用可重复 Observation：

```
Sample.molecular_weight_observations[]
  ├── kind            Mn | Mw | Mv | Mp | Unknown
  ├── value
  ├── unit
  └── measurement_method
```

**PDI 说明**：GT kind 枚举只有 Mn/Mw/Mv/Mp/Unknown，没有 PDI。PDI 无法用本批 GT 验证，可以在 schema 中保留为派生量，但不纳入召回率分母。

---

## 6.2 Solution viscosity — 四分桶，两处同步修复

现状缺陷（比原方案描述更严重）：

- `table_recall_audit.py:75`：四种后缀 `inh|int|sp|red` 塌陷进同一个 `intrinsic_viscosity` 桶，且后缀分组标记为可选（`?`），**裸 `η` 也命中该桶**。
- `polyinfo_coverage_matcher.py:128`：评分侧做了同样的塌陷。

**两处必须同步修改。** 若只改抽取侧不改评分侧，现有 4 条黏度命中会在评分时消失，看起来像回退。

**四个量各自独立，不得三分**（早前版本把 η_red 与 η_sp 并为"其余"，是错的）：

| 规范名 | 记号 | 中文 | 定义 |
|---|---|---|---|
| `inherent_viscosity` | η_inh | 对数黏数 | ln(η_r)/c |
| `intrinsic_viscosity` | [η] | 特性黏数 | c→0 时 η_sp/c 的极限 |
| `reduced_viscosity` | η_red | 比浓黏数 | η_sp/c |
| `specific_viscosity` | η_sp | 增比黏数 | η_r − 1 |

四者量纲与物理含义均不同（η_sp 无量纲，其余为 dL/g），互相不可替代。

本批 42 条 GT 值 **42/42 均为 η_inh**。同时保存单位、测量方法、溶剂、温度、浓度。

---

## 6.3 Degree of polymerization

原方案"必须区分 DPn/DPw/unknown"**没有 GT 支撑**：GT `degree_of_polymerization` 无 kind 字段。schema 可预留 kind，但不作为强制要求。

物理范围：本批实测 **13~350**（完整值集 13/14/29/34/39/52/58/59/69/74/84/334/338/339/341/347/350），原方案"20~200"过窄，会误杀 13 和 14。

建议：硬检查 `DP > 0`；极端值（< 10 或 > 10000）仅触发 warning。

---

## 6.4 Thermal mass fraction at temperature（A2 21 组）

从 Td 讨论中切出，归入第一类——这是**唯一能合法提升已发布数字的工作**（21 组当前 0 命中）。

**槽位命名**：不用 `thermal_mass_change_at_temperature`——residual mass 是**剩余比例**而非"变化量"，
用 change 描述会与失重量混淆。改用 `thermal_mass_fraction_at_temperature`，
以 `quantity_kind`（`residual_mass_fraction` / `mass_loss_fraction`）区分两个互补的比例量。

### 6.4.1 A2 的三组构成与证据状态

21 条 A2 **并非同一物理量**。逐条核查 GT `remark` 与原文后确认分为三组：

| 组 | 条数 | GT remark | 原文报告的量 | GT 存的值 | 证据状态 |
|---|---:|---|---|---|---|
| 0020284 | 11 | `Converted from residual mass X%` | residue % | wt loss %（PolyInfo 已换算并声明） | 确认，`100−td_wl` 与 remark 数字 11/11 精确一致 |
| 0021296 | 4 | 无 remark | `% residue (N2)` | wt loss %（由 `1 − residue` 得来） | 已人工确认 |
| 0037645 | 6 | `Total wt. loss at 800C` | `wt loss (%)`（TGA 表） | wt loss %（原样） | 已人工确认，**不得换算** |

0037645 原文表头为 *Table 2. Differential Scanning Calorimetry (DSC) and Thermogravimetric Analysis (TGA) Data for the Boron Quinolate Polymers*，报告的就是失重量。

**0037645 一组不做 `100 − x` 换算**，理由：

1. 原文没有报告 residual mass；
2. PolyInfo 在 0020284 组换算时明确写了 `Converted from residual mass`，说明它换算时会声明——本组没有声明即未换算；
3. 本组 evidence 是 `wt loss (%)` 而非 `residue (%)`，凭空补一步换算没有原文依据。

**不换算 ≠ 不处理**：这 6 条照常进入 GT 与抽取范围，只是以"失重量"这一基准存放。

### 6.4.2 槽位设计：基准必须显式声明

三组的角色判断一致（温度是设定值），但**被测量的物理量不同**：0020284/0021296 报残余质量，0037645 报失重量。若用单一含义固定的槽位承接，必然要在某处隐式做 `100 − x`。

因此槽位改为：

```
Property: thermal_mass_fraction_at_temperature
  ├── quantity_kind  residual_mass_fraction | mass_loss_fraction   ← 原文报告的是哪个量
  ├── value          (%)
  ├── reported_term  原文用词（char yield / residue / total wt. loss / …）
  └── condition      temperature
```

**抽取侧规则**：一律存原文报告的量，`quantity_kind` 记录其种类，**抽取阶段绝不做 `100 − x`**。

**匹配侧规则**：换算不取消，而是从抽取侧挪到匹配侧——仅当两侧 `quantity_kind` 均已显式声明且互为补集时，才允许按 `100 − x` 判等，且该次换算必须写入日志可追溯。

这样处理后：

- 0037645 抽取得 `quantity_kind=mass_loss_fraction, value=75`，与 GT 同基准直接比对，不触发换算；
- 0020284 / 0021296 抽取得 `quantity_kind=residual_mass_fraction, value=25/34`，由匹配层做一次显式换算后与 GT 的 wt loss 比对。

若不加 `quantity_kind`，0020284 与 0021296 的原文（报 residue）与 GT（存 wt loss）将必然失配。

保留 `reported_term` 的原因：原文用词不统一（char yield / residue / total wt. loss），但语义同族，不应在归一化时丢失原始表述。

### 6.4.3 迁移前置项

TSV 中这 21 条的 `pair_row` 列为空——配对 td 行的行号未回填。GT 迁移前必须先补齐配对关系，否则取不到"设定温度"这一条件值。

---

# 7. 第二类：优先检查

## 7.1 Crystallinity — 原方案前提已被证否

原方案 §5.1 推测"可能不是抽取失败，而是 Stage5 → Stage6 输出链丢失"。核查结论：

- 0817 产物中 crystallinity 共 3 条记录，**全部**来自 reference_no_0042367；
- GT 的 20 条 crystallinity 数值分布在 0020284 / 0021296 / 0037268 / 0038527 / 0042246；
- 两组文档**零重叠**。

因此这不是输出链问题，是**真实抽取缺口**。同样的零重叠也出现在 d_spacing（我方 0 条，GT 45 条）和 morphology 尺寸（我方 7 条在 0042246/0043590，GT 在 0037268/0039705/0101911）——原方案 P3"检查是否已抽取但未进入最终数据库"的整个前提不成立。

追加约束：GT 的 43 个 crystallinity 样品中只有 20 个带 `crystallinity_min` 数值，其余 23 个只有 `state_after_molding: ["Crystal"]`。Schema 必须同时表达：

1. 数值结晶度（%）；
2. 仅有定性状态（Crystal / Amorphous / Semicrystalline）而无数值。

**所有权必须唯一**：`polymer_schema.yaml:161` 的 `xrd_crystallinity` 已在 `stage5_property_vocabulary` 中，不能同时被 Stage 4 认领，否则会产生双写与重复计数。

---

## 7.2 Crystallographic data（d-spacing）

GT 共 **45 个 `d_value` 条目**，分布在 0020284 / 0021296 / 0038527；0817 产物 d_spacing 命中 **0**。

`polymer_schema.yaml:161` 附近已有 `xrd_diffraction_peak_2theta`、`raman_peak_wavenumber`、`saxs_scattering_peak` 等 Stage 5 词表条目，但未产出 d_spacing。

建议结构：

```
Characterization.XRD
  ├── 2theta
  ├── d_spacing
  ├── intensity   ← 无 GT，暂不纳入召回率分母
  └── hkl         ← 无 GT，暂不纳入召回率分母
```

原方案给出的四字段结构本身合理，但须标注 intensity/hkl 无法用本批 GT 验证。

---

## 7.3 Morphology — 暂缓 PolyInfo 对齐，信息改道

原方案 §5.3 提出 `morphology_type / feature_size / particle_size / fiber_diameter / aspect_ratio / method / evidence` 结构。核查结论：**本批 13 条 GT 值全部不是尺寸型数值**：

| GT 实际内容 | 条数 | 真实语义 | 正确去向 |
|---|---:|---|---|
| `[mesophase]grainy(POM)` | 5 | 定性形貌描述 | 文本字段，无数值槽 |
| `[mesophase]unidentified(POM)` | 1 | 定性形貌描述 | 文本字段 |
| `Partially / Strongly compatible [IGC, chi23=…]` | 6 | 相容性参数 χ23 | `polymer_compatibility_parameter` |
| `core–shell ratio=6:4` | 1 | 组分结构比 | `component_structure.composition_ratio` |

原方案的尺寸类槽位在本批 GT 中**无一条适用**。这些字段设计本身没错，但 PolyInfo morphology 对齐工作应暂缓，等有对应 GT 时再设计。

**信息不丢弃，改道处理**：χ23 → `polymer_compatibility_parameter`；6:4 → `component_structure / composition_ratio`。

附注：`polyinfo_missing_properties_20260819.tsv` 中 morphology 的"11 可定位数值"是错的——该数字来自 `locate_missing_props.py` 从 `chi23=-0.15`、`core–shell ratio=6:4` 等字符串中正则抽取的数字。实际可抽取的形貌数值约为 0。

---

# 8. 第三类：暂缓

**8.1 Primary structure information** — 属 PolymerEntity / Sample 结构描述而非性能，包含主链、侧链、取代方式、重复单元、立构描述。需要独立的结构描述模块，暂缓。

**8.2 Stereoregularity** — GT 0 篇 / 0 样品，无验证数据，暂缓。

**8.3 Characteristics of material** — 描述型（high thermal stability / flexible / transparent），16 篇 / 186 样品但 0 数值。需建立 `qualitative_material_attribute`，暂缓。

---

# 9. Td / Td_wl 问题分析

这是当前最重要的 ontology 修正。过去认为 `td_wl = 测量条件`，重新检查发现 97 条 td_wl 点中并非全部如此，需按角色拆为 A1 / A2。

## 9.1 情况 A1（76 条）：失重是设定值，温度是测量值

例如 `5% weight loss temperature`、`10% weight loss temperature`、`50% weight loss temperature`。

固定失重比例，测量温度。应表示为：

```
Property : thermal_decomposition_temperature
Condition: weight_loss_percentage = 5%
```

**建议**：在召回率统计中剔除（Curated 口径中标记 `drop_A1_tdwl_level`，76 条）。理由：它们不是新增性质，而是同一性质的不同测量条件。

但抽取系统**必须保留条件字段** `weight_loss_percentage`，不得直接丢弃档位信息。

现状核查：0817 有 12 条名称含 "weight loss" 的记录，全部在 0039705，均为 `thermal_decomposition_temperature` 序列（`5% weight loss temperature` / `50% weight loss temperature`）——档位只存活在名称字符串里，从未作为独立的条件字段值。归一化为 `thermal_decomposition_weight_loss` 的记录为 0 条。

---

## 9.2 情况 A2（21 条）：温度是设定值，质量变化是测量值

例如 `Char yield at 700℃`、`Total wt. loss at 800℃`。固定温度，测量质量变化百分比。应表示为：

```
Property : thermal_mass_fraction_at_temperature
quantity_kind : residual_mass_fraction | mass_loss_fraction
Condition: temperature = 700℃
```

分布：0020284×11、0037645×6、0021296×4。

**注意**：三组的角色判断一致（温度是设定值），但被测量的物理量不同——0020284/0021296 原文报残余质量，0037645 原文报失重量。因此槽位必须带 `quantity_kind` 字段显式声明基准，抽取阶段不做换算。完整设计见 §6.4。

这是当前系统真实漏抽的信息。

---

## 9.3 A1 / A2 判别依据

判别依据是 GT `property_item.remark` 中的角色描述——weight_loss 与 temperature 哪一个是设定值。两类的角色恰好互换，不能用同一个槽位表达。

21 条 A2 的证据状态（均已确认，可进入 P0-e 迁移）：

| 组 | 条数 | 判别依据 |
|---|---:|---|
| 0020284 | 11 | remark 明确写 `Converted from residual mass X%`，`100−td_wl` 与 remark 数字 11/11 精确一致 |
| 0021296 | 4 | GT 无 remark，原文报 `% residue (N2)`，GT 值由 `1 − residue` 得来——已人工确认 |
| 0037645 | 6 | remark 为 `Total wt. loss at 800C`，原文 TGA 表报 `wt loss (%)`——已人工确认，**不得换算** |

0037645 一组不做 `100 − x` 的理由：原文未报告 residual mass；PolyInfo 在 0020284 组换算时会明确声明，本组未声明即未换算；本组 evidence 是 `wt loss (%)` 而非 `residue (%)`。

---

## 9.4 其余清洗类别

| 类别 | 条数 | 处理 |
|---|---:|---|
| A1 失重档位 | 76 | 剔除（争议项，见下） |
| A2 残炭/残余质量 | 21 | **保留**，新增槽位 |
| B 互为倒数对 | 70 | 剔除（无争议） |
| C 单位记法差异 | 39 | 仅标记，不剔除 |
| D 重复项 | 2 | 剔除（无争议） |

**待决定项**：A1 的 76 条是否剔除。B 与 D 无争议；A2 必须保留；C 仅标记。

---

# 10. Stage 架构调整建议

当前：

```
Stage4   正文 + 表格一次抽取
Stage4R  漏格修复（Preview-only）
```

存在问题：输出规模过大、表格理解不足、样品绑定不稳定、Stage4R 只能补 `missing_property_cells`（`table_recall_audit.py:512` 产出，`stage4r_table_recovery.py:834` 消费）。

建议三分：

```
Stage4N  正文性质抽取
Stage4T  表格主抽取
Stage4R  完整性审计与修复
```

**Stage 4T 不能排在最后。** 原方案将 Stage4T 放在 P4，但 92% 的缺失数值来自表格——表格抽取能力是绝大部分收益的来源，不应作为末位任务。修正后的安排：P1 先做表结构调查 + Shadow 骨架，P3 全面接管。

---

# 11. Stage4T 设计原则

核心原则（保留自 v1）：

> **表是处理单元，列是语义判断单元，格是数据生成单元，样品是绑定单元。**

**v2 新增原则**：

> Stage 4T **不得假设**"行 = 样品 / 列 = 性质"。表格方向（正置 / 转置 / 混合）必须作为需要检测的变量，而非固定前提。

## 11.1 三层数据架构

### 原始表格层

Stage 0 继续作为事实源，保留全部单元格、表头层级、caption、`rowspan/colspan`、页码和 cell 定位。
后续语义解释不得覆盖或重写这一层。

### 宽松候选层

Stage 4T 对可定位单元格尽可能生成 observation candidate，范围包括：

- 97 项规范化正式性质；
- 分子量、XRD、IR、NMR、元素组成等 material characteristic；
- 暂无 Schema 的 unknown observation；
- soluble、amorphous 等定性值；
- 温度、频率、Ox/Red 等条件轴和状态。

未归一候选必须保留原始语义、值、样品标签和 cell evidence，例如：

```json
{
  "candidate_class": "material_characteristic",
  "semantic_status": "mapped_characteristic",
  "property_name_raw": "χ23",
  "semantic_label": "polymer_polymer_interaction_parameter",
  "value_raw": "-0.15",
  "sample_label_raw": "AP-PCL",
  "conditions": {},
  "evidence": {
    "table_id": "T_19_142",
    "cell_id": "T_19_142:r0001:c0002"
  }
}
```

“宽松”不等于把表中所有数字都当作性质。温度/频率条件、配方与投料量、行号/样品编号、
Calcd/Found 角色、计算/实验来源、多峰/范围/复合格和脚注数字必须先分类；无法可靠解释时保留为
`unmapped` 或过程/标识候选，不得伪装为正式性质。

### 权威发布层

只有语义、稳定 `sample_id` 或明确 subject、条件绑定、值结构、脚注和 evidence 均通过校验的候选，
才可进入正式 `PropertyObservation` 或 `material_characteristic_observations[]`。门控失败的候选保留在
Shadow 中并记录 blocker，不得以成功状态发布。

## 11.2 混合执行流程

流程：

```
Stage 0 table cells + spans + caption
  ↓  确定性规则
方向、轴角色、表头和简单高置信语义
  ├─ 高置信简单表 → 确定性生成宽松候选
  └─ unknown / 多级分组 / 复合格 / 高 unmapped → LLM 结构解释
                                      ↓
                         方向、轴角色、绑定策略、表头语义
                                      ↓
确定性代码按 cell_id 读取原值、单位和定位
  ↓
Schema 校验 + 完整性检查 + 规则复核
  ↓
candidate_only / authoritative publication
```

规则优先处理简单、高置信表，以保证可复现和低成本。LLM 只补充复杂表的结构解释，不重新抄写整表数值；
低置信或校验失败结果回落为 `candidate_only`，不得改变 Stage 0 原值。

## 11.3 LLM 的使用位置

不是：

```
sample → LLM → 所有性质
```

而是：

```
caption + spans + header cells + redacted data preview
  → direction + axis roles + binding strategy + header semantics
```

LLM 输出不得包含 `value_raw`、数值数组或计算后的性质值；`source_cell_ids` 只能引用请求中真实存在的 cell。
计算性质、Calcd/Found、多值/范围和条件轴只解释角色，最终值与定位由确定性代码读取并复核。

v0.5 基线候选抽取是纯规则 Shadow；v0.4 sidecar 已增加确定性应用层，但结构解释路径仍不会改写候选值。
5 张 semantic-zero 表已完成受控远程试跑，并以人工 fixture 审计达到 5/5 表、56/56 必需 assignment、
0 缺失。应用层按 cell id/span 重绑定 95 个既有数值候选后，表级 semantic coverage 已达到 51/51；
下一步不是扩大 allowlist，而是扩展逐格精度 fixture，并验证样品、条件与单位绑定。通过前，LLM 解释和
应用结果均不得进入权威发布层。

## 11.4 前置调查（P1-a）

启动 Stage 4T 前必须先对本批 59 张表格做结构调查，输出：方向分布、表头层级数、单位所在位置（表头 / 单元格 / caption）、样品标识所在列。调查结论直接决定方向检测规则是否可行。

### 11.4.1 demo20 实测结果（2026-08-21 基线；2026-08-22 更新）

调查器已按 Stage 0 的真实 `table_cells` / `table_body` 运行，未覆盖批次产物。结果如下：

| 维度 | 实测分布 | 对 Stage 4T 的约束 |
|---|---:|---|
| 逐行样品（`row_samples`） | 38 | 作为默认高置信路径，但仍须验证样品标签与性质列绑定 |
| 横向并列样品（`column_samples`） | 2 | 必须支持首列性质、后续列为样品的转置布局 |
| 混合（`mixed`） | 1 | 需保留行/列双候选，禁止静默选择一侧 |
| 未知（`unknown`） | 18 | 进入人工复核或专用表型路径，不得默认当作逐行样品 |
| 含数值表 | 54 | 数值存在不代表已识别性质 |
| 可识别性质列 | 24 | 列级语义映射仍需 Shadow 评估 |

v0.2 方向调查在保持 59 张表分母不变的前提下，将方向更新为：`row_samples=46`、
`column_samples=8`、`mixed=1`、`condition_series=2`、`unknown=2`。新增 `condition_series`
不是样品轴；其中频率或温度必须作为 Observation 条件保存。该变化只代表结构识别改善，不代表
性质词汇和格级绑定已经全部通过人工准确性验收。

单位并非只在表头：表头 27 张、单元格 7 张、caption 1 张、多位置 19 张、未发现 5 张。因此抽取绑定必须综合
`column header + unit + caption + neighbor columns`，并把原始单位位置写入证据；不能只依赖列标题。

其中 30 张表含数值但当前未识别性质列。v0.4 已将其与 18 张 unknown 表的 41 张并集逐表复核：
35 张属于 PropertyObservation 或 material characteristic（其中 33 张 numeric eligible、2 张纯定性），
2 张是配方/工艺条件，2 张不 eligible，另 2 张计算性质保持 ambiguous。说明
`numeric_table_without_property_columns` 既包含真实漏抽，也包含应排除内容，不能为了提高召回率而统一强制映射。

v0.5 基线的宽松候选覆盖为 51/51、语义覆盖为 46/51；v0.4 sidecar 应用层又将 5 张结构复杂表的
95 个既有候选重绑定，并排除 5 个 reflection-index 表头候选，使表级语义覆盖达到 51/51。
这只是结构承接率，不是逐格准确率结论；稳定 subject/sample 绑定和发布门控完成前，权威发布资格仍为 0/51。

---

# 12. 最终数据库结构建议

从：

```
Sample
 └── Property[]
```

升级为：

```
PolymerEntity
    │
Sample
    │
    ├── material_characteristic_observations[]    ← 统一可重复结构
    │       ├── characteristic_name   molecular_weight | viscosity |
    │       │                         degree_of_polymerization | crystallinity
    │       ├── variant               Mn|Mw|Mv|Mp | inherent|intrinsic|reduced|specific |
    │       │                         DPn|DPw | null
    │       ├── numeric_value         数值（与 categorical_value 二选一）
    │       ├── categorical_value     Crystal | Amorphous | Semicrystalline | null
    │       ├── unit_raw              原文单位，可空，不得补造
    │       ├── unit_normalized       规范单位，可空
    │       ├── unit_status           reported | dimensionless | not_reported | null
    │       ├── method                GPC | 乌氏黏度计 | XRD | DSC | …
    │       ├── context               溶剂 / 温度 / 浓度 / 加工状态
    │       └── evidence              出处（表号 / 行列 / 段落）
    │
    ├── structural_information                    暂缓
    │
    ├── morphology                                暂缓对齐
    │       （χ23 改道 polymer_compatibility_parameter；
    │         6:4 改道 component_structure.composition_ratio）
    │
    ├── processing_history
    │
    └── PropertyObservation[]
            ├── Tg
            ├── Td（condition: weight_loss_percentage）
            ├── thermal_mass_fraction_at_temperature
            │     （quantity_kind: residual_mass_fraction | mass_loss_fraction）
            ├── mechanical properties
            └── electrical properties
```

## 12.1 为何统一为可重复结构

早前版本只把分子量数组化，黏度、DP、结晶度仍是单值字段——这不一致。这三者同样会产生多观测：

| 字段 | 多观测来源 |
|---|---|
| 黏度 | 不同溶剂、温度、浓度 |
| DP | DPn / DPw、不同表征方法 |
| 结晶度 | XRD 与 DSC 结果不同；不同加工状态（淬火 / 退火）不同 |

统一为 `material_characteristic_observations[]`，每条带完整上下文与出处，按 `characteristic_name`
建立受控字段与量纲校验。新增一种表征量只需扩枚举，不必改表结构。

### 为何拆成 `characteristic_name` + `variant` 两层

早前版本把 `Mn`、`eta_inh`、`crystallinity` 平铺在同一个 `kind` 枚举里——层级混用：
`Mn` 是分子量的一个**子类型**，`crystallinity` 是一个**顶层量**。混在一起会导致
"取该样品全部分子量观测"这类查询必须硬编码枚举值前缀。拆两层后按 `characteristic_name` 即可聚合。

### 为何必须有 `categorical_value` 和显式单位状态

PolyInfo 的 23 条结晶状态（Crystal / Amorphous）**没有数值**。只有 `value` 字段时，
它们要么被丢弃，要么被塞成字符串污染数值列。拆开后二者互斥：

- **值约束**：`numeric_value` 与 `categorical_value` **有且仅有一个非空**；
- 数值有量纲且原文报告单位 ⇒ `unit_status=reported`，保留 `unit_raw` 并按规则填写 `unit_normalized`；
- DP、`eta_sp` 等无量纲量 ⇒ `unit_status=dimensionless`，两个单位字段为空；
- 数值有量纲但原文未报告单位 ⇒ `unit_status=not_reported`，两个单位字段为空，**不得补造且不得拒绝该观测**；
- `categorical_value` 非空 ⇒ 两个单位字段与 `unit_status` 均为空（单位不适用）。

违反“二选一”或单位状态自洽约束的记录判为结构错误，不得入库。`not_reported` 是允许入库的
数据质量状态，不等同于结构错误。

---

# 13. 当前实施路线

总体原则是“宽抽取、集中修复、窄发布”，但宽松仅指**允许承接的语义范围**。证据真实性、原始值、
来源定位和结构关系始终严格。系统不承诺纠正 OCR 未识别的原始内容；可验证目标是：

> Stage 0 已识别的每个 eligible data cell，都能追踪为观测候选、结构角色、待复核项或带原因的拒绝项，
> 不再静默丢失。

### 13.1 Eligible cell 与证据节点

- **eligible data cell**：人工规则判定可能承载性质、材料表征或计算结果的数据格，是逐格召回分母；
- **evidence node**：表头、样品轴、条件轴、组成轴、单位和脚注 cell，用于解释数据格，不进入观测分母；
- **非候选结构角色**：`condition`、`composition`、`identifier` 不是 rejected candidate；
- **rejected candidate**：只有经过候选判定后因证据或质量问题被拒绝的对象，且必须保存拒绝原因；
- Stage 0 之外仍需单独报告 OCR 漏表、跨页断裂、合并单元格错误、单格多值拆分失败和定性值遗漏。

### 13.2 九步实施路线

| 阶段 | 目标 | 主要交付物 | 当前状态 |
|---|---|---|---|
| 1. 4T 证据型宽松候选 | 承接正式性质、characteristic、定性值和未知语义 | `candidate_role/state`、原始值、cell、表头路径、轴角色、warnings；数值只读 Stage 0 | 核心链路完成；7 张表 212 条 fixture，全部非权威 |
| 2. Eligible-cell 去向账本 | 消除 Stage 0→4T 的静默丢失 | 每个 eligible data cell 的角色、候选/拒绝状态、证据节点与原因；统计可解释率 | 下一步，尚未完成 |
| 3. 分层人工 fixture | 将结构自洽转为可信准确率 | A：应抽/角色；B：语义/样品/条件；C：4N/4T 关系；D：发布资格 | 212 条为 provisional seed；旧 538 格回归继续保留 |
| 4. 冻结 Candidate Schema | 固定 4N/4T→4R 接口 | `raw_candidate`、`normalized_candidate`、`publishable_observation`、`candidate_partial`、`rejected_candidate`；4R I/O 与 repair audit log | 4T 与 4R audit 已有初版；4N 兼容契约仍未冻结 |
| 5. 稳定 4N 正文候选 | 与 4T 使用兼容契约 | 句子/段落 evidence、原值、局部关系、summary/具体观测、引用表格关系、实验/计算角色 | 尚未适配统一契约 |
| 6. 4R unified Preview | 有限修复，不成为第二个抽取器 | Preview 消费 4N/4T；唯一样品绑定、正式性质窄发布、同格合并、冲突/保留原因审计 | 初版完成；5 篇试跑 69 条新合入、40 条重复合并 |
| 7. 4N/4T 关系与发布门控 | 正确合并证据、保留冲突 | 关系分类、条件感知去重、冲突组、Property/characteristic 分流 | exact/rounded 与同格冲突已有初版；完整关系分类未完成 |
| 8. Stage 5 全文分片 | 防止局部错误清空整篇表征结果 | `plan_shards()`、`extract_shard()`、`merge_shards()`；逐对象校验包含在抽取函数内 | Preview 初版完成；3 篇定向重跑均非空，2 篇因局部问题为 `candidate_partial`；Strict 未改 |
| 9. 全量回归与权威接管 | 逐步替代 legacy 路径 | 完整性、召回、精确率、绑定、重复、冲突、合并准确率及 Preview/Strict 回归 | 当前不满足，暂不接管 |

### 13.3 候选角色和状态

4N/4T 在抽取时必须先分类，而不是把所有数字交给 4R：

```text
candidate_role:
  property_candidate | material_characteristic | condition | composition |
  identifier | calculated_result | unknown_numeric | unknown_observation

candidate_state:
  raw_candidate | normalized_candidate | publishable_observation |
  candidate_partial | rejected_candidate
```

`raw_candidate` 必须具有可验证 evidence；没有可靠来源定位的数字不能因“可能有用”进入候选层。

### 13.4 正文与表格关系

4N 和 4T 分别保留证据，由 4R/合并层建立关系，禁止互相覆盖：

| 关系 | 处理 |
|---|---|
| `exact` | 同一样品、性质、条件和数值，合并为一条观测并保留两份 evidence |
| `rounded` | 正文为表格精确值的合理四舍五入；保留两个原值，以表格精度作为 canonical 候选 |
| `citation_only` | 正文只引用表格；合并 evidence，不新增观测 |
| `summary_detail` | 正文为范围/汇总，表格为逐样品点；分别保留，不去重 |
| `condition_distinct` | 数值相同但方法、处理历史或条件不同；分别保留 |
| `source_conflict` | 条件兼容但值无法解释；建立冲突组，未解决前不发布单值 |
| `independent` | 证据不足以证明同一观测；分别保留 |

去重至少比较 sample/polymer、property/variant、value/unit、method、temperature/frequency/solvent/
atmosphere、processing history、material state、experimental/calculated 和 quantity basis。
`rounded` 容差按性质、单位、有效数字和原文近似措辞定义，不设置全局固定阈值。

### 13.5 Stage 5 全文分片方案

旧 Preview 路径对每篇文章执行一次请求，导致输出长度、单个字段错误和整篇结果绑定在一起。当前 Preview
初版已统一改为按规范化表征方法分片，配置为目标 18k 字符、硬上限 30k 字符、单 shard 最多 12k token；
Strict 默认仍保留旧整篇路径。旧 3 篇空壳原因和当前定向结果如下：

| 文献 | 旧直接原因 | 当前结果 |
|---|---|---|
| 0020284 | `finish_reason=max_tokens`，JSON 截断 | 6 shard，5 Characterization/50 Property；DSC 与 viscometry 语义校验待复核，`candidate_partial` |
| 0038813 | `source_text/source_sentence` 不兼容 | 10 shard，8/36；4 个 shard 有 evidence/归属问题，`candidate_partial` |
| 0038527 | 单元素 `series_ids` 校验失败 | 6 shard，5/6，`success` |

所有文章统一采用以下流水线，而不是只为失败文章增加特殊分支：

```text
Stage 5
  ├─ plan_shards()    按表征类别和证据区域生成分片
  ├─ extract_shard()  抽取、逐对象校验、保留合法对象、局部重试
  └─ merge_shards()   合并、去重、重编号和引用修复
          ↓
      Stage5Document
```

三者是同一 Stage 内部的函数边界，不是三个新增 Pipeline Stage。每个模型请求原则上只输入一个表征
大类；仅当该类别仍超过大小上限或包含多个明显独立的 measurement instance 时，才继续拆 shard。

#### 13.5.1 分片维度

目标主键为 `method_normalized + evidence_region + measurement_instance`。当前初版已完成规范化方法路由和
超限拆分，evidence region/measurement instance 的进一步细分仍需通过 5 篇人工审阅校准：

1. **先按规范化表征方法路由**：FTIR、不同核种 NMR、XRD/WAXD/SAXS、GPC/SEC、DSC、TGA、
   DMA/流变、SEM/TEM/AFM、UV-Vis/荧光、元素分析及 `unknown`；
2. **同一方法再按局部证据区域拆分**：小节、连续段落、图/表引用、实验条件和 measurement instance；
3. **Sample 不是主拆分轴**：同一测量往往比较多个样品或形成 series，按 Sample 拆会破坏比较关系；
4. **Methods 描述可作为共享上下文**，但每个 shard 只携带相关 Sample/Entity、Stage 4 Property/Series
   和方法词表子集，避免把整篇对象列表重复送入每个请求；
5. 初始大小目标为每 shard `10k-20k` 字符，硬上限 `25k-30k` 字符，输出预算先按
   `8k-12k tokens` 试跑后由 fixture 校准；这些是工程初值，不是固定业务口径。

同一段同时讨论 DSC/TGA 等多方法时，可以进入多个 shard，但必须使用同一原文 locator；后续按对象语义
和 evidence 去重。无法可靠识别方法的证据进入 `unknown` shard，不静默丢弃，也不直接发布。

#### 13.5.2 分片产物与失败状态

每个 shard 至少保存：`shard_id`、方法、证据 block 清单、相关对象 ID、输入字符数、prompt/model 版本、
原始响应、`finish_reason`、解析来源、前后缀文本、Schema 错误、修复记录、重试次数和最终状态。

- `complete`：该 shard 校验和物化成功；
- `complete_no_evidence`：路由器确认没有 eligible 表征证据，不调用模型，并保存判定依据；
- `candidate_partial`：保留有效对象及失败对象/原因，可只重试该 shard；
- `failed`：没有可安全物化的对象，但原始响应和诊断必须保留；
- 禁止用空 `CharacterizationStageResponse()` 覆盖失败事实，也禁止把 degraded 空壳登记为 success。

#### 13.5.3 `extract_shard()` 内的有限修复与逐对象校验

修复只处理可证明等价的结构差异，例如 `source_text → source_sentence`、单元素
`series_ids → series_id`；每次修复保存字段前后值、规则版本和理由。随后逐个校验
Characterization、Property 和 Series：一个对象失败不能删除同一 shard 中其他合法对象。

Stage 5 不得通过修复创造原文没有的数值、样品、方法或条件。语义或样品仍不明确的对象进入
`candidate_partial/unresolved`，而不是为了通过 Schema 强行补全。

#### 13.5.4 确定性合并

合并层负责稳定重编号 `characterization_id`、`prop_s5_*`，并修复 `derived_property_ids` 等引用。
去重必须比较样品/实体、方法、性质/variant、值/单位、条件和 evidence，不能只比较数值。
相同证据和兼容语义合并；不同 measurement instance 或条件分别保留；无法解释的差异形成冲突组。

#### 13.5.5 Stage 5 验收

1. fixture 中每个 eligible 表征 evidence block 都进入至少一个 shard，或有明确排除原因；
2. 每次模型调用均保存 raw response、解析诊断和 finish reason，失败记录不得丢失；
3. 注入一个非法对象时，同 shard 的其余合法对象仍能保留，且失败对象有定位和原因；
4. shard 重跑和合并具备幂等性，ID 唯一，`derived_property_ids` 等引用全部可解析；
5. 0020284、0038813、0038527 不再因当前三类错误整篇空壳；无证据的空结果必须标为
   `complete_no_evidence`，不得与失败混淆；
6. 5 篇和 demo20 分别报告路由覆盖、shard 成功率、对象保留率、重复率、冲突数和人工抽查准确率；
   Stage 6 `0 errors` 只代表结构校验通过，不能替代语义准确率。

### 13.6 接下来五步

1. **完成 5 篇人工审阅**：补跑/复核 0043590、0043541，逐 shard 检查方法路由、样品/Series 归属、
   evidence locator、Property 类型、重复和跨 shard 引用；为 3 篇当前结果建立对象级 fixture。
2. **收敛 partial shard**：修复 0020284 的 DSC/viscometry 归属，以及 0038813 的 locator、cell value、
   Series 归属问题；只重跑受影响 shard，未解决对象继续保持 `candidate_partial`。
3. **补齐路由边界**：为 unknown/unrouted、多 measurement instance、超大方法块和无受控方法证据建立
   明确 fixture；校准 evidence region 拆分，避免一个方法 shard 重新膨胀成整篇请求。
4. **冻结 Stage 5→6 门控**：明确 `success/candidate_partial/complete_no_evidence/failed` 在 Preview candidate
   与 Strict 发布中的行为；保留 raw、修复审计和失败原因，结构通过不等于语义可发布。
5. **跑 demo20 全流程**：从 Stage 0 到 Stage 6 重跑并生成逐篇人审报告，统计 shard 成功率、对象保留率、
   partial/failed、表征/性质数、重复/冲突和人工准确率；完成前不切换 Strict。

### 目标主流程

```text
Stage 0
  ├─ Stage 4N：正文候选
  └─ Stage 4T：表格候选
          ↓
      Candidate Schema 校验
          ↓
      Stage 4R unified shadow：有限修复与规范化
          ↓
      4N/4T 关系判定、合并与冲突分组
          ↓
      Stage 5：按表征类别分片抽取与确定性合并
          ↓
      发布校验
       ├─ PropertyObservation
       ├─ material_characteristic_observations
       ├─ candidate_partial / unmapped
       └─ rejected_candidate（保留原因）
```

<details>
<summary>历史 P0-P3 任务映射（保留追溯）</summary>

## 历史实施顺序（P0~P3）

## P0：稳定性修复 + 指标冻结（先行）

| 编号 | 任务 | 关键文件 |
|---|---|---|
| P0-a | 新增 `parse_json_response` 修复围栏解析，并保留 `extract_json_object` 兼容包装 | `llm_client.py:298` |
| P0-b | 修复两条空壳降级路径及 `candidate_partial` 状态传递 | `stage4_property.py:~L6389, ~L6420` + `batch_runner.py` |
| P0-c | Stage 4 仅启用 `max_validation_retries: 1`，分别验证 0814 四篇的状态与有效对象保留 | `pipeline.yaml` |
| P0-d | 冻结 Legacy / Curated；Extended-numeric 重跑后冻结，Extended-qualitative 单列；统一改称"召回率" | 文档 + 指标脚本 |
| P0-e | A2 GT 迁移：**21 组，输入 42 行 → 输出 21 条 Observation**（含 `quantity_kind`；先回填 `pair_row`）；生成**版本化 Curated GT，不得覆盖 Legacy GT** | GT 清洗脚本 |
| P0-f | 固化 `0043955/stage4_llm_response.json` 为解析器回归 fixture | tests/ |
| P0-g | **建立匹配器回归 fixture 并固化当前基线**（Legacy 695 + Curated 526 两套输入输出快照）| `polyinfo_coverage_matcher.py` + tests/ |
| P0-h | **黏度四分桶**（η_inh / [η] / η_red / η_sp），**同步修改** `table_recall_audit.py:75` 与 `polyinfo_coverage_matcher.py:128`，改完立即跑 P0-g 回归 | 依赖 **P0-g** |

P0-h 的两处必须在同一次改动中完成，否则现有 4 条命中会在评分侧消失，引发假回退。

P0 完成后重跑 0814，确认 85 点中的 Pydantic 失败部分重新参与评估，方可进入 P1。

### 为什么 P0-g / P0-h 从 P1 / P2 提前到 P0

原排序有一个依赖环：**§14.1 第 7 条把黏度四分桶列为 P0 验收项**，任务却排在 P1-c；
而 P1-c 会改匹配器，其回归 fixture 却要等到 P2-d 才建立——等于"先改动、后建基线"，
改动前后无从比对。修正后的顺序是：

```
P0-g 建基线 fixture  ──►  P0-h 改黏度匹配器  ──►  跑 P0-g 回归，逐项解释变化
                                                        │
P2-d ──────────────────────────────────────────────►  扩展 fixture 至 crystallinity / XRD
```

fixture 的用途是**检出未解释的变化**，不是"召回率不得下降"的闸门（见 §3.2 指标变动规则）。

### P0 的可审查实施包

P0-a~P0-h 是逻辑任务，不直接等同于提交顺序。实际实施拆成以下六包，每包独立测试、独立审查，
避免把解析、重试、ontology 与匹配器同时改动：

| 实施包 | 内容 | 行为边界 |
|---|---|---|
| 1. 基线与可复现数据 | corrected TSV 必须由脚本生成，不能只保留手工副本；建立 P0-g 的 Legacy / Curated fixture；固化 GT、matcher 版本与输入哈希 | 不改变生产行为 |
| 2. JSON 解析 | 新增 `parse_json_response -> ParsedJSON`；保留 `extract_json_object -> dict` 兼容包装；由 `LLMJSONResponse` 承载诊断；增加 0043955、截断、多围栏测试 | 不同时修改 retry 与 ontology |
| 3. 部分成功与空壳状态 | 增加 Stage 4 blocking warning；使 batch runner 的 partial 状态持续到流程结束；禁止 replay 空壳被视为恢复成功 | 补 Stage 4 与 batch runner 状态测试 |
| 4. 重试与历史验证 | Stage 4 的 validation retry 设为 1；先离线回放，再只重跑 0043955 与 0814 四篇 | 0043955 历史 fixture 应解析出 10 条性质，但仍判 `candidate_partial` |
| 5. GT 与匹配器 | 完成 A2 迁移与黏度四分桶；每项变化输出逐点差异 | 不覆盖 Legacy GT，不以召回率只升不降为门槛 |
| 6. Stage 4T 调研 | 执行 P1-a 表结构调查并产出人工复核 fixture、指标定义与候选阈值 | 此前 §14.2 八项指标不冻结门槛 |

---

## P1：Sample 级性质 + 表结构调查 + Stage 4T Shadow

| 编号 | 任务 | 依赖 |
|---|---|---|
| P1-a | 59 张表格结构调查（方向 / 表头层级 / 单位位置 / 样品标识列） | — |
| P1-b | Mw/Mn 可重复 Observation 结构 + Stage 4T 三层 Shadow 骨架 | P1-a；已完成宽松候选层与独立发布门控，未接管现有 Stage 4 |
| P1-d | DP（`DP > 0`，极端值 warning） | — |
| P1-e | A2 抽取能力（`thermal_mass_fraction_at_temperature`，抽取侧存原文基准、不换算） | P0-e |

（原 P1-c 黏度四分桶已提前至 P0-h。）

---

## P2：Crystallinity + XRD + Stage 4/5 所有权确定

| 编号 | 任务 | 依赖 |
|---|---|---|
| P2-a | 确定 crystallinity 由 Stage 4 或 Stage 5 唯一持有 | — |
| P2-b | Schema 同时支持数值结晶度和定性 state | P2-a |
| P2-c | d-spacing 抽取 | P2-a |
| P2-d | **扩展** P0-g 回归 fixture，覆盖 crystallinity / d-spacing 新增槽位 | P0-g、P2-b、P2-c |

回归 fixture（P0-g 建立、P2-d 扩展）是 P3 的门控条件——Stage 4T 全面接管表格之前必须可运行。

---

## P3：Stage 4T 全面接管表格

前置条件：P1-a 调查报告出炉、P0/P1/P2 全部通过回归；5 张复杂表人工结构 fixture、LLM 完整性检查、
失败 fallback、显式开关、allowlist、成本审计、受控远程试跑和 assignments 到确定性候选的应用层均已具备；
仍须扩展候选精度 fixture，并完成稳定 subject/sample 解析与 Stage4N/Stage4T 合并审计。

| 编号 | 任务 |
|---|---|
| P3-a | 完整 Stage 4T（规则优先 + 复杂表 LLM 结构解释 + 确定性格值读取 + 发布门控） |
| P3-b | 用 P0-g/P2-d 回归 fixture 比对，**逐项解释每处指标变化**；召回率/准确率/假匹配数联合验收（见 §14.2） |
| P3-c | Stage4N/Stage4T 合并去重、失败状态链与权威发布审计 |

---

</details>

# 14. 验收清单

## 14.1 P0 验收（8 条）

1. **解析器算法**：`parse_json_response` 按 §4.2.1 五步顺序实现，对 `0043955` fixture 解析出
   `measurement_conditions=4, properties=10`，且尾随文本被记录；`extract_json_object` 兼容包装仍返回 `dict`。
2. **完整性判定**：同一 fixture 被正确标记为**不完整响应**（尾部"仅保留示例…需补全"命中检测），
   不得以成功状态发布。
3. **空壳三态与状态传递**：§4.3.1 三态实现，`candidate_partial` 与 Stage 失败可区分；
   Stage 4 的 blocking warning 不阻断后续 Stage，但最终状态仍为 `candidate_partial`；
   degraded 空壳不再以成功或 recovered 状态出现在产物中。
4. **0814 四篇分别验收**：判据是**状态可信**，不是"85 点全部抽中"。四项同时满足：
   ① 四篇均不再以"成功的空壳"发布；② 失败对象有明确状态与失败原因；③ 有效对象被保留；
   ④ 85 个 GT 点重新具备参与评估的机会。
   0021296(38) / 0037645(30) / 0043541(15) 属 Pydantic 类，**0033617(2) 语义校验类单独验收**。
   实际召回多少由后续召回率报告衡量，**不作为 P0 门槛**。
5. **口径一致**：Legacy 当前实测为 313/695；Curated 分母固定为 526，文档冻结参考为 303/526（可信）、
   263/526（严格），v2.2 版本化 matcher 当前实测为 307/526（可信）、267/526（严格）。
   两套 Curated 数字的差异必须引用 `curated_manifest.v2.2` 中的 0021296 四条 residue 解释，脚本可复现。
6. **A2 迁移**：21 组（输入 42 行 → 输出 21 条 Observation）迁移完成，
   `quantity_kind` 正确区分三组，0037645 一组**未被换算**。
7. **黏度四分桶（P0-h，须在 P0-g 基线建立之后）**：`table_recall_audit.py:75` 与
   `polyinfo_coverage_matcher.py:128` 同步修改，
   四个量各自独立；现有 4 条命中**逐条确认语义正确性**（确认为错桶的应剔除并说明，不得为保数保留）。
8. **假匹配基准**：物理不可能命中（导电率/电阻率混淆桶等）当前约 8 条，记录绝对数量、命中率、
   与上次基准 delta 三项，联合召回率与准确率呈报。

## 14.2 Stage 4T 接管前追加验收（8 条）

P0/P1/P2 的验收偏重召回率，不足以放行 Stage 4T 这一重构级改动——只看召回率会放行
"多抽但抽错"的实现。P3 前追加准确性维度。

P1-b 已产出 v0.3 人工复核 fixture，覆盖当前全部 26 张有 Shadow 输出的 eligible 表和 538 个数值格；
方向/性质映射/样品绑定/数值格召回/输出精确率/重复输出均已有可执行公式。当前审计为 538/538，
性质映射 538/538，可评价样品绑定 528/528，重复为 0。

该范围仍然**不能冻结 P3 全面接管门槛**：v0.5 的宽松候选已覆盖 51/51 张 numeric eligible 表，
但宽松候选总量扩展到 1602 条，旧 fixture 只证明原有 538 个数值格仍存在，不能代表新增候选的全量精度。
v0.4 sidecar 已把 5 张表的结构解释确定性应用到 98 个既有候选，使 semantic-zero 从 5 张降为 0 张；
另有 2 张定性溶解性表已产生 114 条候选。当前 v0.3 provisional fixture 合计 7 张表、212 条，
这只证明 fixture 与 sidecar 的结构一致，不证明性质、样品、条件和单位已经人工确认。当前仍为 0 张表具有权威发布
资格；正文/表格合并准确率和不完整响应数量也等待合并器与扩展 fixture。在此之前不得据此放行 P3。

当前公式：数值格召回率 = 命中的标注 cell / eligible 标注 cell；输出精确率 = 命中的标注 cell /
该 fixture 明确审计列中的 Shadow 输出条数（同表未标注列不自动计错）；性质映射准确率同时比较规范名、
未归一语义、variant 与条件；样品绑定准确率
只在人工标记为可评估的 cell 上比较原始样品标签；重复输出率 = 同一 cell 的额外输出数 / 总输出数。

### 非权威 Shadow sidecar 接入门槛（已冻结）

下列门槛只允许 Stage 4T 作为独立、可关闭、非权威 sidecar 随 Preview 运行；sidecar 不得修改
`stage4_properties.json`、Stage 4R 输入、candidate 状态或最终发布结果：

| 指标 | 门槛 | v0.3 当前值 |
|---|---:|---:|
| 方向准确率 | ≥ 99% | 100%（27/27） |
| 数值格召回率 | ≥ 98% | 100%（538/538） |
| 输出精确率 | ≥ 99% | 100%（538/538） |
| 严格性质语义准确率 | ≥ 99% | 100%（538/538） |
| 可评价样品绑定准确率 | ≥ 99% | 100%（528/528） |
| 重复输出率 | ≤ 0.5% | 0% |
| fixture 内 eligible 零产出表 | 0 | 0 |
| 互斥性质映射冲突数 | 0 | 0（524 个可审计映射） |

所有 `inferred_*` 对齐还必须保留原表头列、实际数值列和 `alignment_status`，否则即使上述比例达标也不得接入。
任何 sidecar 代码改动后必须重跑同一版本 fixture；指标下降可以接受的前提是逐格解释且仍满足门槛。
这些阈值不适用于 P3 接管。5 张 semantic-zero 表及 2 张定性表已有 212 条 provisional fixture；P3 仍须完成
人工独立标注并扩展其余新增候选、建立 eligible-cell 去向账本和稳定 subject/sample 绑定，
并完成 Stage4N/Stage4T 合并准确率
和失败状态链。

补充表级门槛：numeric eligible 分母固定为 51 张。v0.5 的宽松候选覆盖为 51/51，已映射语义覆盖为
46/51；应用结构解释后的 v0.6 审计输入为 51/51。权威发布资格前后均为 0/51。全面接管不能只要求
`eligible zero-output tables=0`，还必须分别呈报候选覆盖、语义覆盖和发布资格；当前 sidecar 允许运行
仅因为它非权威且不影响发布结果。

| # | 指标 | 说明 |
|---|---|---|
| 1 | 性质列映射准确率 | 列头 → property_name 映射正确比例 |
| 2 | 样品绑定准确率 | 数值格 → sample_id 绑定正确比例 |
| 3 | 表格数值格召回率 | 应抽格中实际产出的比例 |
| 4 | 重复输出率 | 同一格产出多条记录的比例 |
| 5 | 互斥性质映射冲突数 | 按互斥关系表检查：同一数值格、列或观测被映射到物理上互斥的性质类别；不把所有不同性质名都视为冲突 |
| 6 | Eligible-cell 去向可解释率 | Stage 0 已识别的 eligible data cell 中，有候选、结构角色、待复核或带原因拒绝去向的比例；目标 100% |
| 7 | 零产出表数量 | 分母限定为 **eligible tables**；作为表级哨兵，不能替代逐格完整性 |
| 8 | 正文/表格关系准确率 | exact/rounded/summary_detail/condition_distinct/citation_only/source_conflict/independent 分类与合并正确率 |
| 9 | 不完整响应数量 | 被 §4.2.2 判定为不完整的响应数 |

“互斥性质映射冲突数”采用分层统计：cell-level（同一数值格被映射到互斥性质）、
column-level（同一列的主语义被错误归类）和 observation-level（已发布观测之间的互斥类型）。
互斥关系由评测 fixture 的 `forbidden_pairs` 冻结；例如
`thermal_mass_vs_decomposition` 类别中的 `char_yield → thermal_decomposition_temperature`
只是一个具体哨兵案例，不作为唯一冲突类型。`Ti`、`T10`、`Tmax` 的条件差异，
以及四种黏度量之间的术语差异，应由性质 variant/condition 表达，不直接计为冲突。

## 14.3 其余阶段验收

当前验收只看“候选可审计、语义可解释、发布门控不越权”，不把候选覆盖当作正式召回率或准确率。

| 范围 | 当前结果 | 下一验收 |
|---|---|---|
| 4T 表格候选 | 全批 v0.6 aggregate 基线 1597 条；当前 7 张代表表 v0.3 fixture 为 212 条，均 `candidate_only` | eligible-cell 去向账本、分层人工 fixture、重复率和互斥冲突 |
| 4T 发布 | `0/51` 获得权威发布资格 | 稳定 sample/subject、条件和 evidence 绑定 |
| 4N 正文 | 仍负责正文候选，不承担完整表格解析 | 完整性、重试、失败状态和来源字段统一 |
| 4R 修复 | unified Preview 初版已接入；5 篇中新合入 69 条、合并重复 40 条 | 扩展关系分类、冲突 fixture 和 repair audit；Strict/legacy 暂不接管 |
| Stage 5 表征 | Preview 分片初版完成；3 篇旧空壳均恢复非空结果，0020284/0038813 为 partial、0038527 success；三篇 Stage 6 0 errors | 完成 5 篇人工 fixture、收敛 partial shard、再跑 demo20；Strict 保持旧路径 |
| 权威接管 | 暂不允许 | §13.2 九步路线的门槛全部通过后再评估 |

<details>
<summary>历史基线与已完成项</summary>

- **结晶度 GT 覆盖**（P2）：crystallinity 在至少 3 篇 GT 文档中有非零命中（当前零重叠）。
- **表格调查报告**（P1-a）：59 张表格方向调查输出完成，Stage 4T Shadow 骨架可运行。
- **Stage 4T Shadow（P1-b）**：demo20 独立 Shadow v0.3 报告为 59 表 / 538 候选 /
  316 个规范性质完整绑定 / 222 unresolved。未归一语义中包含分子量 79、分子量分布 65、
  结晶度 20、`char_yield` 8、失重率 6、残余质量分数 6、泡孔密度 5 和液晶 `transition_temperature_ti` 12；
  这些信息均未误入不相容的正式性质桶。
  v0.3 人工 fixture 覆盖当前全部 26 张有输出 eligible 表（另含 1 张 categorical unknown），
  当前 538/538 格命中；方向、输出精确率、严格性质语义与可评估样品绑定均为 100%，重复率为 0。
  unresolved 必须继续保留 cell 定位。当前 Shadow 的三类互斥冲突为 0，已作为非权威、可关闭、
  best-effort sidecar 接入 Preview；但不构成 Stage 4T 接管许可。
- **Stage 4T eligibility（P1-b/v0.4）**：41 张调查候选已逐表分类；与 v0.3 合并后全批
  numeric eligible 为 51 张；v0.4 runtime 当前 41 张有输出、10 张零输出，表级输出覆盖率 80.39%。
  14 张 unknown 方向 fixture 已全部有输出；新增输出仍需逐格人工 fixture，不能以“有输出”替代准确性结论。
- **Stage 4T 三层 Shadow（P1-b/v0.5）**：59 张表共 1602 条宽松候选，其中正式性质 419、
  material characteristic 853、unmapped 330；numeric eligible 的候选/语义/发布三层覆盖分别为
  51/51、46/51、0/51。1602 条全部为 `candidate_only`，符合当前无稳定 `sample_id` 时的发布门控。
  新增 LLM 结构解释契约及 5 张人工结构 fixture 已通过测试；远程试跑 5/5 表通过，人工必需 assignment
  56/56、缺失 0。该条保留为应用前基线。
- **Stage 4T 结构应用（sidecar v0.4 / 审计输入 v0.6）**：5 张复杂表将 100 个旧规则候选重绑定为
  95 个语义候选，另排除 5 个条件表头；这是 v2.17 的历史基线。其后已补回 3 个脚注度数漏格，
  当前为 98 个数值候选，并新增两张定性表 114 条候选；应用后候选/语义/发布三层覆盖仍为 51/51、51/51、0/51。
  原 `rule_observations`、assignment cell 和冲突状态均保留；本轮复用已有解释，新增模型调用和费用为 0。
  当前 212 条 provisional fixture 仍须人工独立冻结，51/51 不作准确率结论。
- **回归 fixture**：P0-g 建立基线、P2-d 扩展至新槽位，两阶段均存在且通过。
  注意：该 fixture 用于**检出未解释的变化**，不是"召回率不得下降"的闸门（见 §3.2 指标变动规则）。

</details>

---

# 总结

当前问题的本质有三层：

1. **Stage 4 存在已定位的代码缺陷**，导致 0814 批次约 12% 的 GT 点落在空壳文档中、0817 批次 0043955 的 10 个性质被丢弃——这是最优先修复的问题，影响数字的真实性。
2. **数据库模型仍偏向性能数据库**，而 PolyInfo 实际上是材料知识数据库：9 项 specialized_properties 共 296 条源文可定位数值（其中 273 条、91.6% 在表格）完全落在当前 schema 覆盖范围之外。
3. **召回率指标定义不清**：非排他匹配不该叫覆盖率，695 分母含 A1 和 B 类噪声，四条数值口径（Legacy / Curated / Extended-numeric-all / -locatable）需要明确冻结，定性 67 条单列。当前 Curated 分母固定为 526；文档冻结参考为 303/526（可信）、263/526（严格），v2.2 当前实测为 307/526、267/526，差异来自 0021296 四条 residue 观察的有效重入。

后续路线固定为：

1. 建立 eligible data cell 与 evidence node 定义，并为每个 eligible data cell 建立去向账本；
2. 将 212 条 provisional fixture 分层人工冻结，并扩展到全部新增候选；
3. 冻结 4N/4T Candidate Schema、状态机、4R I/O 和 repair audit log；
4. 适配 4N 正文候选，严格保留文本 evidence、原值、summary/detail 和表格引用关系；
5. 扩展已接入 Preview 的 4R unified，完善 4N/4T 证据关系、条件感知去重和 source conflict 分组；
6. 对 Stage 5 Preview 分片结果完成人工 fixture，收敛 partial shard，并补齐 unknown/多实例/超大块路由边界；
7. 实现发布门控，未解决冲突、partial、unmapped 和 rejected 不进入权威单值；
8. 在已完成 3 篇 Stage 5 定向重跑的基础上回归 5 篇，最后完成 demo20 的 Stage 0-6 全量重跑；
9. 满足逐格完整性、人工准确率、绑定、重复、冲突、关系分类、Preview/Strict 和全量回归门槛后，
   才逐步评估 4T/4R unified 权威接管。

当前不让 4T 接管 Strict 正式输出，也不直接替换 legacy 4R。Preview unified 已证明接线可运行，
但表级 `51/51`、fixture `212/212` 和 5 篇 Stage 6 `0 errors` 均不是论文原始内容绝对完整或人工准确率结论。

最终目标不是简单提高 Legacy 695 召回率，而是建立面向高分子材料全生命周期信息的结构化知识数据库。
