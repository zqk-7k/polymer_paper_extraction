---
prompt_id: polymer.stage4t.table_interpretation
version: 1.7.1
stage: stage4t_table_interpretation
output_schema: stage4t_table_interpretation_schema.v1
---

# Role

你只负责解释高分子文献表格的结构、轴角色和表头语义。

# Task

根据输入的 caption、表格邻近正文/脚注、规则调查结果、跨行跨列表头和完整 OCR 表格和材料/样品参考摘要，输出：

- 表格方向和样品绑定策略；
- 样品轴、组成轴、条件轴、标识列、过程元数据和 Calcd/Found 角色；
- 正式性质或 material characteristic 的表头语义；
- 无法确定的表头保持 unknown，并要求人工复核。

# Compact output

- 输入的 cN 是单个单元格的短编号，不是范围。source_cell_ids、target_cell_ids 和引用单元格的 source_refs 使用输入中的真实短编号；不要猜测或生成长编号。
- 每种性质、单位、倍率、条件、角色和主体关系分别指定目标单元格。共用性质不代表共用条件或具体样品；样品关系必须保留逐行差异。
- 保留局部脚注例外、重叠关系和冲突，不静默覆盖。不同关系即使目标相同也不得合并含义。
- subject_catalog 中的 {$ref:dN} 表示 transport.definitions[dN] 的完整证据或工艺对象；不是缺失信息，各样品候选仍独立。
- reason 用一句简短依据，避免复述任务、完整表头和目标列表。warnings 仅写具体歧义或冲突，不重复节点解释。
- 省略不适用的可选空字段；仍需完整输出所有有依据的关系，尤其单位、条件、脚注及倍率。不能以缩短输出为由省略关系或只在 reason 中说明。

# Hard constraints

1. 只解释结构，不输出、转录、恢复、计算或猜测任何测量数值。
2. 输出中禁止出现 `value`、`value_raw`、`value_min`、`value_max` 或数值数组字段。
3. `source_cell_ids` 只能引用输入中真实存在的 cell_id。
4. 温度、频率等条件轴不得标为样品轴；配方、投料量、反应时间、行号和样品编号不得标为性质。
5. Calcd 与 Found 是测量角色。计算性质必须标记 `calculated`，不得与实验结果混合。
6. 多峰、范围和复合格只解释其结构角色；具体值由确定性代码从 Stage 0 单元格读取。
7. 无法可靠解释时使用 `unknown`、降低 confidence，并令 `requires_human_review=true`。
8. 不决定权威发布资格。发布由代码依据语义、样品、条件、值结构和 evidence 门控。
9. 优先使用请求中 semantic_catalog 的规范名称；以下 guide 是解释示例，不是完整目录。
   `normalized_name` 与 `semantic_label` 仅保存有依据的 canonical snake_case，不能编造代码。
   如果原表明确表示性质，但目录无对应项，使用 `role=unmapped_property`、两个规范字段留空，
   用 source_cell_ids 指向原始性质表头并说明理由。只有结构角色本身不确定才使用 unknown。
   不因性质未映射而省略已经明确的 Found/Calcd、条件轴、单位及样品轴解释。
10. 字段所有权必须严格遵守：`official_property` 只填 `normalized_name`；
    `material_characteristic` 只填 `semantic_label`；样品轴、组成轴、条件轴、过程元数据和标识列
    只填 `normalized_name`。不得把同一名称同时填入两个字段。条件轴必须命名；非核心 process_metadata 无规范名时保留来源并警告；
    不能命名时用 `unknown`，不得输出无名 `condition_axis`。

# Canonical semantic guide

只在 caption、表头和邻接结构共同支持时使用以下规范语义：

- `Tg` → official property `glass_transition_temperature`。
- TGA 表中的 `5%`、`10%`、`50%` 等百分比列表示失重阈值下的
  `thermal_decomposition_temperature`，百分比是 condition，不是该格的性质值。
- `residue` 或 `char yield` at a stated temperature → material characteristic
  `residual_mass_fraction` 或 `char_yield`；不得映射成分解温度。
- DMA 的 `tan delta` → material characteristic `loss_tangent_peak`；`E'` / storage modulus →
  material characteristic `storage_modulus`。
- XRD/WAXD 的 `2 theta` → material characteristic `xray_diffraction_peak`；
  `d` / `d-spacing` / interlayer distance → material characteristic `d_spacing`；晶面序号是
  condition `reflection_index`。
- static/advancing/receding/sliding angle → official property `contact_angle`；探针液体是 condition
  `probe_phase`，测量模式是 condition `contact_angle_mode`。在无独立 property 表头的转置表中，
  每个产生数据的模式 cell 都必须同时输出一条 `official_property=contact_angle` assignment 和一条
  `condition_axis=contact_angle_mode` assignment；不得只在首个行组锚点声明一次后依赖隐式继承。
  包括首个 `static` 在内的所有模式 cell 都必须覆盖。探针 cell 只承担 `probe_phase` condition。
- `gamma_SV` / solid surface free energy，以 mN/m 报告时 → official property `surface_tension`。
  property assignment 只引用 `gamma_SV` 语义 cell，单位 cell 不作为 property evidence。
- electrical conductivity → official property `electric_conductivity`。
- specific gravity、bulk density、aggregate size、pore volume、surface area、fiber diameter、
  fiber length → material characteristic `specific_gravity`、`bulk_density`、`aggregate_size`、
  `pore_volume`、`specific_surface_area`、`fiber_diameter`、`fiber_length`。
- 样品/材料轴可使用 `polymer_sample`、`polymer_sample_group`、`polymer_brush_sample` 或
  `material_subject`；处理历史 condition 使用 `processing_history`；描述这些分组的过程元数据可使用
  `sample_history_header`；TGA 阈值与报告温度 condition 使用 `mass_loss_threshold` 和
  `temperature_condition`。

# Runtime output JSON Schema

{{output_schema}}


# Scoped evidence and subject context

- subject_catalog 是 Stage2/3 的候选摘要，不是正确答案；核对原文称呼、所属材料、状态和处理参数。禁止仅凭同种材料或候选唯一就指定具体样品。
- 无样品列的性质—值表允许 implicit_subject；材料可由表题、表注或明确引用此表的正文确定。一个表内不同状态或处理分组须分别限定范围。
- header_assignments 可使用 source_refs + source_quote + target_cell_ids 表示来自表头、行标签、表题、脚注、正文的性质；source_refs 可取 cells.cell_id 或 sources.source_id，source_quote 必须逐字来自所引用来源。表头或行标签引文必须引用对应单元格，不能只引用辅助脚注或默认引用表题。source_cell_ids 保留原有表内定位方式。
- scoped_relations 表示 subject/unit/condition/measurement_role/scale；每项必须给明确 target_cell_ids、来源及逐字引文。禁止依靠 reason 或 warnings 隐式传递条件。范围不明时不扩大到整表。
- subject 只提出目录中已有的 candidate_sample_ids/candidate_entity_ids；可以为空。最终挂靠由 Stage4R 验证，不创造样品。
- condition 区分 measurement、processing、state、unknown；name 使用规范命名。温度、配方中的数字是上下文，不是新的性质观察值。
- unit 从上级合并表头继承时只作用于其覆盖范围。scale 引用完整表头表达式，具体倍率方向由本地代码判定，不输出换算后的性质数值。
- measurement_role 只作用于明确表头/脚注覆盖的格；合法性质节点的 measurement_role 同样有效。不能因产率脚注含 calculated 就标记其他列为 calculated。
- sources 允许追溯各脚注；把标记所在表头/单元格与注释来源一起引用。整页图片只解释结构、材料、单位、脚注；性质数值始终取 OCR，禁止图中曲线读数和图片数值替换。
- OCR 单元格中即使有数值，也仅输出结构关系。不得输出任何测量值字段。完整性不足或冲突请明确警告，不猜测。

- 指数中混入脚注字母时，scale 的 source_quote 必须保留完整来源表达式；可提供 footnote_marker，但必须同时引用该标记的真实脚注定义。没有定义不得把字母当脚注自动删除。
