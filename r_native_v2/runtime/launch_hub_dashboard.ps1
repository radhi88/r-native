# launch_hub_dashboard.ps1 — start the visual hub dashboard (:8801, read-only).
# Reads the hub at :8800. Loopback · DEMO · no execution.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$mt5  = Split-Path -Parent $root
$py   = Join-Path $mt5 ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$app  = Join-Path $root "hub_dashboard.py"
Write-Host "[launch_hub_dash] starting on http://127.0.0.1:8801 ..."
Start-Process -FilePath $py -ArgumentList $app -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $root "data\hub_dash.out") `
  -RedirectStandardError  (Join-Path $root "data\hub_dash.err")
Start-Sleep -Seconds 2
try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:8801/" -TimeoutSec 5 -UseBasicParsing; Write-Host "[launch_hub_dash] up -> http://127.0.0.1:8801" }
catch { Write-Host "[launch_hub_dash] WARN: not reachable yet — check data\hub_dash.err" }
