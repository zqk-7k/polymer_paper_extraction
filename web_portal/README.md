# PolymerLit Extractor Web Tool

这是高分子论文抽取流水线的本地在线工作台。

## 五个主入口

1. **上传文献**：选择 PDF，创建真实抽取任务，并根据 Stage 产物显示进度。
2. **抽取结果**：只列出 `web_runtime/tasks/` 中由网页上传产生的任务，按时间从新到旧排列。打开论文后先查看聚合物目录，再进入独立的聚合物样品页和样品性质页。
3. **批处理结果**：独立展示 API 从 `batch_results/` 选择的最新合法批次，批次名称、日期、模式和数量均读取 `RESULT_INDEX.json`，不混入网页结果列表。
4. **PoLyInfo 对照**：独立读取 `整理结果/polyinfo数据/有doi` 与 `无doi` 中的真实样品 JSON，按 `reference_no` 与当前所选批处理结果比较。
5. **样品详情**：查看当前选中样品的性质、测量语境、置信度和原文证据。

抽取结果页和批处理页均显示“文献 → 聚合物 → 样品 → 性质”的数量摘要。论文级页面保留聚合物目录、知识图谱和数据表；点击聚合物后进入不含论文概览的样品列表整页，点击样品后进入独立性质表，并可逐级返回。

知识图谱采用“文献来源 → 聚合物实体 → 样品状态 → 工艺事件 → 性质观测 / 表征方法”的分层布局，并按真实关系对齐节点。打开性质或实体证据时，API 会缓存渲染对应 PDF 页；前端使用保存的 bbox 绘制红框，并单独显示证据区域裁剪图。

聚合物目录为规范名称生成稳定的系统 PID。结构式和 CU formula 只在候选数据提供重复单元信息，或命中受控的常见均聚物词典时显示。仅凭名称无法唯一确定结构的共聚物、共混物和复杂聚合物保持“待补充”，避免生成未经证实的结构。

PoLyInfo 对照页将两种数据源保持独立。逐性质比较会统一常见名称与 GPa/MPa 等单位，再区分“数值一致、同名但值不同、仅 PoLyInfo、仅最新批处理”。数量差异只用于定位问题，不直接解释为准确率。数据根目录可通过环境变量 `POLYINFO_DATA_ROOT` 覆盖。

内置 `reference_no_0101911` 仅作为明确标注的页面演示数据。默认首页不展示该论文；新上传论文完成后，结果页读取对应任务自己的 `candidate.json`。

## 启动

在项目根目录运行：

```powershell
./start_web_tool.ps1
```

然后访问：

```text
http://localhost:3000
```

本地服务：

- 前端：`http://localhost:3000`
- 抽取 API：`http://localhost:8000`
- 健康检查：`http://localhost:8000/api/health`

PDF 证据页和 bbox 裁剪预览依赖系统命令 `pdftocairo`；当前工作站已通过 MiKTeX 提供该命令。

## 进度来源

界面不使用模拟进度。后端根据任务目录中的实际文件判断状态：

```text
stage0_blocks.json
stage1_mentions.json
stage2_entities.json
stage3_process.json
stage4_properties.json
stage5_characterizations.json
candidate.json
```

每篇论文使用独立任务目录，输出位于项目根目录的 `web_runtime/tasks/`。

## 安全约束

- 仅接受 PDF，生产环境默认单文件不超过 50 MB。
- 用户在 HTTPS 页面提交 API Key 和 MinerU Key；密钥只传给当前任务进程，不写入 Git、镜像或任务记录。
- Preview 结果必须显示“尚未验证”，不得直接当作入库或统计数据。
- 上传真实论文会调用 MinerU 和大模型，可能产生耗时与费用。
