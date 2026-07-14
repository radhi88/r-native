#Requires -Version 5.1
<#
.SYNOPSIS
  DNA EVOLVE v7.2 — Full System Launcher
  Starts ea_monitor.py in a new terminal and shows MT5 setup instructions.
#>

param(
    [switch]$NoMonitor,    # Skip launching ea_monitor (if already running)
    [switch]$NoBrowser     # Don't open browser automatically
)

$Root  = "C:\Users\Radhi\MT5"
$Venv  = "$Root\.venv\Scripts\python.exe"
$Port  = 7799
$Url   = "http://localhost:$Port"

# ─── Environment ────────────────────────────────────────────────────
$env:FRIDAY_PROJECT_ROOT = $Root
$env:FRIDAY_ROOT         = $Root

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   DNA EVOLVE v7.2 — GOLD Stop-Reverse EA    ║" -ForegroundColor Cyan
Write-Host "  ║   Claude-supervised parameter evolution      ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ─── Check ANTHROPIC_API_KEY ────────────────────────────────────────
if (-not $env:ANTHROPIC_API_KEY) {
    Write-Host "  [WARN] ANTHROPIC_API_KEY not set." -ForegroundColor Yellow
    Write-Host "         Claude suggestions will fail — set it first:" -ForegroundColor Yellow
    Write-Host "         `$env:ANTHROPIC_API_KEY = 'sk-ant-...'" -ForegroundColor Gray
    Write-Host ""
}

# ─── Launch ea_monitor.py in new terminal window ────────────────────
if (-not $NoMonitor) {
    Write-Host "  [1/3] Starting ea_monitor.py ..." -ForegroundColor Green
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$Root'; `$env:FRIDAY_PROJECT_ROOT='$Root'; & '$Venv' ea_monitor.py"
    ) -WorkingDirectory $Root
    Start-Sleep -Milliseconds 1500
}

# ─── Open browser ───────────────────────────────────────────────────
if (-not $NoBrowser) {
    Write-Host "  [2/3] Opening dashboard → $Url" -ForegroundColor Green
    Start-Process $Url
}

# ─── MT5 Setup Instructions ─────────────────────────────────────────
Write-Host ""
Write-Host "  [3/3] MT5 Setup Instructions:" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  1. Copy EA to MT5:" -ForegroundColor White
Write-Host "     Copy v7_2_DNA_EVOLVE.mq5 → MT5\MQL5\Experts\" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. In MetaEditor: compile v7_2_DNA_EVOLVE.mq5" -ForegroundColor White
Write-Host ""
Write-Host "  3. Open Strategy Tester:" -ForegroundColor White
Write-Host "     View → Strategy Tester (Ctrl+R)" -ForegroundColor Gray
Write-Host "     Expert:  v7_2_DNA_EVOLVE" -ForegroundColor Gray
Write-Host "     Symbol:  XAUUSDm (Gold)" -ForegroundColor Gray
Write-Host "     Timeframe: M15 or H1" -ForegroundColor Gray
Write-Host "     Model:   Every tick" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. Load settings:" -ForegroundColor White
Write-Host "     In Inputs tab → Load → v7_2_DNA_EVOLVE.set" -ForegroundColor Gray
Write-Host ""
Write-Host "  5. Enable file writing (must be ON for monitor):" -ForegroundColor White
Write-Host "     InpWriteFiles = true" -ForegroundColor Gray
Write-Host "     InpReadCmds   = true" -ForegroundColor Gray
Write-Host ""
Write-Host "  6. Click Start — watch the monitor at $Url" -ForegroundColor White
Write-Host ""
Write-Host "  JSON files written by EA → MT5 Common Files:" -ForegroundColor DarkGray
Write-Host "  %APPDATA%\MetaQuotes\Terminal\Common\Files\" -ForegroundColor Gray
Write-Host "  ─────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Dashboard:     $Url" -ForegroundColor Cyan
Write-Host "  API state:     $Url/api/state" -ForegroundColor Cyan
Write-Host "  FRIDAY hub:    http://localhost:8790 (if running)" -ForegroundColor DarkGray
Write-Host ""
