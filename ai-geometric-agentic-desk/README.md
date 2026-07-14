# AI Geometric Agentic Desk

A self-contained, multi-agent MetaTrader 5 trading ecosystem built on the
geometric/SMC/ML stack from the spec: **Micro-Equity survival calculus
(modified Kelly + ATR stops + fractional sizing), Gann Square-of-9 & Gann
angles, Williams fractals, Smart Money Concepts, and a small honest ML vote**,
fused through a confluence matrix and gated by a walk-forward exam.

It runs live on a **DEMO** account out of the box. Execution is hard-guarded:
demo-only, mandatory stop-loss, no martingale/averaging/reversing, a per-trade
and daily-loss ceiling, and the `$10` survival rule that refuses any trade
whose minimum lot risks more than 15% of equity.

## Honest preface (read this)

This project's own out-of-sample research has repeatedly found the prediction
side of this stack to be **NO_EDGE net of cost** — SMC, fractals, and ML
direction all ~random once spread is paid; the one confirmed edge is
**discipline + sizing**. This desk is therefore built so the *risk engine* is
the load-bearing part and the *geometry* is measured, not blindly trusted. The
walk-forward exam exists to keep an overfit model from ever reaching the
account. See the project memory for the full NO_EDGE record.

## Layout

```
ai-geometric-agentic-desk/
  config.py              Safety flags, micro-equity params, per-market profiles
  core/
    micro_equity.py      Modified Kelly, ATR stop, survival-sized volume
    gann.py              Square of 9 + Gann-angle fans
    fractals.py          Williams fractals (right-confirmed, causal)
    smc.py               BOS / CHoCH / OB / FVG / liquidity sweep
    ml_signal.py         Dependency-free logistic next-bar vote
    confluence.py        The trade-or-pass confluence matrix
    charts.py            Annotated geometric chart artist (PNG)
  data/
    db.py                Per-market SQLite (enterprise schema + audit BLOB)
  agents/
    broker.py            MT5 IO + demo guard + guarded order_send
    desk_agents.py       MarketData / Analysis / Risk / Chart / Execution / HRExam
  exam/
    backtest.py          Walk-forward exam, net of spread, 0–100 score
  orchestrator.py        The Infinite Geometric Loop + exam gate + daily halt
  run.py                 Entry point (selftest / once / loop)
```

## Run it

```bash
# Offline — full pipeline on synthetic data, never touches a broker:
python run.py --selftest

# One live demo-guarded cycle:
python run.py --once --symbols XAUUSDm BTCUSDm --tf M5

# The infinite loop (Ctrl-C to stop):
python run.py --symbols XAUUSDm BTCUSDm EURUSDm --tf M5 --interval 60
```

## Safety contract (`config.py`)

| Flag | Default | Meaning |
|------|---------|---------|
| `LIVE_TRADING` | `False` | Real-money execution master switch |
| `DEMO_ONLY` | `True` | Refuse orders unless the account server is a Trial/Demo |
| `EXEC_MAGIC` | `20260626` | Tags every order from this desk |
| `MAX_RISK_PER_TRADE` | `0.05` | 5% per-trade ceiling |
| `MAX_DAILY_LOSS` | `0.10` | 10% daily drawdown halt |
| `KELLY_CAP` | `0.15` | Hard `f*` ceiling |
| `SURVIVAL_REJECT_RISK` | `0.15` | Reject if min-lot risk exceeds this |
| `MIN_CONFLUENCES` | `3` | Trade only when ≥3 signals align |
| `ML_CONFIDENCE_GATE` | `0.70` | …and ML confidence > 70% |
| `REQUIRE_EXAM_PASS` | `False` | `True` = no live trade until exam ≥95 & PF≥2.5; `False` = forward-test live on demo, let reality judge |

## The exam gate

`exam/backtest.py` replays the entire pipeline bar-by-bar with **no
look-ahead** (the ML model only ever trains on past bars), resolves each trade
to its real forward outcome, subtracts an estimated round-trip spread, and
folds the result across walk-forward blocks. The 0–100 score rewards profit
factor toward 2.5, positive expectancy, sample size, and cross-fold
consistency. With `REQUIRE_EXAM_PASS=True`, nothing deploys until the geometry
pays net of cost — which, given the research record, is the point.

## Markets

Per-market profiles live in `config.PROFILES`: Gold (ATR×2, London+NY,
Sq9 360°), Forex (SMC+OB+FVG, Sq9 90/180), Indices (BOS+CHoCH+1×1), Crypto
(24/7 fractal/VP), Stocks (OB+daily FVG). Symbols route to a class via
`config.classify`.
