# Codex CLI 双模式（账号登录 / 中转 API）

身份应用可以通过环境变量在两种 Codex 传输模式之间自由切换，切换只影响 API 路由，不影响化学内核、工具与采用逻辑（Kernel 0.9.0 不变）。两种模式可以在同一台机器上并行使用，互不干扰。

## 模式选择规则

| 模式 | 条件 | 认证 |
|---|---|---|
| 账号模式（默认） | 不设置 `IDENTITY_RELAY_CODEX_CONFIG` | 本机 `~/.codex` 的 ChatGPT 登录态 |
| 中转 API 模式 | 设置 `IDENTITY_RELAY_CODEX_CONFIG` | 中转站的 API key（环境变量注入，provider `env_key`） |

实现：`identity_app/runner.py` 的 `invoke()` 在命令末尾（`-` 之前）追加该环境变量里的 JSON 覆盖参数列表；参数逐字记入每个 call 的 `command.json` 回执。API key 值不写入任何源码或任务文件。

## 账号模式（什么都不用设）

```
python -m identity_app.runner preflight        # 惯例：实现变更后/12小时窗口过期后刷新
python -m identity_app.runner run --pdf <PDF>
python -m identity_app.runner resume --job <任务目录>
```

## 中转 API 模式（DMX，首选）

PowerShell（Windows）：

```powershell
$Data = "<...>\Polymer_Identity_App_Data"
$env:CODEX_HOME = "$Data\private\codex-home-relay"                 # 隔离 home，不碰本机登录
$env:DMX_API_KEY = "<DMX key>"                                     # 或从 .env 读取
$env:IDENTITY_RELAY_CODEX_CONFIG = Get-Content -Raw "$Data\private\relay-overrides-dmx.json"
python -m identity_app.runner preflight
python -m identity_app.runner run --pdf <PDF>
```

Git Bash：

```bash
DATA="/d/.../Polymer_Identity_App_Data"
export CODEX_HOME="$DATA/private/codex-home-relay"
export DMX_API_KEY=$(grep '^DMX_API_KEY=' .env | cut -d= -f2 | tr -d '\r')
export IDENTITY_RELAY_CODEX_CONFIG=$(cat "$DATA/private/relay-overrides-dmx.json")
python -m identity_app.runner preflight && python -m identity_app.runner run --pdf <PDF>
```

llmrelay（https://llmrelay.site/v1）同理：改用 `relay-overrides-llmrelay.json` + `RELAY_GPT_KEY`。该站只有 `gpt-6.1-sol`，没有 `-cdx` 变体；DMX 两者都有。

## 模型规则

- **完整抽取管线固定 `gpt-6.1-sol`**（`config/runtime.json` 的 model + preflight 对生效上下文的模型门校验），两种模式一致。中转只是换通道，不换模型。
- `gpt-6.1-sol-cdx` 仅用于管线外的独立会话（如评分/对比脚本 `runs/IDENTITY-API-TEST-0025452-20261012-01/rerun_010_dmx.py`），不能通过 preflight 的模型门。

## Preflight（两种模式共用一张回执）

`Data/preflight.json` 校验的是**实现快照 sha + 12 小时新鲜度**，与传输模式无关；任意一种模式跑一次 preflight，两种模式都视为已验证。惯例：

- 实现变更后（含本文件对应的挂钩合入后）刷新一次；
- 超过 12 小时刷新一次；
- 中转模式的 preflight 会在 `Data/jobs/` 留下一个 `PREFLIGHT-*` 任务目录，属正常工程记录。

两点已知情况：

- **账号通道 MODEL_CAPACITY**：上游 OpenAI 对账号模式的 `gpt-6.1-sol` 偶发"Selected model is at capacity"，属上游容量波动，与本双模式机制无关（账号模式命令与合入前逐字一致）。失败重试即可；若失败把回执覆盖成 FAILED，用任一模式重跑一次 preflight 恢复 PASS。
- **模型写文件的 UTF-8 BOM**：模型偶尔用带 BOM 的 PowerShell 写法生成 checkpoint 类 JSON，`storage.read()` 已改为 `utf-8-sig` 读取（对无 BOM 文件逐字节等价）。

## 隔离与证据

- 中转模式所有 Codex 状态（sessions/rollouts、日志）落在 `Data/private/codex-home-relay/`；**不要删除其中 `sessions/`** —— 已封存任务的 `verified-runtime.json` 按路径 + sha256 引用这些 rollout 作为证据。
- 账号模式的 `~/.codex` 在中转模式下零读取、零写入；反之亦然。
- key 只放 `.env`（不入库）或临时环境变量；`environment-references.json` 只记录变量名不记录值。

## 成本参考（DMX 第 1 档，2026-10-12 实测）

- 完整抽取一篇：≈¥8（实测 ¥7.94：纯输入 174 / 缓存创建 765k / 缓存命中 7.03M / 输出 56k tokens，42 分钟）
- preflight：≈¥0.5；轻量冒烟：＜¥0.1
- 第 2 档（2 倍价，长度 >272k）在 `gpt-6.1-sol` 上**不可能触发**：其上下文窗口 258,400 本身低于 272k。
- DMX `dashboard/billing/usage` 不实时更新，精确账单以网页端为准。

## 验证记录

- 中转链路端到端实证（preflight PASS + _0025452 完整抽取 DELIVERED、无人干预）：`runs/IDENTITY-API-TEST-0025452-20261012-01/REPORT.md`
- 挂钩正式合入后：319 项 pytest 全绿；中转模式 preflight 两次 PASS（`PREFLIGHT-e481bf0c`、当前回执 `PREFLIGHT-962b84ab`，后者含 `utf-8-sig` 修复）；账号模式命令经 command.json 核验与合入前逐字一致（挂钩惰性），仅受上游容量波动影响。
