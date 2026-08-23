# 代码与数据提交规范

> 所有准备合并到生产 `main` 的改动，先阅读 [main 分支安全写入与网页发布说明](docs/main_branch_safe_write_guide.md)。该文档给出了完整命令、网页接口契约、PR 门禁和合并后验收步骤。

## 1. 仓库职责

`leexh2333-jpg/polymer_paper_extraction` 是开发上游，负责抽取代码、Prompt、Schema、测试和正式批处理结果。`zqk-7k/polymer_paper_extraction` 是生产集成仓库，负责自动同步、前后端发布和服务器部署。

通用功能应先提交到开发上游。生产仓库中的服务器配置、Secrets 和部署脚本不得反向复制真实密钥到上游。

## 2. 分支和 Pull Request

禁止直接在 `main` 上开发。建议分支：

- `feature/<功能>`：新功能；
- `fix/<问题>`：缺陷修复；
- `data/<批次>`：正式批处理结果；
- `docs/<主题>`：文档。

提交前先同步最新 `main`。一个 PR 只解决一个明确问题，不混入无关重构、运行缓存或批处理数据。

## 3. Preview 流程变更要求

当前 Preview 正式顺序为：

```text
Stage 0 → Stage 1 → Stage 2 → Stage 3 → Stage 4
→ Stage 4R table recovery → Stage 5 → candidate publish
```

修改流程时必须：

1. 更新 `PREVIEW_STAGES` 和对应测试；
2. 明确新 Stage 的输入、输出、失败语义和是否允许降级；
3. 保留稳定对象 ID、证据定位和 unresolved 数据；
4. 更新 README、Schema 版本和批处理发布元数据；
5. 说明是否影响 Strict，不能无意改变 Strict；
6. 不通过提高自动重试次数隐式增加用户 API 费用。

## 4. Prompt、Schema 和配置

- Prompt 修改必须有版本号、行为测试和失败样例；
- Schema 破坏性修改必须提供迁移或兼容读取方案；
- 配置使用仓库相对路径，禁止提交本机绝对路径；
- 模型、最大 token、超时和重试变化必须在 PR 中说明费用影响；
- 自动抽取结论必须保留原文证据，不能只保留模型总结。

## 5. 最低测试要求

```powershell
python -m pytest extraction/tests -q
python -m pytest ocr/tests -q
python -m pytest preview/tests -q
python -m pytest web_api/tests -q
python preview/validate_published_batches.py batch_results
cd web_portal
npm ci
npm run lint
npm test
```

代码必须在 Windows 本地和 GitHub Actions 的 Linux 环境中使用相对路径。CI 未通过不得合并。

## 6. 批处理结果

正式数据必须遵守 [batch_results 发布规范](docs/batch_results_publishing_standard.md)。核心要求是：新建不可变目录、记录生成代码 SHA、声明完整 Preview Stage、提供文件 SHA-256，并在提交前运行发布校验器。

## 7. 安全和版权

- 永远不要提交 `.env`、API Key、服务器密码、SSH 私钥或用户上传凭据；
- 日志和模型原始响应必须检查是否包含密钥或受限制全文；
- 公共仓库只保存允许公开分发的 PDF；
- 用户上传任务、PoLyInfo 私有数据和生产运行结果保存在服务器持久化目录，不进入代码提交。

## 8. PR 描述最少包含

- 解决的问题和影响范围；
- 修改的 Stage、Schema、Prompt 或页面；
- 测试命令和结果；
- 与旧版本的兼容性；
- API 调用成本变化；
- 新批次的代码 SHA、文献数量、失败数量和人工复核情况。
