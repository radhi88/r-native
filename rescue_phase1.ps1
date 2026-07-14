# rescue_phase1.ps1 — Phase 1: Safety Lockdown
# Stops everything, cancels orders, archives state, generates report.

$ErrorActionPreference = 'Continue'
$MT5  = "C:\Users\Radhi\MT5"
$TS   = Get-Date -Format "yyyyMMdd-HHmmss"
$ARCH = "$MT5\archive\$TS"

function H($txt, $color = 'Cyan') {
    Write-Host ""
    Write-Host ("═" * 70) -ForegroundColor $color
    Write-Host "  $txt" -ForegroundColor $color
    Write-Host ("═" * 70) -ForegroundColor $color
}

# ── 1. Verify kill_switch ─────────────────────────────────────────
H "1. Kill Switch"
if (Test-Path "$MT5\kill_switch.txt") {
    Write-Host "  ✓ kill_switch.txt active" -ForegroundColor Green
} else {
    Set-Content "$MT5\kill_switch.txt" "EMERGENCY at $TS" -Encoding UTF8
    Write-Host "  ✓ kill_switch.txt created" -ForegroundColor Yellow
}

# ── 2. Stop ALL FRIDAY python processes ───────────────────────────
H "2. Stopping all FRIDAY processes"
$pids = @()
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object {
        $_.CommandLine -match 'friday_brain|friday_agents|brain_server|smc_dashboard|friday_footprint|friday_binance_dom|friday_fractals|friday_agent_team|friday_ea_evolver|friday_mcp_server|friday_to_ea_bridge|friday_researcher'
    } |
    ForEach-Object {
        $cmd = ($_.CommandLine -replace '.*\\','' -replace '"','').Trim() -replace ' .*$',''
        Write-Host "  stop PID $($_.ProcessId)  $cmd" -ForegroundColor DarkGray
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $pids += $_.ProcessId
    }
Start-Sleep -Seconds 3
$alive = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'friday|brain_server|smc_dashboard' }
if ($alive) {
    Write-Host "  ⚠ Still alive: $($alive.Count) — force-killing" -ForegroundColor Red
    $alive | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep -Seconds 2
}
Write-Host "  ✓ $($pids.Count) processes stopped" -ForegroundColor Green

# ── 3. Cancel ALL pending orders + close any open positions ──────
H "3. Cleaning MT5 — cancel pendings, close positions"
python -c @"
import MetaTrader5 as mt5
mt5.initialize()
info = mt5.account_info()
print(f'  Account: {info.login}  Balance: {info.balance}  Equity: {info.equity}')

pendings = mt5.orders_get(symbol='XAUUSDm') or []
positions = mt5.positions_get(symbol='XAUUSDm') or []
print(f'  Pendings: {len(pendings)}, Positions: {len(positions)}')

for o in pendings:
    r = mt5.order_send({'action': mt5.TRADE_ACTION_REMOVE, 'order': o.ticket})
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    print(f'    cancel #{o.ticket} (magic {o.magic}): {ok}')

# Close positions at market
for p in positions:
    tick = mt5.symbol_info_tick('XAUUSDm')
    close_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
    price = tick.bid if p.type == 0 else tick.ask
    req = {
        'action': mt5.TRADE_ACTION_DEAL,
        'position': p.ticket, 'symbol': 'XAUUSDm',
        'volume': p.volume, 'type': close_type,
        'price': float(price), 'deviation': 50,
        'magic': p.magic, 'comment': 'RESCUE_CLOSE',
        'type_filling': mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    print(f'    close #{p.ticket} (magic {p.magic}): {ok}')

# Final state
mt5.initialize()
remaining_p = mt5.orders_get(symbol='XAUUSDm') or []
remaining_pos = mt5.positions_get(symbol='XAUUSDm') or []
print(f'  After cleanup: {len(remaining_p)} pendings, {len(remaining_pos)} positions')
mt5.shutdown()
"@

# ── 4. Archive current state ───────────────────────────────────────
H "4. Archiving state to $ARCH"
New-Item -ItemType Directory -Force -Path $ARCH | Out-Null
$files = @(
    'friday_tasks.json', 'friday_orders.csv', 'friday_brain_v2_state.json',
    'friday_fractals.json', 'friday_footprint.json', 'friday_binance_dom.json',
    'friday_bus.json', 'friday_levels.json', 'friday_memory.json',
    'friday_agent_team_state.json', 'ea_evolver_state.json', 'ea_evolution.csv',
    'friday_agent_team_log.csv', 'brain_full.log', 'brain_err.log',
    'friday_config.py'
)
foreach ($f in $files) {
    $src = "$MT5\$f"
    if (Test-Path $src) {
        Copy-Item $src "$ARCH\" -ErrorAction SilentlyContinue
        Write-Host "  ✓ archived $f" -ForegroundColor DarkGreen
    }
}

# Archive friday_brain.py + brain_server.py (v1)
Copy-Item "$MT5\friday_brain.py" "$ARCH\friday_brain_v1.py" -ErrorAction SilentlyContinue
Copy-Item "$MT5\brain_server.py" "$ARCH\brain_server_v1.py" -ErrorAction SilentlyContinue

# ── 5. Generate Lockdown Report ────────────────────────────────────
H "5. Generating lockdown report"
$report = @"
# FRIDAY Phase 1 Lockdown Report

**Generated**: $TS
**Trigger**: User authorized full system rebuild (Plan D + tighter)

## Account snapshot
"@

python -c @"
import MetaTrader5 as mt5
import json, sys
from datetime import datetime, timedelta
from collections import defaultdict

mt5.initialize()
info = mt5.account_info()
print(f'- Login: {info.login}')
print(f'- Balance: \${info.balance}')
print(f'- Equity: \${info.equity}')
print(f'- Trade allowed: {info.trade_allowed}')

print(f'\n## Last 7 days — by magic')
deals = mt5.history_deals_get(datetime.now() - timedelta(days=7), datetime.now()) or []
xau = [d for d in deals if d.symbol == 'XAUUSDm']
by_magic = defaultdict(lambda: {'deals': 0, 'wins': 0, 'losses': 0, 'pl': 0.0})
for d in xau:
    m = by_magic[d.magic]
    m['deals'] += 1
    if d.entry in (1, 3):
        if d.profit > 0: m['wins'] += 1
        elif d.profit < 0: m['losses'] += 1
        m['pl'] += d.profit
print()
print('| Magic | Source | Deals | Wins | Losses | P/L |')
print('|---|---|---|---|---|---|')
for magic, m in sorted(by_magic.items(), key=lambda x: x[1]['pl']):
    src = 'BRAIN' if magic == 20260600 else 'OLD EA'
    print(f'| {magic} | {src} | {m[\"deals\"]} | {m[\"wins\"]} | {m[\"losses\"]} | \${m[\"pl\"]:+.2f} |')

# Open state
print(f'\n## Live state after cleanup')
p = mt5.orders_get(symbol='XAUUSDm') or []
pos = mt5.positions_get(symbol='XAUUSDm') or []
print(f'- Pendings: {len(p)}')
print(f'- Positions: {len(pos)}')

mt5.shutdown()
"@ >> "$ARCH\REPORT.md"

# Add lessons learned section
Add-Content "$ARCH\REPORT.md" @"

## Lessons learned

1. **Trading M1 on 280-308pt spread is mathematically impossible** without > 60% win rate (we had 6%)
2. **LLM agents as decision-makers** for trading caused inverted SL/TP, hallucinated levels, no probabilistic reasoning
3. **No backtest before live** — the cardinal sin. Every system needs validation on historical data first
4. **Old EAs running unsupervised** (magic 77701, 20260514) caused 60% of losses
5. **No regime detection** — Brain traded in DEAD market (spread > ATR) and lost on every signal
6. **No memory/learning** — Brain repeated the same losing setup 16 times
7. **Process management chaos** — 30+ python processes competing for MT5 lock
8. **Wrong cycle frequency** — 8s cycles in M1 noise = pure overtrading

## Next steps (see RESCUE_PLAN.md)

- ✅ PHASE 1: Lockdown (this script)
- ⏳ PHASE 2: Build proper backtester
- ⏳ PHASE 3: Redesign brain (M5+, regime-gated, max 3 trades/day)
- ⏳ PHASE 4: Graduated re-entry (paper → micro → small)
- ⏳ PHASE 5: Unified supervisor
"@

Write-Host "  ✓ report saved to $ARCH\REPORT.md" -ForegroundColor Green

# ── 6. Final verification ─────────────────────────────────────────
H "6. FINAL STATE" 'Green'
$leftPy = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'friday|brain_server|smc_dashboard' }
Write-Host "  FRIDAY python processes alive: $($leftPy.Count)"

python -c @"
import MetaTrader5 as mt5
mt5.initialize()
p = mt5.orders_get(symbol='XAUUSDm') or []
pos = mt5.positions_get(symbol='XAUUSDm') or []
print(f'  XAUUSDm pendings: {len(p)}  positions: {len(pos)}')
mt5.shutdown()
"@

Write-Host ""
Write-Host "═" * 70 -ForegroundColor Green
Write-Host "  ✅ PHASE 1 COMPLETE" -ForegroundColor Green
Write-Host "═" * 70 -ForegroundColor Green
Write-Host "  Archive: $ARCH" -ForegroundColor Cyan
Write-Host "  Plan:    $MT5\RESCUE_PLAN.md" -ForegroundColor Cyan
Write-Host ""
Write-Host "  ⏭ NEXT: confirm AutoTrading is OFF in MT5 EXNESS terminal"
Write-Host "         then run rescue_phase2.ps1 to build the backtester"
