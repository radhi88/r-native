# stop_hub.ps1 — stop the R Native 2 hub by the pid recorded in data\hub.lock.
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$lock = Join-Path $root "data\hub.lock"
if (Test-Path $lock) {
  $hubPid = (Get-Content $lock -Raw | ConvertFrom-Json).pid
  if ($hubPid) { Stop-Process -Id $hubPid -Force; Write-Host "[stop_hub] stopped pid $hubPid" }
} else {
  Write-Host "[stop_hub] no hub.lock found"
}
