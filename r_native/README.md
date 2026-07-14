# R Native — Self-Learning Genetic Trading System

A PySide6 desktop app that evolves trading strategies via genetic algorithms,
backtests them on real MT5 data, and executes them via the broker's terminal.
Inspired by — but independent from — Algory.exe.

**Magic number**: `20260605`  ·  **Default mode**: PAPER (no real orders)
**Repo**: https://github.com/radhi88/r-native.git

---

## What it does

1. **Evolves strategies** — multi-tribe genetic algorithm (PG → Tribe A/B → War → Revival → Retrain)
   over a 49-gene catalog (signals · biases · filters · execution · management).
2. **Backtests** every genome on real MT5 bar data (no broker calls).
3. **Persists** the top 2000 strategies per symbol in a deployable vault.
4. **Executes** one deployed strategy per symbol via `r_executor.py` daemon.
5. **Learns** — per-combo gene fitness tracker keeps wins/fails/OOS-pass rates
   across all campaigns, so the engine biases mutation toward proven winners.

---

## Folder layout

```
r_native/
├── app.py                 # PySide6 main window (Hero card, Vault, Inspector, etc)
├── genetic_engine.py      # Multi-tribe GA orchestrator
├── ga_simulator.py        # Pure-numpy backtest engine (trades_log + equity_curve)
├── genes.py               # 49-gene catalog + Genome class + purge logic
├── scanner.py             # Multi-symbol opportunity scanner
├── actions.py             # Deploy/close/optimize helpers
├── inspector.py           # Inspector panel (STATS · SCORE · CLASS · GENOME · EQUITY · TRADES)
├── panels.py              # Center-stack panels (NEW CAMPAIGN · ADVANCED · GENE POOL)
├── dna_widget.py          # DNA helix visualization
├── equity_widget.py       # Mini equity sparkline
├── symbol_learning.py     # Per-symbol meta-learning (gate, blacklist, etc)
├── run_real_campaign.py   # CLI: run one campaign without UI
├── test_campaign.py       # Smoke test for the engine
│
├── heartbeat_server.py    # H.1 — Worker heartbeat HTTP server (:7711)
├── bar_cache.py           # H.4 — LRU bar cache for MT5 fetches
├── combo_fitness.py       # H.14 — Per-combo gene fitness DB (Algory-style)
├── prop_firm.py           # H.12 — FTMO-ready compliance gates
├── asset_classes.py       # H.13 — Per-asset-class slippage/spread/leverage
├── smart_modes.py         # H.16 — Auto-tune bars/trades/OOS + power throttle
├── force_genes.py         # H.15 — Override management genes globally
├── sessions.py            # H.18 — Trading session presets (TO/LO/NYO/Tokyo/London/NY)
├── build_exe.py           # PyInstaller: single-EXE or --two-exe (Launcher + Worker)
│
├── launcher_module/       # H.2 — RNativeLauncher (tray + supervisor)
├── assets/                # Icons (r_logo.svg/ico/png)
├── dashboard/             # Web dashboard HTML (loaded by brain_server)
├── docs/                  # Architecture · ROADMAP · Algory feature audit
└── build_scripts/         # PyInstaller .spec files
```

---

## Running

### From source
```powershell
# Install deps (PySide6, MetaTrader5, flask, psutil, numpy)
pip install PySide6 MetaTrader5 flask psutil numpy

# Run the worker only (legacy)
python -m r_native.app

# Run via the launcher (supervised + auto-restart)
python -m r_native.launcher_module.launcher
```

### Building a standalone .exe
```powershell
# Single-EXE
python r_native\build_exe.py

# Two-EXE (Launcher + Worker share one _internal/)
python r_native\build_exe.py --two-exe
```

Output: `dist/RNative/RNative.exe` (single) or `dist/RNative/RNativeLauncher.exe`
+ `dist/RNative/RNativeWorker.exe` (two-exe).

---

## Phase progress (where we are)

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full continuous-evolution plan.

| Phase | Title | Status |
|---|---|---|
| H.1–H.6 | Launcher + Worker architecture (heartbeat, RSS watchdog, control RPC, two-EXE) | ✅ |
| H.7.1–H.7.7 | Inspector + Engine + Trade Gate integrate the deployed genome | ✅ |
| H.8.0–H.8.6 | Living dashboard (Hero card, live activity, gate status, tray notifications, backtest replay) | ✅ |
| H.9 | Modern UI overhaul (Linear/Vercel palette + Inter font) | ✅ |
| H.10 | Algory-comfort layout (slim hero strip, flat inspector tabs) | ✅ |
| H.11 | Algory feature audit ([`docs/ALGORY_FEATURE_AUDIT.md`](docs/ALGORY_FEATURE_AUDIT.md)) | ✅ |
| H.12 | Prop firm compliance suite (FTMO/MFF) | ✅ |
| H.13 | Asset expansion (18 symbols + per-class fees) | ✅ |
| H.14 | Per-combo gene learning (the secret sauce) | ✅ |
| H.15 | H2 timeframe + force genes | ✅ |
| H.16 | Smart modes (auto_bars/trades/oos + power) | ✅ |
| H.17 | Vault table filters (Market / Performance) | ✅ |
| H.18 | Session lock presets | ✅ |
| H.8.4 | Symbol status heatmap | pending |

---

## Safety

- **DRY_RUN** + **kill_switch.txt** + **paper mode** are the default safeties.
- Daily loss cap: `$10` (configurable in `data/r_native/settings.json`).
- Max concurrent positions: `3`.
- All trades use magic `20260605` — segregated from other EAs on the same account.

**To kill all R activity immediately**: create file `C:\Users\Radhi\MT5\kill_switch.txt`.

---

## Configuration files (auto-created on first use)

`data/r_native/`:
- `settings.json` — executor lot size, position cap, daily cap, magic
- `combo_fitness.json` — gene combo wins/fails (H.14)
- `prop_firm.json` — FTMO-style rules (H.12)
- `smart_modes.json` — auto-tune toggles (H.16)
- `force_genes.json` — management gene overrides (H.15)
- `symbol_configs/<SYMBOL>.json` — per-symbol deployed genome + vault
- `campaigns/<CAMP>/vault.json` — full output of each GA campaign

---

## License & attribution

This project is independent. Inspired by Algory's UX patterns and feature set,
but built from scratch (see `docs/ALGORY_FEATURE_AUDIT.md` for what was studied).
No reverse engineering of any binary was performed.
