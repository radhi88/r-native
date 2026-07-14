# start_my_program.ps1 — one-click persistent launcher for the full FRIDAY/R Native system.
# Each component starts hidden + fully detached (survives this shell). Skips ones already up.
$ErrorActionPreference = "SilentlyContinue"
$env:PYTHONIOENCODING = "utf-8"
# pythonw.exe = NO console window (fixes the terminal-window flood). Fall back to python if absent.
$PY = "C:\Users\Radhi\MT5\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $PY)) { $PY = "pythonw" }
$MT5 = "C:\Users\Radhi\MT5"
$V2  = "C:\Users\Radhi\MT5\r_native_v2"

function Running($needle) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
      Where-Object { $_.CommandLine -like "*$needle*" -and $_.CommandLine -notlike "*shell-snapshot*" } |
      Select-Object -First 1
}
function Launch($label, $argline, $cwd) {
    # needle = the SCRIPT name (token ending in .py) or the -m MODULE — NOT the last token (--loop).
    $parts = $argline -split ' '
    $needle = ($parts | Where-Object { $_ -like '*.py' } | Select-Object -First 1)
    if (-not $needle) { $mi = [array]::IndexOf($parts, '-m'); if ($mi -ge 0) { $needle = $parts[$mi + 1] } }
    if (-not $needle) { $needle = $parts[0] }
    if (Running $needle) { Write-Output "  = $label (already running)"; return }   # never duplicate
    Start-Process -FilePath $PY -ArgumentList $argline -WorkingDirectory $cwd -WindowStyle Hidden
    Write-Output "  > $label launched"
    Start-Sleep -Milliseconds 600
}

Write-Output "=== launching FRIDAY / R Native ==="
# core
Launch "brain (+31 agents)"      "-u -m r_native.brain_server" $MT5
Start-Sleep -Seconds 5
Launch "R Native GUI"            "app.py"                       "$MT5\r_native"
# r_executor (ALGORY 20260600) REMOVED 2026-06-12: ungoverned churner (-$180/12h). Re-enable only by user order.
# traders
Launch "multi_trader"            "multi_trader.py --loop"       $MT5
Launch "btc_live"                "btc_live.py --loop"           $MT5
Launch "coordinator"             "coordinator.py --loop"        $MT5
# chart dashboard
Launch "dashboard :8866"         "algory_chart_dashboard.py"    $MT5
# research / self-learning loops
Launch "market_data_collector"  "market_data_collector.py --loop" $V2
Launch "paper_prover"            "paper_prover.py --loop"          $V2
Launch "accuracy_updater"        "accuracy_updater.py --loop"      $V2
Launch "reoptimize_loop"         "_reoptimize_loop.py"             $V2
Launch "secure_learner"          "secure_learner.py --loop"        $MT5
Launch "intermarket brain"       "intermarket.py --loop"           $MT5
Launch "news engine"             "news_engine.py --loop"           $MT5
Launch "llm analyst"             "llm_analyst.py --loop"           $MT5
Launch "genome evo logger"       "genome_evo_logger.py --loop"     $MT5
Launch "truth tracker"           "truth_tracker.py --loop"         $MT5
Launch "risk manager (ICA)"      "risk_manager.py"                 $MT5
Launch "straddle hunter"         "straddle_hunter.py"              $MT5
Launch "evolution director"      "evolution_director.py"           $MT5
Launch "gene tournament"         "gene_tournament.py"              $MT5
Launch "zone memory"             "zone_memory.py"                  $MT5
Launch "gene ledger (skills)"    "gene_ledger.py"                  $MT5
Launch "delta feed (سياق)"       "delta_feed.py"                   $MT5
Launch "news gene (سلالم)"       "news_gene.py"                    $MT5
Launch "brain animation :8870"  "brain_animation.py"            $MT5
Launch "chart_signal_writer"     "-m runtime.chart_signal_writer --loop" $V2
Launch "plutobrain swarm"        "-m plutobrain_swarm.orchestrator" $MT5
Launch "graph brain (graphify)"  "graph_brain.py"                 $MT5
Launch "tick websocket :8765"    "tick_ws.py"                     $MT5
Launch "WAR ROOM :8888"          "war_room.py"                    $MT5
Launch "macro feed (مجاني)"      "macro_feed.py"                  $MT5
Launch "ORB trader"              "orb_trader.py"                  $MT5
Launch "vol forecast (GARCH)"    "vol_forecast.py"                $MT5
Launch "market internals"        "market_internals.py"            $MT5
Launch "forecast lab"            "forecast_lab.py"                $MT5
Launch "tape recorder"           "tape_recorder.py"               $MT5
Launch "ml indicator"            "ml_indicator.py --symbols XAUUSDm,BTCUSDm,US30m --tf M15" $MT5
Launch "watchdog (never-stop)"   "watchdog_guard.py"             $MT5
Write-Output "=== done — all components launched (persistent) ==="
