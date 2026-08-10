param(
    [int]$FrontendPort = 3000,
    [int]$ApiPort = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Portal = Join-Path $Root "web_portal"
$Logs = Join-Path $Root "web_runtime\logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

if (-not (Get-NetTCPConnection -State Listen -LocalPort $ApiPort -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "web_api.app:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Logs "api.log") `
        -RedirectStandardError (Join-Path $Logs "api.error.log")
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort $FrontendPort -ErrorAction SilentlyContinue)) {
    $env:NEXT_PUBLIC_EXTRACTION_API_BASE_URL = "http://localhost:$ApiPort"
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev", "--", "--host", "localhost", "--port", "$FrontendPort") `
        -WorkingDirectory $Portal `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Logs "frontend.log") `
        -RedirectStandardError (Join-Path $Logs "frontend.error.log")
}

Start-Sleep -Seconds 4
Write-Host "PolymerLit Extractor: http://localhost:$FrontendPort"
Write-Host "Extraction API:       http://localhost:$ApiPort/api/health"
