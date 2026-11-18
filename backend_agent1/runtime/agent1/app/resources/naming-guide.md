# 通用命名工作指引 v1.1

## 新任务：有来源证据的共聚序列与嵌段

复杂脂肪链二价子单元的显式检查入口：结构型proposal可增加subunit_parser_contract:"iupac-substituted-acyclic-diyl/1.0"。当普通本地及OPSIN二价解析不支持时，工具按完整名称拆出饱和直链母体（1至12碳，明确两个自由价位次；也支持methylene/ethylene表达）和逐个明确位次的一价取代基；复杂取代基用配对括号。每个取代基由真实OPSIN一价解析，再按既有显式端口操作组装，核对该子单元及整体图。不能把OPSIN返回的有限烯烃当重复单元。保留电荷、同位素和原子/端口对应；指定立构超出既有组装器范围时返回工具缺口，原图不删立构。该入口检查已提出名称的构成和位次，不自动选择优选CRU/方向/最低位次或认证PIN。采用仍必须写完整规则及最终产物理由。依据：https://iupac.qmul.ac.uk/BlueBook/P2.html §P-29；https://iupac.qmul.ac.uk/BriefGuide/polymer.html §4.1。无需为工具强改一个已可直接核对的名称。

显式新source_declaration.contract:"identity-evidence-nomenclature/1.5"支持两条路线；外层proposal.contract仍identity-model-nomenclature/1.1，沿用review_naming adopt:true。原文只说明共聚/投料比时仍用旧co，不从反应机理猜ran或stat。IUPAC依据：https://iupac.qmul.ac.uk/BriefGuide/polymer.html §3.2表1。

来源共聚物：kind:"source_polymer"，monomers沿用已核对有限源/保留单体字段，sequence选unspecified、alternating、statistical或random。后三者须sequence_evidence:{status:"source_reported",descriptor:与sequence相同,as_reported:"原文字面序列说明",reason:"本对象为何采用此序列",source_refs:[实际原页]}。统计用-stat-，随机用-ran-，二源交替用-alt-；统计不等于随机。原文未知则unspecified/-co-。随机/统计对象不能声明单一整体ideal_repeat/constitution；局部单元与分布、端基、组成未知保留。

嵌段共聚物：先完成每种聚合物子块的名称/图/来源复核。kind:"block_copolymer",combination:"covalent",blocks:[{occurrence_id:"block-1",material_id:"子块id",source_refs:[原页]},...]，按原文实际次序保存；A-B-A可以三次发生而只引用两种材料，occurrence_id须各不相同，不去重。block_evidence:{status:"source_reported",descriptor:"block",as_reported:"原文嵌段说明",reason:"本对象共价嵌段及次序依据",source_refs:[实际原页]}。每个components中的子块绑定relation:"covalent_block_segment"；材料kind为polymer/prepolymer，structure_expression按已有source_only或local_connectivity合同保存源分子/局部图及未知，不把嵌段整体写成物理assembly或单一ideal_repeat。工具生成poly(A)-block-poly(B)等各块名称连接表达；子块的盐/立构/同位素及假设不删，连接位点、端基、块长度分布未知仍保留。物理共混走blend，接枝走graft；缺嵌段证据时退回适用较宽来源名，不为通过合同编造原文。

新任务采用策略 identity-adoption/1.5：提案语义仍1.1，review_naming 的 adopt:true 保存实际回执和确切名称，最后 finalize 一次完成当前材料复核与finish。先稳定身份/图/冲突/依赖名称，避免不断重建提案。明确作用于其他材料的事实/冲突不让本对象命名过期；本对象、依赖组分、未限定对象的共同证据变化仍会过期。工具追加回执、描图或描述符不等于化学改变。所有主动采用的名称、图、电荷、同位素、立构、端口、来源和假设仍参与核对。

名称由本篇主模型提出。本资料是命名规则指引，不是材料答案库；原文事实仍只来自本篇。所有模型核对均为 SAME_PRIMARY_MODEL，不能写成人工或独立审核。

先确认命名对象：有限分子、完整理想重复构成、不规则高分子、后改性、接枝、共混或样品状态。投料比与实际并入组成分别保存。未定链长和端基不阻止理想聚合物命名；指定的盐、电荷、同位素及立体不能省略以换取工具通过。

## 完整理想重复结构

1. 从最终产物图选择可命名的完整二价子单元，逐一给出系统名、SMILES、左右连接端口。必须覆盖全部原子及取代基。稠合环需按固定环系编号判断连接位置，不能按SMILES原子次序编号。
2. 子单元优先级按 RSSOP §4 判断，先区分杂环、杂原子链、碳环和无环碳链，再处理同类内部优先次序。参照 https://iupac.qmul.ac.uk/rssop/ss04.html ，在 rule_review 写出本结构的实际比较理由。
3. 对可行重复单元起点与两种方向进行比较。复杂单元需考虑优先子单元、通向下一优先子单元的路径、平局及位次；不能把RDKit规范SMILES的方向当成命名方向。参照 https://iupac.qmul.ac.uk/rssop/ss05.html （Rules 11–17）。说明为什么选择当前顺序。
4. 完成子单元名称及括号层次。参照 https://iupac.qmul.ac.uk/rssop/ 和 https://iupac.org/wp-content/uploads/2019/07/140-Brief-Guide-to-Polymer-Nomenclature-Web-Final-d.pdf §4.1。各子单元分别加括号后串联，外层随已有层次扩大为 [] 或 {}。指定相对立构时用 proposal.tacticity:{value:"isotactic/syndiotactic/atactic",reason,source_refs}，主名相应加it-/st-/at-；rule_review加tacticity主题。CRU图核对和链级相对立构证据分别记录；明确R/S或其他编码立体不能靠相对立构前缀代替。
5. review_naming 自动先用本地子单元解析器，未支持时尝试真实OPSIN二价解析，核对具体连接位置，再组装并核对整图。这证明的检查范围会单列；优选方向的模型理由不冒充程序证明或完整PIN认证。

## 工具不支持或原文不足

UNSUPPORTED是检查覆盖缺口，不等于化学错误。读回具体缺口，检查名称重述及规则依据，至多两次有实质变化的尝试。工具不能检查的子单元可在完整图组装一致、规则理由明确时作为最可能结构名候选，状态仍注明工具缺口。整图无法核对、发现冲突或关键规则仍 unresolved 时，修正提案或选择更宽且符合适用规则的来源/改性/接枝/组装名称，不把材料描述冒充系统名。

来源名称参照简明指南 §3；它允许真实或假设的命名来源，但不会证明实际反应。后改性参照 https://doi.org/10.1515/pac-2014-0610 ，接枝及来源命名参照 https://doi.org/10.1515/pac-2015-0702 。样品与理想结构的区别、假设和其他可行情况保留。

## 最终产物检查

在 product_identity_check 中逐项说明：名称是否体现本次产物阶段、关键连接/官能团/环化变化、指定立体或盐/掺杂状态；投料/组成是否被错误解释成固定重复单元。若前体与产物的来源名相同，必须解释名称如何区分产物；结构明确时应优先结构名。确实无法完整结构命名时，保留适用的较宽命名表达及身份限定，不声称来源名已验证产物构成。

## 工具输入

review_naming: {material_id, proposal:{contract:"identity-model-nomenclature/1.1",kind:"structure_polymer"或"evidence_name",text,graph_id（结构型）,parts:[{name,smiles,left_port,right_port,src}]（结构型）,tacticity（有指定相对立构时）,source_declaration:{1.0/1.1/1.3证据声明}（来源等；类别路线不填）,name_scope:"class_based"（类别路线）,identity_qualifiers:[],source_refs,evidence_basis:"source_supported/broader_scope/feasible_hypothesis/most_likely_hypothesis",hypotheses:[{statement,reason,source_refs}],hypothesis_ranking（声称最可能时）,conflict_review:{status,examined_source_refs,conflict_ids,reason},selection_reason,product_identity_check,rule_review:[{topic,rule_ref,conclusion:"supported/assumed/broader_scope/unresolved",reason}]}}。

结构型必需 topic：subunit_identity、numbering、cru_selection、direction、syntax、product_identity。其他路线必需 syntax、product_identity。rule_ref 给上述真实规则URL与具体条款；reason 写本对象的应用理由，不能只说“符合IUPAC”。unresolved必须先改成更充分提案/更宽范围，不能空填通过。

本次新任务使用 proposal.contract:"identity-model-nomenclature/1.1"；旧1.0回放不变。成功后保存确切most_likely_name.text和同合同nomenclature_declaration:{contract,review_receipt_id,proposal}。先完成全篇材料、图、关系、事实与冲突，按组分/基础→派生/组装依赖顺序review_naming，最后upsert/review/finish。MODEL_RULE_REVIEWED不等于全名GRAPH_MATCH，也不认证优选名称。

## 较宽名称、聚合侧链与证据强度

来源不明但类别有依据时使用 evidence_name + name_scope:"class_based" + evidence_basis:"broader_scope" + identity_qualifiers:[产物阶段、拓扑/组成限制等]，不提交source_declaration。rule_review必需syntax、product_identity、scope；类别定义用 https://goldbook.iupac.org/ 或 https://publications.iupac.org/pac/81/6/1131/index.html 。这条路线不强制编造可被OPSIN解析的单体，结果是类别名称、模型规则核对及工具覆盖缺口，不是完整分子结构名称验证。

已经有共聚物支链身份的接枝材料使用source_declaration:{contract:"identity-evidence-nomenclature/1.3",kind:"graft",base_material_id,branch_material_id,topology:"polymeric_side_chains",source_refs,evidence_basis,identity_qualifiers}。先核对两个聚合物名；关联必须是骨架→本接枝产物graft_backbone_of及侧链→本接枝产物graft_sidechain_of。此时不再同时填graft_sources，不能以几个有限单体代替已知聚合侧链。

有多个相容候选、无法排序时采用feasible_hypothesis并保留hypotheses；只有明确比较真正备选及来源理由时才用most_likely_hypothesis，额外hypothesis_ranking:{alternatives,reason,source_refs}。不是每次抽取都要扩展候选表；较宽名称足够时优先保留范围。子声明和基础/侧链假设必须继承，不能升级为原文证明。

## 冲突处理

每个新提案含conflict_review:{status:"none_detected",examined_source_refs,conflict_ids,reason}。命名、关系、身份用量要回看原页；存在冲突时把各原值、倍率、单位、来源表示分别放material.evidence_conflicts或带material_id的共同source_conflicts，格式见core-prompt。resolution只能unresolved/hypothesis/source_confirmed；确认需原文依据。数值更合理不是原文修正证据；未知仍保留。命名受影响且未解决时采用broader_scope，按假设选择必须标为假设；不相关冲突保留但不拒绝名称。程序只能守住已声明冲突，不能证明模型已看出所有OCR差异。


新任务1.4最终来源复核：模型决定化学身份/命名，本地只校验声明与当前状态绑定，不声称能够写全IUPAC。命名与来源事实稳定后，finalize除reason外增加source_checks:[{material_ids:[同一原文结论确实作用的主要对象id],topic:"identity",source_refs:[具体原页/块],disposition:"consistent",reason:"本次回看原页后的具体发现"}]。每个主要对象至少覆盖identity和quantities两个主题，可按相同来源/同一系列合并，但不能用一条空泛理由包办全篇。identity回看关键结构图、正文定义、代码和反应步骤的具体异同，包含连接位置、基团、立构/电荷和局部图范围；quantities回看表头/行/原字面数值、倍率、配方基准、状态/方法。优先复看会改变最终身份或关键性质的来源；不逐曲线抄数。原始图文不一致先保存冲突，再选较宽或显式假设名称，不把更合理的数字称source_confirmed。泛讨论/引文/不同状态材料不自动成为本样品冲突；确属同对象的出入保留。source_checks是本session模型复核，绝非独立审核。化学/来源/名称变化使回执过期，重新finalize带当前source_checks；普通派生核对输出不使其过期。

单一聚合物加有限小分子的物理复合物：先分别命名聚合物基体和有图的有限组分，不以专用polymer-blend或唯一全材料CRU替代。可用显式新identity-evidence-nomenclature/1.4声明{kind:"matrix_with_components",base_material_id:"基体id",combination:"physical",source_refs,evidence_basis,identity_qualifiers}，仅适用于已明确的一聚合物+有限组分配方。最终主名为已核对聚合物基体IUPAC范围名，proposal.name_scope:"polymer_matrix"，详细性质/组成中同时展示各组分真实有限名和原始用量/基准。components保存所有物理配方对象、量/基准/未知（包括基体），关系type:"formulation_component"从各组分→整体；structure_expression.kind:"assembly"，不能声明整体constitution。有限组分必须用真实resolve回执核对现有有限图，仍不支持时保留缺口，不冒充命名就绪。这声明只命名基体及组成，不宣称整个混合材料有单一正式IUPAC名；多聚合物仍走既有blend，实际共价反应仍按产物命名。真实盐/立构/同位素/端口不删。旧1.2/1.3任务/采用版本不迁移。


新1.5来源绑定细则（替代旧1.4仅覆盖两个主题的最小格式）：finalize仍带identity/quantities两主题source_checks，每条另有conflict_ids（无冲突[]）、observations:[{material_ids:[本条确实核对的对象],source_refs:[本对象已有原页引用],representation:"page_image",locator:"实际图号/表号及行列/段落位置",as_reported:"原始图文表达/数值含倍率单位；无相应报告时明确原文未报告",material_scope:"this_material",state_basis:"本文样品代称/材料状态/测量条件，未知明确说明"}]。每条的观察覆盖其全部对象；不同原行或状态分别列，不把背景/前体/其他状态当本对象。PDF观察须含page:N且这些引用与各对象source_refs相交；小字号须实看原页/裁剪。此格式只校验声明及绑定，不认证像素解释。原文没有某性质就写未报告，不能为满足格式发明数值。
每条identity复核另带identity_limits:{salt_charge:"报告的电荷/盐及主名称范围；未知明确说明",stereo_isotope:"已报告立构/同位素与编码范围；未定明确保留",end_groups:"已报告端基及主名是否只覆盖理想单元；未知明确说明",assembly_topology:"有限/重复/局部网络/配方范围及实际连接或拓扑未知"}。同源同边界可合并，否则拆条。已保存的各material.evidence_conflicts/source_conflicts须在作用对象的复核conflict_ids中逐个引用，含冲突的条目disposition:"conflict_preserved"；其他主题无冲突仍可consistent/unknown。严格相等的双层冲突只是重复视图，不需删除原始记录；同ID不同内容仍拒绝。名称过宽或漏已知盐态/端基时，在最终名称声明identity_qualifiers及对象unknowns/naming_limits保留边界，不宣称单一全材料正式IUPAC名。
新1.5所有保存identity_properties均须source_evidence:{representation:"page_image",as_reported:"非空原字面值含倍率/单位/状态",material_id:"本对象id"}；表格另有table、column_header、row_label。空白、nd、范围、倍率、估计/测得、feed/并入分别保留。不为程序字段补科学答案，不以合理性私改原值。source_confirmed只可用明确原文证据，仍需保留全部替代值。先完成这些来源/范围事实，再按依赖顺序命名、finalize；不要在工具核对无变化时重复大payload。旧1.4任务与采用版本不会升级。

通用工具合同帮助：遇到字段拒绝可调用help:{}，它只读取当前主要对象ID和中性合同，写正常工具回执，不改current、不调用化学/网络，仍受原截止限制。失败的diagnostics给出对象/检查序号/字段位置/引用差集；据实际原文处理原因，不能为消除错误编造值。每条source_checks.topic只选identity或quantities之一，不能填字面identity/quantities；material_ids只含当前major对象，两主题各覆盖全部major，辅助/背景对象不在此最终清单。source_confirmed是主模型按原文作的声明，程序不证明像素解释；原值/替代说法和未知仍保留。

示例使用一个合法值；按实际来源选择允许值，不能把候选项拼成斜杠字符串。disposition选consistent、conflict_preserved或unknown。conflict_review.status选none_detected或preserved；存在冲突时选preserved并保留全部conflict_ids。resolution.status选unresolved、hypothesis或source_confirmed；representation选一个来源表示，PDF原图观察须page_image。
