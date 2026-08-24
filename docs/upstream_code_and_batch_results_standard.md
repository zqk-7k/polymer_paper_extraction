# 上游开发者代码与 `batch_results` 交付规范

适用仓库：`leexh2333-jpg/polymer_paper_extraction`

生产集成仓库：`zqk-7k/polymer_paper_extraction`
适用对象：抽取流程、Prompt、Schema、前后端代码和离线批处理结果的开发者

## 1. 先理解自动发布关系

上游仓库是开发源，生产仓库负责集成和部署。合并到上游 `main` 的内容不会直接在服务器上运行，而会经过以下流程：

```text
上游功能或数据分支
→ Pull Request、测试与人工审核
→ 合并到 leexh2333-jpg/main
→ zqk-7k 定时或手动同步上游
→ 同步前校验 batch_results
→ 推送生产 main
→ 完整 CI、前后端构建
→ 增量部署服务器
→ API 选择最新合法批次
→ 网页“离线批处理结果”显示新数据
```

任意校验失败都会停止部署，线上继续保留上一版。

## 2. 哪些内容会进入网页

| 内容 | 是否自动部署 | 网页用途 |
|---|---:|---|
| 抽取、OCR、Preview、Prompt、Schema | 是 | 网页上传任务调用最新 Preview 流程 |
| FastAPI 与前端代码 | 是 | 页面和接口更新 |
| `batch_results/<批次>/` | 是 | “离线批处理结果”列表和关系详情 |
| `source_pdfs/<reference_no>.pdf` | 有条件 | 原文和证据页预览，仅限允许公开分发的 PDF |
| `web_runtime/` | 否 | 服务器持久化的网页上传任务，不应提交 Git |
| PoLyInfo 私有对照数据 | 否 | 由服务器独立保存，不进入公开仓库 |
| API Key、MinerU Key、部署密钥 | 否 | 只能由用户请求或 GitHub Secrets 临时提供 |

API 启动时扫描 `batch_results/` 下所有含 `RESULT_INDEX.json` 的目录，按
`result_date`、`generated_at`、目录名依次比较并选择最新批次。前端从 API 读取实际
`collection_id`、日期和模式，不得在页面中写死某个 demo 批次名称。

如果生产环境显式设置 `BATCH_RESULTS_COLLECTION`，页面会固定到指定批次。发布前应由生产维护者确认该变量为空，或同步修改固定值。

## 3. 代码提交规范

### 3.1 分支与提交

禁止直接在 `main` 上开发。使用以下分支名：

- `feature/<name>`：新 Stage、新功能或页面；
- `fix/<name>`：缺陷修复；
- `data/<collection>`：正式批处理结果；
- `docs/<name>`：文档。

代码修改和大批数据发布原则上拆成两个 PR：先合并代码并取得生成代码 SHA，再用该 SHA 跑批并提交数据。一个提交只处理一个主题，不混入缓存、日志和本地路径修改。

### 3.2 Preview 流程契约

当前网页和正式离线候选结果使用：

```text
Stage 0 document parsing
→ Stage 1 material mention
→ Stage 2 polymer entity
→ Stage 3 sample and process
→ Stage 4 property
→ Stage 4R table recovery
→ Stage 5 characterization
→ candidate publish
```

修改流程时必须同步修改编排、测试、README 和发布元数据，并在 PR 中说明：

1. 输入、输出文件及 Schema 变化；
2. 新 Stage 的失败、重试和降级语义；
3. 是否改变 Preview 或 Strict；
4. 对模型调用次数、token 和费用的影响；
5. 与旧 `candidate.json` 的兼容方式；
6. 对稳定对象 ID、样品绑定和证据链的影响。

不得通过增加重试次数、放宽语义校验或静默丢弃 unresolved 数据来制造“成功率提升”。

### 3.3 Prompt、Schema 和路径

- Prompt 必须版本化，并保留成功、失败和边界样例；
- Schema 破坏性变更必须提供迁移或兼容读取方案；
- 所有路径使用仓库相对路径，不得提交 `D:\...`、用户目录或服务器绝对路径；
- 模型输出必须经过结构校验，不能把自然语言总结直接当数据库事实；
- 每条可发布事实必须保留证据引用，歧义关系进入 unresolved，不得猜测绑定。

## 4. `batch_results` 是正式发布物

`batch_results` 不是普通运行输出。只要新批次进入上游 `main`、通过同步和 CI，它就可能自动成为网页展示数据。因此必须满足不可变、可追溯、可校验和可回滚四项要求。

### 4.1 目录规范

每次发布创建新目录，不覆盖旧批次：

```text
batch_results/
└─ <task>_<mode>_YYYYMMDD/
   ├─ RESULT_INDEX.json
   ├─ README.md
   ├─ validation_summary.json
   ├─ reference_no_0000001/
   │  ├─ candidate.json
   │  ├─ report_candidate.html
   │  ├─ stage0_blocks.json
   │  ├─ stage1_mentions.json
   │  ├─ stage2_entities.json
   │  ├─ stage3_process.json
   │  ├─ stage4_properties.pre_recovery.json
   │  ├─ stage4r_recovery.json
   │  ├─ stage4_properties.recovery_preview.json
   │  ├─ stage4_properties.json
   │  └─ stage5_characterizations.json
   └─ reference_no_0000002/
```

目录名只能使用小写字母、数字、点、下划线和连字符，并以 `_YYYYMMDD` 结尾。日期必须与索引中的 `result_date` 一致。已经进入 `main` 的批次视为不可变；修复时发布新目录。

### 4.2 `RESULT_INDEX.json`

新批次必须使用 `polymerlit-batch/2.0`：

```json
{
  "schema_version": "polymerlit-batch/2.0",
  "generated_at": "2026-08-10T16:30:00+08:00",
  "result_date": "2026-08-10",
  "result_mode": "preview",
  "pipeline": {
    "mode": "preview",
    "git_commit": "40位、实际生成本批数据的Git SHA",
    "config_sha256": "64位配置文件SHA-256",
    "stages": [
      "stage0_document",
      "stage1_material_mention",
      "stage2_polymer_entity",
      "stage3_sample_process",
      "stage4_property",
      "stage4r_table_recovery",
      "stage5_characterization",
      "candidate_publish"
    ]
  },
  "documents": [
    {
      "reference_no": "reference_no_0000001",
      "result_dir": "reference_no_0000001",
      "files": [
        {
          "name": "candidate.json",
          "size_bytes": 12345,
          "sha256": "64位文件SHA-256"
        },
        {
          "name": "report_candidate.html",
          "size_bytes": 23456,
          "sha256": "64位文件SHA-256"
        }
      ]
    }
  ]
}
```

`pipeline.git_commit` 必须是运行抽取时检出的代码提交，不是上传数据时新产生的提交。JSON、HTML、Markdown 和 TXT 使用 UTF-8、LF 换行；清单中的大小和 SHA-256 也按 LF 规范化字节计算。

### 4.3 每篇文献的最低要求

每个 `reference_no_*` 必须同时满足：

1. 目录名、索引 `reference_no`、`candidate.document_id` 完全一致；
2. `candidate.json` 和 `report_candidate.html` 存在且非空；
3. `candidate.publication.status` 为 `complete`；
4. 候选数据至少包含 `paper`、`polymer_entities`、`samples`、`process_steps`、`property_observations`、`evidence` 和 `publication`；
5. Stage 4R 位于 Stage 4 和 Stage 5 之间，并保留恢复报告及恢复前数据；
6. 未唯一解析的数据留在 unresolved 或标记未解析，不能伪造确定关系；
7. 文件清单、规范化大小和 SHA-256 与实际文件一致。

### 4.4 关系完整性要求

网页按照“论文 → 聚合物 → 样品 → 性质/工艺/表征 → 证据”逐层展示。仅抽出名称和值但没有对象关系，不算合格批结果。

- `polymer_entities[].entity_id` 在文献内唯一；
- `samples[].sample_id` 在文献内唯一，`refers_to_entity` 指向存在的聚合物；
- `process_steps[].input_sample_ids/output_sample_ids` 指向存在的样品；
- `property_observations[].sample_id` 指向存在的样品，无法确定时明确标记 `sample_resolution_status`；
- `characterizations[].sample_ids/entity_ids` 指向存在对象；
- 所有 `evidence_ids` 指向 `evidence[].evidence_id`；
- 证据至少保留页码、来源类型和原文片段；可获得版面位置时保存有效 `bbox`，供网页红框定位。

禁止为了让页面“有关系”而把论文级、系列级或图表级性质随意挂到某个样品。

### 4.5 质量状态

`publication.status=complete` 只表示流水线和候选发布完成，不代表已成为专家确认数据。必须另外保留：

- `validation_status`：如 `not_validated`、`partially_validated`、`validated`；
- 失败 Stage 和降级情况；
- unresolved 数量；
- 人工抽查数量、比例和发现的问题；
- 与上一批次的实体、样品、性质、证据数量差异。

网页应明确显示候选或待校验状态，未经科学语义校验的数据不得宣称可直接入库。

### 4.6 非生产审阅结果

未满足 `candidate.publication.status=complete`、但需要提交供人工复核的结果，使用
`REVIEW_INDEX.json` 标记为 `polymerlit-review/1.0` 审阅集合。它必须声明
`production_eligible=false`，不得同时存在 `RESULT_INDEX.json`。校验器仍检查关键产物、
本机路径、敏感信息和禁止文件，Web API 不会把它作为生产批次。

## 5. 推荐发布步骤

### 5.1 代码 PR

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/<name>

# 修改代码并运行测试
python -m pytest extraction/tests -q
python -m pytest ocr/tests -q
python -m pytest preview/tests -q
python -m pytest web_api/tests -q
cd web_portal
npm ci
npm run lint
npm test
```

提交并发起 PR。代码 PR 合并后记录生成批数据使用的完整 SHA：

```powershell
git rev-parse HEAD
```

### 5.2 数据 PR

1. 从包含目标代码 SHA 的最新 `main` 创建 `data/<collection>`；
2. 在仓库外的临时目录完成 PDF 解析和跑批；
3. 完成候选发布、关系完整性检查和人工抽查；
4. 创建新的不可变批次目录；
5. 生成 `RESULT_INDEX.json`、验证摘要和文件清单；
6. 运行：

```powershell
python preview/validate_published_batches.py batch_results
python -m pytest preview/tests -q
python -m pytest web_api/tests -q
git status --short
```

7. 确认没有密钥、日志、数据库、缓存或受限 PDF；
8. 只提交新批次及必要说明，发起数据 PR；
9. 数据 PR 合并后通知生产维护者手动同步，或等待每小时第 17 分钟自动同步。

## 6. PR 描述模板

```markdown
## 变更类型
- [ ] 抽取代码
- [ ] Prompt / Schema
- [ ] 前后端
- [ ] batch_results

## 代码变更
- 影响 Stage：
- Preview / Strict 影响：
- 兼容性：
- API 调用与费用变化：

## 批处理发布
- 批次目录：
- 生成代码 SHA：
- 配置 SHA-256：
- 文献总数 / 成功 / 失败：
- 聚合物 / 样品 / 性质 / 证据数量：
- unresolved 数量：
- 人工复核数量与比例：
- 相比上一批次的主要变化：

## 验证
- [ ] extraction tests
- [ ] OCR tests
- [ ] preview tests
- [ ] web API tests
- [ ] frontend lint/tests
- [ ] batch publication validator
- [ ] 未包含密钥、日志、数据库和受限全文
```

## 7. 自动部署后的验收

生产同步完成后检查：

1. GitHub Actions 的同步、测试、镜像构建和 deploy 全部成功；
2. `GET /api/health` 中 `batch_collection` 和 `batch_result_date` 等于新批次；
3. `GET /api/batch-results` 返回预期文献数量；
4. 网页“离线批处理结果”的批次名、日期、模式和数量来自新索引；
5. 随机检查至少三篇文献，确认聚合物、样品、性质、工艺和证据可以逐层打开；
6. 检查证据页码、bbox 红框、原文链接和知识图谱关系；
7. 网页上传历史没有被离线批次覆盖。

当前生产健康检查地址：

```text
https://122.51.104.121:18120/api/health
```

## 8. 禁止提交

- `.env`、API Key、MinerU Key、SSH 密钥、访问令牌和服务器密码；
- `.log`、SQLite、任务状态库、缓存、临时目录和模型调试转储；
- 本机绝对路径；
- GitHub 单文件上限附近的大文件，本项目在 95 MB 时阻止发布；
- 没有再分发许可的出版商 PDF；
- 为减小仓库而覆盖或删除历史批次；
- 未经审核的自动关系修补结果。

非开放获取全文应保存在受控存储，只公开 DOI、权限状态、文件校验值和允许公开的派生证据。任何真实密钥进入 Git 历史后都必须立即吊销，删除文件本身不等于消除泄露。

## 9. 故障与回滚

- 同步校验失败：上游提交不会进入生产 `main`，修复后重新提交，不绕过校验器；
- CI 或镜像构建失败：线上保持上一版本；
- 新批次内容错误：不要修改已经发布的目录，生成修正版新批次；
- 网页选错批次：检查日期、`generated_at` 和生产环境 `BATCH_RESULTS_COLLECTION`；
- 紧急回滚：由生产维护者回退生产提交或临时固定上一合法批次，并保留问题批次用于审计。

## 10. 合并前最终检查表

- [ ] 使用分支和 PR，没有直接改 `main`；
- [ ] 代码和数据分开提交；
- [ ] Preview 阶段、Prompt、Schema 和测试已同步更新；
- [ ] 新批次目录未覆盖历史批次；
- [ ] `RESULT_INDEX.json` 使用 `polymerlit-batch/2.0`；
- [ ] 生成代码 SHA 和配置 SHA-256 真实可追溯；
- [ ] Stage 4R、候选结果、报告和文件清单完整；
- [ ] 聚合物、样品、工艺、性质和证据引用通过关系检查；
- [ ] 校验器和相关测试全部通过；
- [ ] 没有秘密信息、运行垃圾和版权受限全文；
- [ ] PR 描述包含规模、失败、unresolved、人工复核和差异说明。
