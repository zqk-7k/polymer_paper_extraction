---
prompt_id: polymer.stage4t.table_structure
version: 0.1.1
stage: stage4t_table_interpretation
output_schema: stage4t_table_structure.v2
---

你解释目标表的结构，由本地程序从 OCR 读取性质值。输出完整 JSON。
本协议需显式启用，不替代已有逐格协议。

输入包含完整 OCR cells（行列及合并跨度）、表题/脚注/相关正文 sources、
样品候选 subject_catalog、性质目录、可选整页图片及 images 清单。
仅解释 table_id 指定的表；同页其他表、图、正文不会自动成为本表条件。
图片用于表头、脚注、结构、单位及标签。禁止输出或补写图片中的性质数值。
材料代称没有唯一对应样品时保留未解决项，不猜样品。

输出：table_id、原样回填 input_fingerprint、direction、data_scope、excluded_scope、
definitions、rules、exceptions、visual_sources、unresolved。
行列从 0 开始、区间两端包含；所有坐标只对应当前 OCR 网格。
scope 使用 regions（row_start/row_end/column_start/column_end）、cell_ids、exclude_cell_ids。
data_scope 只包含性质数值原格，不包含表头、样品标签、说明或小计；不能把整张表当数值区。
同一区域优先使用 regions，不重复列出相同 cell_ids；稀疏附加格或局部例外仍可用 cell_ids。
范围只表达位置；不同性质、单位、倍率、条件、角色、样品各自指定范围。
不得让整列默认继承一个样品；轴规则的 labels 指定 OCR 标签区，same_row/same_column
由本地程序逐格读取，condition_kind 区分 measurement/processing/state/unknown。
两个条件轴分别给规则。性质—值配对表首行也可能是数据；没有样品轴时保留隐式材料。
合并格不允许被区域切开；可用该单元格 cell_id 定位，不重排或修补 OCR 网格。

definitions 定义一次含义；rules 用 definition_id 和 targets 显式应用，不允许递归引用。
每条 rule 只含 rule_id、definition_id、targets 和可选 axis。
axis 必须是对象 {"mode":"same_row","labels":{"regions":[...]}} 或 same_column，
labels 指向实际样品/条件标签格，targets 指向被解释的数值格；二者不可倒置或重叠。
不能在 rule 根部写 kind、reason、labels、same_row、same_column、content 或 middle_dot。
kind 可为 property、subject、condition、unit、scale、measurement_role、content。
每项有实际 source_refs、逐字 source_quote、简短 reason；不能写测量结果字段。
OCR 引文可引用 cells.cell_id 或 sources.source_id；直接引文来源与辅助脚注分别引用。
source_quote 必须完整存在于至少一个所列来源，不能用分号或说明文字拼接多个来源的原文。
property 必须给 role；目录内给 normalized_name，目录外给 semantic_label 和 unmapped_property。
condition 用简短 snake_case 的 name（如 temperature、solvent、concentration、method），
每个独立条件分别定义，condition_kind 指明用途；不能把整段脚注当作条件名称。
measurement_role 定义的 measurement_role 字段明确 experimental/calculated/reported_unknown；
只在 reason 写“计算值”不会传入逐格结果，也不能把局部 calculated 扩散至整表。
无目录名称仍保留 unmapped_property，不能删数据。
scale 必须引用完整表头；混入指数的字母只有引用真实脚注定义后才可识别为脚注。
此时显式给 footnote_marker，并在 source_refs 同时列出表头和对应脚注，source_quote 仍是完整表头原文。
scale_relation 区分 display_equals_quantity_times_power 与 quantity_equals_display_times_power，
power 是原表达式中的指数；不确定方向时放入 unresolved，不自行猜测。

content 描述整个区域内的内容类型：scalar/range/uncertainty/multiple/value_with_qualifier/text/unknown。
程序从原格生成数值片段，不能把材料、配比、样品代号里的数字当性质值。
multiple 表示多个报告值，不表示千分位。数字中点作小数点时显式声明 middle_dot；
具体写在独立 kind=content 定义的 decimal_style="middle_dot"，并给 content_type，
通过自己的 rule 指定范围；不能把这些字段附在性质、倍率定义或 rule 上。
不能把化学式、乘法中点一律当小数点。不符合规则的局部格保持原文并标未解决。
value_with_qualifier 必须给 qualifier_name 和 qualifier_kind，不把括号配比当多个性质值。

exceptions 必须指向 base_rule_id，并给局部 targets、独立证据和操作
replace/supplement/exclude/unresolved。只修改同一个 kind/name 字段，不能整包替换。
范围更小本身不构成例外；重叠矛盾例外保留冲突，不靠输出顺序决定。
需要替换轴关系时提供明确独立规则及排除区域，不猜例外标签。

图片中新识别的文字放在 visual_sources：visual: 前缀 source_id、已提供 image_id、
kind（header/footnote/caption/label）、text 和相对于整页的 0..1 bbox。
它是视觉转录，不能声称已通过 OCR 逐字验证。无法定位、不可读或和 OCR 冲突时写入 unresolved。
不输出全部原始数值、不逐行复述公共规则；也不能为了简短遗漏局部例外。
JSON 完整仅表示格式完整，不能声称所有脚注/性质/样品均已正确解释。
unresolved 是字符串数组；可在字符串中说明位置和理由，不输出嵌套对象。
省略不适用的可选字段，不编造未明示的单位；不同测量方法得到的值不因数值关系反常就改写。

以下仅说明字段形状，示例编号不能直接用于当前表（以实际输入为准）：
{"definition_id":"subject_axis","kind":"subject","source_refs":["actual_header_id"],"source_quote":"Sample","reason":"Explicit sample header"}
{"rule_id":"subject_rule","definition_id":"subject_axis","targets":{"regions":[{"row_start":1,"row_end":3,"column_start":1,"column_end":2}]},"axis":{"mode":"same_row","labels":{"regions":[{"row_start":1,"row_end":3,"column_start":0,"column_end":0}]}}}

完整输出 JSON Schema（字段与类型以此为准）：
{{output_schema}}
