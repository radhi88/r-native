# ================================================================
# restart_friday.ps1 - restart the unified FRIDAY stack
# Run with: PowerShell -ExecutionPolicy Bypass -File restart_friday.ps1
# ================================================================

$Root    = Resolve-Path (Join-Path $PSScriptRoot ".")
$Python  = Join-Path $Root ".venv\Scripts\python.exe"
$LogsDir = Join-Path $Root "logs"

$FRIDAY_DASHBOARD_URL   = "http://127.0.0.1:8790"
$FRIDAY_GATEWAY_URL     = "http://127.0.0.1:8799"
$FRIDAY_CHAT_URL        = "http://127.0.0.1:8811"
$FRIDAY_TRADINGVIEW_URL = "http://127.0.0.1:8822"
$FRIDAY_AGENTS_URL      = "http://127.0.0.1:8833"
$FRIDAY_BRAIN_URL       = "http://127.0.0.1:8844"

$env:FRIDAY_DASHBOARD_URL   = $FRIDAY_DASHBOARD_URL
$env:FRIDAY_BASE            = $FRIDAY_DASHBOARD_URL
$env:FRIDAY_SSE_URL         = "$FRIDAY_DASHBOARD_URL/events"
$env:FRIDAY_GATEWAY_URL     = $FRIDAY_GATEWAY_URL
$env:FRIDAY_CHAT_URL        = $FRIDAY_CHAT_URL
$env:FRIDAY_TRADINGVIEW_URL = $FRIDAY_TRADINGVIEW_URL
$env:FRIDAY_AGENTS_URL      = $FRIDAY_AGENTS_URL
$env:FRIDAY_BRAIN_URL       = $FRIDAY_BRAIN_URL
$env:FRIDAY_ROOT            = $Root
$env:JARVIS_PROJECT_ROOT    = $Root
$env:FRIDAY_SYMBOLS = "all"
$env:FRIDAY_MAX_SYMBOLS = "0"
$env:FRIDAY_SYMBOLS_VISIBLE_ONLY = "0"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Start-FridayService($name, $argsList, $logName) {
    $outLog = Join-Path $LogsDir "$logName.out.log"
    $errLog = Join-Path $LogsDir "$logName.err.log"
    $proc = Start-Process -FilePath $Python `
        -ArgumentList $argsList `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden `
        -PassThru
    Write-Host "  Started $name PID $($proc.Id) | logs: $outLog / $errLog"
}

Write-Host "=== FRIDAY Unified Restart ===" -ForegroundColor Cyan
Write-Host "Root: $Root"
Write-Host "Hub : $FRIDAY_DASHBOARD_URL"

# 1. Stop old workers.
Write-Host "`n[1] Stopping old FRIDAY workers..." -ForegroundColor Yellow

$patterns = @(
    "friday_safe_supervisor.py",
    "run_live_insight.py",
    "run_friday.py",
    "run_agents.py",
    "run_server.py",
    "jarvis_ui.py",
    "friday_web_dashboard.py",
    "friday_auto_trader.py",
    "friday_live_brain_state.py",
    "friday_autopilot_supervisor.py",
    "friday_realtime_scalper_demo_executor.py",
    "friday_touch_demo_executor.py",
    "friday_demo_position_governor.py",
    "friday_demo_position_governor_v2.py",
    "friday_scalper_live_dashboard.py",
    "friday_agents_browser.py",
    "friday_chat_app.py",
    "friday_local_gateway:app",
    "mark_xxxix"
)

$regex = ($patterns | ForEach-Object { [regex]::Escape($_) }) -join "|"
Get-CimInstance Win32_Process |
Where-Object { $_.CommandLine -and $_.CommandLine -match $regex } |
ForEach-Object {
    try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "  Killed PID $($_.ProcessId): $($_.CommandLine)"
    } catch {}
}

Start-Sleep -Seconds 2

# 2. Report core port state.
Write-Host "`n[2] Checking unified ports..." -ForegroundColor Yellow
foreach ($port in @(8790, 8799, 8811, 8822, 8833, 8844, 8855)) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object -First 1
    if ($conn) {
        Write-Host "  Port $port : LISTENING (PID $($conn.OwningProcess))"
    } else {
        Write-Host "  Port $port : free"
    }
}

# 3. Start one coordinated stack. 8790 is the hub and aggregates the other logs.
Write-Host "`n[3] Starting unified FRIDAY services..." -ForegroundColor Yellow
Start-FridayService "Gateway 8799" @("-m", "uvicorn", "friday_local_gateway:app", "--host", "127.0.0.1", "--port", "8799") "friday_gateway"
Start-Sleep -Seconds 1

Start-FridayService "Chat 8811" @("friday_chat_app.py") "friday_chat"
Start-Sleep -Seconds 1

Start-FridayService "TradingView 8822" @("friday_scalper_live_dashboard.py") "friday_tradingview"
Start-Sleep -Seconds 1

Start-FridayService "Brain 8844" @("friday_live_brain_state.py", "--serve", "--port", "8844") "friday_brain"
Start-Sleep -Seconds 1

Start-FridayService "Agents 8833" @("friday_agents_browser.py") "friday_agents"
Start-Sleep -Seconds 1

Start-FridayService "AI Dashboard / SSE Hub 8790" @(
    "scripts\friday_web_dashboard.py",
    "--profile", "scalping",
    "--symbols", "all",
    "--max-open-positions", "3",
    "--entry-cooldown-seconds", "30",
    "--analysis-only",
    "--port", "8790"
) "friday_web_dashboard"
Start-Sleep -Seconds 2

Start-FridayService "Safe Paper Supervisor" @(
    "scripts\friday_safe_supervisor.py",
    "--mode", "paper",
    "--interval-seconds", "15",
    "--position-interval-seconds", "1",
    "--symbols", "all",
    "--max-symbols", "0",
    "--max-open", "3",
    "--profiles", "scalping,smc",
    "--no-gold-scalper-mode",
    "--no-reserve-gold-slot",
    "--ignore-spread-filter"
) "friday_supervisor"

# 4. Open the unified views.
Start-Sleep -Seconds 4
Write-Host "`n[4] Opening dashboards..." -ForegroundColor Yellow
Start-Process $FRIDAY_DASHBOARD_URL
Start-Process $FRIDAY_BRAIN_URL
Start-Process $FRIDAY_AGENTS_URL
Start-Process $FRIDAY_TRADINGVIEW_URL
Start-Process $FRIDAY_CHAT_URL

Write-Host "`n=== FRIDAY is running through one hub ===" -ForegroundColor Green
Write-Host "AI Dashboard / SSE hub $FRIDAY_DASHBOARD_URL"
Write-Host "Gateway              $FRIDAY_GATEWAY_URL"
Write-Host "Chat                 $FRIDAY_CHAT_URL"
Write-Host "TradingView          $FRIDAY_TRADINGVIEW_URL"
Write-Host "Agents               $FRIDAY_AGENTS_URL"
Write-Host "Brain                $FRIDAY_BRAIN_URL"
Write-Host "Logs                 $LogsDir"
