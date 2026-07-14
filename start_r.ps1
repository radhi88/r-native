# start_r.ps1 — One-command launcher for the R trading system.
#
# What it starts:
#   1. brain_server.py    (port 5055) — the dashboards + APIs
#   2. algory_watcher     (every 30s) — learns from Algory's vault
#   3. r_executor LIVE    (every 8s)  — multi-symbol trading bot
#
# Usage:
#   .\start_r.ps1                  # PAPER mode (default, no real orders)
#   .\start_r.ps1 -Live            # LIVE mode (sends real orders, magic 20260605)
#   .\start_r.ps1 -Stop            # stop everything cleanly
#   .\start_r.ps1 -Status          # quick status check
param(
    [switch]$Live,
    [switch]$Stop,
    [switch]$Status,
    [switch]$NoBypass             # disable session/weekend bypass (use real Algory hours)
)

$ErrorActionPreference = "SilentlyContinue"
$TMP = "$env:LOCALAPPDATA\Temp"

function Stop-All {
    Write-Host "🛑 Stopping all R processes..." -ForegroundColor Yellow
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
             Where-Object { $_.CommandLine -match 'r_executor|brain_server|algory_watcher' }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force
        Write-Host "  killed PID $($p.ProcessId)"
    }
    Write-Host "✓ Stopped." -ForegroundColor Green
}

function Show-Status {
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  R SYSTEM STATUS" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════" -ForegroundColor Cyan

    $procs = @{
        "brain_server"    = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*brain_server*' } | Measure-Object).Count
        "algory_watcher"  = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*algory_watcher*' } | Measure-Object).Count
        "r_executor"      = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*r_executor*' } | Measure-Object).Count
    }
    foreach ($k in $procs.Keys) {
        $c = $procs[$k]
        $ico = if ($c -gt 0) { "🟢" } else { "🔴" }
        Write-Host "  $ico ${k}: $c proc(s)"
    }

    # API health
    try {
        $ex = Invoke-RestMethod "http://localhost:5055/api/r/executor" -TimeoutSec 5
        Write-Host ""
        Write-Host "  mode:    $($ex.mode)  armed: $($ex.armed)"
        Write-Host "  today:   $($ex.today_wins)/$($ex.today_trades) wins  P/L: `$$($ex.today_pl)"
        Write-Host "  open R positions: $($ex.r_open_positions.Count)"
        $ex.r_open_positions | ForEach-Object {
            Write-Host "    ⚡ #$($_.ticket) $($_.type) @ $($_.price_open) P/L=`$$($_.profit)"
        }
    } catch {
        Write-Host "  ⚠ brain_server not responding"
    }
    Write-Host ""
    Write-Host "  📊 Dashboard: http://localhost:5055/r/" -ForegroundColor Yellow
}

if ($Stop)   { Stop-All; exit }
if ($Status) { Show-Status; exit }

# ─── Launch sequence ───
Write-Host "════════════════════════════════════════" -ForegroundColor Green
$mode = if ($Live) { "LIVE 🔴 (real orders!)" } else { "PAPER 🟢 (simulation)" }
Write-Host "  Starting R System — mode: $mode" -ForegroundColor Green
Write-Host "════════════════════════════════════════" -ForegroundColor Green

# Stop any old instances first
Stop-All
Start-Sleep -Seconds 2

# 1. Brain server
Write-Host "1. Starting brain_server.py (port 5055)..."
Start-Process python -ArgumentList "brain_server.py" -WindowStyle Hidden `
    -RedirectStandardOutput "$TMP\brain_server.log"
Start-Sleep -Seconds 5

# 2. Algory watcher
Write-Host "2. Starting algory_watcher daemon (interval 30s)..."
Start-Process python -ArgumentList "-u","-m","friday_v3.algory.algory_watcher","--interval","30" `
    -WindowStyle Hidden -RedirectStandardOutput "$TMP\algory_watcher.log"
Start-Sleep -Seconds 3

# 3. R executor
$liveArg    = if ($Live) { "--live " } else { "" }
$bypassArgs = if (-not $NoBypass) { "set R_BYPASS_SESSION=1&& set R_BYPASS_WEEKEND=1&& set R_BYPASS_FRIDAY=1&& " } else { "" }
Write-Host "3. Starting r_executor ($mode)..."
$cmd = "$($bypassArgs)python -u -m friday_v3.algory.r_executor $($liveArg)--no-brain-json --interval 8 > $TMP\r_solo.log 2>&1"
Start-Process cmd -ArgumentList "/c",$cmd -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅ ALL UP" -ForegroundColor Green
Write-Host "════════════════════════════════════════" -ForegroundColor Green
Write-Host ""

Show-Status

Write-Host ""
Write-Host "  📋 Logs:" -ForegroundColor Gray
Write-Host "     brain:    $TMP\brain_server.log"
Write-Host "     algory:   $TMP\algory_watcher.log"
Write-Host "     executor: $TMP\r_solo.log"
Write-Host ""
Write-Host "  ⛔ Stop:    .\start_r.ps1 -Stop"
Write-Host "  📊 Status:  .\start_r.ps1 -Status"
Write-Host ""
