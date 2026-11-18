2026-10-10两篇未交付修复已闭合：本次新授权两篇均 DELIVERED，合计 21 个主要对象。原20轮的封存结果仍为18交付/2未交付；这两篇在独立新任务中重新执行后，原选定20份来源已全部有正式采用结果，原失败回执保持不变。

OPSIN 懒编译目录已改为每个任务的 tool-runtime/opsin-build，修复 workspace-write 下 WinError 5；预检新增真实 OPSIN 解析和有限图匹配。310 pytest、阅读器与语法测试、中性运行复核、真实同会话 CLI 预检、176 既有采用版本只读合同回放通过。每篇原60分钟、持续 gpt-6.1-sol/xhigh/workspace-write 串行，实际 31.8/9.8 分钟；仅原来源输入，无旧答案或人工参考。

组分库自动更新：175篇/4,225记录/2,176身份 → 177篇/4,253记录/2,186身份，新增 28 条组分记录，采用与服务接口读回一致。在线 PubChem 性质补充状态独立记录于完整报告，不等同于论文交付状态。2,246 个历史保护文件未变，182 条封存反馈绑定通过；Kernel 0.9.0 不变，独立 NOT_REVIEWED/PIN 未认证，无其他论文或旧队列启动。

修复报告：[REPORT_FINAL.md](../runs/IDENTITY-TWO-NONDELIVERY-REPAIR-20261010-01/REPORT_FINAL.md)。以下为历史阶段记录。

2026-10-09新授权20篇已正式开始（IDENTITY-FOLLOWING-TWENTY-20261009-01）：从剩余48篇中冻结20篇，17份已校验OCR+原始PDF页、3份直接原始PDF页，无新OCR上传。每篇一个持续gpt-6.1-sol/xhigh/workspace-write会话、原60分钟逐篇串行，隔离执行副本冻结为f826ff65665e，Kernel0.9.0不变；首篇SC-20261009T083909Z-d3dffa95已于16:39开始。此前两篇自动交付并入库已核实：157篇/3,968记录/2,096身份，共新增67记录。PubChem与本地性质后台继续独立执行，不占用论文预算；完整批查询尚未完成，新交付论文在线补充等待全量批结束后自动增量处理。实时抽取状态见 runs/IDENTITY-FOLLOWING-TWENTY-20261009-01/PROGRESS.md，完成后实际封存报告为 REPORT_FINAL.md；当前不宣称20篇已完成。未选28篇与旧队列不启动，独立NOT_REVIEWED/PIN未认证。以下为历史阶段。

2026-10-09等待PubChem期间新授权2篇已完成：2 DELIVERED、20高分子主要对象，原60分钟/持续6.1-sol-xhigh-workspace-write串行，实际32.8/30.5分钟。组分库实测155→156→157篇，新增67条，当前3,968记录/2,096汇总身份/346跨文献共享身份，新组分本地性质立即可读。1,215旧保护文件无变化、160反馈绑定PASS，Kernel0.9.0，独立NOT_REVIEWED/PIN未认证。PubChem全量仍自动续跑：检查点622/1,676，累计缓存643明确结果/92失败/941待请求，HTTP429后预计16:43再试；该在线等待未阻碍两篇交付。未启动余下48篇或旧队列。详见 runs/IDENTITY-TWO-WHILE-PUBCHEM-20261009-01/REPORT.md；以下为历史阶段。

2026-10-09组分工具性质与增量更新已交付至 http://127.0.0.1:8780/knowledge?sort=sources ，start.ps1默认8780。默认显示既有RDKit计算和实际PubChem資料；单篇命名理由/未知项在明确选择的“来源身份”。新增交付PDF自动入库，独立后台30秒检查并补充缺失性质，页面10秒检查并保持当前操作；不改变论文求解预算、核心工具/命名/采用门槛。155篇/3,901条/2,058身份；已冻结并实际执行1,676个PubChem查询，全量仍未完成，实际缓存432项得到匹配/候选/明确无匹配结果、143失败、1,101待请求，服务429冷却后由断点进程自动继续，详情以Data/library-enrichment和实际日志为准。305pytest、全部15个Node阅读脚本/语法、真实同会话工程预检、API及浏览器通过；1,215保护文件无变化，Kernel0.9.0、独立NOT_REVIEWED/PIN未认证，无新论文/旧队列。本次执行清单与封存前后实现分开留证。见 ../runs/IDENTITY-LIBRARY-PUBCHEM-20261009-01/REPORT.md；以下为历史阶段。

当前2026-10-09授权后续5篇已闭合：{"DELIVERED": 5}，累计155唯一采用PDF。原60分钟/持久6.1-sol/xhigh逐篇串行，10主要对象封存后模型原文有限回查，158反馈绑定，全库回放/历史保护/API/UI通过。人工JSON内容未读，50未选和旧队列未启动，无第6篇。Kernel0.9.0，主模型复核与独立NOT_REVIEWED/PIN未认证分开。详见runs/IDENTITY-FOLLOWING-FIVE-20261009-01/REPORT_FINAL.md。

2026-10-09组分库重新设计已交付至 http://127.0.0.1:8777/knowledge?sort=sources ，start.ps1默认8777。紧凑卡片、横向用途筛选、共享/排序/搜索；化学身份、12篇分页来源、分类文献关联在同一身份证窗口中阅读，保留列表与筛选，文献链接默认新页面。修正水→4BI等辅助关系的展示：原文明确“不属于产物组成”的关系归入工艺辅助，不再统称“使用该组分的材料”；逐篇身份按选中版本绑定。291pytest、17项Node阅读检查、两份JS语法和真实API/浏览器通过，缓存目录/检索约0.28–0.56秒。1,192项保护中1,190项不变，另一个既有任务的run/current两项状态变化单独留证，原采用版本及封存文件无变化。Kernel0.9.0、原文献及文本命名流程不改，本轮无论文或命名CLI；有限结构汇总不代表完整实物身份或独立化学审核。见 ../runs/IDENTITY-LIBRARY-REDESIGN-20261009-01/REPORT.md；以下旧地址与旧统计为历史。

2026-10-09组分来源汇总已交付至 http://127.0.0.1:8776/knowledge?shared=1&sort=sources 。相同已保存有限结构按组分汇总，卡片显示可点击文献数及组分记录出现次数，12篇分页来源保留角色、关联材料与原文献身份证；提供逐篇记录、跨文献共享筛选和来源数排序。最终只读统计151篇、3,753条记录、1,966项汇总、324项跨文献共享；甲醇71篇/71次、苯乙烯28篇/28次、氧化镁3篇/4次。统计期间另一既有PDF任务完成并自动纳入，本任务未启动任何论文或命名CLI。完整286pytest通过，随后搜索排序的19项专项通过；全部Node阅读检查及语法通过。前轮1,092个保护文件与本轮原有采用版本/封存回执不变；另一个既有任务的run/current状态变化单独留证。Kernel0.9.0及文献/文本化学功能不改，结构汇总不等同完整真实材料身份。审批策略阻止停止本轮8775预览进程，最终版另开8776。见 runs/IDENTITY-LIBRARY-SOURCES-20261009-01/REPORT.md；以下旧地址与旧统计为历史。

2026-10-09组分库与文本工作台修复已交付至 http://127.0.0.1:8774/ 。组分库改为24条分页检索、常用用途分类、搜索式来源筛选、结构详情与材料/文献链接，版本绑定索引支持跨进程复用；150篇/3,742条记录不变。文本工作台的提交、队列、原文重用、结果来源与IUPAC显示已贯通，单个中性乙烯均聚物文本持续6.1-sol/xhigh一次CLI自动交付poly(methylene)。274pytest、全部Node阅读测试与语法、真实CLI预检和浏览器通过；1,092原有状态/封存/采用/版本文件哈希不变。Kernel0.9.0，独立NOT_REVIEWED/PIN未认证，无新论文/旧队列。旧8773替换操作被自动审批策略阻止，新版单独运行8774。详见runs/IDENTITY-LIBRARY-WORKBENCH-20261009-01/REPORT.md；此前记录均为历史。

当前授权后续15篇已闭合：{"DELIVERED": 14, "INCOMPLETE": 1}，全库150唯一采用PDF。逐对象命名复核写盘修复应用于本批，冻结同一实现、原60分钟/持久6.1-sol/xhigh逐篇串行；三批共29主要对象模型原文有限回查、152反馈绑定、全库原合同回放/历史保护/API/UI通过。4篇人工JSON存在优先，内容未读。Kernel0.9.0，主模型复核与独立NOT_REVIEWED/PIN未认证分开。55未选与旧队列未启动，无第16篇。详见runs/IDENTITY-CHECKPOINT-CAPABILITY-FIFTEEN-20261008-01/REPORT_FINAL.md。

当前2026-10-08命名/技能优化十篇已闭合：9DELIVERED、1INCOMPLETE，136唯一采用PDF。新增序列/有序共价块与复杂二价子单元入口；新十篇实际使用新后备路线1例。第6篇24命名评估保存已验证；批后逐对象review写盘与通用求解方法修复完成，工程/同型号模型中性复验/136旧合同回放/保护/真实CLI门槛通过。原执行与批后实现分开留证，Kernel0.9.0。新授权15篇已选但本段发布时未启动；4篇人工JSON存在优先，不读人工内容；真实进度见runs/IDENTITY-CHECKPOINT-CAPABILITY-FIFTEEN-20261008-01/extraction.json。完整结果见runs/IDENTITY-NAMING-OPTIMIZATION-TEN-20261008-01/REPORT_FINAL.md。

当前2026-10-08新批执行前评估完成：127个唯一采用来源/1,449个高分子主要对象；3,930图和1,221原页图工程绑定PASS，11材料/22保存图固定6.1-sol/xhigh有限模型复审完成。新增显式序列/有序共价块及复杂脂肪链二价子单元入口；模型发现B01序列静默降级已修并同SID复验。polymer-identity技能安装，127只读派生诊断绑定PASS；264pytest/Node/真实CLI/回放/103,201保护PASS，Kernel0.9.0不变。新增10篇已选但本段发布时尚未启动，不读人工JSON内容、旧证据不改。详见runs/IDENTITY-NAMING-OPTIMIZATION-TEN-20261008-01/PRE_TEN_ASSESSMENT.md；实际后续进度见同run/extraction.json。

## 当前最新状态：2026-10-08十篇完成及批后引用校验修复

新授权10篇全部DELIVERED；每篇原60分钟、持久6.1-sol/xhigh/workspace-write串行，原文先核对后有限19份人工JSON回读闭合。现有127个唯一采用PDF SHA（旧117＋10），历史合同回放PASS。第9篇六个未定义组件引用保持封存并在页面提示；所有十篇冻结完成后，新任务另启用identity-material-references/1.0机械校验，采用1.5/来源复核1.1/Kernel0.9.0不变。218 passed, 6 warnings in 311.46s (0:05:11)，Node及语法/真实非paper预检/API/UI/103,073保护文件PASS。实际十篇实现c4cbc1ee6c845cf8f5a93424cf7f2eeecb47b5fb1cdc76b856f16c540759b1df，批后工程实现80b7c61e3e29224af51c29ea3997fae0ba51fb5147242d1efa75cf2ef2f0e704分别留证。独立NOT_REVIEWED/PIN未认证；新合同尚未经新增论文运行，无第11篇/旧队列/80未选来源启动。详见runs/IDENTITY-MATERIAL-REFERENCES-POSTTEN-20261008-01/REPORT_FINAL.md。

## 当前最新状态：2026-10-08新授权10篇已完成

本轮10篇已尝试并封存：{"DELIVERED": 10}；有限原文核对与19份人工JSON投影回读已绑定保存版本。唯一采用原PDF现为127（旧117＋本批10），不是骨架数量。实际实现c4cbc1ee6c845cf8f5a93424cf7f2eeecb47b5fb1cdc76b856f16c540759b1df，内核0.9.0，历史保护95,733文件PASS。独立化学审核NOT_REVIEWED、PIN未认证。没有第11篇或旧队列执行。详情见runs/IDENTITY-FOLLOWING-TEN-20261007-01/REPORT_FINAL.md。

当前2026-10-07新授权10篇已冻结并开始顺序执行，全部来自有精确人工JSON的未尝试来源目录；9份验证既有OCR+原页，1份直接原页，新OCR POST0。当前实现c4cbc1ee6c84、identity-adoption/1.5、source-review/1.1、Kernel0.9.0不变，复用完全相同实现的200pytest/Node工程PASS并已做新的真实同SID CLI预检PASS。每篇持续6.1-sol/xhigh/workspace-write，原60分钟，人工仅封存后有限阅读。95,733既有保护文件已建清单并初验PASS；未选80个与旧队列不启动，独立NOT_REVIEWED/PIN未认证。实际进度见runs/IDENTITY-FOLLOWING-TEN-20261007-01/extraction.json；本批尚未完成，以下保留此前阶段历史。

当前2026-10-07 00:34上海本轮已闭合：新增15实际尝试/15DELIVERED，按人工JSON同路径存在优先选取；一处已读人工文件封存后确认非同文配对。现有117个唯一采用PDF SHA（原102+新15），全部按原合同回放PASS。1.5来源对象/字面原值/状态/冲突复核及四类身份范围用于本批；全部封存后另加字段级失败诊断、只读help、主模型确认标识、版本绑定封存后说明和保守数值显示。实际200 passed, 6 warnings in 404.51s (0:06:44)，Node阅读器/范围/新说明与语法、旧85,619保护文件、真实非paper CLI预检、只读API及浏览器UI验收PASS；Kernel0.9.0不变。

本批实际实现651f9d6a038d，批后实现c4cbc1ee6c84，原执行清单和四篇最初封存保留。每篇一个持续6.1-sol/xhigh/workspace-write CLI，原60分钟，未据人工补化学JSON/采用、延长截止、追加第16篇或恢复旧队列。原文先有限核对后每篇2份人工有界投影，共30份；没有全量独立审查。第8篇原图确认声明错误、第5篇数值副本和第11篇制备归属/人工错配以版本绑定说明曝光，原采用保持封存。独立NOT_REVIEWED、PIN未认证；90未选来源不启动。新服务[阅读文献](http://127.0.0.1:8771/paper)已实际核验。完整评估/处理/结果见[REPORT_FINAL.md](<D:/work/szlab/project/on going/agent/polymer project/Polymer_Identity_App/runs/IDENTITY-GENERAL-AND-FIFTEEN-20261006-01/REPORT_FINAL.md>)。以下段落保留历史记录，旧“运行中/未完成”和历史服务地址不表示当前状态或新启动授权。

当前2026-10-06新授权：102篇采用/103篇至少尝试的通用评估完成，1.5来源对象/原值/状态绑定、冲突复核/严格重复视图、身份范围展示已实现。178pytest/Node阅读与语法/102旧版回放/真实6.1-sol-xhigh-workspace-write同session读图工具写入预检PASS，Kernel仍0.9.0。新15篇已冻结并由单顺序driver24916执行，全部来自有精确人工JSON的路径；13既有OCR+原页、2直接原页，新POST0，人工参考不进入worker/调参，旧封存不改，90未选和旧队列不启动。15尚未完成，实际状态见runs/IDENTITY-GENERAL-AND-FIFTEEN-20261006-01/extraction.json和报告；独立NOT_REVIEWED/PIN未认证。以下为此前历史阶段记录。

2026-10-06阅读器修复：目录缓存/刷新合并/gzip/折叠原始记录按需生成，长系列标签不再压缩重叠。163pytest与10组Node、语法、13124保护条目检查通过；102篇目录字段和V20采用版本/238主要记录保持一致。新UI服务http://127.0.0.1:8772（旧8771保留），缓存后目录约0.11秒，服务初始完整校验仍约19秒。本次不改化学结果、不跑新文献；最近两轮仍有来源冲突/名称范围/工具覆盖通用问题，独立NOT_REVIEWED。详见runs/IDENTITY-READER-PERFORMANCE-20261006-01/REPORT.md。以下为历史阶段记录。

当前2026-10-06T04:59:50.677798+00:00：固定1.4后续V20已20真实尝试/20DELIVERED/0INCOMPLETE，4批原文先粗看、候选主要身份/代表图/关键性质比较、保存SOURCE_REVIEW后有限匹配参考、运行/封存/采用/保护全部闭合。driver4124真实exit0；FINAL_RUNTIME_PROOF无活动paper/CLI、冻结3385ba.../gate/22051保护及20原预算/同SID/有效6.1-sol/xhigh/workspace-write PASS。238主要=229polymer/blend/network（133结构/63来源/19类别工具缺口/14规则工具缺口）+9有限（8passport名+MTM actual name）。无人工补化学JSON/手工采用/旧答案续填/扩预算，有运营监督。独立NOT_REVIEWED/PIN未认证；有限粗查未见检查范围系统性主身份错误，不能推全量科学准确率/近人工或105无人验收。

实工具3381领域/482resolve=476真OPSIN+5cache+1解析前归属fail，458PARSED17UNSUPPORTED6INVALID1TOOL_FAILED；117图像包装/314同模型sourcechecks/686工程图绑定/publiclookup0/providerNOT_EXPOSED。第20篇3PVC+有限DBTM实际matrix仅命名基体，9双polymer blend另走旧路径；MinerU25旧GET/newPOST0。P160工程用例及真实中性预检PASS只证明工程范围。T旧19/1外部fail和U重确认恢复保持各自历史，不改旧失败。B4dodecene45原值纠正监督43误读、文件summary/aggregate有限额外阅读边界和所有撤回留证；首批4WordCU截图监督确见但SOURCE_REVIEW之后/未入worker，不能声称像素完全隔离。

完整阶段与规模结论见[REPORT_FINAL.md](<D:/work/szlab/project/on going/agent/polymer project/Polymer_Identity_App/runs/IDENTITY-FOLLOWING-TWENTY-20261006-01/REPORT_FINAL.md>)，工具范围见[TOOL_COVERAGE_FINAL.md](<D:/work/szlab/project/on going/agent/polymer project/Polymer_Identity_App/runs/IDENTITY-FOLLOWING-TWENTY-20261006-01/TOOL_COVERAGE_FINAL.md>)，通用改善实际验证/剩余问题见[ANALYSIS_AFTER_FOLLOWING_TWENTY.md](<D:/work/szlab/project/on going/agent/polymer project/Polymer_Identity_App/runs/IDENTITY-NEXT-TWENTY-GENERAL-IMPROVEMENT-20261005-01/ANALYSIS_AFTER_FOLLOWING_TWENTY.md>)。105未选与旧队列不启动。以下为截至闭合前的历史观察；旧RUNNING/尚未粗查/尚未完成等只反映当时时态，不是当前进度或启动指令。


当前2026-10-06固定1.4后续20已20真实启动/19DELIVERED，序20原SID健康运行driver4124/CLI18252/原deadline05:03:50UTC不变。前三批1–15源先粗查/有限参考/封存保护闭合；16–19只有机械封存与原文预备，候选正文/参考未读，20原文未准备。222封存主要=213高分子（129结构51来源19类别14规则工具缺口）+9有限（8passport名+MTM actual name），已粗查/实工具汇总仍前15。原driver在18封存后19启动前真实12h中性续检PASS[0,0]/同SID图像工具写入，工程健康不当科学增益。018呋喃聚酯feed/并入/原页DP与malate出入、019quinolate配位/残Si及原表/步骤TgTdec和epsilon出入仅source-only预备，不给worker。冻结/22051保护PASS、25旧GET/newPOST0/public0；无人工补化学JSON/采用，有运营监督，105未选不启动。20全批粗查/最终报告/工具范围/规模结论尚未完成，独立NOT_REVIEWED/PIN未认证。见runs/IDENTITY-FOLLOWING-TWENTY-20261006-01/REPORT.md，下文旧时态仅历史。

当前2026-10-05通用改进1.4已实现：来源复核绑定、聚合物基体+有限组分配方范围、独立固定CLI保存。160pytest/Node/语法/编译及真实同session读图/工具/写入预检PASS；21572旧证据保护通过。原本批20已19交付1外部未交付，新job SC-20261005T150456Z-8c32b8f3正在确认原未交付来源；后续20已授权，尚未选择/启动，确认封存粗查后从剩余125选择。新工程通过不能推科学正确率，旧12/14/15未静默改写，独立NOT_REVIEWED/PIN未认证。当前阶段见runs/IDENTITY-NEXT-TWENTY-GENERAL-IMPROVEMENT-20261005-01/REPORT.md，下文为历史状态。

当前2026-10-05本批20已闭合：19DELIVERED/1固定CLI消失外部INCOMPLETE，源先有限参考后粗查全部完成。247已采用主要名称；仍有原图冲突漏标、表数值误读、复合材料主名/回执缺口，不宣称近人工全面合格或可全量无人。原9483与新封存保护通过；旧外部runtime当前缺失。用户已授权父P通用改进/新版本真实验证后再20篇，后续20尚未启动，125未选及旧队列不启动。详见runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT_FINAL.md和runs/IDENTITY-NEXT-TWENTY-GENERAL-IMPROVEMENT-20261005-01/PLAN.md。独立NOT_REVIEWED，PIN未认证。

当前实际进展（2026-10-05）：固定1.3新20已18启动/17自动交付/0未交付，第18篇运行；1–17源先粗查/有限参考已闭合。230主要记录含221聚合物/组装范围名称（100结构/111证据/5规则工具缺口/5类别）及9有限passport名，不误计finite缺名。16图文酯O冲突保留、17缩甲醛线性/有限环和测量/计算分子量合理，17实际CLI[1]自动45min收尾已有READY，自动采用未改预算。12骨架漏冲突、15表值误确认、14/16主名过宽等仍待通用改进。原9483+新10609封存保护/冻结PASS，独立NOT_REVIEWED；无人工补化学JSON/改代码/续填/采用，有运营监督，16有限参考投影嵌套图字段遗漏已纠正留证、未进worker/调参。20OCR校验/26GET/newPOST0，125未选与旧队列不启动。完整20及最终规模结论未完成，当前NOT_READY。见[实际报告](../runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT.md)和[工具实调用范围](../runs/IDENTITY-NEXT-TWENTY-20261005-01/TOOL_COVERAGE.md)。下文历史状态不作启动指令。

截至2026-10-05T13:37:27.572872+00:00，固定1.3新20已19启动/18DELIVERED/0INCOMPLETE，原驱动继续第19篇，原截止2026-10-05T13:59:29.839982+00:00。1–18原文先粗看、有限参考和封存/采用/图像/实际模型期限审查已闭合；18结晶poly(vinylcyclohexene)主要身份/性质粗看相符，异常投料/立构不确定保留，重复图片空白疑虑撤回。原9483/新10949保护PASS。12骨架冲突漏标、15一处表值误确认、14组装主名/有限回执缺口仍在，冻结不改旧结果。无人工补化学JSON/采用，有运营监督，独立NOT_REVIEWED。完整20及最终效果/工具范围/扩大规模结论未完，125未选和旧队列不启动。见[实际报告](../runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT.md)与[工具范围](../runs/IDENTITY-NEXT-TWENTY-20261005-01/TOOL_COVERAGE.md)。

当前实际进展（2026-10-05）：固定1.3新20已18启动/17自动交付/0未交付，第18篇运行；1–17源先粗查/有限参考已闭合。230主要记录含221聚合物/组装范围名称（100结构/111证据/5规则工具缺口/5类别）及9有限passport名，不误计finite缺名。16图文酯O冲突保留、17缩甲醛线性/有限环和测量/计算分子量合理，17实际CLI[1]自动45min收尾已有READY，自动采用未改预算。12骨架漏冲突、15表值误确认、14/16主名过宽等仍待通用改进。原9483+新10609封存保护/冻结PASS，独立NOT_REVIEWED；无人工补化学JSON/改代码/续填/采用，有运营监督，16有限参考投影嵌套图字段遗漏已纠正留证、未进worker/调参。20OCR校验/26GET/newPOST0，125未选与旧队列不启动。完整20及最终规模结论未完成，当前NOT_READY。见[实际报告](../runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT.md)和[工具实调用范围](../runs/IDENTITY-NEXT-TWENTY-20261005-01/TOOL_COVERAGE.md)。下文历史状态不作启动指令。

当前实际任务（2026-10-05）：原20首轮12成功/8未交付已结束；固定1.2新确认8结束为7DELIVERED/1INCOMPLETE，全部封存粗查完成，跨版本19/20来源至少一次交付。原13重复冲突视图通用误判进入显式1.3修复/工程检查；还未新job确认，不扩大剩余145，旧全OCR/19队列均不恢复。原始/参考/旧结果保护，新任务不输入人工答案。详见[最新修复状态](runs/IDENTITY-GENERAL-NONDELIVERY-TOOL-COVERAGE-20261004-01/REPORT.md)与[八篇封存报告](runs/IDENTITY-GENERAL-REPAIR-CONFIRMATION-20261005-01/REPORT_FINAL.md)。下文包含历史状态，不是当前启动指令。

当前执行（2026-10-05）：原20篇12交付/8未交付证据封存。策略1.2通过130工程测试/真实CLI预检；8篇确认全部启动、7封存（6自动交付、1未交付），源先/有限参考后粗查至第7篇，新增91主要范围名。原16纯原页成功（9PI结构/8PAA来源），原18成功且组成/扫描/XPS/网络假设分范围；最后原20运行。原13同源冲突双视图误报待全8/停点且noactive后通用修复/新任务确认。3460保护/新seal及采用读回/固定实现PASS，无人工化学干预，独立NOT_REVIEWED，4/7未定位新参考。完整阶段未完成，扩大规模NOT_READY；其他145/旧队列未执行。见[修复与确认证据](../runs/IDENTITY-GENERAL-NONDELIVERY-TOOL-COVERAGE-20261004-01/REPORT.md)；以下为历史记录。

当前任务持续进行（2026-10-03，IDENTITY-ALL-SOURCES-OCR-EXTRACTION-20261003-01）：两处331份PDF按SHA去重208篇；41篇既有VLM校验复用，2篇旧排队结果成功取回，165篇新v4/VLM/OCR已全部上传、当前仍远端pending。OCR完成门槛208篇尚未达到；顺序驱动等待后自动处理剩余166篇，每5篇记一批，旧42篇交付不改。人工Word/JSON不进入抽取；已安排本对话每小时跟进。108项pytest/阅读器/语法通过。详见[实际进度与交接](runs/IDENTITY-ALL-SOURCES-OCR-EXTRACTION-20261003-01/REPORT.md)，不要启动第二份驱动。以下为历史证据。

## Naming scope and source conflicts — 2026-10-03

IDENTITY-NAMING-SCOPE-CONFLICT-20261003-01 adds explicit new-task model-naming1.1, relative tacticity prefixes, named copolymer graft branches, model-reviewed broad class names, feasible-versus-ranked hypotheses, declared raw source-conflict preservation and bounded Windows replace retries. Historical contracts and sealed outputs remain; no new paper run, gold input or queue restart. Real receipt/gate/dependency checks and reader checks pass; full engineering command logs define final status. New version's unattended diverse-paper gate remains untested; independent chemistry NOT_REVIEWED. MinerU unchanged: public NXDOMAIN for old oss-mineru, but real Agent reservation returns Shanghai OSS; 4 prior v4 batches nowdone and one ZIP CRCpasses. Direct authority DNS was intercepted and one download had SSLError. [Report](../runs/IDENTITY-NAMING-SCOPE-CONFLICT-20261003-01/REPORT.md), [ADR](ADR-20261003-naming-scope-conflicts.md). Earlier sections retain historical evidence only.

# Delivery status — 2026-10-03

## Remaining cached-source execution

Task IDENTITY-REMAINING-CACHED-BATCH-20261002-01 finished on 2026-10-03: FINISHED_WITH_NONDELIVERY, driver exit1. Original33: four previously delivered skipped; all29 new attempted,28 auto-delivered/sealed/adopted/read back, one INCOMPLETE (Ignition Properties of Polymers). Total32/33 delivered. No human chemical JSON repair, in-run implementation edits, manual continuation or adoption; eight used existing same-session automatic closeout. Raw PDF/completed MinerU only, zero fresh MinerU calls; no human answers/prior chemical input. 251 new adopted major records have scoped names; graft/hardener/tacticity primary coverage, weak-hypothesis ranking and one unpreserved original-image/text Mw conflict remain deficient. Full unattended/scientific readiness unconfirmed. Frozen103/protected196 files unchanged; actual home42 latest-completed papers excludes incomplete. Tests not rerun, source unchanged. [Full evidence](../runs/IDENTITY-REMAINING-CACHED-BATCH-20261002-01/REPORT.md). Later sections retain historical evidence only.

## Current model naming and five-paper confirmation

Task IDENTITY-MODEL-NAMING-FIVE-20261002-01 is DELIVERED. Generic model-proposal review uses the existing Kernel/NamingService, local-unit then actual explicit-divalent OPSIN fallback, exact attachment/encoded-chemistry and whole-product graph checks. Model rules, tool equality, coverage gaps and preferred certification remain separate; old contracts are replayable. Typed relations distinguish precursor/product, sample/base, blend/component and comparison; unclassified historical endpoints use neutral labels.

PBO rerun plus four new-to-App distinct paper types completed sequentially under one frozen chemistry/host/prompt implementation. Each one persistent gpt-6.1-sol/xhigh/workspace-write CLI exited 0; all sealed, adopted, hash-read back with no human JSON repair, in-run code changes, continuation or adoption. 53 main records contain names: 36 model structure graph-checked, 16 model evidence-scope reviewed, one finite main monomer graph-matched. PBO's previous 20 source primary names became 20 structural candidates. Coarse original-page and live-reader checks found no systematic main identity errors; no measured manual accuracy score or preferred IUPAC certification, independent review NOT_REVIEWED.

Raw PDF and completed MinerU VLM ZIP only, original-dataset PDF hash equivalence confirmed; no manual reference JSON or legacy chemical result solver input, zero fresh MinerU calls. This passes the five-paper cached-source operational gate and supports a bounded larger sequential trial; none started. 91 pytest tests, final seven Node reader checks and JS syntax pass. After all five sealed, reader-only changes group explicit comparison pairs, name MM/MG source series and render structured product identity reasons; sealed chemistry unchanged. Remaining improvements: redundant context reviews, tacticity naming expression and bounded atomic-save resilience. [Full evidence](../runs/IDENTITY-MODEL-NAMING-FIVE-20261002-01/REPORT.md). Earlier status sections retain historical evidence only.

## Current cached-MinerU three-paper execution

Task IDENTITY-CACHED-MINERU-BATCH-20261002-01 is DELIVERED: three distinct paper types in the latest fixed implementation, each one persistent gpt-6.1-sol/xhigh/workspace-write invocation exiting 0. All sealed, adopted and hash-read back automatically without human answer repair, in-run implementation edits, continuation or adoption. Source PDF and completed raw MinerU ZIP only; no manual JSON/legacy chemical result input and no fresh MinerU request. The run-local importer is not default UI cache integration.

48 main records have source-scope names and SOURCE_SCOPE_MATCH, with 19 local / 20 ideal-repeat / 9 local-or-assembly expressions. Limited original-page and live-reader checks found no main-identity confusion. PBO primary structure naming remains unsupported for benzoxazole subunits; PHA/PBO broad source-pair names require stage qualifiers. Two Japanese-paper relations point sample-to-base while universal reader labels imply reaction direction; typed relationship semantics need improvement. Preferred naming remains uncertified, independent review NOT_REVIEWED; no manual accuracy comparison.

This satisfies the cached-source three-paper operational gate and supports a bounded 5–10 sequential trial. It does not establish stable fresh MinerU timing or full scientific coverage. Of 36 initially unrun new-App PDFs, three are delivered and 33 remain unstarted; all 40 completed MinerU PDFs have legacy execution records. Production source unchanged: no pytest/Node/legacy/catalog rerun; actual source hashes/CRC/page mapping, existing runner validation, version/pointer readback and live-reader checks passed. [Full task evidence](../runs/IDENTITY-CACHED-MINERU-BATCH-20261002-01/REPORT.md), [remaining PDF inventory](../runs/IDENTITY-CACHED-MINERU-BATCH-20261002-01/remaining-pdfs.md). Prior “latest implementation gate outstanding” statements below describe their earlier task states.

## Current MinerU test, completed-paper directory and pending cleanup

Task IDENTITY-MINERU-LIBRARY-CLEANUP-20261002-01 centers the paper home with concise sealed overviews and material counts. The existing 8771 reader now shows seven latest completed papers and the library shows 181 source records from those owners; incomplete/draft candidates and invalid historical versions are hidden. The new server GET gates are verified through a read-only 8772 preview. The original service was not restarted: its stop/restart command was automatically rejected, so its backend still uses the older API while the reader safely projects completed sealed versions.

MinerU's unchanged VLM path, using the root .env key, successfully uploaded a new two-page probe but remained pending for the existing 600-second wait and again at later readback. One previously completed real archive was downloaded, CRC checked, normalized and page mapped: 9 pages, 112 blocks, 1 table, 13 image assets. Authentication/results are usable; fresh-task timing remains unstable. No MinerU code/configuration, paper extraction or adoption changed.

The authorized deletion scope is four incomplete jobs and one invalid historical version, 897 files, with no completed reference conflict. **Nothing was deleted:** both native deletion attempts were rejected by automatic approval as blocked by policy. The run contains hash-only scope evidence and a reviewed-by-implementation, not independently reviewed, manual cleanup/restart script. All 5906 pre-existing DATA files retain hashes. Do not claim the cleanup is complete.

85 pytest, five Node reader checks and syntax pass. An obsolete, removed local CLI installation initially blocked preflight; config now pins the actual running installation at the same codex-cli version with checksum enforcement unchanged. Real file/image/tool/write/session-resume preflight passes. Naming rules remain unchanged, runtime chemistry 0.9.0, independent chemical review NOT_REVIEWED. The naming assessment distinguishes prompt/Skill guidance from the executable Kernel/NamingService; strict preferred naming and the latest implementation's diverse-paper operational gate remain outstanding.

[Task evidence and pending actions](../runs/IDENTITY-MINERU-LIBRARY-CLEANUP-20261002-01/REPORT.md), [naming capability and improvement judgement](NAMING_CAPABILITY_ASSESSMENT.md).

## Latest constitution/name implementation and explicit revisions

Task IDENTITY-CONSTITUTION-NAMING-20261002-01 adds opt-in product-expression decisions, source-hash-bound selected residue edits, graph-roundtripped names for bounded neutral regular units, a separate divalent OPSIN scope, null-draft handling and exact successful parse-receipt reuse. TMPMT/PEDOT/PTh and PDMS have explicit post-seal revised versions; prior jobs, bundles and names remain replayable. Browser verification shows product figures, source alternatives, assumptions and component figures. 82 pytest and four Node reader checks plus syntax pass. All 5847 pre-existing DATA files and existing tests retain hashes. Preferred-name certification is unset; independent chemical review NOT_REVIEWED.

MinerU implementation/configuration was not changed. Three read-only queries using the user-specified root .env key all returned HTTP200/code0 and done; the key equals the previously used private key, and original requests already used VLM. The prior local FAILED was a 600-second wait timeout while remote pending, not an observed remote parsing error. Deeper queue cause and actual remote completion times are unavailable. No late result was adopted into extraction.

This is a development revision, not a new unattended three-paper trial. The prior gate belongs to its original frozen implementation; the new implementation needs its own diverse-paper operational observation before expansion. No new paper, old queue or human reference JSON was used. [Current evidence, exact versions and limitations](../runs/IDENTITY-CONSTITUTION-NAMING-20261002-01/REPORT.md).


## Latest fixed three-paper unattended gate — 2026-10-02

Task IDENTITY-UNATTENDED-THREE-20261001-01 passes the current user's three-paper small-batch gate. 0011942 (common polymers), 0075156 (12 aromatic polyamides) and 0033617 (electrochemical copolymer/device) used one unchanged extraction/naming/tool/adoption implementation and delivered automatically, with sealed hash readback and no human JSON repair, in-run code change, continuation or adoption. Paper 0075156 had an initial CLI timeout followed by bounded automatic closeout in the same session and original deadline. No human reference JSON was opened or supplied. Qualitative source/graph/UI review found no systematic identity error; this is not measured accuracy or independent chemical review.

All 20 main research objects have declared-scope names (19 polymers and 1 finite monomer); PDMS retains an explicit hypothetical naming source. Preferred IUPAC certification remains unset and NOT_REVIEWED. All three MinerU attempts timed out in pending polling and fell back automatically to direct PDF text plus original page images. Two upsert null-field failures were handled by the persistent core, not hidden; a model reason incorrectly said human checked and that interpretation is explicitly withdrawn in the report.

62 APP pytest tests and four existing Node reader checks plus JS syntax passed before freeze. The 4035 pre-existing DATA files and existing tests retain their hashes; each source/candidate/completion/bundle reads back correctly. After all three sealed, reader wording alone was corrected for a main monomer: 4 research objects (3 polymers). Relevant Node checks passed again. Runtime chemistry remains 0.9.0; no chemical-rule/schema changes or scoring module. The practical next step is a 5–10-paper sequential trial, not unrestricted scale. No additional batch or old queue was started.

[Full task evidence, limitations, exact exits, input hashes and next risks](../runs/IDENTITY-UNATTENDED-THREE-20261001-01/REPORT.md). Previous five-paper suggestions and four-paper recoveries below are historical; the current authorized gate is three.


## Current series navigation and batch-readiness decision

Task IDENTITY-SERIES-READINESS-20261001-01 changes the shared reader only: the sidebar contains paper overview and polymer reading series, with selected-series samples across the card top. Explicit series/parent relations take priority; original numbered labels or material-kind reading categories are fallbacks and never merge chemical objects. All four accepted papers were opened; cross-series/sample selection, remembered samples, overview, component search/preparation/return and prior read-only version replay were exercised. Four existing Node reading checks and JS syntax pass; no new comparison/scoring script, chemical run or test was added.

Qualitative judgement requested by the user: core identity content is broadly close to manual extraction and some provenance/uncertainty information is more complete. This does not establish a measured accuracy rate or superiority in complex graft/structure-preferred naming. Normal autonomous end-to-end delivery has been demonstrated, but the latest four runs needed separate recovery for three papers; stable unattended operation is not yet accepted. A fixed implementation completing a small consecutive set (suggested five diverse normal papers) without manual JSON repair, continuation, adoption or in-run code edits is the practical next gate. Then start a 5–10-paper sequential batch and expand gradually; do not revive old queues. No such new batch was started in this task.

The earlier bpp reference concern is corrected: bpp is an existing saved b-PP comparison-series object with valid component links, not a missing ID. Its assignment to a specific b-PP1/2 sample remains source-limited and must not be guessed. See [current execution evidence and conclusion](../runs/IDENTITY-SERIES-READINESS-20261001-01/REPORT.md). The prior 57-case Python run below belongs to the previous task; it was not rerun for this frontend-only change.

## Latest authorized rerun and UI acceptance

Task IDENTITY-PARITY-RERUN-20261001-01 is delivered: four new adopted versions, hash readback, 30 main-material source-scope names (3/3/15/9), four MMI-related hypothesis-bearing main objects. The original PDFs and protected APP/DATA files remain unchanged. Only paper 0021850 completed as an uninterrupted first attempt; the other three have recorded failed/interrupted attempts and separate recoveries. Do not describe this as four unattended first-run successes.

The legacy read-only viewer and all four new paper views were opened. At the same actual desktop width, the header and main-card dimensions match; component images, source aliases/prepared tool names, actual RDKit/OPSIN results, PubChem not-run status, overview names, version replay and original page-image links were exercised. Long source titles and individual-material navigation differ from the older family view. Mobile responsiveness was not verified because the browser did not apply the requested mobile width.

Final fixed code: 57 pytest cases passed (one existing RequestsDependencyWarning), four Node reading checks and JS syntax exit 0. Earlier failed checks remain evidence, including an invalid full check that overlapped a source-reader change and was rerun on fixed code. A receipt-projection engineering correction during the third paper is disclosed; post-seal ordering/UI/source-reader changes do not rewrite the four adopted bundles. Runtime remains 0.9.0; nomenclature 1.1 is explicit. Preferred IUPAC certification is unset; independent chemistry review remains NOT_REVIEWED. Graph-to-preferred-CRU naming and some support-object ambiguities are still incomplete.

See [complete execution evidence](../runs/IDENTITY-PARITY-RERUN-20261001-01/REPORT.md), [21 manual-record comparisons](../runs/IDENTITY-PARITY-RERUN-20261001-01/COMPARISON.md) and [actual flow / next priorities](NAMING_PIPELINE_AND_NEXT_STEPS.md). The following sections preserve previous task results and do not redefine this run.

## Current requested naming and reader revision

Task `IDENTITY-IUPAC-READER-20261001-01` is adopted as four explicit development revisions; the first runs and prior bundles remain immutable. The original 21 material descriptions and four unsupported names are now assessed individually: 12 source/base/network/blend names are supported at their declared scope; six functionalized polymers and six blends retain partial identity; MMI has two separately OPSIN/graph-verified isomer names with unresolved selection. None is certified as a preferred IUPAC name.

Nine triazine repeat graphs now generate complete-graph consistency candidates through the opt-in `iupac-triazine-graph-candidate/1.0` contract. The old 1.1 namespace still retains its NO_NAME result. The evidence naming contract is `identity-evidence-nomenclature/1.0`; runtime remains 0.9.0. Two finite EPDM source objects/graphs were added. Four real local OPSIN calls parsed successfully; no new public lookup, model extraction or MinerU run was made.

The shared passport reader now embeds component depictions, precursor/conditional graphs, scoped formulas and RDKit properties, bound OPSIN/PubChem results, source links and identity qualifiers. Unsupported aliases, unqueried tools, missing structures and unknown connections remain visible. Historical versions stay read-only.

Validation: 48 application pytest cases pass, with the existing requests dependency warning. All Node reader checks and JavaScript syntax checks pass after correcting a missing-field compatibility issue; its failed test log is retained. Hash checks preserve 835 pre-existing jobs, versions, reports and test files. No original legacy suite, catalog release evaluation, new paper first run or independent chemical review was performed.

See [IUPAC improvement path](IUPAC_IMPROVEMENT_PATH.md) and `runs/IDENTITY-IUPAC-READER-20261001-01/REPORT.md` for per-object names, scope limits, exact commands, hashes, withdrawals and actual deltas. The following sections retain earlier delivery evidence rather than redefining it.

Task: IDENTITY-SINGLE-CORE-MIGRATION-20260930-01. The independent application, sibling data directory and three shared reading entrances are implemented. The chemistry runtime is 0.9.0; the application protocol is identity-single-core/1.0.

The four authorized first runs sealed automatically in this order:

| Paper | Minutes | CLI invocations | First-run intervention | Adopted version prefix |
|---|---:|---:|---|---|
| 0021850 | 21.4 | 1 | None | 55d7b11ec715 |
| 0072665 | 25.7 | 1 | None | 5ce6978724b9 |
| 0022930 | 24.5 | 1 | None | 9657b7e00ec2 |
| 0000573 | 26.9 | 1 | None | a35303a030bf |

All were delivered, adopted and hash-read back without supervisory JSON repair, continuation or adoption. All four first-reader checks preceded reader changes. MinerU completed for every paper. One CLI invocation includes multiple provider requests and tools; provider request counts are not exposed.

Later reader changes render facts as normal text, place supporting objects in a disclosure, preserve sample hierarchy, filter relations to the selected member, and link related materials and source pages. These changes made no model calls and did not alter sealed candidates or adoption pointers. The exact first-run code/resources are preserved in the migration run's four-paper-frozen-application.zip.

Scientific status is NOT_REVIEWED. Candidate names are supplied, but certified preferred IUPAC names are unset. Local rule naming remains unsupported for several siloxane and all nine polyguanamine repeat candidates. The PP/EPDM paper has partial PP/DMI fragments; full EPDM constitution and actual graft bonds/positions remain unresolved. Photo-network topology, sequence, end groups, stereochemistry and conflicting source values remain unknown where reported.

New application tests pass (11 pytest cases plus the Node request-race/reading regression). Historical `verify_handoff.py` failed because 27 old report files were absent; existing baseline files had no hash mismatch. Original full pytest, legacy suite, catalog evaluation and independent chemistry review were not run. Original protected files and the ten known legacy conflicts were left intact.

Recovery code is implemented and same-session continuation was exercised in preflight. Forced process failure, host restart recovery and multi-server locking were not exercised by these four one-invocation runs. Full chemical scope is not ready merely because engineering tests pass. Future work requires a current user request.

## Requested foundation integration — 2026-10-01

Task IDENTITY-FOUNDATION-INTEGRATION-20261001-01 adds typed graph/passport inputs, finite name/graph checks, explicit naming contracts, scoped RDKit properties, bounded public lookups with actual receipts, necessary named preparation components, and immutable post-seal revisions. All three reader entrances follow the revision pointer; prior versions remain readable. The first four runs and original adoption pointers remain sealed. Four local enrichment revisions were adopted with hash readback; no new paper, primary model invocation or MinerU extraction was performed.

This is an engineering integration and source-field restoration, not a new independently reviewed chemical release. Polyguanamine candidate names can now be checked against supplied repeat graphs through the existing parser, while graph-to-name generation and preferred CRU rules still have gaps. A nonempty kernel primary may be an input name verified for consistency or a source-expression fallback; it must not be counted as a newly generated IUPAC name. General performance measurements remain outside the required identity reading scope.

See [actual flow and IUPAC development](IDENTITY_FLOW_AND_IUPAC.md) and [task evidence](../runs/IDENTITY-FOUNDATION-INTEGRATION-20261001-01/REPORT.md) for exact class deltas, calls, failures, tests and limitations.
## 2026-10-10 缩写解析增强与两篇新来源复核

当前流程已增加来源绑定的缩写/同义词补充路径：`prepare_component` 保存原文写法、来源定义的全名和别名；主 `resolve` 返回 `UNSUPPORTED`/`INVALID` 时，只对本篇声明的 `raw_name` 与 `aliases` 做有界真实 OPSIN 探测；若已有有限结构图，同时返回 supplemental graph check。补充结果必须通过结构图核对后才可由模型考虑，绝不把本地词典命中、同义词解析或分子式相同自动升级为原文事实、优选 IUPAC 或真实材料身份。组分库封存后核验也会读取来源准备中的全名/别名，读者只读补充回执，不在打开页面时运行 OPSIN。

相关工程测试为 317 项 pytest（含同义词真实解析与结构核对回归）、Node reader、组分库工作台和 JavaScript 语法检查；独立化学审核仍为 `NOT_REVIEWED`。

本次“两篇真正未执行来源”中，45 已交付并自动写入组分库（178 篇来源、4,254 条记录、2,186 个汇总身份）；46 的两个独立尝试均因同一模型容量问题在原 session 有界重试后 `INCOMPLETE`，没有采用版本，也没有写入组分库。不能把这两次不完整尝试计为第二篇交付。详见 [两篇最终评估](../runs/IDENTITY-FRESH-TWO-20261010-01/REPORT_FINAL.md) 与 [第二篇重试记录](../runs/IDENTITY-FRESH-SECOND-RETRY-20261010-01/REPORT_FINAL.md)。

正式版本流程固定为：**来源冻结 → 每篇一个持久模型 session → current 候选 → 工具回执/结构核对 → 一次 finalize/review/finish → 宿主原子 publish 一个不可变版本**。实质化学修正才生成新版本并保留旧版本；OPSIN/RDKit/PubChem 补充回执不改论文版本。历史封存结果和失败回执保持只读。

