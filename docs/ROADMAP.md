# R Factory — Continuous Evolution Roadmap

> Each item is a self-contained improvement. The scheduled task picks the next
> unchecked item every 15 minutes, implements it, verifies, and ticks the box.

## ⚙ Format
```
- [ ] PRIORITY · CATEGORY · TITLE
      WHY: one-line rationale
      DOD: definition of done (testable)
      EST: rough minutes
```

---

## 🎯 PHASE A — Stability & Visibility (Foundation)

- [x] P1 · UI · Embed live position symbol pill in /r/ executor panel
- [x] P1 · UI · Account snapshot KPIs at top of /r/
- [x] P1 · UI · Recent trades table from broker history
- [x] P1 · GATE · Multi-TF direction consensus + RSI sanity
- [x] P1 · GATE · Real price levels (PDH/VWAP/FVG/swings) for SL/TP
- [x] P1 · EXEC · Trailing SL + multi-position (max 3)
- [x] P1 · LEARN · Per-archetype stats + manual override detection
- [x] P1 · MULTI · Symbol scanner + blacklist/whitelist
- [x] P1 · TRAIN · Offline replay with simulated archetypes
- [x] P1 · APP · Desktop .exe shell (PySide6 + webview)
- [x] P1 · DASH · R_Analytics_Dashboard.html (full performance dashboard)

- [x] P2 · UI · Add per-symbol mini-chart in symbol scanner row (sparkline last 24h)
      WHY: visual context for each candidate
      DOD: each row shows 30-bar sparkline; updates with scanner
      EST: 30 min

- [x] P2 · UI · Live equity curve panel on /r/ (last 24h, updates every 10s)
      WHY: see balance evolution at a glance
      DOD: chart.js line chart, color-coded segments (green/red)
      EST: 25 min

- [ ] P2 · GATE · Add ADX trend strength to direction check
      WHY: avoid trading in pure chop even when bias agrees
      DOD: gate refuses if ADX < 20 on H1
      EST: 20 min

---

## 🧠 PHASE B — Intelligence Enhancements

- [ ] P1 · LEARN · Save winning trade contexts for pattern matching
      WHY: detect "this setup looks like 5 winners last week"
      DOD: trades.jsonl gets context fingerprint; matcher finds similar
      EST: 60 min

- [ ] P2 · LEARN · Per-hour-of-day quality score per symbol
      WHY: only trade BTC at 02-06 UTC if that's where it wins
      DOD: symbol_book includes hours_pass_rate; gate respects it
      EST: 40 min

- [ ] P2 · GATE · News blackout window using FF calendar (±15 min around High)
      WHY: avoid getting whipsawed
      DOD: gate adds news_blackout hard check (use existing news_straddle parser)
      EST: 30 min

- [ ] P1 · SMC · Detect liquidity sweeps (recent high/low taken then reversal)
      WHY: classic SMC trigger for entries
      DOD: r_levels exposes sweep_above / sweep_below booleans
      EST: 45 min

- [ ] P2 · SMC · Order Block detection (last bullish before drop, bearish before rally)
      WHY: precision SL placement
      DOD: r_levels.OB_bull / OB_bear with mitigation status
      EST: 50 min

---

## 🎨 PHASE C — Visualization & UX

- [ ] P1 · CHART · Embed Lightweight Charts on /r/ with R's entries marked
      WHY: see what R sees in real time
      DOD: candle chart for current symbol with markers for SL/TP/entry
      EST: 60 min

- [ ] P2 · UI · "Why?" button on each trade — opens modal with full reasoning
      WHY: trust + learning
      DOD: modal shows snapshot, gate verdict, archetype, all 10 checks
      EST: 40 min

- [ ] P2 · UI · Heatmap — best hour × best symbol grid
      WHY: surface time-symbol patterns
      DOD: 24×N grid colored by net_pl, click to drill
      EST: 35 min

- [ ] P2 · UI · Side-by-side: R's gate verdict vs Algory's latest matching strategy
      WHY: cross-validation
      DOD: panel shows both opinions for current setup
      EST: 30 min

---

## 🔌 PHASE D — Integration & Distribution

- [ ] P1 · MCP · Setup FastMCP properly + register tools with Claude Desktop
      WHY: I (Claude) can query/control R directly
      DOD: claude_desktop_config.json updated, tools visible
      EST: 30 min

- [ ] P2 · APP · PyInstaller build → working dist/RFactory/RFactory.exe
      WHY: standalone install
      DOD: .exe runs on clean machine with MT5 installed
      EST: 30 min

- [ ] P3 · ALERT · Telegram bot for trade open/close + daily summary
      WHY: mobile notifications
      DOD: bot sends formatted messages on each R trade event
      EST: 45 min

- [ ] P3 · ALERT · Voice alerts (TTS) for major events (TP hit, freeze, BE+)
      WHY: ambient awareness
      DOD: pyttsx3 announces critical events
      EST: 25 min

---

## 🧪 PHASE E — Validation & Backtest

- [ ] P1 · BACKTEST · Replay historical data through R's full gate logic
      WHY: prove the rules work before live
      DOD: r_backtest.py runs 30 days, reports WR/PF/DD with same rules
      EST: 90 min

- [ ] P2 · BACKTEST · Walk-forward optimization on adjustments
      WHY: prevent overfitting
      DOD: 70/30 split per period, only adapt on IS, measure OOS
      EST: 60 min

- [ ] P2 · MONITOR · Slippage tracking — actual fills vs intended price
      WHY: detect broker quality degradation
      DOD: r_executor logs slip on each order, dashboard shows avg
      EST: 25 min

---

## 🤖 PHASE F — Autonomy & Self-Evolution

- [ ] P1 · GENESIS · R's own genetic factory (not just consuming Algory's)
      WHY: generate strategies R OWNS and trains
      DOD: r_genesis.py evolves genome over 50 generations on backtest data
      EST: 120 min

- [ ] P2 · LEARN · LLM commentary on each closed trade ("why won / why lost")
      WHY: human-readable post-mortems
      DOD: each closed trade gets 2-line analysis in journal
      EST: 40 min

- [ ] P2 · ADAPT · Auto-tune lot size based on Kelly criterion + recent WR
      WHY: scale winners, shrink losers
      DOD: r_executor computes lot per archetype + per symbol from Kelly
      EST: 50 min

- [ ] P3 · ADAPT · Detect regime shift (volatility regime change) → switch archetype
      WHY: BREAKOUT_HUNTER fails in chop, MEAN_REVERTER fails in trend
      DOD: regime classifier feeds gate → preferred archetype
      EST: 60 min

---

## 📦 PHASE G — Professional Polish

- [ ] P2 · DOCS · One-page user manual PDF (how to install + run + safety)
- [ ] P2 · LOG · Daily report email/file (P/L, trades, lessons learned)
- [ ] P3 · I18N · English UI toggle
- [ ] P3 · MULTI-ACCOUNT · Support trading multiple accounts in parallel
- [ ] P3 · SECURITY · Encrypt sensitive data in r_learning/

---

## 🏗️ PHASE H — Launcher + Worker Architecture (Algory-style)

> Full spec: [ARCHITECTURE_LAUNCHER_WORKER.md](ARCHITECTURE_LAUNCHER_WORKER.md)
> Motivation: R Native current monolith = 1329 MB; Algory.exe (parent + worker) = 184 MB.
> Target: 1.3 GB → 280 MB (~4.5× reduction) + crash-resilience.

- [ ] P1 · ARCH · Worker heartbeat server on `127.0.0.1:7711`
      WHY: launcher needs a way to detect worker health
      DOD: Flask daemon thread in `r_native/app.py`; `curl /heartbeat` returns ok+uptime+ram
      EST: 45 min

- [ ] P1 · ARCH · RNativeLauncher skeleton (tray + status window + subprocess.Popen)
      WHY: small always-on supervisor that spawns and monitors the worker
      DOD: `r_native_launcher/launcher.py` (~400 lines); tray icon, restart-on-death works
      EST: 90 min

- [ ] P1 · BUILD · Two-EXE PyInstaller setup
      WHY: ship `RNativeLauncher.exe` + `RNativeWorker.exe` sharing one `_internal/`
      DOD: single `.spec` file with two EXE blocks; folder size unchanged
      EST: 60 min

- [ ] P1 · MEMORY · Worker cleanup after GA campaign + LRU bar cache
      WHY: prevent the 1.3 GB accumulation; vault persisted to disk not RAM
      DOD: post-campaign `vault=[]; gc.collect()`; MT5 bar cache LRU-evicts to 5 symbols
      EST: 50 min

- [ ] P2 · ARCH · Worker auto-restart at 500MB RSS threshold
      WHY: belt-and-suspenders for any memory leaks not caught by cleanup
      DOD: worker self-terminates via `POST /shutdown`; launcher detects + respawns
      EST: 30 min

- [ ] P2 · ARCH · Launcher control RPC (restart-worker / kill-worker from tray menu)
      WHY: user can force-restart without losing launcher state
      DOD: tray menu items wired to TCP commands; works without UI freeze
      EST: 40 min

- [ ] P3 · ARCH · Hot-swap workers (atomic .exe.new replacement)
      WHY: zero-touch updates — drop new worker.exe, launcher swaps it on next restart
      DOD: launcher checks for `.exe.new`, validates signature, swaps + restarts
      EST: 60 min

---

## 📈 Iteration Protocol (every 15 min)

1. **HEALTH CHECK**: query `/api/r/executor` → confirm armed + balance OK
2. **PICK**: read this file, find first `- [ ]` item by priority
3. **IMPLEMENT**: write code, follow DOD strictly
4. **VERIFY**: run a quick test (curl endpoint, eval HTML, query DB)
5. **CHECK BOX**: edit this file, change `[ ]` → `[x]`
6. **LOG**: append result + timestamp to `data/r_evolution_log.jsonl`
7. **HANDOFF**: short summary message
