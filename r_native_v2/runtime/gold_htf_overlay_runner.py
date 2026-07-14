"""gold_htf_overlay_runner.py — standalone LIVE runner for the validated gold
HTF trend overlay (genome GOLD-HTF-TREND-BULL-OVERLAY-G1).

WHAT THIS IS
------------
A small, self-contained live loop that trades the ONE OOS-validated edge:
XAUUSDm, H4 EMA50>EMA200 uptrend gate, LONG ONLY, H1 pullback-to-EMA20 +
bullish-resume entry, structural ATR stop, chandelier x3 trailing stop that
only ratchets UP, and a hard kill when the H4 trend dies (EMA50<EMA200).

It REUSES the validated strategy primitives from runtime/gold_htf_trend.py
(load_bars, ema, atr, swing_low) — it does NOT reinvent the strategy.

ISOLATION / SAFETY (non-negotiable)
-----------------------------------
  * OWN MAGIC ONLY. This overlay uses magic OVERLAY_MAGIC=99783. The LIVE
    trader uses 99782. We NEVER read, modify, or close any position whose
    magic != 99783. Every positions_get is filtered to our magic.
  * ONE POSITION MAX. We refuse to open a 2nd overlay position.
  * LONG ONLY. No shorts, ever.
  * DEFAULT DISABLED. order_send is reachable ONLY when
    os.environ["ENABLE_GOLD_HTF_OVERLAY"] == "1" AND --dry was not passed.
    Otherwise the runner computes and logs decisions but NEVER sends orders.
  * CAUSAL. We act only on NEWLY CLOSED H1/H4 bars (we drop the still-forming
    last bar from MT5 and track the last processed H1 bar time). No look-ahead.
  * STOP RATCHETS UP ONLY. The chandelier SL is moved via TRADE_ACTION_SLTP and
    is never lowered below the current broker SL.
  * KILL AT MARKET when H4 EMA50<EMA200 on a newly closed H4 bar.

USAGE
-----
  # safe self-test (no orders, single cycle):
  python gold_htf_overlay_runner.py --once --dry

  # armed live loop (only trades if env flag is also set to "1"):
  set ENABLE_GOLD_HTF_OVERLAY=1
  python gold_htf_overlay_runner.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

# ─────────────────────────── paths / root ──────────────────────────────────
_HERE = Path(__file__).resolve()
ROOT = _HERE.parent.parent if (_HERE.parent.parent / "runtime").exists() else Path(
    r"C:\Users\Radhi\MT5\r_native_v2"
)
DATA = ROOT / "data"
STATUS_PATH = DATA / "gold_htf_overlay_status.json"
PROPOSAL_PATH = DATA / "proposal_GOLD-HTF-TREND-BULL-OVERLAY-G1.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─────────────────────────── reuse validated strategy ──────────────────────
# These come straight from the OOS-validated module. Do NOT reimplement them.
from runtime.gold_htf_trend import load_bars, ema, atr, swing_low, Bars  # noqa: E402

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover
    mt5 = None


# ════════════════════════════════════════════════════════════════════════════
# Constants / config (genome-driven with safe defaults)
# ════════════════════════════════════════════════════════════════════════════
OVERLAY_MAGIC = 99783          # MUST differ from live trader's 99782
LIVE_TRADER_MAGIC = 99782      # never touch positions with this magic
SYMBOL = "XAUUSDm"
SIDE = "BUY"                   # long-only
POLL_SECONDS = 60


def _load_genome() -> dict:
    """Read tunables from the proposal genome JSON; fall back to validated defaults.

    NOTE: the proposal is a PROPOSAL, not live state. We only read numeric
    knobs from it (EMA periods, ATR mult, lot, risk). We never let it change
    side/symbol/magic or arm the runner.
    """
    defaults = {
        "htf": "H4",
        "ema_fast": 50,
        "ema_slow": 200,
        "entry_tf": "H1",
        "pullback_ema": 20,
        "pullback_atr_mult": 1.0,
        "require_resume": True,
        "swing_lookback": 10,
        "atr_period": 14,
        "sl_swing_buffer_atr": 0.5,
        "sl_min_atr": 1.0,
        "chandelier_atr_mult": 3.0,
        "lot": 0.01,
        "risk_dollars": 10.0,
        "min_lot": 0.01,
        "max_lot": 1.0,
        "lot_step": 0.01,
        # Spread guard: adversarial stress test (gold_htf_adversarial.py) showed
        # the edge DIES when spread widens (PF 1.32 -> 0.78 at 2x spread). Only
        # enter when the live spread is tight. Gold "point" = 0.01, so 0.50 = 50pt.
        "max_spread_usd": 0.50,
    }
    try:
        raw = json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))
        p = raw.get("params", {})
        newp = p.get("_NEW_PARAMS_NOT_YET_HONORED_BY_unified_trader", {})
        gate = newp.get("regime_gate", {})
        entry = newp.get("entry", {})
        stop = newp.get("stop", {})
        exit_ = newp.get("exit", {})
        sizing = newp.get("sizing", {})

        defaults["htf"] = gate.get("htf", defaults["htf"])
        defaults["ema_fast"] = int(gate.get("ema_fast", defaults["ema_fast"]))
        defaults["ema_slow"] = int(gate.get("ema_slow", defaults["ema_slow"]))
        defaults["entry_tf"] = entry.get("entry_tf", defaults["entry_tf"])
        defaults["pullback_ema"] = int(entry.get("pullback_ema", defaults["pullback_ema"]))
        defaults["pullback_atr_mult"] = float(entry.get("pullback_atr_mult", defaults["pullback_atr_mult"]))
        defaults["require_resume"] = bool(entry.get("require_resume", defaults["require_resume"]))
        defaults["swing_lookback"] = int(entry.get("swing_lookback", defaults["swing_lookback"]))
        defaults["atr_period"] = int(stop.get("atr_period", defaults["atr_period"]))
        defaults["sl_swing_buffer_atr"] = float(stop.get("sl_swing_buffer_atr", defaults["sl_swing_buffer_atr"]))
        defaults["sl_min_atr"] = float(stop.get("sl_min_atr", defaults["sl_min_atr"]))
        defaults["chandelier_atr_mult"] = float(exit_.get("chandelier_atr_mult", defaults["chandelier_atr_mult"]))
        defaults["risk_dollars"] = float(sizing.get("risk_dollars", defaults["risk_dollars"]))
        defaults["min_lot"] = float(sizing.get("min_lot", defaults["min_lot"]))
        defaults["max_lot"] = float(sizing.get("max_lot", defaults["max_lot"]))
        defaults["lot_step"] = float(sizing.get("lot_step", defaults["lot_step"]))
        # top-level lot
        if isinstance(p.get("lot"), (int, float)) and p.get("lot", 0) > 0:
            defaults["lot"] = float(p["lot"])
    except Exception as e:  # genome unreadable -> validated defaults
        _log(f"WARN could not parse genome ({e}); using validated defaults")
    if not defaults.get("lot") or defaults["lot"] <= 0:
        defaults["lot"] = 0.01
    return defaults


# ════════════════════════════════════════════════════════════════════════════
# Logging
# ════════════════════════════════════════════════════════════════════════════
def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}Z] [GOLD-HTF-OVERLAY] {msg}", flush=True)


# ════════════════════════════════════════════════════════════════════════════
# Bar helpers (drop the still-forming last bar so we are strictly causal)
# ════════════════════════════════════════════════════════════════════════════
def _closed_bars(symbol: str, timeframe: str, days: int) -> Optional[Bars]:
    """Load bars from MT5/cache and DROP the last (still-forming) bar.

    The final bar returned by MT5 is the current, not-yet-closed candle. Acting
    on it would be look-ahead. We slice it off so the last element is the most
    recently CLOSED bar.
    """
    b = load_bars(symbol, timeframe, days=days, source="auto")
    if b is None or len(b) < 2:
        return None
    return Bars(
        symbol=b.symbol, timeframe=b.timeframe,
        time=b.time[:-1], open=b.open[:-1], high=b.high[:-1],
        low=b.low[:-1], close=b.close[:-1], source=b.source,
    )


# ════════════════════════════════════════════════════════════════════════════
# Strategy evaluation on CLOSED bars (mirrors gold_htf_trend.backtest logic)
# ════════════════════════════════════════════════════════════════════════════
def _htf_trend_now(h4: Bars, g: dict) -> tuple[int, float, float]:
    """Trend as-of the last CLOSED H4 bar. Returns (trend, ema_fast, ema_slow)."""
    ef = ema(h4.close, g["ema_fast"])
    es = ema(h4.close, g["ema_slow"])
    k = len(h4) - 1
    f, s = float(ef[k]), float(es[k])
    if np.isnan(f) or np.isnan(s):
        return 0, f, s
    if f > s:
        return 1, f, s
    if f < s:
        return -1, f, s
    return 0, f, s


def _entry_signal(h1: Bars, g: dict) -> dict:
    """Evaluate the pullback-to-EMA20 + bullish-resume long setup on the last
    CLOSED H1 bar. Returns a dict with 'fires' and supporting numbers."""
    i = len(h1) - 1
    pb = ema(h1.close, g["pullback_ema"])
    a_arr = atr(h1.high, h1.low, h1.close, g["atr_period"])
    a = float(a_arr[i])
    pbv = float(pb[i])
    out = {"fires": False, "atr": a, "ema20": pbv, "i": i}
    if np.isnan(a) or a <= 0 or np.isnan(pbv):
        out["reason"] = "indicators not ready"
        return out
    long_setup = (
        (h1.low[i] <= pbv + g["pullback_atr_mult"] * a)          # pulled back near EMA20
        and (not g["require_resume"] or h1.close[i] > pbv)       # resume: close back above EMA20
        and (h1.close[i] > h1.open[i])                            # bullish resume bar
    )
    out["fires"] = bool(long_setup)
    out["reason"] = "long setup fired" if long_setup else "no pullback-resume"
    return out


def _compute_sl(h1: Bars, g: dict, entry_px: float, a: float) -> float:
    """Structural SL = swing_low(lookback) - buffer*ATR, floored at min_atr*ATR."""
    i = len(h1) - 1
    struct = swing_low(h1.low, i, g["swing_lookback"])
    raw_sl = struct - g["sl_swing_buffer_atr"] * a
    sl_dist = entry_px - raw_sl
    min_dist = g["sl_min_atr"] * a
    if sl_dist < min_dist:
        raw_sl = entry_px - min_dist
    return float(raw_sl)


def _round_lot(lot: float, g: dict) -> float:
    lot = max(g["min_lot"], min(g["max_lot"], lot))
    step = g["lot_step"]
    return round(round(lot / step) * step, 2)


# ════════════════════════════════════════════════════════════════════════════
# MT5 isolation helpers — magic==99783 ONLY
# ════════════════════════════════════════════════════════════════════════════
def _overlay_position():
    """Return our single overlay position or None. NEVER returns other magics."""
    if mt5 is None:
        return None
    poss = mt5.positions_get(symbol=SYMBOL)
    if not poss:
        return None
    ours = [p for p in poss if p.magic == OVERLAY_MAGIC]
    if not ours:
        return None
    return ours[0]


def _send_market_buy(lot: float, sl: float, armed: bool) -> dict:
    if not armed:
        _log(f"DRY: would BUY {lot} {SYMBOL} sl={sl:.3f} (magic {OVERLAY_MAGIC}) — NO ORDER SENT")
        return {"action": "dry_buy", "lot": lot, "sl": sl}
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": float(lot),
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "sl": float(sl),
        "tp": 0.0,
        "deviation": 30,
        "magic": OVERLAY_MAGIC,
        "comment": "GOLD-HTF-OVERLAY",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if (not r or r.retcode != mt5.TRADE_RETCODE_DONE):
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    _log(f"LIVE BUY result ok={ok} retcode={getattr(r,'retcode',None)} "
         f"deal={getattr(r,'deal',None)} price={getattr(r,'price',None)}")
    return {"action": "buy", "ok": ok, "retcode": getattr(r, "retcode", None)}


def _modify_sl(pos, new_sl: float, armed: bool) -> dict:
    """Ratchet SL UP only. Refuse to lower an existing stop."""
    if pos.magic != OVERLAY_MAGIC:
        _log("REFUSED _modify_sl on non-overlay magic — aborting")
        return {"action": "refused_wrong_magic"}
    cur = float(pos.sl) if pos.sl else 0.0
    if cur and new_sl <= cur + 1e-9:
        return {"action": "sl_hold", "sl": cur}  # never lower / no-op
    if not armed:
        _log(f"DRY: would RATCHET SL {cur:.3f} -> {new_sl:.3f} on ticket {pos.ticket} — NO ORDER SENT")
        return {"action": "dry_sltp", "from": cur, "to": new_sl}
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": SYMBOL,
        "position": pos.ticket,
        "sl": float(new_sl),
        "tp": float(pos.tp),
        "magic": OVERLAY_MAGIC,
    }
    r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    _log(f"LIVE SLTP ratchet {cur:.3f}->{new_sl:.3f} ticket={pos.ticket} ok={ok} "
         f"retcode={getattr(r,'retcode',None)}")
    return {"action": "sltp", "ok": ok, "from": cur, "to": new_sl}


def _close_at_market(pos, armed: bool, why: str) -> dict:
    """Close ONLY our overlay position at market."""
    if pos.magic != OVERLAY_MAGIC:
        _log("REFUSED _close_at_market on non-overlay magic — aborting")
        return {"action": "refused_wrong_magic"}
    if not armed:
        _log(f"DRY: would CLOSE overlay ticket {pos.ticket} at market ({why}) — NO ORDER SENT")
        return {"action": "dry_close", "ticket": pos.ticket, "why": why}
    tick = mt5.symbol_info_tick(SYMBOL)
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": float(pos.volume),
        "type": mt5.ORDER_TYPE_SELL,  # close a long
        "position": pos.ticket,
        "price": tick.bid,
        "deviation": 30,
        "magic": OVERLAY_MAGIC,
        "comment": f"GOLD-HTF-KILL"[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    r = mt5.order_send(req)
    if (not r or r.retcode != mt5.TRADE_RETCODE_DONE):
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    _log(f"LIVE CLOSE ({why}) ticket={pos.ticket} ok={ok} retcode={getattr(r,'retcode',None)}")
    return {"action": "close", "ok": ok, "why": why}


# ════════════════════════════════════════════════════════════════════════════
# Status heartbeat
# ════════════════════════════════════════════════════════════════════════════
def _write_status(d: dict) -> None:
    d = dict(d)
    d["ts"] = datetime.now(timezone.utc).isoformat()
    d["magic"] = OVERLAY_MAGIC
    d["symbol"] = SYMBOL
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"WARN could not write status: {e}")


# ════════════════════════════════════════════════════════════════════════════
# One evaluation cycle
# ════════════════════════════════════════════════════════════════════════════
def run_cycle(g: dict, armed: bool, state: dict) -> dict:
    """Evaluate one cycle. `state` carries last-processed bar times across loops."""
    status = {
        "armed": armed,
        "in_position": False,
        "trend": None,
        "entry": None,
        "sl": None,
        "swap": None,
        "accumulated_cost": None,
        "last_action": "none",
    }

    if mt5 is None or not mt5.initialize():
        _log("FATAL MT5 not available / initialize failed")
        status["last_action"] = "mt5_unavailable"
        _write_status(status)
        return status

    h4 = _closed_bars(SYMBOL, g["htf"], days=560)
    h1 = _closed_bars(SYMBOL, g["entry_tf"], days=480)
    if h4 is None or len(h4) < g["ema_slow"] + 2 or h1 is None or len(h1) < g["pullback_ema"] + g["atr_period"] + 5:
        _log(f"insufficient closed bars (h4={None if h4 is None else len(h4)} "
             f"h1={None if h1 is None else len(h1)})")
        status["last_action"] = "insufficient_bars"
        _write_status(status)
        return status

    last_h1_t = h1.time[-1]
    last_h4_t = h4.time[-1]
    new_h1 = (state.get("last_h1") != last_h1_t)
    new_h4 = (state.get("last_h4") != last_h4_t)

    trend, ef, es = _htf_trend_now(h4, g)
    status["trend"] = {"dir": trend, "ema_fast": round(ef, 3), "ema_slow": round(es, 3),
                       "as_of_h4_bar": str(last_h4_t)}
    _log(f"H4 trend={'UP' if trend==1 else 'DOWN' if trend==-1 else 'FLAT'} "
         f"EMA{g['ema_fast']}={ef:.3f} EMA{g['ema_slow']}={es:.3f} "
         f"(as-of closed H4 {last_h4_t}); newH1={new_h1} newH4={new_h4}")

    # CRITICAL: load_bars()/_bars_from_mt5() calls mt5.shutdown() in its finally,
    # which tears down the IPC connection. Without re-initializing here, every
    # subsequent positions_get / symbol_info_tick / order_send returns None
    # (-10004 "No IPC connection") — which would make the runner blind to its own
    # position (trail & kill become dead code) and, when armed, stack new longs
    # on every H1 bar. Re-init now so all position/tick/order calls below work.
    if not mt5.initialize():
        _log("FATAL MT5 re-initialize failed after bar load — aborting cycle")
        status["last_action"] = "mt5_reinit_failed"
        _write_status(status)
        return status

    pos = _overlay_position()

    # ---------- manage existing overlay position ----------
    if pos is not None:
        atr_arr = atr(h1.high, h1.low, h1.close, g["atr_period"])
        a = float(atr_arr[-1])
        swap = float(getattr(pos, "swap", 0.0) or 0.0)
        commission = float(getattr(pos, "commission", 0.0) or 0.0)
        accumulated_cost = swap + commission
        status.update({
            "in_position": True,
            "entry": round(float(pos.price_open), 3),
            "sl": round(float(pos.sl), 3) if pos.sl else None,
            "swap": round(swap, 2),
            "accumulated_cost": round(accumulated_cost, 2),
            "ticket": int(pos.ticket),
            "volume": float(pos.volume),
            "profit": round(float(pos.profit), 2),
        })
        _log(f"IN POSITION ticket={pos.ticket} entry={pos.price_open:.3f} "
             f"sl={pos.sl:.3f} vol={pos.volume} profit={pos.profit:.2f} "
             f"swap={swap:.2f} commission={commission:.2f} acc_cost={accumulated_cost:.2f}")

        # KILL on newly-closed H4 trend death
        if new_h4 and trend == -1:
            res = _close_at_market(pos, armed, why="trend_death_H4_EMA50<EMA200")
            status["last_action"] = res.get("action", "close")
            _write_status(status)
            return status

        # Chandelier trail (only on newly-closed H1 bar). highestHigh since entry.
        if new_h1 and not np.isnan(a) and a > 0:
            entry_time = datetime.fromtimestamp(int(pos.time), tz=timezone.utc)
            mask = np.array([t >= entry_time for t in h1.time])
            highs_since = h1.high[mask] if mask.any() else h1.high[-1:]
            highest_high = float(np.max(highs_since)) if len(highs_since) else float(h1.high[-1])
            chand_sl = highest_high - g["chandelier_atr_mult"] * a
            status["chandelier_sl"] = round(chand_sl, 3)
            res = _modify_sl(pos, chand_sl, armed)
            status["last_action"] = res.get("action", "sl")
        else:
            status["last_action"] = "hold_position"
        _write_status(status)
        return status

    # ---------- FLAT: look for entry (only on newly-closed H1 bar) ----------
    if not new_h1:
        status["last_action"] = "flat_no_new_h1"
        _write_status(status)
        return status

    if trend != 1:
        _log("FLAT: H4 trend not UP -> no entry")
        status["last_action"] = "flat_trend_not_up"
        _write_status(status)
        return status

    sig = _entry_signal(h1, g)
    _log(f"FLAT entry-scan: fires={sig['fires']} ({sig.get('reason')}) "
         f"ema20={sig['ema20']:.3f} atr={sig['atr']:.3f}")
    if not sig["fires"]:
        status["last_action"] = "flat_no_setup"
        _write_status(status)
        return status

    # Setup fired and trend UP -> size & buy.
    tick = mt5.symbol_info_tick(SYMBOL)

    # SPREAD GUARD — the edge dies under wide spread (adversarial test: PF 1.32
    # -> 0.78 at 2x spread). Only trade the tight-spread condition where the
    # edge is profitable. Refuse (defer to a later bar) if spread is too wide.
    spread = float(tick.ask) - float(tick.bid)
    max_spread = g.get("max_spread_usd", 0.50)
    if spread > max_spread:
        _log(f"SETUP FIRED but spread too wide ${spread:.2f} > ${max_spread:.2f} "
             f"— skipping entry (edge dies on wide spread)")
        status.update({"last_action": "skip_wide_spread", "spread": round(spread, 3)})
        _write_status(status)
        return status

    entry_px = float(tick.ask)
    a = sig["atr"]
    sl = _compute_sl(h1, g, entry_px, a)
    sl_dist = entry_px - sl
    if sl_dist <= 0:
        _log("computed SL >= entry — skipping (safety)")
        status["last_action"] = "skip_bad_sl"
        _write_status(status)
        return status

    # Sizing: per the genome this overlay starts at the fixed 0.01 lot floor.
    # (ATR risk-sizing is available in the backtest; live we use the genome lot
    # to keep exposure minimal and deterministic.) We still log the ATR-implied
    # size for transparency.
    contract = 100.0
    risk_per_lot = sl_dist * contract
    atr_implied = g["risk_dollars"] / risk_per_lot if risk_per_lot > 0 else None
    lot = _round_lot(g["lot"], g)
    if atr_implied is not None:
        _log(f"sizing: using genome lot={lot} (ATR-implied for ${g['risk_dollars']} "
             f"risk would be ~{atr_implied:.3f})")
    status.update({"entry": round(entry_px, 3), "sl": round(sl, 3)})
    res = _send_market_buy(lot, sl, armed)
    status["last_action"] = res.get("action", "buy")
    _write_status(status)
    return status


# ════════════════════════════════════════════════════════════════════════════
# Single-instance lock — two ARMED loopers on the same magic could race and open
# two overlay positions (breaking one-position-max). Refuse to start a second.
# ════════════════════════════════════════════════════════════════════════════
LOCK_PATH = DATA / "gold_htf_overlay.pid"


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:
        pass
    try:
        os.kill(pid, 0)  # signal 0 = existence check (Windows: raises if dead)
        return True
    except Exception:
        return False


def _acquire_singleton() -> bool:
    """Return True if we got the lock; False if another live instance holds it."""
    try:
        if LOCK_PATH.exists():
            old = LOCK_PATH.read_text(encoding="utf-8").strip()
            if old.isdigit() and int(old) != os.getpid() and _pid_alive(int(old)):
                _log(f"REFUSED to start — another overlay runner is alive (pid {old}). "
                     f"Only one armed instance may run. Exiting.")
                return False
        DATA.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        _log(f"WARN singleton lock check failed ({e}); proceeding")
        return True


def _release_singleton() -> None:
    try:
        if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_PATH.unlink()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gold HTF trend overlay live runner")
    ap.add_argument("--once", action="store_true", help="run a single cycle then exit")
    ap.add_argument("--dry", action="store_true", help="force DRY mode (never send orders)")
    args = ap.parse_args(argv)

    env_armed = os.environ.get("ENABLE_GOLD_HTF_OVERLAY", "") == "1"
    armed = env_armed and not args.dry

    g = _load_genome()
    _log("=" * 64)
    _log("Gold HTF trend overlay runner starting")
    _log(f"magic={OVERLAY_MAGIC} (live trader={LIVE_TRADER_MAGIC}, never touched) "
         f"symbol={SYMBOL} side={SIDE}")
    _log(f"ENABLE_GOLD_HTF_OVERLAY={os.environ.get('ENABLE_GOLD_HTF_OVERLAY','<unset>')} "
         f"--dry={args.dry} -> ARMED={armed} "
         f"({'LIVE ORDERS ENABLED' if armed else 'DRY: no orders will be sent'})")
    _log(f"genome: htf={g['htf']} ema={g['ema_fast']}/{g['ema_slow']} "
         f"entry_tf={g['entry_tf']} pullback_ema={g['pullback_ema']} "
         f"chandelier_x{g['chandelier_atr_mult']} lot={g['lot']} risk=${g['risk_dollars']}")
    _log("=" * 64)

    state: dict = {"last_h1": None, "last_h4": None}

    if args.once:
        try:
            run_cycle(g, armed, state)
        finally:
            if mt5 is not None:
                try:
                    mt5.shutdown()
                except Exception:
                    pass
        _log("single cycle complete (--once) — exiting cleanly")
        return 0

    if not _acquire_singleton():
        return 2  # another live instance already holds the lock

    try:
        while True:
            try:
                status = run_cycle(g, armed, state)
                # update processed-bar markers from what the cycle saw
                tr = status.get("trend") or {}
                if tr.get("as_of_h4_bar"):
                    state["last_h4"] = _parse_iso(tr["as_of_h4_bar"])
                # last_h1 derived inside cycle via fresh load; re-read marker:
                state["last_h1"] = _last_closed_time(g["entry_tf"], 480)
            except Exception as e:
                _log(f"ERROR in cycle: {e}")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        _log("interrupted — shutting down")
    finally:
        _release_singleton()
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:
                pass
    return 0


def _parse_iso(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return s


def _last_closed_time(tf: str, days: int):
    b = _closed_bars(SYMBOL, tf, days=days)
    return b.time[-1] if b is not None and len(b) else None


if __name__ == "__main__":
    raise SystemExit(main())
