# GitLab 发布与验收清单

## 上传前

- [ ] 不提交 `.env`、API key、PDF、`batch_results/`、`.venv/`、Java 或 Codex 可执行文件。
- [ ] 保留 `config/agent1_pipeline.yaml` 的模型、阶段、提示和并发配置；凭据只通过环境变量提供。
- [ ] 确认 `PACKAGE_MANIFEST.json` 与发布目录一致。

## 新机器安装

```powershell
.\install.ps1 -CodexCli C:\path	o\codex.exe -JavaHome C:\Program Files\Java\jdk-21 -InstallDependencies
$env:DMX_API_KEY = '<local-secret>'
notepad .\ocr\.env
```

下游模型根据 `agent1_pipeline.yaml` 的 provider 读取 `DMX_API_KEY`、`ARK_API_KEY` 或 `LLM_API_KEY/OPENAI_API_KEY`。不要把这些值写回配置文件或提交到 GitLab。

## 无模型冒烟

把测试 PDF 放入 `input/pdf/` 后运行 `smoke_test.ps1`。dry-run 只检查入口和选择，不调用模型。

## 正式验收

用一篇原始 PDF 完成一次正式运行，确认 `identity_job.json` 为 `DELIVERED`、交接回执存在、Stage3/Stage4N/Stage4T/Stage5 均有结果，且最终 `delivery_status.json` 为 `completed`。

流程固定为：原始 PDF → agent1 → 自动交接 → Stage3 → Stage4N/4T → Stage4R → Stage5 → 最终导出。
