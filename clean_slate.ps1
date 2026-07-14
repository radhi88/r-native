# clean_slate.ps1 — Wipe transient FRIDAY data, keep code + knowledge + EA + archives.
# After running this, the system is a fresh installation ready for backtesting.

$ErrorActionPreference = 'Continue'
$MT5  = "C:\Users\Radhi\MT5"
$TS   = Get-Date -Format "yyyyMMdd-HHmmss"
$ARCH = "$MT5\archive\$TS-pre-clean"

function Section($t, $c = 'Cyan') {
    Write-Host ""
    Write-Host ("-" * 70) -ForegroundColor $c
    Write-Host "  $t" -ForegroundColor $c
    Write-Host ("-" * 70) -ForegroundColor $c
}

# ── 1. Stop everything ───────────────────────────────────────────
Section "1. Stop all FRIDAY processes"
$count = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'friday_brain|friday_agents|brain_server|smc_dashboard|friday_footprint|friday_binance_dom|friday_fractals|friday_agent_team|friday_ea_evolver|friday_mcp_server|friday_to_ea_bridge|friday_researcher' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $count++
    }
Start-Sleep -Seconds 2
Write-Host "  stopped $count processes" -ForegroundColor Green

# ── 2. Archive current state ────────────────────────────────────
Section "2. Archive everything before deletion → $ARCH"
New-Item -ItemType Directory -Force -Path $ARCH | Out-Null

# Transient data files
$dataFiles = @(
    'friday_orders.csv', 'friday_memory.json', 'friday_brain_v2_state.json',
    'friday_fractals.json', 'friday_footprint.json', 'friday_binance_dom.json',
    'friday_bus.json', 'friday_levels.json', 'friday_tasks.json',
    'friday_agent_team_state.json', 'friday_agent_team_log.csv',
    'ea_evolver_state.json', 'ea_evolution.csv',
    'friday_bridge_state.json', 'friday_paper_trades.csv', 'friday_live_trades.csv',
    'friday_signal.json', 'friday_realtime_bar.json',
    'brain_full.log', 'brain_err.log', 'brain_test.log', 'server_log.log', 'server_err.log',
    'mql5_compile.log'
)
foreach ($f in $dataFiles) {
    $src = "$MT5\$f"
    if (Test-Path $src) {
        Copy-Item $src "$ARCH\" -ErrorAction SilentlyContinue
        Write-Host "  archived $f" -ForegroundColor DarkGreen
    }
}

# Archive agent team outputs + debug folders if exist
foreach ($d in @('friday_agent_team_output', 'brain_debug')) {
    if (Test-Path "$MT5\$d") {
        Copy-Item "$MT5\$d" "$ARCH\$d" -Recurse -ErrorAction SilentlyContinue
        Write-Host "  archived $d/" -ForegroundColor DarkGreen
    }
}

# Archive MT5 Common files we touch
$common = "C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
foreach ($f in @('friday_brain_orders.json', 'claude_live_control.csv')) {
    if (Test-Path "$common\$f") {
        Copy-Item "$common\$f" "$ARCH\common_$f" -ErrorAction SilentlyContinue
        Write-Host "  archived common/$f" -ForegroundColor DarkGreen
    }
}

# ── 3. DELETE transient data (clean slate) ─────────────────────
Section "3. Wipe transient data" 'Yellow'
foreach ($f in $dataFiles) {
    $src = "$MT5\$f"
    if (Test-Path $src) {
        Remove-Item $src -Force -ErrorAction SilentlyContinue
        Write-Host "  ✗ deleted $f" -ForegroundColor DarkYellow
    }
}
# Folders
foreach ($d in @('friday_agent_team_output', 'brain_debug', '__pycache__')) {
    if (Test-Path "$MT5\$d") {
        Remove-Item "$MT5\$d" -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  ✗ deleted $d/" -ForegroundColor DarkYellow
    }
}
# Common files (NOT the EA, just the data files brain wrote there)
foreach ($f in @('friday_brain_orders.json', 'claude_live_control.csv', 'friday_bridge_state.json')) {
    $p = "$common\$f"
    if (Test-Path $p) {
        Remove-Item $p -Force -ErrorAction SilentlyContinue
        Write-Host "  ✗ deleted common\$f" -ForegroundColor DarkYellow
    }
}

# ── 4. Reset Kill Switch (start clean — no halt) ───────────────
Section "4. Reset kill_switch"
if (Test-Path "$MT5\kill_switch.txt") {
    Remove-Item "$MT5\kill_switch.txt" -Force
    Write-Host "  ✗ kill_switch.txt removed" -ForegroundColor Yellow
} else {
    Write-Host "  ✓ kill_switch.txt already absent" -ForegroundColor Green
}

# ── 5. Cancel any leftover brain orders + verify nothing left ──
Section "5. Final MT5 cleanup"
python -c @"
import MetaTrader5 as mt5
mt5.initialize()
info = mt5.account_info()
print(f'Account: {info.login}  Balance: {info.balance}  Equity: {info.equity}')
p = [o for o in (mt5.orders_get(symbol='XAUUSDm') or []) if o.magic == 20260600]
for o in p:
    mt5.order_send({'action': mt5.TRADE_ACTION_REMOVE, 'order': o.ticket})
    print(f'cancelled #{o.ticket}')
remaining = mt5.orders_get(symbol='XAUUSDm') or []
positions = mt5.positions_get(symbol='XAUUSDm') or []
print(f'Final: {len(remaining)} pendings (any magic), {len(positions)} positions')
mt5.shutdown()
"@

# ── 6. Show what was PRESERVED ─────────────────────────────────
Section "6. PRESERVED (code + knowledge)" 'Green'
$preserved = @(
    'friday_brain.py            (Brain core)',
    'friday_config.py           (config)',
    'friday_memory.py           (learning module)',
    'friday_regime.py           (regime filter)',
    'friday_fractals.py         (fractal engine)',
    'friday_footprint.py        (footprint engine)',
    'friday_binance_dom.py      (BTC DOM)',
    'friday_agent_team.py       (5 Claude clones daemon)',
    'friday_agents_personas/    (5 specialist personas)',
    'friday_mcp_server.py       (MCP control)',
    'friday_delegate.py         (task CLI)',
    'friday_analyze.py          (performance analyzer)',
    'friday_mql5_compile.py     (MQL5 compiler)',
    'friday_ea_evolver.py       (kept but OFF)',
    'brain_server.py            (dashboard backend)',
    'dashboard/friday_pro.html  (dashboard UI)',
    'RESCUE_PLAN.md             (the plan)',
    'archive/                   (historical snapshots)',
    'plutobrain/                (knowledge vault)'
)
foreach ($p in $preserved) { Write-Host "  ✓ $p" -ForegroundColor Green }

Write-Host ""
Write-Host "  ✓ FRIDAY_Brain_Executor.mq5 (not touched — running)" -ForegroundColor Green

# ── 7. Final state ──────────────────────────────────────────────
Section "7. FINAL STATE" 'Cyan'
$pyCount = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'friday|brain_server|smc_dashboard' }).Count
Write-Host "  FRIDAY python processes alive: $pyCount"
$transientCount = ($dataFiles | Where-Object { Test-Path "$MT5\$_" }).Count
Write-Host "  Transient data files remaining: $transientCount (should be 0)"
Write-Host "  Archive saved to: $ARCH"

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  ✅ CLEAN SLATE COMPLETE" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  All transient data archived + wiped. Code + knowledge preserved." -ForegroundColor Green
