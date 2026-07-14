# launch_unified_v2.ps1 — Single command starts the entire unified stack.
#
# After this script runs, you can close every other terminal/IDE — the
# trading system is fully autonomous in dedicated PowerShell windows.
# Close any console window to stop that specific service.
#
# Run from PowerShell:
#   cd C:\Users\Radhi\MT5\r_native_v2
#   .\runtime\launch_unified_v2.ps1
#
# To also launch the R Native dashboard UI, pass -WithDashboard:
#   .\runtime\launch_unified_v2.ps1 -WithDashboard

param(
    [switch]$WithDashboard,    # Also launch sql_dashboard
    [switch]$WithRNativeUI     # Also launch R Native's Streamlit UI
)

$root = "C:\Users\Radhi\MT5\r_native_v2"
$rnativeRoot = "C:\Users\Radhi\MT5\r_native"
$py = "python"

Write-Host "════════════════════════════════════════════════════════════"
Write-Host " UNIFIED TRADING STACK v2 — LAUNCH"
Write-Host "════════════════════════════════════════════════════════════"
Write-Host ""

function Start-Service([string]$Label, [string]$Cmd, [string]$Title) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle = '$Title'; cd $root; $Cmd" -WindowStyle Normal
    Write-Host "  ✓ $Label" -ForegroundColor Green
    Start-Sleep -Milliseconds 800
}

Write-Host "[INFRASTRUCTURE — 4 producers]" -ForegroundColor Cyan
Start-Service "brain_v1              (market snapshot every 2s)"   "$py -m runtime.brain_v1"            "🧠 brain_v1"
Start-Service "regime_classifier     (TREND/CHOP every 5s)"       "$py -m runtime.regime_classifier"  "🌡️ regime"
Start-Service "trader_orchestrator   (regime-aware gate)"          "$py -m runtime.trader_orchestrator" "🚦 orchestrator"
Start-Service "genome_promoter       (auto-promote best gene)"     "$py -m runtime.genome_promoter"    "👑 promoter"

Write-Host ""
Write-Host "[EVOLUTION]" -ForegroundColor Cyan
Start-Service "genome_evolver        (GA breeds new genomes)"     "$py -m runtime.genome_evolver"     "🧬 evolver"

Write-Host ""
Write-Host "[EXECUTION — single trader]" -ForegroundColor Cyan
Start-Service "unified_trader        (the ONE — magic 99782)"     "$py -m runtime.unified_trader"     "🎯 unified_trader"

Write-Host ""
Write-Host "[SAFETY & LOGGING]" -ForegroundColor Cyan
Start-Service "trailing_stop_manager (universal SL trail)"        "$py -m runtime.trailing_stop_manager" "🪜 trailing"
Start-Service "decision_outcome_filler (PnL backfill every 30s)"  "$py -m runtime.decision_outcome_filler" "📝 filler"

if ($WithDashboard) {
    Write-Host ""
    Write-Host "[VISUALIZATION]" -ForegroundColor Cyan
    Start-Service "sql_dashboard         (live competition view)"  "$py -m runtime.sql_dashboard"      "📊 dashboard"
}

if ($WithRNativeUI) {
    Write-Host ""
    Write-Host "[R NATIVE UI]" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "`$Host.UI.RawUI.WindowTitle = '🎨 R Native UI'; cd $rnativeRoot; $py app.py" -WindowStyle Normal
    Write-Host "  ✓ r_native UI (Streamlit dashboard)" -ForegroundColor Green
}

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════"
Write-Host " STACK ONLINE" -ForegroundColor Yellow
Write-Host "════════════════════════════════════════════════════════════"
Write-Host ""
Write-Host " Each service runs in its own console window."
Write-Host " Close a window to stop that service."
Write-Host " Close ALL windows to shut down trading."
Write-Host ""
Write-Host " Live status:    python -m runtime.sql_dashboard"
Write-Host " Query log:      python -m runtime.decision_log_query --rank"
Write-Host " Breed new gene: python -m runtime.genome_birth"
Write-Host ""
