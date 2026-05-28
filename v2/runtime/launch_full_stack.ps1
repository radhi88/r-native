# launch_full_stack.ps1 — Launch all Claude trading systems in one shot
#
# Run from PowerShell:
#   cd C:\Users\Radhi\MT5\r_native_v2
#   .\runtime\launch_full_stack.ps1
#
# Each system runs in its own console window. Close any to stop that service.

$root = "C:\Users\Radhi\MT5\r_native_v2"
$py = "python"

Write-Host "════════════════════════════════════════════"
Write-Host " CLAUDE TRADING STACK — full launch"
Write-Host "════════════════════════════════════════════"

# 1. Brain v1 — captures indicators every 2s
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.brain_v1" -WindowStyle Normal
Write-Host "[1/6] brain_v1 launched (captures indicators)"
Start-Sleep -Seconds 1

# 2. User trade observer — logs every manual trade
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.user_trade_observer" -WindowStyle Normal
Write-Host "[2/6] user_trade_observer launched (logs human trades)"
Start-Sleep -Seconds 1

# 3. Footprint brain bridge — merges MQL5 footprint into brain
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.footprint_brain_bridge" -WindowStyle Normal
Write-Host "[3/6] footprint_brain_bridge launched (MQL5 → brain)"
Start-Sleep -Seconds 1

# 4. R Native brain link — feeds 5 genomes
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.r_native_brain_link" -WindowStyle Normal
Write-Host "[4/6] r_native_brain_link launched (5 genomes)"
Start-Sleep -Seconds 1

# 5. Performance coordinator — tracks all engines
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.performance_coordinator" -WindowStyle Normal
Write-Host "[5/6] performance_coordinator launched (multi-engine perf)"
Start-Sleep -Seconds 1

# 6. Claude autonomous trader — executes trades (magic 99777)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.claude_autonomous_trader" -WindowStyle Normal
Write-Host "[6/9] claude_autonomous_trader launched (magic 99777)"
Start-Sleep -Seconds 1

# 7. Palace council — votes on every signal before execution
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.palace_council" -WindowStyle Normal
Write-Host "[7/9] palace_council launched (5 experts vote)"
Start-Sleep -Seconds 1

# 8. Genome evolver — GA mutation every 10 min
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.genome_evolver" -WindowStyle Normal
Write-Host "[8/9] genome_evolver launched (GA mutation/crossover)"
Start-Sleep -Seconds 1

# 9. Genome promoter — auto-promotes best genome to LIVE
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd $root; $py -m runtime.genome_promoter" -WindowStyle Normal
Write-Host "[9/9] genome_promoter launched (auto-LIVE selection)"

Write-Host ""
Write-Host "════════════════════════════════════════════"
Write-Host " ALL 9 SERVICES LAUNCHED — PALACE COMPLETE"
Write-Host "════════════════════════════════════════════"
Write-Host ""
Write-Host "Next steps in MetaTrader 5:"
Write-Host "  • Attach CLAUDE_FOOTPRINT_v1.ex5 to XAUUSDm chart"
Write-Host "  • Attach CLAUDE_BRAIN_EA_v1.ex5 to XAUUSDm chart"
Write-Host "  • Enable Auto-Trading (top button)"
Write-Host ""
Write-Host "Data files to monitor:"
Write-Host "  data/brain_live.json          — current snapshot"
Write-Host "  data/brain_memory.jsonl       — per-M1-close history"
Write-Host "  data/brain_decisions.jsonl    — every decision"
Write-Host "  data/genome_signals.jsonl     — genome decisions"
Write-Host "  data/genome_fitness.json      — genome stats"
Write-Host "  data/engine_performance.json  — per-magic perf"
Write-Host "  data/footprint_cells.json     — MT5 → Python bridge"
