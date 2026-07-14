# PlutoBrain Swarm launcher
# Starts the never-sleeps orchestrator loop + serves the live dashboard.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # ...\MT5
Set-Location $root

Write-Host "[swarm] starting orchestrator loop (30s cycle)..." -ForegroundColor Cyan
Start-Process -WindowStyle Minimized powershell -ArgumentList @(
  "-NoExit","-Command","Set-Location '$root'; python -m plutobrain_swarm.orchestrator"
)

Write-Host "[swarm] serving dashboard at http://localhost:8099/dashboard.html" -ForegroundColor Cyan
Set-Location "$root\plutobrain_swarm"
Start-Process "http://localhost:8099/dashboard.html"
python -m http.server 8099
