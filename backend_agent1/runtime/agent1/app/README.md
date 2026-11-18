2026-10-10两篇未交付修复已闭合：本次新授权两篇均 DELIVERED，合计 21 个主要对象。原20轮的封存结果仍为18交付/2未交付；这两篇在独立新任务中重新执行后，原选定20份来源已全部有正式采用结果，原失败回执保持不变。

OPSIN 懒编译目录已改为每个任务的 tool-runtime/opsin-build，修复 workspace-write 下 WinError 5；预检新增真实 OPSIN 解析和有限图匹配。310 pytest、阅读器与语法测试、中性运行复核、真实同会话 CLI 预检、176 既有采用版本只读合同回放通过。每篇原60分钟、持续 gpt-6.1-sol/xhigh/workspace-write 串行，实际 31.8/9.8 分钟；仅原来源输入，无旧答案或人工参考。

组分库自动更新：175篇/4,225记录/2,176身份 → 177篇/4,253记录/2,186身份，新增 28 条组分记录，采用与服务接口读回一致。在线 PubChem 性质补充状态独立记录于完整报告，不等同于论文交付状态。2,246 个历史保护文件未变，182 条封存反馈绑定通过；Kernel 0.9.0 不变，独立 NOT_REVIEWED/PIN 未认证，无其他论文或旧队列启动。

修复报告：[REPORT_FINAL.md](runs/IDENTITY-TWO-NONDELIVERY-REPAIR-20261010-01/REPORT_FINAL.md)。以下为历史阶段记录。

2026-10-09新授权20篇已正式开始（IDENTITY-FOLLOWING-TWENTY-20261009-01）：从剩余48篇中冻结20篇，17份已校验OCR+原始PDF页、3份直接原始PDF页，无新OCR上传。每篇一个持续gpt-6.1-sol/xhigh/workspace-write会话、原60分钟逐篇串行，隔离执行副本冻结为f826ff65665e，Kernel0.9.0不变；首篇SC-20261009T083909Z-d3dffa95已于16:39开始。此前两篇自动交付并入库已核实：157篇/3,968记录/2,096身份，共新增67记录。PubChem与本地性质后台继续独立执行，不占用论文预算；完整批查询尚未完成，新交付论文在线补充等待全量批结束后自动增量处理。实时抽取状态见 runs/IDENTITY-FOLLOWING-TWENTY-20261009-01/PROGRESS.md，完成后实际封存报告为 REPORT_FINAL.md；当前不宣称20篇已完成。未选28篇与旧队列不启动，独立NOT_REVIEWED/PIN未认证。以下为历史阶段。

2026-10-09等待PubChem期间新授权2篇已完成：2 DELIVERED、20高分子主要对象，原60分钟/持续6.1-sol-xhigh-workspace-write串行，实际32.8/30.5分钟。组分库实测155→156→157篇，新增67条，当前3,968记录/2,096汇总身份/346跨文献共享身份，新组分本地性质立即可读。1,215旧保护文件无变化、160反馈绑定PASS，Kernel0.9.0，独立NOT_REVIEWED/PIN未认证。PubChem全量仍自动续跑：检查点622/1,676，累计缓存643明确结果/92失败/941待请求，HTTP429后预计16:43再试；该在线等待未阻碍两篇交付。未启动余下48篇或旧队列。详见 runs/IDENTITY-TWO-WHILE-PUBCHEM-20261009-01/REPORT.md；以下为历史阶段。

2026-10-09组分工具性质与增量更新已交付至 http://127.0.0.1:8780/knowledge?sort=sources ，start.ps1默认8780。默认显示既有RDKit计算和实际PubChem資料；单篇命名理由/未知项在明确选择的“来源身份”。新增交付PDF自动入库，独立后台30秒检查并补充缺失性质，页面10秒检查并保持当前操作；不改变论文求解预算、核心工具/命名/采用门槛。155篇/3,901条/2,058身份；已冻结并实际执行1,676个PubChem查询，全量仍未完成，实际缓存432项得到匹配/候选/明确无匹配结果、143失败、1,101待请求，服务429冷却后由断点进程自动继续，详情以Data/library-enrichment和实际日志为准。305pytest、全部15个Node阅读脚本/语法、真实同会话工程预检、API及浏览器通过；1,215保护文件无变化，Kernel0.9.0、独立NOT_REVIEWED/PIN未认证，无新论文/旧队列。本次执行清单与封存前后实现分开留证。见 runs/IDENTITY-LIBRARY-PUBCHEM-20261009-01/REPORT.md；以下为历史阶段。

当前2026-10-09授权后续5篇已闭合：{"DELIVERED": 5}，累计155唯一采用PDF。原60分钟/持久6.1-sol/xhigh逐篇串行，10主要对象封存后模型原文有限回查，158反馈绑定，全库回放/历史保护/API/UI通过。人工JSON内容未读，50未选和旧队列未启动，无第6篇。Kernel0.9.0，主模型复核与独立NOT_REVIEWED/PIN未认证分开。详见runs/IDENTITY-FOLLOWING-FIVE-20261009-01/REPORT_FINAL.md。

2026-10-09组分库重新设计已交付至 http://127.0.0.1:8777/knowledge?sort=sources ，start.ps1默认8777。紧凑卡片、横向用途筛选、共享/排序/搜索；化学身份、12篇分页来源、分类文献关联在同一身份证窗口中阅读，保留列表与筛选，文献链接默认新页面。修正水→4BI等辅助关系的展示：原文明确“不属于产物组成”的关系归入工艺辅助，不再统称“使用该组分的材料”；逐篇身份按选中版本绑定。291pytest、17项Node阅读检查、两份JS语法和真实API/浏览器通过，缓存目录/检索约0.28–0.56秒。1,192项保护中1,190项不变，另一个既有任务的run/current两项状态变化单独留证，原采用版本及封存文件无变化。Kernel0.9.0、原文献及文本命名流程不改，本轮无论文或命名CLI；有限结构汇总不代表完整实物身份或独立化学审核。见 runs/IDENTITY-LIBRARY-REDESIGN-20261009-01/REPORT.md；以下旧地址与旧统计为历史。

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

当前实际进展（2026-10-05）：固定1.3新20已18启动/17自动交付/0未交付，第18篇运行；1–17源先粗查/有限参考已闭合。230主要记录含221聚合物/组装范围名称（100结构/111证据/5规则工具缺口/5类别）及9有限passport名，不误计finite缺名。16图文酯O冲突保留、17缩甲醛线性/有限环和测量/计算分子量合理，17实际CLI[1]自动45min收尾已有READY，自动采用未改预算。12骨架漏冲突、15表值误确认、14/16主名过宽等仍待通用改进。原9483+新10609封存保护/冻结PASS，独立NOT_REVIEWED；无人工补化学JSON/改代码/续填/采用，有运营监督，16有限参考投影嵌套图字段遗漏已纠正留证、未进worker/调参。20OCR校验/26GET/newPOST0，125未选与旧队列不启动。完整20及最终规模结论未完成，当前NOT_READY。见[实际报告](runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT.md)和[工具实调用范围](runs/IDENTITY-NEXT-TWENTY-20261005-01/TOOL_COVERAGE.md)。下文历史状态不作启动指令。

截至2026-10-05T13:37:27.572872+00:00，固定1.3新20已19启动/18DELIVERED/0INCOMPLETE，原驱动继续第19篇，原截止2026-10-05T13:59:29.839982+00:00。1–18原文先粗看、有限参考和封存/采用/图像/实际模型期限审查已闭合；18结晶poly(vinylcyclohexene)主要身份/性质粗看相符，异常投料/立构不确定保留，重复图片空白疑虑撤回。原9483/新10949保护PASS。12骨架冲突漏标、15一处表值误确认、14组装主名/有限回执缺口仍在，冻结不改旧结果。无人工补化学JSON/采用，有运营监督，独立NOT_REVIEWED。完整20及最终效果/工具范围/扩大规模结论未完，125未选和旧队列不启动。见[实际报告](runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT.md)与[工具范围](runs/IDENTITY-NEXT-TWENTY-20261005-01/TOOL_COVERAGE.md)。

当前实际进展（2026-10-05）：固定1.3新20已18启动/17自动交付/0未交付，第18篇运行；1–17源先粗查/有限参考已闭合。230主要记录含221聚合物/组装范围名称（100结构/111证据/5规则工具缺口/5类别）及9有限passport名，不误计finite缺名。16图文酯O冲突保留、17缩甲醛线性/有限环和测量/计算分子量合理，17实际CLI[1]自动45min收尾已有READY，自动采用未改预算。12骨架漏冲突、15表值误确认、14/16主名过宽等仍待通用改进。原9483+新10609封存保护/冻结PASS，独立NOT_REVIEWED；无人工补化学JSON/改代码/续填/采用，有运营监督，16有限参考投影嵌套图字段遗漏已纠正留证、未进worker/调参。20OCR校验/26GET/newPOST0，125未选与旧队列不启动。完整20及最终规模结论未完成，当前NOT_READY。见[实际报告](runs/IDENTITY-NEXT-TWENTY-20261005-01/REPORT.md)和[工具实调用范围](runs/IDENTITY-NEXT-TWENTY-20261005-01/TOOL_COVERAGE.md)。下文历史状态不作启动指令。

当前实际任务（2026-10-05）：原20首轮12成功/8未交付已结束；固定1.2新确认8结束为7DELIVERED/1INCOMPLETE，全部封存粗查完成，跨版本19/20来源至少一次交付。原13重复冲突视图通用误判进入显式1.3修复/工程检查；还未新job确认，不扩大剩余145，旧全OCR/19队列均不恢复。原始/参考/旧结果保护，新任务不输入人工答案。详见[最新修复状态](runs/IDENTITY-GENERAL-NONDELIVERY-TOOL-COVERAGE-20261004-01/REPORT.md)与[八篇封存报告](runs/IDENTITY-GENERAL-REPAIR-CONFIRMATION-20261005-01/REPORT_FINAL.md)。下文包含历史状态，不是当前启动指令。

当前执行（2026-10-05）：原20篇12交付/8未交付证据封存。策略1.2通过130工程测试/真实CLI预检；8篇确认全部启动、7封存（6自动交付、1未交付），源先/有限参考后粗查至第7篇，新增91主要范围名。原16纯原页成功（9PI结构/8PAA来源），原18成功且组成/扫描/XPS/网络假设分范围；最后原20运行。原13同源冲突双视图误报待全8/停点且noactive后通用修复/新任务确认。3460保护/新seal及采用读回/固定实现PASS，无人工化学干预，独立NOT_REVIEWED，4/7未定位新参考。完整阶段未完成，扩大规模NOT_READY；其他145/旧队列未执行。见[修复与确认证据](runs/IDENTITY-GENERAL-NONDELIVERY-TOOL-COVERAGE-20261004-01/REPORT.md)；以下为历史记录。

当前任务持续进行（2026-10-03，IDENTITY-ALL-SOURCES-OCR-EXTRACTION-20261003-01）：两处331份PDF按SHA去重208篇；41篇既有VLM校验复用，2篇旧排队结果成功取回，165篇新v4/VLM/OCR已全部上传、当前仍远端pending。OCR完成门槛208篇尚未达到；顺序驱动等待后自动处理剩余166篇，每5篇记一批，旧42篇交付不改。人工Word/JSON不进入抽取；已安排本对话每小时跟进。108项pytest/阅读器/语法通过。详见[实际进度与交接](runs/IDENTITY-ALL-SOURCES-OCR-EXTRACTION-20261003-01/REPORT.md)，不要启动第二份驱动。以下为历史证据。

最新修改（2026-10-03，IDENTITY-NAMING-SCOPE-CONFLICT-20261003-01）：新任务命名采用合同1.1，保留相对立构主名前缀、已命名共聚接枝侧链及较宽类别名称；区分可行/有依据优先假设，保存原页/解析冲突原值和修正状态。旧采用结果不迁移，独立审核NOT_REVIEWED。MinerU未改：公共DNS中旧oss-mineru缺失，但当前Agent实际返回上海OSS桶；4个旧v4任务均done，结果ZIP可下载。新增通用工程用例通过，未新跑论文或重启队列。见[本次报告](runs/IDENTITY-NAMING-SCOPE-CONFLICT-20261003-01/REPORT.md)。以下均为各轮历史证据。

# Polymer Identity App

最新执行完成（2026-10-03，IDENTITY-REMAINING-CACHED-BATCH-20261002-01）：原33篇逐项处理，4篇前批交付跳过，29篇新执行中28篇自动DELIVERED、1篇INCOMPLETE，累计32/33交付。固定化学/宿主/提示词/阅读器，无人工补化学JSON、运行中改实现、手工续接或采用；8篇用既有同会话自动收尾。无人工答案/旧化学输入、新MinerU调用0。251个新采用主要记录有范围名称；接枝/固化剂/立构主名、弱假设排序及一处Mw原图/文字冲突仍不足，未通过全量无人交付或完整IUPAC认证。103冻结文件及196旧文件保护通过，首页只显示最新完成文献。见[完整结果与边界](runs/IDENTITY-REMAINING-CACHED-BATCH-20261002-01/REPORT.md)；以下为历史证据。

最新完成（2026-10-02，IDENTITY-MODEL-NAMING-FIVE-20261002-01）：通用模型命名与明确关系方向已实现；固定化学/宿主/提示词下 PBO 重跑＋四篇新到 App 的不同类型文献全部首跑自动 DELIVERED、封存、采用、哈希读回，每篇一个会话，无人工补 JSON、运行中改代码、续接或采用。53 个主要记录均有名称（36 结构候选、16 来源范围、1 有限主单体）；PBO 上版 20 个来源主名现为 20 个结构候选主名，优选名仍未认证。原文粗查未见系统性身份错误，主身份可用性接近人工粗读，可扩大缓存来源的有上限顺序试批；未启动下一批。无人工答案/旧化学结果输入，新 MinerU 调用 0。91 项 pytest、最终 7 组 Node 阅读检查及 JS 语法通过。封存后微调明确比较对的系列/样品导航、MM/MG 标题和产物核对对象字段；化学版本未改。见[完整结果与边界](runs/IDENTITY-MODEL-NAMING-FIVE-20261002-01/REPORT.md)及[当前流程](docs/NAMING_PIPELINE_AND_NEXT_STEPS.md)。以下各轮记录为历史，不定义本次状态。

最新执行（2026-10-02）：复用已有完成 MinerU 解析，在同一固定实现下连续处理乙烯/丙烯腈、含氟 PHA/PBO、日文 EVA/硅氧烷膜三篇，全部首跑自动 DELIVERED、封存、采用及哈希读回；各一次 CLI，无人工补 JSON、改运行中实现、续接或采用。人工参考 JSON 未读取，新增 MinerU 请求为 0。48 个主要对象均有来源范围名称；粗查未见主身份混淆，PBO结构主名及关系方向表述仍有缺口。通过本轮缓存来源三篇工程门槛，可做 5–10 篇顺序试批，未启动余下33篇；不是优选 IUPAC认证或fresh MinerU稳定验证。见[完整证据](runs/IDENTITY-CACHED-MINERU-BATCH-20261002-01/REPORT.md)及[剩余原PDF清单](runs/IDENTITY-CACHED-MINERU-BATCH-20261002-01/remaining-pdfs.md)。后文“尚未重复三篇”属于此前任务状态。

最新修改（2026-10-02）：TMPMT文献现有PTh/PEDOT理想重复图及共聚物假设局部图；PDMS主要名称升级为图一致的poly[oxy(dimethylsilanediyl)]，来源名与商品限制保留。新增有边界的位点编辑、结构命名和产物表达合同，旧版本仍可回放。82项pytest、4项Node和语法通过。MinerU未改；根目录密钥查询三个旧任务均已done，先前为宿主排队等待超时，原请求已使用VLM。新实现尚未重复三篇无人干预门槛。见[执行证据](runs/IDENTITY-CONSTITUTION-NAMING-20261002-01/REPORT.md)及[当前实际流程与提升路径](docs/NAMING_PIPELINE_AND_NEXT_STEPS.md)。


最新任务（2026-10-02）：固定抽取/命名/工具/保存实现连续处理三篇不同类型文献，全部自动 DELIVERED、封存、采用和哈希读回，无人工补 JSON、改运行中代码、续接或采用；第二篇由宿主在同会话、原截止时间内自动收尾。粗看未发现系统性身份错误，达到本轮“三篇”小批门槛，可进入 5–10 篇顺序试批（本任务未启动更多）。人工参考答案 JSON 未读取或进入抽取。20 个主要对象均有范围名称；优选 IUPAC 未认证。三次 MinerU 超时后自动使用 PDF 文本与原页图，不能计为 MinerU 成功。62 项 pytest、四项 Node 阅读检查及 JS 语法通过；封存后修正主单体被计为高分子的显示标签。见[本轮完整证据和结论](runs/IDENTITY-UNATTENDED-THREE-20261001-01/REPORT.md)。后面的四篇恢复记录为历史，不再定义最新三篇的无人干预状态。

最新阅读微调与跑批判断：左侧“本文概览＋高分子系列”，上方仅列选中系列的样品；组分详情、检索、图片和版本回放保留。粗看四篇的主要身份准确性接近人工，来源和不确定性的表达部分更充分；复杂结构优选名不能声称全面超过人工。最新四篇有三篇需要独立恢复，尚未通过稳定无人额外干预交付的门槛。先小批试运行，达到固定实现下连续正常自动交付再扩大。见[本次计划、结论和验收](runs/IDENTITY-SERIES-READINESS-20261001-01/REPORT.md)。本次只改阅读器与说明，没有新增论文、推断、比较评分或改写采用版本。

2026-10-01 当前交付：四篇原文重新解析/核对及命名，30 个主要材料均有正式来源范围名称；MMI 的区域选择及相关共混物保留明确假设。四篇已 DELIVERED/采用/哈希读回，只有第一篇首跑无人干预，其余存在有记录的独立恢复。旧版和四篇新页面已实际打开验收，恢复连续身份证布局、组分图、名称准备与真实工具信息，新增已有原页的阅读入口。固定最终代码 57 项 pytest 和 4 个 Node 阅读检查通过；严格优选 IUPAC 名未认证，独立化学审核 NOT_REVIEWED。

最新依据：[本次完整报告和逐项比较](runs/IDENTITY-PARITY-RERUN-20261001-01/REPORT.md)、[实际流程及持续提升路径](docs/NAMING_PIPELINE_AND_NEXT_STEPS.md)、[旧/新界面验收](runs/IDENTITY-PARITY-RERUN-20261001-01/ui-acceptance.json)。运行内核仍为 0.9.0；新命名合同显式采用 1.1，旧采用版本/命名空间保留。下面保留先前任务的交付记录，不能将其首跑状态或测试数量视为本次状态。

Current requested integration: [actual identity flow and IUPAC improvement](docs/IDENTITY_FLOW_AND_IUPAC.md), [delivery evidence](runs/IDENTITY-FOUNDATION-INTEGRATION-20261001-01/REPORT.md). The first four paper runs stay sealed; post-seal revisions have explicit parent versions and replay.

独立应用：identity-single-core/1.0，化学内核0.9.0。

运行 `./start.ps1`，打开 http://127.0.0.1:8774 。工作台 `/`、文献身份证 `/paper`、组分库 `/knowledge` 共用连续身份证正文和同一不可变采用版本；每篇一个持续 gpt-6.1-sol/xhigh 会话，workspace-write。运行数据和私有MinerU配置在同级 Polymer_Identity_App_Data，正常执行不扫描旧项目或旧队列。

CLI：`python -m identity_app.runner run --pdf <PDF>`，明确恢复使用 `resume --job <本应用任务目录>`。总预算60分钟，恢复沿用截止时间。运行前真实CLI预检必须通过。名称、图、公式范围、真实身份和严格优选名认证分别保存，独立审核NOT_REVIEWED。

来源版本/迁移哈希在迁移任务报告中；config/runtime.json定位完整安装CLI目录和实际Python。认证不保存在源码；程序只使用既有本机Codex认证及数据目录private/mineru.env。

本机实际依赖版本见 `requirements-actual.txt.json`；这是运行记录，不是跨机器安装锁文件。OPSIN JAR校验值固定，CLI使用完整已安装目录；换机器需要重新配置路径、凭据和真实预检。

四篇已完成首次自动交付，数据与首次代码封存，详见 `docs/STATUS.md` 和 `docs/DESIGN.md`。第四篇九个3a–3i聚合物成员与2a–2c有限环状副产物分别可读。图名式是候选范围，独立审核仍为 NOT_REVIEWED。三入口阅读改进发生于四篇封存后，不替代首次记录。

工程验证：`python -m pytest tests -q`；`node tests/test_reader.cjs`；`node --check web/app.js`。完整执行证据在旧项目本次新增的 `runs/IDENTITY-SINGLE-CORE-MIGRATION-20260930-01/REPORT.md`，应用运行无需访问它。


## 当前项目流程与图件

按实际目录、同级运行数据目录、启动方式、单篇持续 Agent、来源准备、工具循环、宿主采用、恢复和验证命令整理的完整说明见：

- [PROJECT_WORKFLOW.md](docs/PROJECT_WORKFLOW.md)
- [项目全流程图](docs/figures/project-flow-overview.svg)
- [单篇 Agent 循环图](docs/figures/identity-generation-loop.svg)

其中代码根目录是 `Polymer_Identity_App`，运行数据根目录是同级 `Polymer_Identity_App_Data`；项目内部 `data` 目录只保存轻量配置与规则快照。


## 材料领域评审版流程说明与图件

本版将项目实际执行链路转换为材料领域人员可直接确认的表达：以文献中的材料对象、实验/谱图证据、结构候选、组成与命名、人工确认和身份档案为主线，弱化计算机模块名称；图件采用项目长期使用的深绿、青绿色和浅灰绿配色，保持简明、少色、可打印。

- [材料领域流程说明 Word](docs/material_workflow_20261012/Polymer_Identity_App_材料领域流程说明.docx)
- [材料身份识别主流程 PNG](docs/material_workflow_20261012/material-identity-overview.png)
- [材料身份 Agent 循环 PNG](docs/material_workflow_20261012/material-agent-loop.png)
- [复杂论文与稳定批次方法比较 PNG](docs/material_workflow_20261012/material-method-comparison.png)

Word 文档包含：真实项目路径与运行数据边界、材料证据链、候选结构形成、单篇 Agent 迭代、材料身份档案、材料工具问题、复杂论文与规则优先批处理的适用边界、材料专家确认清单，以及最小运行与复核说明。

- [完整数据流可编辑 draw.io](docs/material_workflow_20261012/material-identity-complete-dataflow.drawio)
- [完整数据流 PNG 预览](docs/material_workflow_20261012/material-identity-complete-dataflow.png)
- [完整数据流 SVG 预览](docs/material_workflow_20261012/material-identity-complete-dataflow.svg)

完整数据流图按数据对象编号展示“任务说明 → 原始文献包 → 预检 → 来源清单 → 解析语料 → 证据单元 → 材料出现/角色 → 组分与候选结构图 → 性质/命名 → 分层身份轮廓 → 验收 → 采用 → 封存 → 材料身份库”，并明确解析回退、Agent循环、未知项、恢复检查点和专家反馈。
