# stop_hub_dashboard.ps1 — stop the :8801 dashboard (by lock pid, fallback by port).
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$lock = Join-Path $root "data\hub_dash.lock"
$stopped = $false
if (Test-Path $lock) {
  $hubPid = (Get-Content $lock -Raw | ConvertFrom-Json).pid
  if ($hubPid) { Stop-Process -Id $hubPid -Force; Write-Host "[stop_hub_dash] stopped pid $hubPid (lock)"; $stopped = $true }
}
if (-not $stopped) {
  $c = Get-NetTCPConnection -LocalPort 8801 -State Listen -ErrorAction SilentlyContinue
  if ($c) { Stop-Process -Id $c.OwningProcess -Force; Write-Host "[stop_hub_dash] stopped pid $($c.OwningProcess) (port)" }
  else { Write-Host "[stop_hub_dash] nothing on :8801" }
}
