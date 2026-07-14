# Goals

> Trading AI mission targets. Claude reads this every session. Update as goals shift. Be specific — vague goals produce vague advice.

---

## 1-year horizon (by 2027-05-21)

### Wealth / Trading
- FRIDAY live on XAUUSDm M1 with verified positive expectancy over 3 months of paper trading first
- Profitable enough to cover costs (VPS, API, data feeds) from trading revenue
- Risk per trade: max 1% of account per signal, automated

### System (FRIDAY) milestones
- Complete 18-phase architecture refactor (currently at Phase 2)
- Stop-loss on entry: implemented and tested — fix the known open bug
- Kill-switch: fully enforced (not just in config)
- LIVE_TRADING_ENABLED: only activated after paper trading validation
- Local AI assistant (Ollama/llama.cpp) responding to market queries in <500ms
- Semantic trade log: search past trades by pattern via sentence-transformers

### AI / ML
- Keras NN retrained monthly from live trade outcomes
- Gene learning loop: active and updating signal weights
- Algory factory: producing consistent signal inputs

### Knowledge
- Vault holds structured research on: SMC, fractal theory, NN architectures for time-series, MT5 automation

---

## 3-year horizon (by 2029)

- FRIDAY running live with positive Sharpe ratio (>1.0) over 12 rolling months
- Expanded to 5+ pairs beyond XAUUSDm
- System self-improving: retrains on outcomes without manual intervention
- Income from trading covers full living expenses
- AI assistant integrated directly into MT5 decision flow via ZeroMQ pipeline
- Published knowledge base of SMC + fractal + AI trading approach

---

## 10-year horizon

- Full trading automation — system runs with minimal daily intervention
- Known in Arabic/English AI trading space for FRIDAY methodology
- Possible: expand into fund/proprietary trading if track record established
- Financial independence from trading + AI consulting/products

---

## Gating conditions

- **LIVE_TRADING_ENABLED = True** — gate on: paper trading > 500 trades with positive expectancy + SL bug fixed + kill-switch enforced
- **Expanding to new pairs** — gate on: XAUUSDm stable + Phase 2 architecture complete
- **Gene learning in production** — gate on: backtester validated on at least 6 months of historical data

---

## ARCHIVE — completed goals

- [x] 2026-05-21 — Algory factory replicated into FRIDAY (9 files, running)
- [x] 2026-05-21 — Fractal engine complete (all phases, live monitor on 40 pairs)
- [x] 2026-05-21 — Architecture refactor Phase 0+1 done (7 reports, archive created)
- [x] 2026-05-21 — ALGORY_MAGIC = 20260600 added
