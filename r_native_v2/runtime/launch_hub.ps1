# launch_hub.ps1 — start the R Native 2 read-only hub (:8800) as a managed process.
# Read-only · loopback · DEMO. Single-instance is enforced by the port bind inside hub.py.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # ...\MT5\r_native_v2
$mt5  = Split-Path -Parent $root                  # ...\MT5
$py   = Join-Path $mt5 ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$hub  = Join-Path $root "hub.py"
$log  = Join-Path $root "data\hub.out"
Write-Host "[launch_hub] starting hub.py on 127.0.0.1:8800 (read-only)..."
# Start detached; stdout/stderr to hub.out. If :8800 is taken, hub.py exits 1 (single-instance).
Start-Process -FilePath $py -ArgumentList $hub -WindowStyle Hidden `
  -RedirectStandardOutput $log -RedirectStandardError (Join-Path $root "data\hub.err")
Start-Sleep -Seconds 2
try {
  $r = Invoke-RestMethod -Uri "http://127.0.0.1:8800/health" -TimeoutSec 5
  Write-Host "[launch_hub] up. hub=$($r.hub) pid=$($r.pid)"
} catch {
  Write-Host "[launch_hub] WARN: /health not reachable yet — check data\hub.err"
}
