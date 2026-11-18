# agent1 全链路 GitLab 发布包（20261117）

## 发布状态

这是经过本地真实整链验收的**可部署源码版本**，入口固定为：

`原始 PDF → agent1 → 自动交接 → Stage3 → Stage4N/4T → Stage4R → Stage5 → 最终导出`

0033940 和 0041387 已用同一默认入口完成真实运行。发布包本身不包含本机的 Codex CLI、Java、Python 虚拟环境、PDF 或密钥；安装脚本配置这些外部依赖后运行。

## 安装

```powershell
.\install.ps1 -CodexCli C:\path\to\codex.exe -JavaHome C:\Program Files\Java\jdk-21 -InstallDependencies
$env:DMX_API_KEY = '<local-secret>'
notepad .\ocr\.env
```

`install.ps1` 会创建 `.venv`、生成 agent1 的 `runtime.json`，并把 Java 路径写入 `config/agent1_entry.json`。凭据只通过环境变量和本地 `ocr/.env` 提供，不要提交到 GitLab。

## 无模型冒烟

把测试 PDF 放入 `input/pdf/`，执行：

```powershell
.\smoke_test.ps1 -RefNo 0033940
```

该命令只验证入口和文件选择，不调用模型。

## 正式运行

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\pipeline_runner.py `
  --input-dir .\input\pdf `
  --ref-no reference_no_0033940 `
  --workers 3
```

运行结果写入 `batch_results/agent1/`。已完成任务可以用 `--status` 查询，用 `--resume` 恢复；恢复时不要更换输入、并发或配置。

## 边界

本包不做额外质检、格式转换或图中性质数值抽取。agent1 原生化学结构检查和交付检查保留。模型服务、MinerU、Java 和 Codex CLI 的版本与权限必须在目标机器上满足安装要求。

详见 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) 和 [PACKAGE_MANIFEST.json](PACKAGE_MANIFEST.json)。
