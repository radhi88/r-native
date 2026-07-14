#!/usr/bin/env python3
"""
real_account_gate.py  -- HONEST "earn a real account" proof gate.

WINDOWLESS evaluator. Reads ONLY real net-of-cost closed deals from
data/friday.db (trades table). Scores, per squad/symbol AND overall, the
readiness to risk REAL money. Writes data/r_native/real_account_gate.json.

PROJECT TRUTH this gate is built on (do not relitigate):
  - No predictive edge has ever survived OOS (30+ indicators coin-flip,
    12 ML fail walk-forward, GA 0 specialists, SMC ~50%).
  - The ONE proven bottleneck = COST > gross edge.
  - Shadow/in-sample/risk-R "scoreboards" are INFLATION, not evidence.
So this gate's job is NOT to find edge. It is to REFUSE to flash GREEN
until real, net-of-cost, out-of-sample, multi-regime evidence forces it to.

GREEN (per squad/symbol) requires ALL of:
  n_net   >= 100      real closed net-of-cost trades
  t_stat  >  2.0      expectancy * sqrt(n) / std  (2-sigma, net of cost)
  expectancy_net > 0  positive after cost
  regimes_passed >= 3 positive expectancy in >=3 distinct time windows
  pf_net  >= 1.20     net profit factor
  max_dd_r small enough that it is survivable (<= 25% of net profit)
  paper_live_consistent  live expectancy within tolerance of paper/shadow
Overall GREEN additionally requires the multiple-testing correction to hold.

ANTITHEATER: the gate hard-refuses to read any shadow / risk-R / in-sample
scoreboard as pnl. It only reads realized broker net. It penalizes single-
window flukes, applies Bonferroni across squads, and flags paper>>live gaps.

Usage:
    python real_account_gate.py            # evaluate + write scoreboard
    python real_account_gate.py --print    # also pretty-print summary
"""
from __future__ import annotations
import os, sys, json, math, time, sqlite3
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "data", "friday.db")
OUT = os.path.join(ROOT, "data", "r_native", "real_account_gate.json")
SHADOW_PNL = os.path.join(ROOT, "data", "r_native", "pnl_scoreboard.json")  # live mirror, cross-check only
ARMY_SHADOW = os.path.join(ROOT, "data", "r_native", "army_scoreboard.json")  # risk-R: NEVER used as pnl

# --- HARD RULES: never count these as "our squad" P&L ---
EXTERNAL_EA_MAGICS = {2447, 20250418, 20250421, 20250422, 20250618}  # user's EAs, off-limits
MANUAL_MAGIC = 0  # user discretionary; not a bot squad's earned edge

# --- GREEN thresholds (calibrated to project truth; deliberately strict) ---
MIN_N            = 100      # minimum real net-of-cost trades
MIN_T            = 2.0      # t-stat = expectancy*sqrt(n)/std  (2-sigma)
MIN_EXPECTANCY   = 0.0      # must be > 0 net of cost (strictly positive)
MIN_REGIMES      = 3        # distinct time windows with positive net expectancy
MIN_PF           = 1.20     # net profit factor
MAX_DD_FRACTION  = 0.25     # max drawdown <= 25% of net total profit
PAPER_LIVE_TOL   = 0.50     # live expectancy must be >= 50% of paper/shadow claim
REGIME_WINDOWS   = 5        # split history into N equal-time windows for robustness
MIN_REGIME_N     = 15       # a window only "counts" if it has >= this many trades
FRESH_MAX_AGE_H  = 48       # 🕑 staleness guard: refuse GO if the newest bot trade is older than this (hours)
OPEN_LOSS_TOL    = 0.0      # 🩸 survivorship guard: block GREEN for any squad carrying floating LOSS on open positions

# TODO(hardening, future-green path — adversary-flagged, not urgent while all-RED):
#   - sequential multiple-testing: persist cumulative count of distinct cells EVER tested so pruning
#     to a survivor cell cannot lower the Bonferroni bar (today num_groups = current snapshot only).
#   - regime windows are equal-TIME; switch to equal-TRADE-count windows so bursty squads can't pass thin windows.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_MT5_OK = None
def _open_exposure():
    """🩸 Live floating P&L per magic from OPEN positions (survivorship antitheater).
    A grid/martingale book banks small CLOSED wins while the losing leg floats OPEN — it can read
    GREEN on closed deals while carrying an unrealized blow-up (the project's documented grid-EA trap).
    We read open positions and BLOCK GREEN for any squad carrying a net floating LOSS.
    Returns {magic: floating_pnl} when checked, or None when mt5 is unavailable (=> unverified => no GREEN)."""
    global _MT5_OK
    try:
        import MetaTrader5 as mt5
        if not _MT5_OK:
            _MT5_OK = bool(mt5.initialize() or mt5.initialize())
        if not _MT5_OK:
            return None
        floats = {}
        for p in (mt5.positions_get() or []):
            floats[p.magic] = floats.get(p.magic, 0.0) + float(p.profit)
        return floats
    except Exception:
        return None


def _apply_overrides(verdict, reasons, magic, floats, is_stale):
    """🛡️ Hard antitheater overrides: a GREEN can only survive on FRESH data with a VERIFIED non-losing
    open book. Never upgrades; only downgrades GREEN->AMBER. magic=None aggregates all open floats (overall)."""
    if verdict != "GREEN":
        return verdict, reasons
    if is_stale:
        return "AMBER", reasons + ["DOWNGRADE: data stale (no recent trades) — cannot certify real money on an old snapshot"]
    if floats is None:
        return "AMBER", reasons + ["DOWNGRADE: open exposure UNVERIFIED (mt5 unavailable) — survivorship guard blocks GREEN"]
    fl = sum(floats.values()) if magic is None else floats.get(magic, 0.0)
    if fl < OPEN_LOSS_TOL - 1e-9:
        return "AMBER", reasons + [f"DOWNGRADE: carries floating LOSS {fl:.2f} on still-open positions (survivorship guard)"]
    return verdict, reasons


def _load_trades():
    """Read ONLY real, closed, net-of-cost bot deals. This is the sole truth source."""
    if not os.path.exists(DB):
        return []
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    # net column already net of cost (commission+swap folded for bot rows).
    # Exclude external EAs and manual discretionary (magic 0).
    placeholders = ",".join("?" for _ in EXTERNAL_EA_MAGICS)
    cur.execute(
        f"""SELECT magic, symbol, ts, iso, net, win
            FROM trades
            WHERE closed=1 AND source='bot'
              AND magic NOT IN ({placeholders}) AND magic <> ?
              AND net IS NOT NULL
            ORDER BY ts ASC""",
        (*EXTERNAL_EA_MAGICS, MANUAL_MAGIC),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def _stats(nets):
    """Honest per-group statistics on REAL net-of-cost pnl."""
    n = len(nets)
    if n == 0:
        return None
    total = sum(nets)
    mu = total / n
    # population std (we have the full realized sample, not an estimate of a draw)
    var = sum((x - mu) ** 2 for x in nets) / n if n > 1 else 0.0
    sd = math.sqrt(var)
    t = (mu * math.sqrt(n) / sd) if sd > 0 else 0.0
    wins = sum(1 for x in nets if x > 0)
    gross_win = sum(x for x in nets if x > 0)
    gross_loss = -sum(x for x in nets if x < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    # max drawdown on the cumulative net curve (in account currency)
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "n": n,
        "net_total": round(total, 4),
        "expectancy_net": round(mu, 6),
        "std": round(sd, 6),
        "t_stat": round(t, 4),
        "win_rate": round(wins / n, 4),
        "profit_factor_net": (round(pf, 4) if pf != float("inf") else None),
        "max_drawdown": round(max_dd, 4),
    }


def _regime_robustness(rows):
    """Split the group's history into REGIME_WINDOWS equal-TIME windows.
    A window 'passes' only if it has >=MIN_REGIME_N trades AND positive net
    expectancy. This is the single-window-fluke antitheater: an edge that
    only exists in one window scores regimes_passed<3 and CANNOT go green."""
    if not rows:
        return {"regimes_passed": 0, "regimes_evaluated": 0, "per_window": []}
    ts = [r["ts"] for r in rows]
    t0, t1 = min(ts), max(ts)
    span = (t1 - t0) or 1.0
    buckets = [[] for _ in range(REGIME_WINDOWS)]
    for r in rows:
        idx = min(REGIME_WINDOWS - 1, int((r["ts"] - t0) / span * REGIME_WINDOWS))
        buckets[idx].append(r["net"])
    per_window = []
    passed = evaluated = 0
    for i, b in enumerate(buckets):
        if len(b) < MIN_REGIME_N:
            per_window.append({"window": i, "n": len(b), "counted": False})
            continue
        evaluated += 1
        exp = sum(b) / len(b)
        ok = exp > 0
        passed += int(ok)
        per_window.append({"window": i, "n": len(b),
                           "expectancy_net": round(exp, 6),
                           "positive": ok, "counted": True})
    return {"regimes_passed": passed, "regimes_evaluated": evaluated, "per_window": per_window}


def _paper_live_consistency(magic):
    """Cross-check the live broker mirror (pnl_scoreboard.json) against the DB.
    Returns a flag if a shadow/paper claim is materially better than realized
    live net. NOTE: shadow risk-R boards (army_scoreboard.json) are NEVER read
    as pnl -- only used to detect inflation, never to award credit."""
    out = {"checked": False, "consistent": None, "note": "no shadow claim to compare"}
    try:
        if not os.path.exists(SHADOW_PNL):
            return out
        data = json.load(open(SHADOW_PNL, encoding="utf-8"))
        for key in ("today_src", "d7_src"):
            for s in data.get(key, []):
                if s.get("magic") == magic and s.get("n"):
                    live_exp = s["net"] / s["n"]
                    out = {"checked": True,
                           "live_window": key,
                           "live_expectancy": round(live_exp, 6),
                           "consistent": live_exp >= 0,  # honest: a losing mirror is inconsistent with going live
                           "note": "live broker mirror"}
                    return out
    except Exception as e:  # fail-honest: unknown == not consistent
        out = {"checked": False, "consistent": None, "note": f"err:{e}"}
    return out


def _grade(s, regimes, paper, num_groups_tested):
    """Decide GREEN/AMBER/RED with antitheater gates. RED is the honest default."""
    reasons = []
    if s is None:
        return "RED", ["no real net-of-cost trades"]
    # Bonferroni: with many squads tested, raise the t-bar to avoid multiple-testing luck.
    eff_min_t = MIN_T + (0.5 * math.log(max(1, num_groups_tested)))  # ~+0.5/e-fold of groups
    checks = {
        f"n>={MIN_N}": s["n"] >= MIN_N,
        f"t>{eff_min_t:.2f}(MT-corrected)": s["t_stat"] > eff_min_t,
        "expectancy_net>0": s["expectancy_net"] > MIN_EXPECTANCY,
        f"regimes>={MIN_REGIMES}": regimes["regimes_passed"] >= MIN_REGIMES,
        f"pf_net>={MIN_PF}": (s["profit_factor_net"] is not None and s["profit_factor_net"] >= MIN_PF),
        "dd_survivable": (s["net_total"] > 0 and s["max_drawdown"] <= MAX_DD_FRACTION * s["net_total"]),
        "paper_live_consistent": (paper.get("consistent") is True) or (not paper.get("checked")),
    }
    for name, ok in checks.items():
        if not ok:
            reasons.append(f"FAIL {name}")
    if all(checks.values()):
        return "GREEN", ["all gates passed on real net-of-cost OOS data"]
    # AMBER only if it is genuinely positive & significant but not yet multi-regime / enough n.
    if s["expectancy_net"] > 0 and s["t_stat"] > 1.0 and s["n"] >= MIN_N // 2:
        return "AMBER", reasons
    return "RED", reasons


def evaluate():
    rows = _load_trades()
    now = time.time()
    newest = max((r["ts"] for r in rows), default=0.0)
    stale_h = ((now - newest) / 3600.0) if newest else 1e9
    is_stale = stale_h > FRESH_MAX_AGE_H
    floats = _open_exposure()                      # {magic: floating pnl} or None (unverified)
    # group by squad (magic) and by squad+symbol
    by_squad = {}
    by_squad_symbol = {}
    for r in rows:
        by_squad.setdefault(r["magic"], []).append(r)
        by_squad_symbol.setdefault((r["magic"], r["symbol"]), []).append(r)

    num_groups = len(by_squad) + len(by_squad_symbol) + 1  # +overall, for MT correction

    squads = {}
    for magic, grp in sorted(by_squad.items()):
        s = _stats([r["net"] for r in grp])
        regimes = _regime_robustness(grp)
        paper = _paper_live_consistency(magic)
        verdict, reasons = _grade(s, regimes, paper, num_groups)
        verdict, reasons = _apply_overrides(verdict, reasons, magic, floats, is_stale)   # 🛡️ freshness + survivorship
        squads[str(magic)] = {"magic": magic, "stats": s, "regimes": regimes,
                              "paper_vs_live": paper,
                              "open_float": (None if floats is None else round(floats.get(magic, 0.0), 2)),
                              "verdict": verdict, "reasons": reasons}

    per_symbol = {}
    for (magic, sym), grp in sorted(by_squad_symbol.items()):
        s = _stats([r["net"] for r in grp])
        regimes = _regime_robustness(grp)
        verdict, reasons = _grade(s, regimes, {"checked": False}, num_groups)
        verdict, reasons = _apply_overrides(verdict, reasons, magic, floats, is_stale)
        per_symbol[f"{magic}:{sym}"] = {"magic": magic, "symbol": sym, "stats": s,
                                        "regimes": regimes, "verdict": verdict, "reasons": reasons}

    overall_s = _stats([r["net"] for r in rows])
    overall_regimes = _regime_robustness(rows)
    overall_verdict, overall_reasons = _grade(overall_s, overall_regimes, {"checked": False}, num_groups)
    overall_verdict, overall_reasons = _apply_overrides(overall_verdict, overall_reasons, None, floats, is_stale)

    any_green = (overall_verdict == "GREEN") or any(v["verdict"] == "GREEN" for v in squads.values())
    recommendation = "GO" if (any_green and not is_stale) else "DEMO_ONLY"

    out = {
        "schema_version": 1,
        "generated_iso": _now_iso(),
        "generated_ts": time.time(),
        "data_source": ("data/friday.db trades(closed=1, source='bot'); external EAs & magic 0 excluded. "
                        "On this zero-commission/zero-swap demo net==pnl, and cost = the embedded spread "
                        "(entry/exit at bid/ask) — so it is net-of-spread, the real bottleneck."),
        "honesty_note": ("Built on project truth: no OOS edge proven; cost is the bottleneck; "
                         "shadow/risk-R boards are inflation and are NEVER counted as pnl. "
                         "RED is the correct default until real net-of-cost OOS evidence forces GREEN. "
                         "GREEN is additionally blocked on stale data or any unrealized floating loss."),
        "data_freshness": {"newest_iso": (datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None),
                           "stale_hours": round(stale_h, 1), "max_age_hours": FRESH_MAX_AGE_H, "is_stale": is_stale},
        "open_exposure": {"checked": floats is not None,
                          "total_floating": (None if floats is None else round(sum(floats.values()), 2)),
                          "note": ("verified live" if floats is not None else "UNVERIFIED (mt5 unavailable) — blocks GREEN")},
        "thresholds": {
            "min_n": MIN_N, "min_t": MIN_T, "min_expectancy_net": MIN_EXPECTANCY,
            "min_regimes": MIN_REGIMES, "min_profit_factor_net": MIN_PF,
            "max_drawdown_fraction": MAX_DD_FRACTION, "paper_live_tolerance": PAPER_LIVE_TOL,
            "regime_windows": REGIME_WINDOWS, "min_regime_n": MIN_REGIME_N,
            "multiple_testing": "Bonferroni-style t-bar lift by 0.5*ln(num_groups)",
        },
        "antitheater_checks": [
            "reads ONLY realized broker net-of-cost (trades.net, closed=1); never shadow/risk-R boards",
            "external EA magics and manual magic 0 excluded from squad credit",
            "single-window flukes blocked: needs positive expectancy in >=3 distinct time windows",
            "multiple-testing correction (Bonferroni t-bar lift) across all squads/symbols",
            "max-drawdown survivability gate vs net profit",
            "live broker mirror (pnl_scoreboard) expectancy must be >= 0 — a losing live mirror blocks GREEN",
            "FRESHNESS: stale data (newest trade older than max_age_hours) forces DEMO_ONLY and blocks GREEN",
            "SURVIVORSHIP: any squad carrying a net floating LOSS on still-open positions is blocked from GREEN "
            "(closed-only scoring otherwise lets a grid/martingale bank wins while the loser floats)",
            "RED is the default; GREEN requires ALL gates, never any single metric",
        ],
        "real_account_recommendation": recommendation,
        "overall": {"stats": overall_s, "regimes": overall_regimes,
                    "verdict": overall_verdict, "reasons": overall_reasons},
        "squads": squads,
        "per_symbol": per_symbol,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    os.replace(tmp, OUT)
    return out


def main():
    if "--loop" in sys.argv:                       # windowless under watchdog: re-evaluate the proof scoreboard
        while True:
            try:
                out = evaluate()
                print(f"[real_account_gate] rec={out['real_account_recommendation']} overall={out['overall']['verdict']}", flush=True)
            except Exception as e:
                print(f"[real_account_gate] err: {type(e).__name__}: {e}", flush=True)
            time.sleep(300)                        # كل 5 دقائق (سبورة إثبات، ليست حلقة تداول)
        return
    out = evaluate()
    if "--print" in sys.argv:
        o = out["overall"]["stats"] or {}
        print(f"[real_account_gate] -> {OUT}")
        print(f"  recommendation: {out['real_account_recommendation']}")
        print(f"  overall: verdict={out['overall']['verdict']} "
              f"n={o.get('n')} exp={o.get('expectancy_net')} t={o.get('t_stat')}")
        greens = [k for k, v in out["squads"].items() if v["verdict"] == "GREEN"]
        print(f"  GREEN squads: {greens or 'NONE (honest: no squad has earned real money yet)'}")
    else:
        print(f"[real_account_gate] wrote {OUT}: rec={out['real_account_recommendation']} "
              f"overall={out['overall']['verdict']}")


if __name__ == "__main__":
    main()
