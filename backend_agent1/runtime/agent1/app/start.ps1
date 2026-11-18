param([int]$Port = 8780)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config/runtime.json') -Raw | ConvertFrom-Json
& $runtime.python -X utf8 -m identity_app.server --port $Port
