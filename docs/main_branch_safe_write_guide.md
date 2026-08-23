# `main` 分支安全写入与网页发布说明

## 1. 先理解 `main` 的含义

`zqk-7k/polymer_paper_extraction` 的 `main` 不是普通开发分支，而是生产发布分支。

代码进入 `main` 后会自动触发：

1. Python 抽取、OCR、Preview 和 Web API 测试；
2. `batch_results` 发布集合及对象关系校验；
3. 前端依赖安装、Lint 和测试；
4. API 与前端 Docker 镜像构建；
5. 当 `PRODUCTION_DEPLOY_ENABLED=true` 时，部署到公开服务器。

因此，向 `main` 写入的含义是“准备发布”，不是“先提交试试看”。网页代码、API、抽取 Schema 和批处理结果属于同一个发布单元，必须一起保持兼容。

## 2. 分支职责

| 分支类型 | 用途 | 是否直接部署 |
|---|---|---:|
| `main` | 已验收、可发布版本 | 是 |
| `feature/<name>` | 新功能或新 Stage | 否 |
| `fix/<name>` | 缺陷修复 | 否 |
| `data/<collection>` | 新的正式批处理集合 | 否 |
| `experiment/<name>` | Prompt、自进化或算法实验 | 否 |
| `docs/<name>` | 文档更新 | 否 |

硬性规则：

- 禁止直接在 `main` 开发或执行 `git push origin main`；
- 禁止 force push、改写或删除 `main` 历史；
- 所有改动必须从最新 `main` 建分支，通过 Pull Request 合并；
- 实验分支中的测试集答案、人工 gold 标签和针对单篇论文的特例，不能进入生产 Prompt 或规则；
- 一个 PR 只处理一个明确主题，不混入无关重构、运行产物或新的批次数据。

## 3. 合作者标准操作流程

### 3.1 从生产仓库开发

```powershell
git clone git@github.com:zqk-7k/polymer_paper_extraction.git
cd polymer_paper_extraction

git switch main
git pull --ff-only origin main
git switch -c feature/<简短功能名>
```

完成修改后先检查提交内容：

```powershell
git status --short
git diff --check
git diff --stat origin/main...HEAD
```

然后提交并推送自己的分支：

```powershell
git add <本次需要提交的文件>
git commit -m "feat: 简要说明"
git push -u origin feature/<简短功能名>
```

最后在 GitHub 创建 Pull Request：

- Base repository：`zqk-7k/polymer_paper_extraction`
- Base branch：`main`
- Compare branch：本人的功能分支

不要在本地把功能分支直接推到 `main`。

### 3.2 从开发上游贡献

`leexh2333-jpg/polymer_paper_extraction` 是开发上游。开发者应先在上游通过功能分支和 PR 完成验收，再合并到上游 `main`。生产仓库的 `Sync development upstream` 会定时或手动同步上游 `main`。

上游合并前也必须执行本文第 4 节的完整检查。不能依赖生产仓库“替上游发现问题”，因为同步提交即使未部署，也可能使生产仓库的 `main` 暂时处于 CI 失败状态。

## 4. 合并前必须通过的检查

在仓库根目录运行：

```powershell
python -m pytest extraction/tests -q
python -m pytest ocr/tests -q
python -m pytest preview/tests -q
python -m pytest web_api/tests -q
python preview/validate_published_batches.py batch_results

Set-Location web_portal
npm ci
npm run lint
npm test
npm run build
Set-Location ..
```

以上命令有任意一项失败，不得合并。没有修改某个模块也不能随意跳过 CI，因为抽取 Schema、API 和网页展示存在跨模块依赖。

## 5. 最容易导致网页故障的接口契约

### 5.1 抽取结果的层级关系

网页按“论文 → 聚合物 → 样品 → 工艺、性质、表征、证据”逐层展示。`candidate.json` 必须保持以下引用有效：

| 对象 | 主键或关系字段 | 要求 |
|---|---|---|
| PolymerEntity | `entity_id` | 唯一且稳定 |
| Sample | `sample_id`, `refers_to_entity` | 样品引用已存在的聚合物 |
| ProcessStep | `input_sample_ids`, `output_sample_ids` | 输入和输出样品均存在 |
| PropertyObservation | `sample_id` | 性质绑定到已存在的样品；不能只挂论文 |
| Characterization | `sample_ids`, `entity_ids` | 引用对象必须存在 |
| Evidence | `evidence_id` | 所有 `evidence_ids` 均可解析 |

如果暂时不能唯一绑定，保留 `unresolved` 或候选状态，不得编造 Sample ID。不要为了让页面“有数据”而破坏科学语义。

### 5.2 API 兼容性

前端当前依赖以下 API 类型：

- 健康检查与上传任务：`/api/health`、`/api/tasks/*`；
- 批处理展示：`/api/batch-results`、`/hierarchy`、`/graph`、`/pdf`；
- 批次选择：`/api/batch-collections`；
- PoLyInfo 对照：`/api/polyinfo-results/*`。

修改 API 时遵守：

- 优先新增字段，不直接删除或改名旧字段；
- 必须修改字段时，先提供兼容读取和迁移期；
- `null`、缺失、`unresolved` 和旧 Schema 都要有前端回退显示；
- 不在前端硬编码本机路径、批次目录、IP、端口或某篇论文 ID；
- 新增端点或字段必须补充 `web_api/tests` 和前端测试。

### 5.3 `batch_results` 发布

网页会扫描带 `RESULT_INDEX.json` 的集合，并按发布元数据选择集合。提交批次时必须：

1. 新建不可变目录，名称以 `_YYYYMMDD` 结尾；
2. 不覆盖已经发布的历史集合；
3. 每篇文献提供非空 `candidate.json` 和 `report_candidate.html`；
4. 保证目录名、`reference_no` 与 `candidate.document_id` 一致；
5. 在 `RESULT_INDEX.json` 中记录 Schema、生成时间、模式、代码 SHA 和文件 SHA-256；
6. 运行 `python preview/validate_published_batches.py batch_results`；
7. 不提交无公开分发权限的全文 PDF、API 原始响应、密钥或用户上传文件。

完整格式见 [`batch_results` 发布规范](batch_results_publishing_standard.md)。

## 6. 不同改动的额外要求

| 改动类型 | 合并前额外证明 |
|---|---|
| Prompt 或 LLM 参数 | 版本号、冻结验证集结果、错误类型变化、API 成本变化 |
| Schema | 向后兼容方案、旧批次读取测试、迁移说明 |
| 新 Stage 或 Agent | 输入输出、失败语义、重试与降级、Preview/Strict 影响 |
| 实体或关系规则 | 正例、反例、unresolved 行为、对象 ID 稳定性 |
| 证据和 bbox | 页码基准、坐标系、裁剪回归测试、缺失 bbox 回退 |
| 前端页面 | 桌面和移动截图、空状态、加载态、错误态、长文本测试 |
| Web API | 旧前端兼容性、端点测试、错误码和响应示例 |
| 批处理结果 | 集合校验报告、文献数、成功数、失败数、人工复核状态 |
| 部署脚本 | 回滚方案，不得把真实 Secrets 写入仓库 |

## 7. Pull Request 必须写清楚什么

PR 描述至少包含：

1. 本次解决的问题；
2. 修改了哪些 Stage、Schema、Prompt、API、页面或数据集合；
3. 对旧批次和旧网页的兼容性；
4. 实际运行的测试及结果；
5. 是否改变模型调用次数、费用、并发、超时或重试；
6. 是否包含新批次，以及生成代码 SHA、文献数和失败数；
7. 页面变更前后截图；
8. 风险、回滚方式和仍需人工审核的内容。

合并条件：

- CI 全绿；
- 分支已同步最新 `main`；
- 至少一名非作者审核者批准；
- 审核者确认没有密钥、受限全文、本机绝对路径和测试集答案泄漏；
- 数据、API 或前端改动完成端到端页面检查。

普通功能 PR 建议使用 Squash merge，提交标题采用 `feat:`、`fix:`、`data:`、`docs:`、`test:` 或 `chore:`。

## 8. 合并后的生产验收

合并不是结束。负责人应在 GitHub Actions 查看 `CI and production deployment`，确认 `test`、两个 `container-build` 和 `deploy` 均成功，然后检查：

1. `/api/health` 返回服务可用；
2. 上传页可打开，未配置密钥时给出正确提示；
3. 抽取结果列表可加载；
4. 任取一篇文献，可依次进入聚合物、样品和性质页面；
5. 工艺关系、知识图谱和证据 bbox 正常显示；
6. `batch_results` 最新集合与预期一致；
7. PoLyInfo 对照页可加载且没有把候选结果误标为已审核数据。

生产验收失败时，优先对问题提交执行 `git revert <commit>`，通过修复 PR 回滚。禁止 force push 或重写 `main` 历史。

## 9. GitHub 仓库必须启用的保护规则

建议在 `Settings → Rules → Rulesets` 为 `main` 启用：

- Require a pull request before merging；
- Require at least 1 approval；
- Dismiss stale approvals when new commits are pushed；
- Require status checks to pass，选择 CI 中的 `test`；
- Require branches to be up to date before merging；
- Block force pushes；
- Restrict deletions；
- 限制直接 push，仅允许必要的自动同步身份；
- 普通合作者和管理员均不应随意 bypass。

文档只能约束行为，Ruleset 才能真正阻止误操作。生产仓库应同时保留服务器不可变版本和回滚能力。

## 10. 合作者提交前一分钟检查

```text
[ ] 我不是在 main 上开发
[ ] 本 PR 只解决一个主题
[ ] 已同步最新 main
[ ] 完整 Python、批次、前端测试均通过
[ ] candidate 对象 ID 与引用关系有效
[ ] 新旧 API 和旧批次仍可读取
[ ] batch_results 使用新目录且通过发布校验
[ ] 没有密钥、受限 PDF、本机绝对路径或运行缓存
[ ] 没有把冻结测试集答案写入 Prompt 或规则
[ ] PR 写明兼容性、成本、风险和回滚方式
[ ] 页面改动附截图并完成端到端检查
```
