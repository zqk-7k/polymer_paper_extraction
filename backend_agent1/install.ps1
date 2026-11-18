param(
  [string]$Python = "",
  [string]$CodexCli = "",
  [string]$JavaHome = "",
  [switch]$InstallDependencies
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
if (-not $CodexCli) { $CodexCli = $env:AGENT1_CODEX_CLI }
if (-not $JavaHome) { $JavaHome = $env:AGENT1_JAVA_HOME }
if (-not $CodexCli -or -not (Test-Path -LiteralPath $CodexCli)) { throw '请通过 -CodexCli 或 AGENT1_CODEX_CLI 提供 Codex CLI 路径' }
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) { throw '请通过 -JavaHome 或 AGENT1_JAVA_HOME 提供 Java 21 路径' }
$venv = Join-Path $Root '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts/python.exe'))) { & $Python -m venv $venv }
$py = Join-Path $venv 'Scripts/python.exe'
if ($InstallDependencies) {
  & $py -m pip install -r requirements-agent1.txt -r requirements-extraction.txt -r requirements-ocr.txt
}
$app = Join-Path $Root 'runtime/agent1/app'
$runtime = [ordered]@{
  cli = (Resolve-Path -LiteralPath $CodexCli).Path
  python = (Resolve-Path -LiteralPath $py).Path
  data_root = (Join-Path $Root 'runtime/agent1/app-runtime')
  model = 'gpt-6.1-sol'
  reasoning_effort = 'xhigh'
  sandbox = 'workspace-write'
  runtime_version = 'codex-cli 0.160.0 or compatible'
  runtime_files = @{}
  dependencies = 'requirements-agent1.txt'
  runtime_packaging_contract = 'identity-cli-package/1.1'
}
$runtime | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $app 'config/runtime.json') -Encoding utf8
$entry = [ordered]@{
  agent1_app = '../runtime/agent1/app'
  java_home = (Resolve-Path -LiteralPath $JavaHome).Path
  mineru_env = '../ocr/.env'
  downstream_config = 'agent1_pipeline.yaml'
  output_root = '../batch_results/agent1'
  minutes = 60.0
  workers = 3
}
$entry | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Root 'config/agent1_entry.json') -Encoding utf8
if (-not (Test-Path -LiteralPath (Join-Path $Root 'ocr/.env'))) {
  Copy-Item -LiteralPath (Join-Path $Root 'ocr/.env.example') -Destination (Join-Path $Root 'ocr/.env')
  Write-Warning '已创建 ocr/.env 模板，请填入 MINERU_API_KEY 后再运行。'
}
Write-Host "安装配置完成。Python: $py"
Write-Host '下一步：设置 DMX_API_KEY/LLM_API_KEY/OPENAI_API_KEY，并编辑 ocr/.env。'
