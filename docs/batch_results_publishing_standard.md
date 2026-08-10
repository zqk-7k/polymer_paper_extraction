# `batch_results` 发布规范

## 1. 为什么必须遵守本规范

生产 API 会扫描 `batch_results/` 下包含 `RESULT_INDEX.json` 的集合，并按 `result_date`、`generated_at` 和目录名选择最新集合。上游提交一旦自动同步并通过 CI，该集合就会发布到网页。

因此，`batch_results` 不是普通调试输出目录，而是可公开展示、可追踪、可复现的数据发布物。错误日期、残缺索引、未完成候选结果或被覆盖的旧批次，都可能让网页自动切换到错误数据。

## 2. 目录与版本规则

每次发布必须创建新目录，不得覆盖已经发布的批次：

```text
batch_results/
└── <任务名>_<模式>_YYYYMMDD/
    ├── RESULT_INDEX.json
    ├── reference_no_0000001/
    │   ├── candidate.json
    │   ├── report_candidate.html
    │   └── 各 Stage JSON
    └── reference_no_0000002/
```

规则：

1. 目录名只能使用小写字母、数字、点、下划线和连字符，并以 `_YYYYMMDD` 结尾。
2. 日期必须与 `RESULT_INDEX.json.result_date` 一致。
3. 已发布目录视为不可变。修复数据时创建新日期或新版本目录。
4. 同一次代码修改和批处理结果发布建议分成两个 Git commit，便于审计和回滚。
5. 只有通过 Preview 验收并生成 `candidate.json` 的结果才能进入该目录。

## 3. 新批次索引格式

新批次使用 `polymerlit-batch/2.0`：

```json
{
  "schema_version": "polymerlit-batch/2.0",
  "generated_at": "2026-08-10T15:30:00+08:00",
  "result_date": "2026-08-10",
  "result_mode": "preview",
  "pipeline": {
    "mode": "preview",
    "git_commit": "完整的40位Git提交SHA",
    "config_sha256": "pipeline.yaml的SHA-256",
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
          "sha256": "文件SHA-256"
        }
      ]
    }
  ]
}
```

`pipeline.git_commit` 必须是实际生成该批数据的代码提交，而不是上传数据时的提交。这样才能回答“这批数据是否经过 Stage 4R”。

## 4. 每篇文献必须满足的条件

1. 文件夹名、`candidate.document_id` 和索引中的 `reference_no` 完全一致。
2. 必须有非空的 `candidate.json` 和 `report_candidate.html`。
3. `candidate.publication.status` 必须为 `complete`。
4. `candidate.json` 至少包含论文、聚合物、样品、工艺、性质、证据和发布状态字段。
5. 索引中的文件大小和 SHA-256 必须与实际文件一致。
6. 未解析对象可以保留在 unresolved 字段，但不能伪造实体绑定。
7. Preview 的 Stage 4R 必须位于 Stage 4 与 Stage 5 之间，并保存恢复报告。

## 5. 禁止提交的内容

- `.env`、API Key、MinerU Key、SSH 密钥和访问令牌；
- `.log`、SQLite、缓存、临时目录和失败重试状态库；
- 单文件达到 GitHub 100 MB 限制的内容；本项目在 95 MB 时直接阻止发布；
- 没有再分发许可的出版商 PDF。非开放获取全文应保存在受控服务器，只在公开仓库保存 DOI、文件校验值和权限状态；
- 为减小仓库而覆盖或删除历史批次。

## 6. 发布前命令

在仓库根目录执行：

```powershell
python preview/validate_published_batches.py batch_results
cd extraction
python -m pytest tests -q
cd ../preview
python -m pytest tests -q
```

校验器检查索引、日期、文献目录、候选状态、文件清单、SHA-256、Stage 4R 流程来源和敏感文件。生产 CI 会重复执行同一校验。

## 7. 推荐上传步骤

1. 从最新 `leexh2333-jpg/main` 创建 `data/<批次名>` 分支。
2. 在仓库外的临时目录运行批处理，避免把缓存和密钥带入 Git。
3. 完成抽取、人工抽查和候选发布。
4. 创建新的不可变批次目录。
5. 生成 `RESULT_INDEX.json`、文件大小和 SHA-256。
6. 运行发布校验器和完整测试。
7. 检查 `git status`，确保没有 PDF 版权文件、密钥、日志和数据库文件。
8. 提交数据并发起 Pull Request，不直接覆盖 `main`。
9. PR 中列明代码 SHA、文献数、成功数、失败数、人工复核比例和与上一批的差异。

## 8. 发布后的自动流程

```text
上游 PR 合并
→ zqk-7k 定时或手动同步
→ 同步工作流先校验全部 batch_results，失败则不推送生产 main
→ CI 再次校验全部 batch_results
→ 测试与容器构建
→ 增量传输变化的数据
→ 服务器原子替换 batch_results
→ API 重启并选择日期最新的合法集合
```

任何校验失败都会阻止生产部署，线上继续保留上一版本。
