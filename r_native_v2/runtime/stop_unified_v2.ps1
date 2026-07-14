# stop_unified_v2.ps1 — Clean shutdown of the unified stack.
#
# Run from PowerShell:
#   cd C:\Users\Radhi\MT5\r_native_v2
#   .\runtime\stop_unified_v2.ps1

$services = @(
    'brain_v1', 'regime_classifier', 'trader_orchestrator',
    'genome_evolver', 'genome_promoter',
    'unified_trader', 'trailing_stop_manager',
    'decision_outcome_filler', 'sql_dashboard',
    # Legacy traders — kill if any leaked back in
    'claude_simple_trader', 'claude_smart_trader',
    'claude_genome_trader', 'claude_autonomous_trader',
    'palace_council'
)

Write-Host "════════════════════════════════════════════════════════════"
Write-Host " STOPPING UNIFIED STACK"
Write-Host "════════════════════════════════════════════════════════════"
Write-Host ""

$killed = 0
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"
foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    foreach ($svc in $services) {
        if ($cmd -match "runtime\.$svc\b") {
            try {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
                Write-Host "  🪦 stopped $svc (PID $($p.ProcessId))" -ForegroundColor Yellow
                $killed++
            } catch {
                Write-Host "  ⚠️  could not stop PID $($p.ProcessId): $_" -ForegroundColor Red
            }
            break
        }
    }
}

Write-Host ""
Write-Host "Stopped $killed process(es)." -ForegroundColor Green
Write-Host ""
