[CmdletBinding()]
param(
    [switch]$StopExisting,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding

$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env was not found. Copy .env.example to .env and configure the USTC credentials."
}

$settings = @{}
Get-Content -LiteralPath $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
        return
    }
    $name, $value = $line.Split("=", 2)
    $settings[$name.Trim()] = $value.Trim()
}

if ([string]::IsNullOrWhiteSpace($settings["LLM_API_KEY"])) {
    throw "LLM_API_KEY is empty in .env. Paste a USTC-issued API key before starting."
}

$expectedBaseUrl = "https://api.llm.ustc.edu.cn/v1"
if ($settings["LLM_BASE_URL"] -ne $expectedBaseUrl) {
    throw "LLM_BASE_URL must be $expectedBaseUrl for the USTC gateway."
}

Write-Host "[1/3] Checking USTC connectivity through Python httpx..."
$preflight = @'
import sys

import httpx

from comic_agent.config import get_settings

settings = get_settings()
headers = {
    "Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}",
    "Content-Type": "application/json",
}
payload = {
    "model": settings.llm_model,
    "messages": [{"role": "user", "content": "Reply only: OK"}],
    "stream": False,
}
try:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
    print("USTC preflight succeeded.")
except httpx.HTTPStatusError as exc:
    print(f"USTC preflight failed: HTTP {exc.response.status_code}.", file=sys.stderr)
    sys.exit(1)
except httpx.HTTPError as exc:
    print(f"USTC preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
'@
$preflight | python -
if ($LASTEXITCODE -ne 0) {
    throw "USTC preflight failed. Connect the school VPN or adjust the network route, then retry."
}

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    $processId = $listener.OwningProcess
    if (-not $StopExisting) {
        throw "Port 8000 is occupied by PID $processId. Verify it is an old backend, then rerun with -StopExisting."
    }
    Write-Host "[2/3] Stopping existing process on port 8000 (PID $processId)..."
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    $remainingListener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($remainingListener) {
        throw "Port 8000 is still occupied by PID $($remainingListener.OwningProcess)."
    }
} else {
    Write-Host "[2/3] Port 8000 is available."
}

Write-Host "[3/3] Starting the local API server. Press Ctrl+C to stop it."
$uvicornArgs = @("-m", "uvicorn", "comic_agent.main:app", "--host", "127.0.0.1", "--port", "8000")
if (-not $NoReload) {
    $uvicornArgs += "--reload"
}
& python @uvicornArgs
exit $LASTEXITCODE
