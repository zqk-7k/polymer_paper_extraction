param([string]$RefNo = 'reference_no_0037921', [string]$InputDir = '')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
if (-not $InputDir) { $InputDir = Join-Path $Root 'input/pdf' }
& (Join-Path $Root '.venv/Scripts/python.exe') -B -X utf8 pipeline_runner.py --input-dir $InputDir --ref-no ("reference_no_" + $RefNo.TrimStart('r','e','f','e','r','n','c','e','_','n','o','_')) --dry-run
if ($LASTEXITCODE) { throw "dry-run 失败，退出码 $LASTEXITCODE" }
