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

- [x] P2 · GATE · Add ADX trend strength to direction check
      WHY: avoid trading in pure chop even when bias agrees
      DOD: gate refuses if ADX < 20 on H1
      EST: 20 min

- [x] P1 · EXEC · Sub-second position management (split-second reaction)
      WHY: user: "its response is very slow" / "كل جزء من الثانية أريده" — old loop
           managed open positions only every 30s, so trailing/exits reacted a
           third of an M1 candle late on fast gold moves
      DOD: r_executor two-speed loop — manage (reconcile+trail+freeze) every 0.5s
           (configurable float --manage-interval), entry gate-scan still 30s
           (faster entry is NOT an edge: explosion_ride study), state write
           throttled to ~2s + forced on close/scan/freeze. Verified: 120 mgmt
           ticks/min vs old 2, syntax + timing-logic tests pass
      EST: 25 min

---

## 🧠 PHASE B — Intelligence Enhancements

- [x] P1 · LEARN · Save winning trade contexts for pattern matching
      WHY: detect "this setup looks like 5 winners last week"
      DOD: trades.jsonl gets context fingerprint; matcher finds similar
      EST: 60 min

- [x] P2 · LEARN · Per-hour-of-day quality score per symbol
      WHY: only trade BTC at 02-06 UTC if that's where it wins
      DOD: symbol_book includes hours_pass_rate; gate respects it
      DONE: r_multi_symbol.record_symbol_trade(...,hour_utc) buckets per-hour
            trades/wins/net + rebuilds rec.hours_pass_rate; new hour_quality()
            returns GOOD/NEUTRAL/BAD (TIGHTEN-ONLY: BAD only when >=4 trades AND
            WR<30% AND net<-$1, else fail-open NEUTRAL). r_executor passes the
            position's UTC entry hour. trade_gate adds symbol_hour_quality check
            that HARD-blocks a proven-bad hour, SOFT otherwise. Test: 5-loss
            03h→BAD, sparse/empty/winning→NEUTRAL, back-compat call OK.
      EST: 40 min

- [x] P2 · GATE · News blackout window using FF calendar (±15 min around High)
      WHY: avoid getting whipsawed
      DOD: gate adds news_blackout hard check (use existing news_straddle parser)
      DONE: full chain verified live 2026-07-07 — trade_gate.evaluate_gate has the
            not_in_news_blackout HARD check (impact=="High", ±15min via
            news_straddle.parse_event_time which handles both ISO8601 offset +
            legacy FF split-field formats); brain_server /api/r/trade_gate feeds it
            fresh via _load_news_events_fresh() (self-heals stale FF calendar,
            30-min throttle); r_executor pulls that endpoint and honors the verdict.
            Synthetic test: High +5min→HARD BLOCK, High +40min→clear, Low +5min→
            clear, no-events→clear. Live gate curl shows the check present ("clear").
      EST: 30 min

- [x] P1 · SMC · Detect liquidity sweeps (recent high/low taken then reversal)
      WHY: classic SMC trigger for entries
      DOD: r_levels exposes sweep_above / sweep_below booleans
      DONE: r_levels.detect_liquidity_sweeps(symbol) + pure _scan_sweeps(bars)
            helper. A sweep = confirmed swing high/low pierced intra-bar in the
            last N candles but price closes back inside with a rejection wick
            ≥30% of bar range (stop-hunt). sweep_above (swing high taken then
            rejected → BEARISH) / sweep_below (swing low taken → BULLISH), plus
            swept level price + bars_ago. Wired into compute_all_levels output
            (top-level sweep_above/sweep_below bools + full sweeps dict).
            Verified offline: 11/11 synthetic assertions pass (bull sweep, bear
            sweep, breakout-is-NOT-sweep, insufficient-bars, flat-market).
      EST: 45 min

- [x] P2 · SMC · Order Block detection (last bullish before drop, bearish before rally)
      WHY: precision SL placement
      DOD: r_levels.OB_bull / OB_bear with mitigation status
      DONE: r_levels._scan_order_blocks(bars) pure scanner + detect_order_blocks(symbol)
            on M15. OB = last opposite-colour candle before a displacement impulse
            (≥1.5×avg-range over next 3 bars AND engulfs the OB extreme, so noise is
            rejected). OB_bull=demand (last bearish before rally), OB_bear=supply
            (last bullish before drop); each returns {low,high,mid,bars_ago,mitigated}
            where mitigated=price has since traded back into the zone. Only the most
            recent block each side. Wired into compute_all_levels → top-level OB_bull/
            OB_bear + full order_blocks dict. Verified: 16/16 offline synthetic
            assertions (bull, bear, mitigation, chop→none, insufficient, None) + live
            MT5 on XAU/BTC/EUR (real zones w/ mitigation flags). NOTE: running
            brain_server has old module cached → API exposes it on next restart.
      EST: 50 min

- [x] P1 · MATRIX · Full 21-indicator × 6-timeframe confluence (user request)
      WHY: user asked R to compute on the full FPU-MAX suite instead of ATR/RSI
           only — "خذها المؤشرات والموديلات وضيفها عندنا ونحسب عليها"
      DOD: R computes 21 indicators (EMA-stack, RSI, Stoch, MACD, CCI, MFI, ADX,
           DI, BB%B, W%R, ROC, ATR%, OBV, SuperTrend, Mom, SMA20/50, ROC-of-10)
           across M5/M15/H1/H4/D1/W1 → honest bull/bear confluence score
      DONE 2026-07-14: new friday_v3/algory/indicator_matrix.py — pure
           pandas/numpy port of the user's TradingView "FPU-MAX" Pine script.
           compute_panel() returns the 21-indicator panel per TF; score_panel()
           rolls 19 directional signals into a 0–100 confluence (ADX + ATR% are
           strength/context, not votes); build_matrix() aggregates across TFs
           with trend-alignment. Offline self-test PASSES (clean uptrend 89.5%
           BULL 17/19, downtrend 10.5% BEAR, short-bars guard, mixed-TF aggregate).
           New endpoint /api/r/indicator_matrix?symbol= (brain_server) feeds it
           bars from the shared alive mt5 handle (300 bars/TF, 30s cache — NO new
           mt5 connect, respects the IPC-flood lesson). New /r/ UI panel
           #matrix-panel renders the live 21×6 grid (▲/▼ + values, per-TF score,
           aggregate) on the 30s loop. VERIFIED live: XAUUSDm NEUTRAL 41.2
           (M15+H1 bull, H4/D1/W1 bear), USDCADm 23.7% BEAR 5/6 TFs, panel shows
           21 rows × 7 cols in-browser. NEXT: wire confluence as an advisory gate
           input (fail-open, TIGHTEN-ONLY) once it proves out.
      EST: 60 min

---

## 🎨 PHASE C — Visualization & UX

- [x] P1 · CHART · Embed Lightweight Charts on /r/ with R's entries marked
      WHY: see what R sees in real time
      DOD: candle chart for current symbol with markers for SL/TP/entry
      DONE 2026-07-14: fully implemented + live. r_factory_ui.html has #rchart-panel
            (Lightweight Charts standalone via CDN) — _ensureRChart()/renderRChart()
            draw a candlestick series for the auto-picked symbol (R's open position,
            else executor best_symbol_now) with a TF selector (M1..H1). R's live
            entry/SL/TP drawn as createPriceLine() overlays (3×: entry solid, SL/TP
            dashed) + arrowUp/arrowDown entry markers via setMarkers(), plus a legend
            line (side/entry/SL/TP/profit). Backed by /api/r/candles which returns
            {ok,symbol,tf,digits,candles,positions[ticket,type,entry,sl,tp,profit,
            time_open]} (12s candle cache, position overlay refreshed each call).
            Wired into the 10s refresh loop. VERIFIED live: curl /api/r/candles →
            ok=True symbol=USDCADm 150 candles digits=5 positions=[] (night-block, no
            open R pos); served /r/ contains #rchart-panel + renderRChart +
            3× createPriceLine + setMarkers.
      EST: 60 min

- [x] P2 · UI · "Why?" button on each trade — opens modal with full reasoning
      WHY: trust + learning
      DOD: modal shows snapshot, gate verdict, archetype, all 10 checks
      DONE 2026-07-14: each recent-trades row gets a "؟" button →
            showTradeWhy(ticket) opens #why-modal fetching new endpoint
            /api/r/trade_why/<ticket> (brain_server) which scans the per-genome
            decision_log for the OPEN (+matching CLOSE) record. Modal renders:
            header (ticket/side/symbol/archetype/confidence/lot/genome/ts),
            entry-SL-TP + exit/profit, ✅ signals_fired, 🧭 biases_aligned,
            ⛔ filters_blocking, and 📸 the H4/H1/M15 indicator snapshot
            (price/RSI/ATR/bias/slope) captured at entry. Graceful "no record"
            for manual/older trades. VERIFIED in-browser: showTradeWhy('1675910382')
            → modal display=flex, USDCHFm BUY GENOME conf73 1 signal 3 biases +
            indicator table. NOTE: fixed a PRE-EXISTING SyntaxError (duplicate
            `const totalPL` in refresh()) that was silently breaking the ENTIRE
            /r/ script — all panels now render.
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

- [x] P1 · ARCH · Worker heartbeat server on `127.0.0.1:7711`
      WHY: launcher needs a way to detect worker health
      DOD: Flask daemon thread in `r_native/app.py`; `curl /heartbeat` returns ok+uptime+ram
      EST: 45 min
      DONE 2026-07-13: already implemented as `r_native/heartbeat_server.py` (Flask daemon
      thread, loopback-only, GET /heartbeat + POST /shutdown + POST /restart, RSS watchdog)
      and wired into `r_native/app.py` main() behind try/except. Verified standalone:
      GET /heartbeat → {"ok":true,"pid":...,"ram_mb":40.4,"uptime_sec":2.1,"version":"1.1.0"}.
      Running R Native picks it up on next launch (no restart performed).

- [x] P1 · ARCH · RNativeLauncher skeleton (tray + status window + subprocess.Popen)
      WHY: small always-on supervisor that spawns and monitors the worker
      DOD: `r_native_launcher/launcher.py` (~400 lines); tray icon, restart-on-death works
      EST: 90 min
      DONE 2026-07-13: `r_native_launcher/launcher.py` (435 lines) rewritten to spec —
      config-driven (`launcher_config.json`: worker_cmd/heartbeat_url/poll_sec/
      restart_backoff_sec/max_restarts_per_hour), rotating `launcher.log` (~500KB),
      dead = process-exit OR 3× heartbeat miss OR wants_restart; kills own child tree
      only; exponential backoff capped at 6 restarts/hour then HALT+alert. Tray via
      pystray+Pillow (not installed → console fallback, no pip); tkinter status window
      (pid/uptime/ram/restarts/hb-age, 2s refresh, close=hide). CLI: --console,
      --dry-run (dummy sleep worker, health=process-alive). Refuses to double-spawn if
      a live worker already answers :7711. VERIFIED dry-run: dummy PID 5488 killed
      externally → detected "process exited" → respawned PID 29364 after 2s backoff →
      clean shutdown killed the tree (exit 0, no orphans).

- [x] P1 · BUILD · Two-EXE PyInstaller setup
      WHY: ship `RNativeLauncher.exe` + `RNativeWorker.exe` sharing one `_internal/`
      DOD: single `.spec` file with two EXE blocks; folder size unchanged
      DONE: build/r_native_two_exe.spec — two Analysis/EXE blocks merged into one
            COLLECT → dist/RNative/ (launcher console-subsystem, worker windowed).
            Size discipline: QtWebEngine excluded (~200MB, import sites try/except
            guarded), tf/keras/torch excluded (proven unused); sklearn/scipy kept
            (really imported). Result: 777MB (honest number — vs 1.3GB monolith
            ≈40% smaller; 280MB needs dropping sklearn/scipy/matplotlib later).
            Verified from frozen EXEs: launcher --help exit 0, --dry-run full
            spawn→RPC→clean-exit cycle, worker EXE boots to app layer and
            correctly detects external services without double-starting.
      EST: 60 min

- [x] P1 · MEMORY · Worker cleanup after GA campaign + LRU bar cache
      WHY: prevent the 1.3 GB accumulation; vault persisted to disk not RAM
      DOD: post-campaign `vault=[]; gc.collect()`; MT5 bar cache LRU-evicts to 5 symbols
      EST: 50 min
      DONE 2026-07-14: `r_native/bar_cache.py` = symbol-capped LRU (MAX_SYMBOLS=5,
      90s TTL) routed through scanner + GA pool workers; `CampaignWorker.run`
      clears `engine.vault=[]`/`elites=[]` post-persist; `_on_campaign_done`
      drops the QThread + `gc.collect()` + `shrink_to(5)`. Offline-verified
      (8 symbols → 5 remain, MRU order; fetch dedup; TTL). Twin note with full
      detail in r_native/docs/ROADMAP.md.

- [x] P2 · ARCH · Worker auto-restart at 500MB RSS threshold
      WHY: belt-and-suspenders for any memory leaks not caught by cleanup
      DOD: worker self-terminates via `POST /shutdown`; launcher detects + respawns
      EST: 30 min
      DONE 2026-07-14: env `R_NATIVE_RSS_LIMIT_MB` > settings.json `rss_limit_mb`
      > 500 default (`heartbeat_server.resolve_rss_limit_mb`); breach →
      `wants_restart=true` in /heartbeat → 60s grace → graceful Qt quit →
      `os._exit(0)` fallback. settings.json pinned to 1800 until the two-process
      split (monolith boots ~515MB). Offline-verified with injected fake RSS.
      Live process untouched — picks this up on next relaunch.

- [x] P2 · ARCH · Launcher control RPC (restart-worker / kill-worker from tray menu)
      WHY: user can force-restart without losing launcher state
      DOD: tray menu items wired to TCP commands; works without UI freeze
      EST: 40 min
      DONE 2026-07-14: line-JSON RPC on 127.0.0.1:7712 (`control_port` in
      launcher_config.json). Commands: status / restart-worker / kill-worker /
      swap-check / quit. Tray menu routes through the RPC (falls back to direct
      calls if bind fails); every request handled in its own thread — no UI
      freeze. External client: `python -m r_native_launcher.launcher --send CMD`
      prints the JSON response (exit 0/1). VERIFIED dry-run: --send status →
      JSON; --send restart-worker → kill PID 41036 + respawn PID 2832, launcher
      alive; --send quit → clean exit code 0.

- [x] P3 · ARCH · Hot-swap workers (atomic .exe.new replacement)
      WHY: zero-touch updates — drop new worker.exe, launcher swaps it on next restart
      DOD: launcher checks for `.exe.new`, validates signature, swaps + restarts
      EST: 60 min
      DONE 2026-07-14: `check_hot_swap()` runs before EVERY (re)spawn — if config
      `worker_exe` has sibling `<name>.exe.new`: validate (>1MB, size stable
      across 2 checks 1s apart) → current→`.bak` (latest only), `.new`→current,
      log HOT-SWAP OK. Module-mode (worker_exe="") skips. RPC `swap-check` +
      CLI `--test-swap [PATH]`. VERIFIED: fake 1.2MB exe + 1.5MB .new →
      swapped, .bak kept, .new gone; 100B .new REJECTED (<1MB).

---

## 📈 Iteration Protocol (every 15 min)

1. **HEALTH CHECK**: query `/api/r/executor` → confirm armed + balance OK
2. **PICK**: read this file, find first `- [ ]` item by priority
3. **IMPLEMENT**: write code, follow DOD strictly
4. **VERIFY**: run a quick test (curl endpoint, eval HTML, query DB)
5. **CHECK BOX**: edit this file, change `[ ]` → `[x]`
6. **LOG**: append result + timestamp to `data/r_evolution_log.jsonl`
7. **HANDOFF**: short summary message
