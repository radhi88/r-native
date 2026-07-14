# FRIDAY System Status — 2026-05-19 (checked now)

## Services

| Service | Port | Status | Notes |
|---------|------|--------|-------|
| Ollama | 11434 | ❌ DOWN | Connection refused (exit 7) |
| EA Monitor | 7799 | ❌ DOWN | Connection refused (exit 7) |
| Arena (Vite) | 5173 | ❌ DOWN | Connection refused (exit 7) |
| FRIDAY Gateway | 8799 | ❌ DOWN | Connection refused (exit 7) |
| FRIDAY Chat | 8811 | ❌ DOWN | Connection refused (exit 7) |
| AI Dashboard | 8790 | ❌ DOWN | Connection refused (exit 7) |
| Desktop Agent | 8855 | ❌ DOWN | Connection refused (exit 7) |

> **All 7 services are offline.** Last known-good state: 2026-05-15 (4 days ago).

---

## MT5 Files

| File | Status | Notes |
|------|--------|-------|
| `ea_realtime_status.json` | ❌ NOT FOUND | EA is not writing live telemetry — Strategy Tester likely not running |
| `ea_dna_state.json` | ❌ NOT FOUND | No DNA state file present |
| `dashboard/qader_live_state.json` | ✅ EXISTS (stale) | Last update: 2026-05-15T20:59:51 UTC — cycle 854, state=RUNNING, 16 demo trades |
| `.friday_loop_state.json` | ✅ EXISTS (stale) | Last run: 2026-05-05T01:16:00 — closed 6 DANGER positions |
| `dashboard/agents_state.json` | ✅ EXISTS (stale) | Last updated: 2026-05-15T00:00:00 |
| `friday_live_brain_state.json` | ✅ EXISTS (stale) | Last modified: 2026-05-15 |
| `friday_best_ea_code.json` | ✅ EXISTS | Last modified: 2026-05-18 (most recent) |

### Last Known Qader State (2026-05-15)
- Loop state: **RUNNING** | Cycle: 854
- Symbol: XAUUSDm | Timeframe: M1
- Last signal: **HOLD** — blocked by `structure_without_entry_confirmation`
- Demo trades opened: 16 | Allow new entries: true
- Spread at last check: 308 pips (wide, ratio 0.88 of 350 limit)

### Last Known MT5 State (2026-05-15)
- Server: Exness-MT5Trial15 | Login: 260749517 (DEMO/TRIAL)
- Open positions: 0 | Pending orders: 1
- MT5 status: **BLOCKED**

---

## Recommendations

1. **Start all services** — Run `start_friday_all.ps1` or `start_friday_trading_full.ps1` to bring up the full stack.
2. **Ollama must come first** — Gateway and Chat depend on Ollama being live on port 11434.
3. **No live EA telemetry** — `ea_realtime_status.json` is missing. MT5 terminal may need to be opened and the EA attached to a chart for real-time data to flow.
4. **Strategy Tester not running** — No `ea_dna_state.json` indicates Strategy Tester is idle. Run via `run_backtest.bat` or MT5 manually if needed.
5. **Stale state files** — All JSON state files are 4+ days old (last: May 15). Services need to be restarted to produce fresh data.
6. **Arena / Dashboard** — Port 5173 (Vite dev server) is down. Run `npm run dev` from the MT5 project root to bring Arena back online.

---

*Report generated: 2026-05-19 | Checked by Agent STATUS*
