"""cot_ob_backtest.py — COT-gated trading on REAL SMC order blocks.

Born 2026-05-31 (Track A, step 2). Re-runs the earlier COT supply/demand test,
but the zones now come from the genuine Smart-Money-Concepts detector
``shared/order_blocks.py`` (BOS-confirmed order blocks) instead of the discredited
``EMA50 +/- 1.5*ATR`` proxy.

Two experiments, each WITH vs WITHOUT the COT "Golden Rule" gate, net of the
``shared/cost_model`` round-trip friction, on ~2 years of REAL MT5 H1 bars:

  (1) GOLD LONGS  — enter at unmitigated DEMAND order blocks (price retraces into
      the zone after the OB was confirmed). Gate = supply_long_ok("XAUUSDm", t).
  (2) GBPUSD SHORTS — enter at unmitigated SUPPLY order blocks. Gate =
      supply_short_ok("GBPUSDm", t).

ENTRY / EXIT MODEL (strictly causal, no look-ahead)
  * Detect zones ONCE on the whole series; each zone carries ``idx`` = the BOS
    confirmation bar. We only ever consult a zone on bars strictly AFTER its
    ``idx`` (the detector guarantees idx is causal). We re-derive mitigation
    ourselves bar-by-bar so the global ``mitigated`` flag (which is as-of array
    end) is never used for the trade decision.
  * A zone becomes "armed" once confirmed. We then watch forward bars: the first
    bar whose range touches the zone is the ENTRY (limit-style fill at the near
    edge of the zone — demand: fill at zone hi for a long; supply: fill at zone
    lo for a short — the conservative side you'd realistically get).
  * SL = structure-based: just beyond the far edge of the OB zone, padded by a
    small ATR buffer. demand long SL = zone lo - buffer; supply short SL =
    zone hi + buffer.
  * TP = two variants reported side by side:
        - fixed R multiple (2R and 3R) off the entry vs the SL distance, AND
        - "next opposing zone" (nearest confirmed opposite-type zone beyond
          entry) capped so it is at least 1R; reported as the NZ variant.
  * Exit is decided by walking bars AFTER entry: whichever of SL / TP the bar
    range hits first. If a single bar straddles both, we assume SL-first
    (pessimistic). Open trades at series end are closed at the last close.
  * One trade per zone. Risk is fixed at a constant lot so $ results are
    comparable; cost_model.round_trip_cost is subtracted from every trade.

SPLIT
  67% in-sample / 33% out-of-sample by bar index. A trade is assigned to the
  split of its ENTRY bar. OOS is reported separately — it is the only number
  that counts.

OUTPUT
  Writes a results table to data/cot_ob_results.md and prints a JSON summary
  block (consumed by the orchestrator).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# --- path wiring so shared/ imports resolve regardless of CWD ---------------
RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
DATA = ROOT / "data"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(RUNTIME / "shared"))

from shared.order_blocks import detect_order_blocks  # noqa: E402
from shared.cost_model import round_trip_cost  # noqa: E402
from shared.cot_signal import supply_long_ok, supply_short_ok  # noqa: E402

LOT = 0.10  # constant position size for comparability


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_h1(symbol: str, days: int = 730):
    """Pull ~`days` of real H1 bars from MT5. Returns structured ndarray."""
    import MetaTrader5 as mt5

    ok = mt5.initialize() or mt5.initialize()
    if not ok:
        raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")
    try:
        now = _dt.datetime.now(_dt.timezone.utc)
        since = now - _dt.timedelta(days=days)
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, since, now)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"no rates for {symbol}: {mt5.last_error()}")
        return rates
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backtest core
# ---------------------------------------------------------------------------
def _atr_buffer(high, low, close, period=14):
    """Per-bar ATR used as the SL pad (same TR-SMA shape as order_blocks)."""
    n = high.size
    prev = np.empty(n)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = np.full(n, np.nan)
    if n >= period:
        cs = np.cumsum(tr)
        atr[period - 1:] = (cs[period - 1:] - np.concatenate(([0.0], cs[:-period]))) / period
    else:
        atr[:] = tr.mean()
    return atr


def _bar_time(t_arr, i) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(float(t_arr[i]), _dt.timezone.utc)


def simulate(
    rates,
    symbol: str,
    side: str,            # "long" (demand) or "short" (supply)
    tp_mode: str,         # "2R", "3R", or "NZ"
    gate_fn=None,         # callable(symbol, datetime)->(bool,reason) or None
    sl_buffer_atr: float = 0.25,
    split_frac: float = 0.67,
) -> List[Dict]:
    """Run one configuration. Returns a list of trade dicts (net of costs)."""
    t = rates["time"].astype(np.float64)
    o = rates["open"].astype(np.float64)
    h = rates["high"].astype(np.float64)
    l = rates["low"].astype(np.float64)
    c = rates["close"].astype(np.float64)
    n = c.size
    atr = _atr_buffer(h, l, c)

    zones = detect_order_blocks(rates, swing=5, impulse_atr_mult=1.0, lookahead_impulse=3)
    want_type = "demand" if side == "long" else "supply"
    my_zones = [z for z in zones if z["type"] == want_type]
    opp_zones = [z for z in zones if z["type"] != want_type]

    split_idx = int(n * split_frac)
    trades: List[Dict] = []

    for z in my_zones:
        conf = z["idx"]
        zlo, zhi = z["lo"], z["hi"]
        a_conf = atr[conf] if np.isfinite(atr[conf]) else (zhi - zlo)
        buf = sl_buffer_atr * a_conf

        # Walk forward from the bar AFTER confirmation to find first touch (entry).
        entry_bar = -1
        for i in range(conf + 1, n):
            if l[i] <= zhi and h[i] >= zlo:  # bar range overlaps the zone
                entry_bar = i
                break
        if entry_bar < 0:
            continue

        # Conservative limit fill at the near edge of the zone.
        if side == "long":
            entry = zhi
            sl = zlo - buf
        else:
            entry = zlo
            sl = zhi + buf

        risk = abs(entry - sl)
        if risk <= 0:
            continue

        # COT gate evaluated at the ENTRY bar time (asof = last report <= bar).
        gate_ok = True
        gate_reason = "no-gate"
        if gate_fn is not None:
            gate_ok, gate_reason = gate_fn(symbol, _bar_time(t, entry_bar))
            if not gate_ok:
                continue

        # Target.
        if tp_mode in ("2R", "3R"):
            rmult = 2.0 if tp_mode == "2R" else 3.0
            tp = entry + rmult * risk if side == "long" else entry - rmult * risk
        else:  # NZ — nearest opposing confirmed zone beyond entry, >= 1R away
            tp = None
            best = None
            for oz in opp_zones:
                if oz["idx"] >= entry_bar:  # only zones already confirmed by entry
                    continue
                if side == "long":
                    edge = oz["lo"]  # supply zone above
                    if edge > entry + risk and (best is None or edge < best):
                        best = edge
                else:
                    edge = oz["hi"]  # demand zone below
                    if edge < entry - risk and (best is None or edge > best):
                        best = edge
            if best is None:
                # fallback to 2R if no opposing structure available
                tp = entry + 2.0 * risk if side == "long" else entry - 2.0 * risk
            else:
                tp = best

        # Walk forward from entry_bar to resolve SL/TP (entry_bar+1 onward; the
        # entry bar itself filled the limit, exits start next bar).
        outcome = None
        exit_price = None
        exit_bar = None
        for j in range(entry_bar + 1, n):
            hit_sl = l[j] <= sl if side == "long" else h[j] >= sl
            hit_tp = h[j] >= tp if side == "long" else l[j] <= tp
            if hit_sl and hit_tp:
                outcome, exit_price, exit_bar = "sl", sl, j  # pessimistic
                break
            if hit_sl:
                outcome, exit_price, exit_bar = "sl", sl, j
                break
            if hit_tp:
                outcome, exit_price, exit_bar = "tp", tp, j
                break
        if outcome is None:
            outcome, exit_price, exit_bar = "eod", float(c[-1]), n - 1

        # P&L in price units -> dollars via point_value embedded in cost_model.
        # point_value per lot: gold 0.10$/pt(0.001), fx 1$/pt(0.00001).
        # Convert price delta to dollars: delta_price / point * point_value * lot.
        if side == "long":
            delta = exit_price - entry
        else:
            delta = entry - exit_price

        gross = _price_to_dollars(symbol, delta, LOT)
        cost = round_trip_cost(symbol, lot=LOT, price=entry)
        net = gross - cost

        trades.append({
            "zone_idx": conf,
            "ob_bar": z["ob_bar"],
            "entry_bar": entry_bar,
            "exit_bar": exit_bar,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "outcome": outcome,
            "delta": delta,
            "gross": gross,
            "cost": cost,
            "net": net,
            "split": "IS" if entry_bar < split_idx else "OOS",
            "entry_time": _bar_time(t, entry_bar).isoformat(),
        })

    return trades


def _price_to_dollars(symbol: str, delta_price: float, lot: float) -> float:
    """Convert a price move (quote ccy) into account dollars for `lot`.

    point_value/lot = point*contract_size (USD). dollars = (delta/point)*pv*lot
    = delta * contract_size * lot for USD-quoted symbols. We pull the profile
    from cost_model to stay consistent."""
    from shared.cost_model import _profile

    p = _profile(symbol)
    # delta (price units) / point = number of points; * point_value = $/lot.
    return (delta_price / p.point) * p.point_value * lot


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def metrics(trades: List[Dict]) -> Dict:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "net": 0.0, "max_drawdown": 0.0}
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    # equity curve max drawdown (in $)
    eq = np.cumsum(nets)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    maxdd = float(dd.max()) if dd.size else 0.0
    return {
        "trades": len(trades),
        "win_rate": round(100.0 * len(wins) / len(trades), 1),
        "profit_factor": round(pf, 3) if np.isfinite(pf) else 999.0,
        "net": round(float(sum(nets)), 2),
        "max_drawdown": round(maxdd, 2),
    }


def split_metrics(trades: List[Dict]) -> Dict[str, Dict]:
    return {
        "ALL": metrics(trades),
        "IS": metrics([t for t in trades if t["split"] == "IS"]),
        "OOS": metrics([t for t in trades if t["split"] == "OOS"]),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_experiment(rates, symbol, side, label, gate_fn):
    out = {}
    for tp_mode in ("2R", "3R", "NZ"):
        trades = simulate(rates, symbol, side, tp_mode, gate_fn=gate_fn)
        out[tp_mode] = {"splits": split_metrics(trades), "trades": trades}
    return out


def _fmt_row(label, m):
    return (f"| {label} | {m['trades']} | {m['win_rate']}% | "
            f"{m['profit_factor']} | {m['net']:.2f} | {m['max_drawdown']:.2f} |")


def main():
    print("Loading MT5 H1 data (~730d)...")
    gold = load_h1("XAUUSDm", days=730)
    gbp = load_h1("GBPUSDm", days=730)
    print(f"  XAUUSDm: {len(gold)} bars")
    print(f"  GBPUSDm: {len(gbp)} bars")

    results = {}

    # (1) GOLD LONGS at demand OBs
    results["gold_long_nogate"] = run_experiment(gold, "XAUUSDm", "long", "GOLD LONG no-gate", None)
    results["gold_long_gate"] = run_experiment(gold, "XAUUSDm", "long", "GOLD LONG COT-gate", supply_long_ok)

    # (2) GBP SHORTS at supply OBs
    results["gbp_short_nogate"] = run_experiment(gbp, "GBPUSDm", "short", "GBP SHORT no-gate", None)
    results["gbp_short_gate"] = run_experiment(gbp, "GBPUSDm", "short", "GBP SHORT COT-gate", supply_short_ok)

    # ---- build markdown report ----
    lines = []
    lines.append("# COT-gated REAL Order-Block Backtest")
    lines.append("")
    lines.append(f"Generated: {_dt.datetime.now(_dt.timezone.utc).isoformat()}")
    lines.append("")
    lines.append("Zones from `shared/order_blocks.py` (BOS-confirmed SMC order blocks). "
                 "Net of `cost_model.round_trip_cost`. H1, ~2y real MT5 data. "
                 f"Lot={LOT}. SL = structure (zone far edge + 0.25*ATR). "
                 "No look-ahead: zone consulted only on bars > its causal `idx`; "
                 "COT asof = last report <= entry-bar time.")
    lines.append("")
    lines.append("**OOS (out-of-sample, last 33%) is the only number that counts.**")
    lines.append("")

    config_titles = {
        "gold_long_nogate": "(1) GOLD LONGS @ demand OB — NO gate",
        "gold_long_gate": "(1) GOLD LONGS @ demand OB — COT gate (supply_long_ok)",
        "gbp_short_nogate": "(2) GBP SHORTS @ supply OB — NO gate",
        "gbp_short_gate": "(2) GBP SHORTS @ supply OB — COT gate (supply_short_ok)",
    }

    struct_results = []  # for StructuredOutput

    for key in ["gold_long_nogate", "gold_long_gate", "gbp_short_nogate", "gbp_short_gate"]:
        lines.append(f"## {config_titles[key]}")
        lines.append("")
        for tp_mode in ("2R", "3R", "NZ"):
            sp = results[key][tp_mode]["splits"]
            lines.append(f"### TP = {tp_mode}")
            lines.append("")
            lines.append("| Split | Trades | Win% | PF | Net $ | MaxDD $ |")
            lines.append("|---|---|---|---|---|---|")
            for split in ("ALL", "IS", "OOS"):
                lines.append(_fmt_row(split, sp[split]))
            lines.append("")
            # structured: record the OOS row for each config/tp
            oos = sp["OOS"]
            struct_results.append({
                "label": f"{config_titles[key]} | TP={tp_mode} | OOS",
                "trades": oos["trades"],
                "win_rate": oos["win_rate"],
                "profit_factor": oos["profit_factor"],
                "net": oos["net"],
                "max_drawdown": oos["max_drawdown"],
            })

    out_path = DATA / "cot_ob_results.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out_path}")

    # JSON summary block for the orchestrator
    print("\n===RESULTS_JSON_START===")
    print(json.dumps({"results": struct_results}, indent=2))
    print("===RESULTS_JSON_END===")

    return struct_results


if __name__ == "__main__":
    main()
