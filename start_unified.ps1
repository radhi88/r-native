# Unified Trading Brain - Startup Script
# Starts all components: Ollama, Orchestrator, Dashboard

Write-Host "🧠 Unified Trading Brain Startup" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan

# 1. Check Ollama
Write-Host "`n🔍 Checking Ollama..." -ForegroundColor Yellow
try {
    $ollamaCheck = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
    Write-Host "✅ Ollama is running" -ForegroundColor Green
} catch {
    Write-Host "❌ Ollama not running. Starting..." -ForegroundColor Red
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

# 2. Set Keep-Alive
$env:OLLAMA_KEEP_ALIVE = "-1"

# 3. Start Unified Orchestrator (background)
Write-Host "`n🎯 Starting Unified Orchestrator..." -ForegroundColor Yellow
$orchJob = Start-Job -ScriptBlock {
    Set-Location "C:\Users\Radhi\MT5\agents"
    python unified_orchestrator.py --loop --interval 0.5
}

# 4. Start Dashboard
Write-Host "`n📊 Starting Unified Dashboard..." -ForegroundColor Yellow
$dashJob = Start-Job -ScriptBlock {
    Set-Location "C:\Users\Radhi\MT5\agents"
    python unified_dashboard.py
}

# 5. Start VS Code PID bridge
Write-Host "`n🔗 Starting VS Code PID Bridge (2804)..." -ForegroundColor Yellow
$bridgeRunning = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like "python*" -or $_.Name -eq "py.exe") -and $_.CommandLine -like "*vs_pid_bridge.py*--loop*"
}
$bridgeJob = $null
if (-not $bridgeRunning) {
    $bridgeJob = Start-Job -ScriptBlock {
        Set-Location "C:\Users\Radhi\MT5"
        .\.venv\Scripts\python.exe agents\vs_pid_bridge.py --pid 2804 --loop --interval 10 --quiet
    }
} else {
    Write-Host "✅ VS Code PID bridge already running" -ForegroundColor Green
}

Write-Host "`n✅ All systems started!" -ForegroundColor Green
Write-Host "   Dashboard: http://localhost:8080" -ForegroundColor Cyan
Write-Host "   Monitor:   http://127.0.0.1:5173/monitor" -ForegroundColor Cyan
Write-Host "   API:       http://localhost:7799" -ForegroundColor Cyan
Write-Host "   SMC:       http://localhost:5050" -ForegroundColor Cyan
Write-Host "`nPress any key to stop all services..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# Stop all
Write-Host "`n🛑 Stopping services..." -ForegroundColor Red
Stop-Job $orchJob
Stop-Job $dashJob
if ($bridgeJob) { Stop-Job $bridgeJob }
Remove-Job $orchJob
Remove-Job $dashJob
if ($bridgeJob) { Remove-Job $bridgeJob }

Write-Host "👋 Goodbye!" -ForegroundColor Cyan
