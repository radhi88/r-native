"""
r_executor.py — R's actual trade executor (with very strict safety gates).

Magic number: 20260605 (unique — doesn't conflict with:
  20260600 (FRIDAY Brain), 20260514 (QADER),
  20260603 (v3), 20260604 (news straddle))

Default mode: PAPER (no real orders). Switch with --live AFTER 24h paper validation.

Loop every 30s:
  1. Pull /api/r/trade_gate
  2. If verdict == GO and we have no R position:
        a. Compute lot/SL/TP from gate output
        b. Send order (or just log it in paper mode)
        c. Append result to R memory journal
  3. If we have an R position:
        a. Monitor SL/TP via broker
        b. If position closed since last loop → record outcome
        c. Optional: trail SL after near_tp reached
  4. Hard kills:
        - R's total loss for the day exceeds R_DAILY_CAP_USD → freeze 24h
        - Consecutive losing trades hit R_CONSEC_LOSS_LIMIT → freeze 24h
        - kill_switch.txt exists → exit immediately
        - Account balance < R_MIN_BALANCE → exit
"""
from __future__ import annotations
import argparse
import csv
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5

# R Learning hooks (best-effort; failures don't block trading)
try:
    from friday_v3.algory.r_learning import (
        record_trade_origin, record_r_sl_move, detect_manual_override,
        record_closed_trade, get_adjusted_multipliers,
    )
    HAS_LEARNING = True
except Exception as _e:
    HAS_LEARNING = False
    def record_trade_origin(*a, **k): pass
    def record_r_sl_move(*a, **k): pass
    def detect_manual_override(*a, **k): return None
    def record_closed_trade(*a, **k): return None
    def get_adjusted_multipliers(arch): return {"sl_mult":1,"tp_mult":1,"be_trigger_factor":1}

# Decision logger (fail-soft; never blocks trading)
try:
    from r_native import decision_log as _decision_log
    HAS_DECISION_LOG = True
except Exception:
    HAS_DECISION_LOG = False
    _decision_log = None

ROOT          = Path(r"C:\Users\Radhi\MT5\friday_v3")
DATA          = ROOT / "data"
STATE_FILE    = DATA / "r_executor_state.json"
TRADES_CSV    = DATA / "r_trades.csv"
KILL_SWITCH   = Path(r"C:\Users\Radhi\MT5\kill_switch.txt")

# MT5 Common Files (where EA looks for Brain JSON)
MT5_COMMON    = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
BRAIN_JSON    = MT5_COMMON / "friday_brain_orders.json"

# ─── Identity & hard limits ───
R_MAGIC                = 20260605
R_SYMBOL               = "XAUUSDm"
R_LOT_FIXED            = 0.01
R_MAX_POSITIONS        = 5        # SCALED DOWN 2026-05-25: $60 account → 5 max (was 12)
R_DAILY_CAP_USD        = 99999.0  # USER OVERRIDE 2026-05-25: no daily stop, run til win/die
R_CONSEC_LOSS_LIMIT    = 9999     # USER OVERRIDE 2026-05-25: no consec-loss freeze
R_MIN_BALANCE_USD      = 1.0      # USER OVERRIDE 2026-05-25: only bail at $1 (full-balance run)
R_SLIPPAGE_PT          = 30
R_DEVIATION            = 30
R_COMMENT_PREFIX       = "R"      # broker comment

# ─── Trailing SL (lock profits aggressively) ───
# Tightened 2026-05-26 per user: was capturing too small a piece of moves.
R_BREAKEVEN_TRIGGER_USD = 0.20    # was 0.50 — move SL to entry MUCH faster
R_BREAKEVEN_BUFFER_USD  = 0.05    # SL set this much past entry on the safe side
R_TRAIL_TRIGGER_USD     = 0.40    # was 1.00 — start trailing at smaller profit
R_USE_ADAPTIVE_TRAILING = True    # confidence-aware adaptive_trailing.py is primary
R_TRAIL_DISTANCE_USD    = 0.80    # was 1.50 — trail tighter behind price
R_TRAIL_STEP_USD        = 0.05    # was 0.20 — react to every $0.05 of improvement

import os as _os
_BYPASS_QS = []
if _os.environ.get("R_BYPASS_SESSION","0") == "1": _BYPASS_QS.append("bypass_session=1")
if _os.environ.get("R_BYPASS_WEEKEND","0") == "1": _BYPASS_QS.append("bypass_weekend=1")
if _os.environ.get("R_BYPASS_FRIDAY", "0") == "1": _BYPASS_QS.append("bypass_friday=1")
_QS = ("?" + "&".join(_BYPASS_QS)) if _BYPASS_QS else ""
GATE_URL    = f"http://localhost:5055/api/r/trade_gate{_QS}"
ACCOUNT_URL = "http://localhost:5055/api/account?hours=24"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_DEFAULT_STATE = {
    "mode":             "PAPER",
    "ts":               "",
    "armed":            False,
    "frozen_until":     None,
    "frozen_reason":    None,
    "consec_losses":    0,
    "today_pl":         0.0,
    "today_date":       "",
    "total_trades":     0,
    "total_wins":       0,
    "total_pl":         0.0,
    "last_ticket":      None,
    "last_action":      "boot",
    "last_log":         [],
    "brain_cycle":      0,
    "broker_offset_s":  0,
    "paper_open":       None,
}

def _load_state() -> dict:
    s = dict(_DEFAULT_STATE)
    s["ts"] = _now_iso()
    s["today_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            s.update(loaded)
            # Ensure all defaults present (heal old files)
            for k, v in _DEFAULT_STATE.items():
                s.setdefault(k, v)
        except Exception: pass
    return s


def _save_state(state: dict):
    state["ts"] = _now_iso()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def _append_trade_csv(row: dict):
    new = not TRADES_CSV.exists()
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ts","mode","action","ticket","symbol","side","lot","entry","sl",
            "near_tp","far_tp","archetype","confidence","exit_price","exit_reason",
            "profit_usd","r_consec_losses","r_today_pl"])
        if new: w.writeheader()
        w.writerow(row)


def _http_json(url: str, timeout=10) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def _write_brain_json(gate: dict, state: dict, in_position: bool = False):
    """Translate R Trade Gate verdict into the format the EA expects.

    The EA (`FRIDAY_Brain_Executor.mq5`) only accepts PENDING orders
    (BUY_STOP / BUY_LIMIT / SELL_STOP / SELL_LIMIT). We compose entries
    that act as STOP orders just past current market price — fill
    immediately if price moves slightly in our direction (a
    breakout-style entry, which fits BREAKOUT_HUNTER archetype perfectly).
    """
    cycle = int(state.get("brain_cycle", 0)) + 1
    state["brain_cycle"] = cycle

    verdict = gate.get("verdict") or "WAIT"
    if verdict == "GO" and not in_position:
        action = "PLACE"
    elif verdict == "NO" and gate.get("hard_blockers"):
        action = "WAIT"
    else:
        action = "WAIT"

    # ─── Convert market-style entry to PENDING STOP order ───
    side  = gate.get("side") or ""
    entry = gate.get("entry") or 0
    sl    = gate.get("sl") or 0
    near  = gate.get("near_tp") or 0
    far   = gate.get("far_tp") or 0

    # Read live tick to compute stop-order offset (~$0.20 = 200pt above/below market)
    PENDING_OFFSET_PRICE = 0.20    # 200 actual MT5 points
    if action == "PLACE" and side and entry:
        try:
            with urllib.request.urlopen(
                "http://localhost:5055/api/chart",
                timeout=3) as r:
                ch = json.loads(r.read().decode())
                lv = ch.get("levels", {})
                bid, ask = float(lv.get("bid", 0)), float(lv.get("ask", 0))
        except Exception:
            bid, ask = 0, 0
        if bid and ask:
            if side == "BUY":
                # BUY_STOP just above ask (catches breakout up)
                new_entry = ask + PENDING_OFFSET_PRICE
                # Adjust SL/TP to keep R:R based on new entry
                shift = new_entry - entry
                entry = new_entry
                sl   += shift
                near += shift
                far  += shift
            elif side == "SELL":
                # SELL_STOP just below bid (catches breakdown)
                new_entry = bid - PENDING_OFFSET_PRICE
                shift = new_entry - entry
                entry = new_entry
                sl   += shift
                near += shift
                far  += shift

    decision = {
        "final_action": action,
        "side":         side,
        "entry":        round(entry, 3) if entry else 0,
        "sl":           round(sl, 3) if sl else 0,
        "tp":           round(far, 3) if far else 0,
        "near_tp":      round(near, 3) if near else 0,
        "lot":          0.01,
        "confidence":   gate.get("confidence") or 0,
        "archetype":    gate.get("archetype") or "",
        "reason":       (gate.get("reason_ar") or "")[:200],
    }

    # MT5's TimeCurrent() returns BROKER server time. We compute the broker-time
    # offset once from the last tick, then always advance with local time so
    # tick stalling (Friday quiet hours) doesn't make our epoch go backward.
    broker_now = None
    try:
        t = mt5.symbol_info_tick(R_SYMBOL)
        utc_now = int(datetime.now(timezone.utc).timestamp())
        if t and t.time > 0:
            offset = int(t.time) - utc_now
            # Cap offset to ±13h to avoid wild values from a stale tick
            if -13*3600 <= offset <= 13*3600:
                state["broker_offset_s"] = offset
        offset = int(state.get("broker_offset_s", 0))
        broker_now = utc_now + offset
    except Exception: pass
    if broker_now is None:
        broker_now = int(datetime.now(timezone.utc).timestamp())
    broker_epoch = broker_now

    payload = {
        "epoch":   broker_epoch,
        "epoch_utc": int(datetime.now(timezone.utc).timestamp()),  # for debugging
        "cycle":   cycle,
        "source":  "R_EXECUTOR",
        "killed":  False,
        "decision": decision,
        "drawings": [],
    }
    try:
        MT5_COMMON.mkdir(parents=True, exist_ok=True)
        tmp = BRAIN_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(BRAIN_JSON)   # atomic swap
    except Exception as e:
        _log(state, f"⚠ failed to write Brain JSON: {e}")


def _log(state: dict, msg: str):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line)
    state.setdefault("last_log", []).append(line)
    state["last_log"] = state["last_log"][-50:]


def _mt5_init() -> bool:
    if not mt5.initialize():
        return False
    info = mt5.account_info()
    return info is not None


def _r_positions(symbol: str = None) -> list:
    """R-magic positions across ALL symbols (or filter to one)."""
    pos = mt5.positions_get(symbol=symbol) if symbol else (mt5.positions_get() or [])
    return [p for p in (pos or []) if p.magic == R_MAGIC]


def _brain_magic_positions() -> list:
    """Positions opened by the EA (magic 20260600) across all symbols."""
    return [p for p in (mt5.positions_get() or []) if p.magic == 20260600]


def _ensure_symbol_ready(symbol: str) -> bool:
    """Make sure MT5 has this symbol selected in Market Watch (required for trading)."""
    if not mt5.symbol_info(symbol):
        return False
    if not mt5.symbol_info(symbol).visible:
        if not mt5.symbol_select(symbol, True):
            return False
    return True


def _modify_sl(ticket: int, new_sl: float, tp: float) -> tuple[bool, str]:
    """Move SL on an existing position. Returns (ok, msg)."""
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": int(ticket),
        "sl":       float(new_sl),
        "tp":       float(tp),
    }
    res = mt5.order_send(req)
    if res is None:
        return False, f"send None, err={mt5.last_error()}"
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        return True, "OK"
    return False, f"retcode={res.retcode} {res.comment}"


def manage_trailing(state: dict, mode: str):
    """For every R-magic position (across ALL symbols), lock profit aggressively:
       1) once floating P/L ≥ R_BREAKEVEN_TRIGGER_USD → move SL to entry ± buffer
       2) once floating P/L ≥ R_TRAIL_TRIGGER_USD → trail SL R_TRAIL_DISTANCE_USD behind price
       SL only moves IN OUR FAVOR (never widened).
    """
    if mode != "LIVE":
        return
    positions = _r_positions()    # ALL symbols, magic 20260605
    if not positions: return

    for p in positions:
        sym = mt5.symbol_info(p.symbol)
        if not sym: continue
        digits = sym.digits
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick: continue
        bid, ask = tick.bid, tick.ask

        # For 0.01 lot of XAU: 1 price unit = $1 P/L (contract_size 100)
        if p.type == 0:   # BUY
            unreal = (bid - p.price_open) * p.volume * 100
            # SL must be BELOW current bid
            # BE target = entry + buffer (small profit-locked SL)
            be_sl   = p.price_open + R_BREAKEVEN_BUFFER_USD
            trail_sl = bid - R_TRAIL_DISTANCE_USD
        else:             # SELL
            unreal = (p.price_open - ask) * p.volume * 100
            # SL must be ABOVE current ask
            be_sl   = p.price_open - R_BREAKEVEN_BUFFER_USD
            trail_sl = ask + R_TRAIL_DISTANCE_USD

        new_sl = None; reason = ""

        # Stage 0 (NEW): adaptive trailing driven by live gate confidence.
        # Runs from the first cent of profit — much more responsive than the
        # fixed BE+trail stages. Falls through to legacy stages if it returns
        # None (e.g. micro-gain guard tripped).
        if R_USE_ADAPTIVE_TRAILING:
            try:
                from r_native.adaptive_trailing import compute_adaptive_sl
                side_str = "BUY" if p.type == 0 else "SELL"
                cur_px   = bid if p.type == 0 else ask
                spread_price = (ask - bid) if (ask and bid and ask > bid) else 0
                adp_sl, adp_reason = compute_adaptive_sl(
                    ticket=int(p.ticket),
                    symbol=p.symbol,
                    side=side_str,
                    current_price=cur_px,
                    entry=p.price_open,
                    tp=p.tp,
                    current_sl=p.sl,
                    spread_price=spread_price,
                )
                if adp_sl is not None:
                    new_sl = adp_sl
                    reason = f"adapt: {adp_reason}"
            except Exception as _ae:
                pass    # any failure falls through to legacy stages

        # Stage 2: trailing (only if profit big enough)
        if new_sl is None and unreal >= R_TRAIL_TRIGGER_USD:
            if p.type == 0:   # BUY: only move SL UP
                if trail_sl > p.sl + R_TRAIL_STEP_USD:
                    new_sl = trail_sl; reason = f"trail (P/L=${unreal:.2f})"
            else:             # SELL: only move SL DOWN
                if trail_sl < p.sl - R_TRAIL_STEP_USD:
                    new_sl = trail_sl; reason = f"trail (P/L=${unreal:.2f})"

        # Stage 1: break-even (only if not yet at BE)
        elif new_sl is None and unreal >= R_BREAKEVEN_TRIGGER_USD:
            if p.type == 0:   # BUY
                if p.sl < be_sl - R_TRAIL_STEP_USD/2:
                    new_sl = be_sl; reason = f"BE+ (P/L=${unreal:.2f})"
            else:             # SELL
                if p.sl > be_sl + R_TRAIL_STEP_USD/2:
                    new_sl = be_sl; reason = f"BE+ (P/L=${unreal:.2f})"

        if new_sl is not None:
            new_sl = round(new_sl, digits)
            ok, msg = _modify_sl(p.ticket, new_sl, p.tp)
            if ok:
                _log(state, f"🔒 #{p.ticket} SL {p.sl:.{digits}f} → {new_sl:.{digits}f}  {reason}")
                # Record so we don't misread it as user override
                record_r_sl_move(p.ticket, new_sl, reason)
            else:
                _log(state, f"⚠ #{p.ticket} SL move failed: {msg}")

        # ── Detect MANUAL SL/TP changes (user edited via MT5) ──
        ov = detect_manual_override(p.ticket, p.sl, p.tp, digits)
        if ov:
            intents = ov.get("intents", [])
            _log(state, f"🧠 #{p.ticket} USER OVERRIDE: {','.join(intents)} "
                       f"SL {ov['from_sl']}→{ov['to_sl']} TP {ov['from_tp']}→{ov['to_tp']}")


def _send_order(symbol: str, side: str, lot: float, sl: float, tp: float,
                comment: str) -> tuple[bool, dict]:
    """Send a market order on ANY symbol. Returns (ok, raw_result_dict)."""
    if not _ensure_symbol_ready(symbol):
        return False, {"reason": f"symbol_select failed: {symbol}"}
    sym = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not tick or not sym:
        return False, {"reason": f"no tick for {symbol}"}
    price = tick.ask if side == "BUY" else tick.bid
    # Clamp lot to symbol's volume_step / min / max
    lot_step = sym.volume_step or 0.01
    lot = max(sym.volume_min, min(sym.volume_max or 100, lot))
    lot = round(round(lot / lot_step) * lot_step, 2)
    # Round SL/TP to symbol digits
    digits = sym.digits
    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       float(lot),
        "type":         mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
        "price":        round(float(price), digits),
        "sl":           round(float(sl), digits),
        "tp":           round(float(tp), digits),
        "deviation":    R_DEVIATION,
        "magic":        R_MAGIC,
        "comment":      comment[:31],
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res is None:
        return False, {"reason": f"send returned None, err={mt5.last_error()}"}
    return res.retcode == mt5.TRADE_RETCODE_DONE, {
        "retcode":  res.retcode,
        "comment":  res.comment,
        "order":    res.order,
        "deal":     res.deal,
        "volume":   res.volume,
        "price":    res.price,
        "symbol":   symbol,
    }


def check_freeze(state: dict) -> bool:
    """Return True if executor is frozen and must NOT trade."""
    # Day rollover
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("today_date") != today:
        state["today_date"]    = today
        state["today_pl"]      = 0.0
        state["consec_losses"] = 0
        state["frozen_until"]  = None
        state["frozen_reason"] = None
        _log(state, f"🗓 day rollover — counters reset")

    if state.get("frozen_until"):
        try:
            until = datetime.fromisoformat(state["frozen_until"])
            if datetime.now(timezone.utc) < until:
                return True
            # thaw
            _log(state, "🔥 freeze expired — resumed")
            state["frozen_until"] = None
            state["frozen_reason"] = None
        except Exception:
            state["frozen_until"] = None

    # Daily PL cap
    if state.get("today_pl", 0) <= -abs(R_DAILY_CAP_USD):
        state["frozen_until"] = (datetime.now(timezone.utc).replace(
                                  hour=23, minute=59, second=59)).isoformat()
        state["frozen_reason"] = f"daily PL ${state['today_pl']:.2f} ≤ -${R_DAILY_CAP_USD}"
        _log(state, f"🛑 FREEZE: {state['frozen_reason']}")
        return True

    # Consec losses
    if state.get("consec_losses", 0) >= R_CONSEC_LOSS_LIMIT:
        state["frozen_until"] = (datetime.now(timezone.utc).replace(
                                  hour=23, minute=59, second=59)).isoformat()
        state["frozen_reason"] = f"{state['consec_losses']} consecutive losses"
        _log(state, f"🛑 FREEZE: {state['frozen_reason']}")
        return True

    return False


def reconcile_paper_position(state: dict):
    """Check live tick vs paper position SL/TP."""
    pp = state.get("paper_open")
    if not pp: return
    tick = mt5.symbol_info_tick(R_SYMBOL)
    if not tick: return
    bid, ask = tick.bid, tick.ask

    closed = False; profit = 0.0; exit_reason = ""
    if pp["side"] == "BUY":
        # Bid hits SL (close at bid)
        if bid <= pp["sl"]:
            profit = (pp["sl"] - pp["entry"]) * pp["lot"] * 100
            exit_reason = "SL"; closed = True
            exit_price = pp["sl"]
        elif bid >= pp["far_tp"]:
            profit = (pp["far_tp"] - pp["entry"]) * pp["lot"] * 100
            exit_reason = "TP"; closed = True
            exit_price = pp["far_tp"]
    else:  # SELL
        if ask >= pp["sl"]:
            profit = (pp["entry"] - pp["sl"]) * pp["lot"] * 100
            exit_reason = "SL"; closed = True
            exit_price = pp["sl"]
        elif ask <= pp["far_tp"]:
            profit = (pp["entry"] - pp["far_tp"]) * pp["lot"] * 100
            exit_reason = "TP"; closed = True
            exit_price = pp["far_tp"]

    if closed:
        profit = round(profit, 2)
        state["today_pl"] += profit
        state["total_pl"] += profit
        state["total_trades"] += 1
        if profit > 0:
            state["total_wins"] += 1
            state["consec_losses"] = 0
            emj = "✅"
        else:
            state["consec_losses"] += 1
            emj = "❌"
        _log(state, f"{emj} PAPER {pp['side']} closed @ {exit_price} ({exit_reason}) P/L ${profit:+.2f}  today=${state['today_pl']:+.2f}")
        _append_trade_csv({
            "ts": _now_iso(), "mode": "PAPER", "action": "CLOSE",
            "ticket": 0, "symbol": R_SYMBOL, "side": pp["side"],
            "lot": pp["lot"], "entry": pp["entry"], "sl": pp["sl"],
            "near_tp": pp["near_tp"], "far_tp": pp["far_tp"],
            "archetype": pp["archetype"], "confidence": "",
            "exit_price": exit_price, "exit_reason": exit_reason,
            "profit_usd": profit,
            "r_consec_losses": state["consec_losses"],
            "r_today_pl": state["today_pl"],
        })
        state["paper_open"] = None


def reconcile_closed_positions(state: dict, mode: str):
    """Find R positions that closed since last loop → record their P/L."""
    if mode == "PAPER":
        reconcile_paper_position(state)
        return

    last_ticket = state.get("last_ticket")
    if not last_ticket: return

    current = _r_positions()
    if any(p.ticket == last_ticket for p in current):
        return   # still open

    # Position closed — find it in history
    if mode != "LIVE":
        return   # paper mode handled above

    from datetime import timedelta as _td
    since = datetime.now() - _td(hours=24)
    deals = mt5.history_deals_get(since, datetime.now()) or []
    matching = [d for d in deals if d.position_id == last_ticket and d.entry == 1]
    if not matching:
        _log(state, f"   ticket {last_ticket} closed but no closing deal yet")
        return

    closing = matching[-1]
    profit = float(closing.profit) + float(closing.swap) + float(closing.commission)
    state["today_pl"] += profit
    state["total_pl"] += profit
    state["total_trades"] += 1
    won = profit > 0
    if won:
        state["total_wins"] += 1
        state["consec_losses"] = 0
        emj = "✅"
    else:
        state["consec_losses"] += 1
        emj = "❌"
    _log(state, f"{emj} R trade {last_ticket} closed: P/L ${profit:+.2f}  today=${state['today_pl']:+.2f}")
    # ── Learning: feed closed-trade outcome to the adaptive model
    try:
        # Determine exit reason from closing price vs orig SL/TP
        exit_reason = "MANUAL"
        from friday_v3.algory.r_learning import get_trade_origin as _gto
        o = _gto(last_ticket)
        if o:
            entry_p = o["open_price"]
            close_p = float(closing.price)
            last_sl = o.get("last_observed_sl", o["orig_sl"])
            last_tp = o.get("last_observed_tp", o["orig_tp"])
            if abs(close_p - last_sl) < 0.5:    exit_reason = "SL"
            elif abs(close_p - last_tp) < 0.5:  exit_reason = "TP"
            elif (o["side"] == "BUY"  and close_p > entry_p) or \
                 (o["side"] == "SELL" and close_p < entry_p):
                exit_reason = "TRAIL_TP" if o.get("r_sl_history") else "WIN_CLOSE"
            else:
                exit_reason = "TRAIL_SL" if o.get("r_sl_history") else "LOSS_CLOSE"
        record_closed_trade(int(last_ticket), float(closing.price), profit, exit_reason)
        _log(state, f"  📚 learning updated: exit={exit_reason}")
        # Adaptive trailing — drop ticket from baseline state so file stays small
        try:
            from r_native.adaptive_trailing import forget_ticket
            forget_ticket(int(last_ticket))
        except Exception: pass
        # Exposure guard — record the close so cool-down + DD floor track today
        try:
            from r_native.exposure_guard import record_close as _expo_close
            sym = getattr(closing, "symbol", R_SYMBOL)
            _expo_close(sym,
                        "BUY" if getattr(closing, "type", 0) == 0 else "SELL",
                        int(last_ticket), float(profit), exit_reason)
        except Exception: pass
        # Also update the per-symbol book (blacklist/whitelist tracking)
        try:
            from friday_v3.algory.r_multi_symbol import record_symbol_trade
            sym = getattr(closing, "symbol", R_SYMBOL)
            symrec = record_symbol_trade(sym, profit)
            if symrec.get("status") == "BLACKLIST":
                _log(state, f"  🚫 {sym} → BLACKLIST (WR {symrec['win_rate']}%, net ${symrec['net_pl']})")
            elif symrec.get("status") == "WHITELIST":
                _log(state, f"  ⭐ {sym} → WHITELIST (WR {symrec['win_rate']}%, net ${symrec['net_pl']})")
        except Exception as e:
            _log(state, f"  [symbol_book err: {e}]")
        # ── R Native v2: per-symbol learning bucket
        try:
            from r_native.symbol_learning import record_trade as record_sym
            from datetime import datetime as _dt
            orig = _gto(last_ticket) if o else None
            record_sym(
                symbol=sym,
                profit=profit,
                archetype=(o or {}).get("archetype", "UNKNOWN"),
                side=(o or {}).get("side", "?"),
                entry=(o or {}).get("open_price", 0),
                exit_price=float(closing.price),
                sl=(o or {}).get("last_observed_sl", (o or {}).get("orig_sl", 0)),
                tp=(o or {}).get("last_observed_tp", (o or {}).get("orig_tp", 0)),
                duration_min=((o or {}).get("open_ts") and
                    (_dt.now(__import__("datetime").timezone.utc) - _dt.fromisoformat(o["open_ts"].replace("Z","+00:00"))).total_seconds()/60) or 0,
                exit_reason=exit_reason,
                hour_utc=(o or {}).get("hour_utc", 0),
            )
            _log(state, f"  🧬 per-symbol intel updated for {sym}")
        except Exception as e:
            _log(state, f"  [symbol_learning err: {e}]")
        # ── Hall of Fame live P/L tracker — credits the ACTUAL genome that
        # opened the trade (parsed from the OPEN deal's comment).
        # OLD BUG: was crediting symbol's primary deployed_genome, even
        # when a competitor genome was the real opener. Plus when SL/TP
        # closed the trade, broker overwrote close-deal comment with
        # "[sl X]" / "[tp Y]" losing the R-<gid>-<side> tag entirely.
        # FIX: look up the OPEN deal for this ticket → parse its comment.
        _dl_genome_id = None
        try:
            from r_native.hall_of_fame import record_live_trade
            import re as _re
            _opener_gid = None
            try:
                # Find the OPEN deal (entry=0) for this position ticket
                _open_deals = mt5.history_deals_get(position=int(last_ticket)) or []
                for _d in _open_deals:
                    if int(_d.entry) == 0:
                        m = _re.match(r"R-([A-F0-9]{6})-", _d.comment or "")
                        if m:
                            _opener_gid = m.group(1)
                            break
            except Exception: pass
            if _opener_gid:
                # Pass symbol so HoF can auto-create a stub if this genome
                # isn't yet registered (retired competitors keep trading).
                _opener_sym = None
                try:
                    for _d in _open_deals:
                        if int(_d.entry) == 0:
                            _opener_sym = getattr(_d, "symbol", None); break
                except Exception: pass
                record_live_trade(_opener_gid, profit, symbol=_opener_sym)
                _dl_genome_id = _opener_gid
                _log(state, f"  🏆 HoF: ${profit:+.2f} → genome {_opener_gid} (from open comment)")
            else:
                _log(state, f"  ⚠ HoF: ticket {last_ticket} has no R-<gid>- open comment")
        except Exception as e:
            _log(state, f"  [HoF live tracker err: {e}]")
        # ── Decision log: persist trade CLOSE (fail-soft) ──
        try:
            if HAS_DECISION_LOG and _decision_log is not None:
                # If HoF lookup didn't find a genome, try query_by_ticket as fallback
                _close_gid = _dl_genome_id
                if not _close_gid:
                    try:
                        _prev = _decision_log.query_by_ticket(int(last_ticket))
                        if _prev: _close_gid = _prev.get("genome_id")
                    except Exception: pass
                _decision_log.record_close(
                    ticket=int(last_ticket),
                    genome_id=_close_gid,
                    exit_price=float(closing.price),
                    profit=profit,
                    exit_reason=exit_reason,
                )
        except Exception as e:
            _log(state, f"  [decision_log close err: {e}]")
    except Exception as e:
        _log(state, f"  [learning close err: {e}]")
    _append_trade_csv({
        "ts": _now_iso(), "mode": mode, "action": "CLOSE",
        "ticket": last_ticket, "symbol": R_SYMBOL, "side": "",
        "lot": "", "entry": "", "sl": "", "near_tp": "", "far_tp": "",
        "archetype": "", "confidence": "",
        "exit_price": closing.price, "exit_reason":
        "TP" if won else "SL",
        "profit_usd": profit,
        "r_consec_losses": state["consec_losses"],
        "r_today_pl": state["today_pl"],
    })
    state["last_ticket"] = None


def _pick_best_symbol(state: dict) -> str:
    """Multi-symbol scanner: returns the highest-quality TRADEABLE symbol now.

    PRIORITY: symbols with a deployed_genome are checked FIRST — those are
    the user's hand-picked strategies and shouldn't lose to a random
    high-quality scan candidate that may not even have a genome.
    """
    # ── PRIORITY 0: symbols with deployed_genome get first look ──
    # If any of them has a passing trade_gate, return immediately. This
    # makes "DEPLOY a genome on BTCUSDm" actually mean what the user
    # thinks it means: the executor focuses on that symbol.
    try:
        from pathlib import Path as _P
        import json as _j
        cfg_dir = _P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        deployed_syms = []
        if cfg_dir.exists():
            for p in cfg_dir.glob("*.json"):
                try:
                    cfg = _j.loads(p.read_text(encoding="utf-8"))
                    dg = cfg.get("deployed_genome") or {}
                    if dg.get("id") and (dg.get("flags") or {}) \
                       and cfg.get("tradeable", True):
                        deployed_syms.append((p.stem, float(dg.get("score") or 0)))
                except Exception: continue
        # Rank deployed symbols by genome score (highest first)
        deployed_syms.sort(key=lambda x: x[1], reverse=True)
        held = { (p.symbol, "BUY" if p.type == 0 else "SELL")
                  for p in (_r_positions() or []) }
        held_syms = {sym for sym, _ in held}
        # Round-robin index per cycle so all deployed symbols get checked
        # over time, not just the highest-scored one. The deployed_syms list
        # is already sorted highest-score-first; we rotate through them.
        rr_idx = int(state.get("_deployed_rr_idx", 0))
        n = len(deployed_syms)
        for offset in range(n):
            sym, score = deployed_syms[(rr_idx + offset) % n]
            if sym in held_syms: continue
            # NOTE: skip symbol_learning trust check — deploy is explicit user intent
            state["best_symbol_now"]     = sym
            state["best_symbol_quality"] = 100  # deployed always wins
            state["scanner_mode"]        = "deployed_priority"
            state["_deployed_rr_idx"]    = (rr_idx + offset + 1) % n
            return sym
    except Exception as _e:
        pass

    # ── PRIORITY 1: fallback to ranked scan of all tradeable symbols ──
    try:
        from friday_v3.algory.r_multi_symbol import rank_symbols
        ranking = rank_symbols(max_symbols=80)
        if not (ranking.get("ok") and ranking.get("candidates")):
            return R_SYMBOL
        cands = ranking["candidates"]
        held = { (p.symbol, "BUY" if p.type == 0 else "SELL")
                  for p in (_r_positions() or []) }
        held_syms = {sym for sym, _ in held}
        state["symbols_scanned"] = ranking["total_tradeable"]

        # Lazy-import gates so failure doesn't kill the cycle
        try:
            from r_native.symbol_learning import should_trade_symbol
        except Exception:
            should_trade_symbol = lambda _s: (True, "")
        try:
            from r_native.exposure_guard import can_open
        except Exception:
            can_open = lambda _s, _d: (True, "")

        # Lazy import seeder — never fail the cycle if missing
        try:
            from r_native.genome_seeder import ensure_seeded
        except Exception:
            ensure_seeded = lambda _s: (False, "no seeder")

        # Fetch free margin once so the affordability filter doesn't burn it
        try:
            _acc = mt5.account_info()
            _free_margin = float(getattr(_acc, "margin_free", 0) or 0)
        except Exception:
            _free_margin = 0

        for c in cands:
            sym = c["symbol"]
            if sym in held_syms: continue
            ok, _why = should_trade_symbol(sym)
            if not ok: continue
            # exposure side-agnostic check: if BOTH sides are blocked, skip;
            # otherwise pass it through (gate decides direction later)
            ok_b, _ = can_open(sym, "BUY")
            ok_s, _ = can_open(sym, "SELL")
            if not (ok_b or ok_s): continue
            # Affordability gate — compute the margin a 0.01-lot order on this
            # symbol would need, and skip if free margin * 0.83 < need. Without
            # this the scanner sticks on a high-margin symbol like USTEC_x100m
            # ($45 margin) that the executor's pre-flight will reject every
            # cycle, instead of falling through to a cheaper symbol it can
            # actually afford in the SAME cycle.
            try:
                _ref_px = c.get("ask") or c.get("bid") or 0
                _need = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 0.01, _ref_px)
                if _need is not None and _need > _free_margin * 0.83:
                    continue
            except Exception: pass
            # NOTE: auto-seeding DISABLED. It was creating empty-flag stubs
            # for every symbol the scanner touched, polluting the system
            # with 1600+ fake HoF entries + 24 fake symbol_configs.
            # Symbols only get genomes via deliberate deploy_multi_symbol.py
            # or via continuous_evolution discovering a real one.
            pass
            state["best_symbol_now"]     = sym
            state["best_symbol_quality"] = c["quality"]
            return sym

        # All filtered out — fall back to top-quality candidate to keep state
        # populated, but the gate/exposure will block anyway
        top = cands[0]
        state["best_symbol_now"]     = top["symbol"]
        state["best_symbol_quality"] = top["quality"]
        return top["symbol"]
    except Exception as e:
        _log(state, f"  scanner err: {e}")
    return R_SYMBOL


def _list_deployed_pairs() -> list[tuple[str, str, float]]:
    """Return (symbol, genome_id, score) for EVERY deployed competitor.
    A symbol can have multiple competing genomes — each gets its own gate
    evaluation and own position. The HoF tracks per-genome live PnL so
    after ~20 trades each, we can see which one wins on that symbol.
    """
    try:
        from pathlib import Path as _P
        import json as _j
        cfg_dir = _P(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")
        out = []
        for p in cfg_dir.glob("*.json"):
            try:
                cfg = _j.loads(p.read_text(encoding="utf-8"))
                if not cfg.get("tradeable", True): continue
                # competitors list (NEW) takes priority; falls back to
                # singular deployed_genome (legacy single-deploy)
                comps = cfg.get("competitors") or []
                if not comps and cfg.get("deployed_genome"):
                    comps = [cfg["deployed_genome"]]
                for g in comps:
                    gid = g.get("id")
                    if not gid: continue
                    if not any((g.get("flags") or {}).values()): continue
                    out.append((p.stem, gid, float(g.get("score") or 0)))
            except Exception: continue
        # Sort highest-score first
        out.sort(key=lambda x: -x[2])
        return out
    except Exception:
        return []


def _list_deployed_symbols() -> list[str]:
    """Legacy: unique symbol list for fallback path."""
    return list({s for s,_,_ in _list_deployed_pairs()})


def try_enter_trade(state: dict, mode: str):
    """Aggressive multi-PAIR scan: every cycle, check the gate for EVERY
    (symbol, genome) competitor. Each genome on a symbol is treated as
    its own strategy — its OWN gate evaluation, its OWN position. After
    enough trades the HoF live_pnl per genome reveals the winner.
    """
    pairs = _list_deployed_pairs()
    if not pairs:
        return _try_enter_one_symbol(state, mode, None)

    # Avoid stacking: each (symbol, genome) competitor can only have ONE
    # open position at a time (via R-<gid>-<side> comment matching).
    open_by_gid = {}    # gid -> count of open positions tagged with that gid
    for p in (_r_positions() or []):
        comment = (p.comment or "")
        if comment.startswith("R-"):
            parts = comment.split("-", 2)
            if len(parts) >= 2:
                gid = parts[1]
                open_by_gid[gid] = open_by_gid.get(gid, 0) + 1

    held_count = sum(open_by_gid.values())
    fired = 0
    scans = 0
    for sym, gid, score in pairs:
        if held_count >= R_MAX_POSITIONS: break
        if open_by_gid.get(gid, 0) >= 1:
            continue   # this genome already has an open position somewhere
        scans += 1
        # Force the executor's symbol AND the genome id for this iteration
        state["_force_symbol_override"]  = sym
        state["_force_genome_override"]  = gid
        before = sum(1 for p in (_r_positions() or [])
                     if f"R-{gid}-" in (p.comment or ""))
        _try_enter_one_symbol(state, mode, sym)
        after = sum(1 for p in (_r_positions() or [])
                    if f"R-{gid}-" in (p.comment or ""))
        if after > before:
            fired += 1
            held_count += 1
            open_by_gid[gid] = open_by_gid.get(gid, 0) + 1
    state.pop("_force_symbol_override", None)
    state.pop("_force_genome_override", None)

    if fired:
        _log(state, f"  🎯 fired {fired} new trades across {scans} (sym,genome) pairs")
        state["last_action"] = f"fired {fired}/{scans}"
    elif scans:
        state["last_action"] = f"scanned {scans} pairs, none GO"


def _try_enter_one_symbol(state: dict, mode: str, force_sym: str):
    """Single-symbol gate + entry — the legacy try_enter_trade body."""
    if force_sym:
        best_sym = force_sym
        state["best_symbol_now"]     = force_sym
        state["best_symbol_quality"] = 100
        state["scanner_mode"]        = "multi_scan"
    else:
        best_sym = _pick_best_symbol(state)
    # Build gate URL — if competition mode set a specific genome to test
    # on this iteration, append it so trade_gate uses THAT genome's flags
    extras = []
    if best_sym != R_SYMBOL:
        extras.append(f"symbol={best_sym}")
    gov = state.get("_force_genome_override")
    if gov:
        extras.append(f"genome={gov}")
    if extras:
        sep = "&" if "?" in GATE_URL else "?"
        gate_url_with_sym = GATE_URL + sep + "&".join(extras)
    else:
        gate_url_with_sym = GATE_URL
    gate = _http_json(gate_url_with_sym, timeout=8)
    if not gate or gate.get("verdict") == "ERROR":
        _log(state, f"  gate error: {gate.get('reason_ar', gate.get('_error',''))}")
        state["last_action"] = "gate_error"
        _write_brain_json({"verdict": "WAIT", "reason_ar": "gate_error"}, state, in_position=False)
        return

    verdict = gate.get("verdict")
    state["last_action"] = f"gate={verdict}"

    # Count CURRENT R positions
    if mode == "LIVE":
        r_positions = _r_positions()
        r_count = len(r_positions)
    else:
        # In PAPER, we don't allow multiple (paper bookkeeping is single-trade)
        r_count = 1 if state.get("paper_open") else 0

    ea_in_position = bool(_brain_magic_positions())
    _write_brain_json(gate, state, in_position=ea_in_position)

    if verdict != "GO":
        return

    if r_count >= R_MAX_POSITIONS:
        state["last_action"] = f"R at max positions ({r_count}/{R_MAX_POSITIONS})"
        return

    # ─── R Native v2: per-symbol gate ───
    proposed_symbol = state.get("best_symbol_now", R_SYMBOL)
    lot_multiplier = 1.0
    try:
        from r_native.symbol_learning import should_trade_symbol, get_symbol_intelligence
        ok, why = should_trade_symbol(proposed_symbol)
        if not ok:
            state["last_action"] = f"{proposed_symbol} blocked: {why}"
            _log(state, f"  🚫 symbol_learning blocks {proposed_symbol}: {why}")
            return
        intel = get_symbol_intelligence(proposed_symbol)
        verdict = intel.get("verdict", "UNKNOWN")
        if verdict == "PREFERRED":
            lot_multiplier = 1.0           # full lot for proven winners
        elif verdict == "OK":
            lot_multiplier = 0.8
        elif verdict == "CAUTION":
            lot_multiplier = 0.5           # half lot
        elif verdict == "UNKNOWN":
            lot_multiplier = 0.6           # cautious on new symbols
        state["symbol_verdict"] = verdict
        state["lot_multiplier"]  = lot_multiplier
    except Exception as e:
        _log(state, f"  [symbol_gate err: {e}]")

    # ─── F2-b OOS efficiency gate: trade what's PROVEN, sized by proof ───
    # robust (4/4 folds) → size up · marginal → as-is · failed OOS → tiny size · unscanned → as-is
    try:
        import json as _oj
        from pathlib import Path as _op
        _g = _oj.loads(_op(r"C:\Users\Radhi\MT5\r_native_v2\data\market_gate.json").read_text(encoding="utf-8"))
        _tier = None
        for _k, _v in _g.get("results", {}).items():
            if _k.replace("_x100m", "m").replace("_x10m", "m") == proposed_symbol:
                _tier = _v.get("tier"); break
        if _tier == "robust":
            lot_multiplier = min(1.5, lot_multiplier * 1.3)
            state["lot_multiplier"] = lot_multiplier
        elif _tier == "fail":
            lot_multiplier = lot_multiplier * 0.3
            state["lot_multiplier"] = lot_multiplier
            _log(state, f"  ⚠ {proposed_symbol} FAILED OOS gate → lot×0.3 (no proven edge)")
        state["oos_tier"] = _tier or "unscanned"
    except Exception:
        pass

    # Apply LLM trust certificate's recommended lot multiplier (intersect with
    # symbol_learning's). Cert is the tighter bound so a low-trust genome
    # never gets full lot even on a PREFERRED symbol.
    try:
        gid_for_cert = (gate.get("deployed_genome_id") or "").upper()
        if gid_for_cert:
            from r_native.genome_certifier import get_certificate
            cert = get_certificate(gid_for_cert)
            if cert:
                cert_mult = float(cert.get("recommended_lot_multiplier") or 1.0)
                ts = int(cert.get("trust_score") or 50)
                if cert_mult < state.get("lot_multiplier", 1.0):
                    _log(state, f"  📜 cert {gid_for_cert} trust={ts} → "
                                f"lot×{cert_mult} (was ×{state['lot_multiplier']})")
                    state["lot_multiplier"] = cert_mult
                state["cert_trust"] = ts
                # REJECT verdict → don't trade at all
                if cert.get("verdict") == "REJECT":
                    state["last_action"] = f"cert REJECT {gid_for_cert} (trust {ts})"
                    _log(state, f"  ⛔ cert REJECT {gid_for_cert} trust={ts} — skip")
                    return
    except Exception: pass

    # ─── Scanner config gate (from full_scan) ───
    try:
        from r_native.scanner import load_symbol_config
        cfg = load_symbol_config(proposed_symbol)
        if cfg.get("tradeable") is False and cfg.get("last_scan"):
            # Scanner has run but found no DEPLOY strategies for this symbol
            state["last_action"] = f"{proposed_symbol} scanner: no DEPLOY strategy"
            _log(state, f"  ⚠ scanner says {proposed_symbol} has no deploy-grade strategy yet")
            # Don't block — just warn (R may still trade if gate says GO)
    except Exception as e:
        _log(state, f"  [config gate err: {e}]")

    # Pre-flight margin check — compute the EXACT margin this trade would
    # need via mt5.order_calc_margin() and compare to free margin + a 20%
    # safety buffer. Stops retcode 10019 ("No money") log floods cleanly.
    if mode == "LIVE":
        try:
            info = mt5.account_info()
            _free = float(getattr(info, "margin_free", 0) or 0)
            _side_int = mt5.ORDER_TYPE_BUY if (gate.get("side") == "BUY") else mt5.ORDER_TYPE_SELL
            _entry   = float(gate.get("entry") or 0)
            _needed  = mt5.order_calc_margin(_side_int, proposed_symbol,
                                              R_LOT_FIXED * state.get("lot_multiplier", 1.0),
                                              _entry)
            if _needed is None: _needed = 0
            if _needed > 0 and _free < _needed * 1.2:
                state["last_action"] = (f"need ${_needed:.2f} margin, "
                                          f"have ${_free:.2f}")
                _log(state, f"  💸 skip {proposed_symbol}: "
                            f"need ${_needed:.2f} × 1.2 buffer > free ${_free:.2f}")
                return
        except Exception: pass

    # Same-SYMBOL same-side proximity guard. Different symbols (even with
    # similar prices like US30m vs US30_x10m) are NOT compared — they're
    # distinct instruments. Only intra-symbol stacking on noise is blocked.
    if mode == "LIVE" and r_positions:
        proposed_symbol_u = (proposed_symbol or "").upper()
        proposed_side = (gate.get("side") or "").upper()
        proposed_entry = gate.get("entry") or 0
        proposed_sl    = gate.get("sl") or 0
        sl_dist = abs(proposed_entry - proposed_sl) if proposed_entry and proposed_sl else 1.0
        for p in r_positions:
            if (p.symbol or "").upper() != proposed_symbol_u:
                continue   # different instrument — skip
            same_side = (p.type == 0 and proposed_side == "BUY") or \
                        (p.type == 1 and proposed_side == "SELL")
            if same_side and abs(p.price_open - proposed_entry) < sl_dist * 0.8:
                state["last_action"] = f"too close to existing #{p.ticket} on {p.symbol} (same side)"
                return
            # Cycle 27 anti-hedge: same symbol, OPPOSITE side. Wastes
            # spread×2 with no possible directional gain (one wins what
            # other loses, both pay spread). Block unless the existing
            # position is already deeply profitable (>$1) where hedging
            # could lock the gain.
            if (not same_side
                    and float(p.profit) < 1.0):
                state["last_action"] = (f"hedge-block: opposite of #{p.ticket} "
                                         f"on {p.symbol} (pl ${p.profit:+.2f})")
                _log(state, f"  🚫 anti-hedge: opposite side of #{p.ticket} "
                            f"on {p.symbol} (pl ${p.profit:+.2f}, only allowed if existing pl>$1)")
                return

    side    = gate.get("side")
    entry   = gate.get("entry")
    sl      = gate.get("sl")
    far_tp  = gate.get("far_tp")
    arch    = gate.get("archetype")
    conf    = gate.get("confidence", 0)

    if not all([side, entry, sl, far_tp]):
        _log(state, f"  GO but missing prices: {side}/{entry}/{sl}/{far_tp}")
        return

    # Use the symbol chosen by the scanner (NOT hardcoded XAUUSDm)
    trade_symbol = state.get("best_symbol_now", R_SYMBOL) or R_SYMBOL
    # Build broker comment so each MT5 trade shows which genome opened it.
    # Format: R-<genome_id>-<side[0]>  (e.g. R-B99880-B → "BUY by genome B99880")
    # Falls back to R-<arch> when no genome_id (Algory-archetype path or ensemble).
    _gid = (gate.get("deployed_genome_id") or "").upper()[:6] if isinstance(gate, dict) else ""
    if _gid:
        comment = f"R-{_gid}-{(side or '?')[0]}"
    else:
        comment = f"{R_COMMENT_PREFIX}_{arch[:6] if arch else 'ALG'}"

    # Apply lot multiplier from per-symbol intel verdict
    base_lot = R_LOT_FIXED * state.get("lot_multiplier", 1.0)
    # 🔥 MONSTER BOOST — if genome qualifies AND live conviction is at ceiling,
    # scale lot up to MONSTER_LOT_CAP_X. Pure additive — failure is no-op.
    monster_mult, monster_reason = 1.0, ""
    try:
        from r_native.monster_genome import compute_lot_multiplier as _monster_mult
        monster_mult, monster_reason = _monster_mult(_gid or None,
                                                     int(gate.get("confidence") or 0))
    except Exception: pass
    if monster_mult > 1.0:
        base_lot *= monster_mult
        state["last_monster_mult"] = monster_mult
        _log(state, f"  🔥 monster boost ×{monster_mult}: {monster_reason}")
    # ⚖ REGIME SCALER — per-symbol-per-side multiplier driven by MTF alignment
    # (M15+H1+H4) from the market_scanner agent. Aligned trends get boosted,
    # counter-trend trades get throttled, DEAD regimes get halved. File is
    # written by agents/regime_scaler.py every 2 min; missing file = 1.0×.
    try:
        from pathlib import Path as _P
        import json as _j
        _rfile = _P(r"C:\Users\Radhi\MT5\data\r_native\regime_multipliers.json")
        if _rfile.exists():
            _rdata = _j.loads(_rfile.read_text(encoding="utf-8"))
            _sym_block = (_rdata.get("symbols") or {}).get(trade_symbol) or {}
            _key = "buy_mult" if (side or "").upper() == "BUY" else "sell_mult"
            _regime_mult = float(_sym_block.get(_key) or 1.0)
            if _regime_mult != 1.0:
                base_lot *= _regime_mult
                state["last_regime_mult"] = _regime_mult
                _log(state, f"  ⚖ regime ×{_regime_mult} ({_sym_block.get('mtf_alignment','?')}"
                            f" {_sym_block.get('alignment_count',0)}/3, "
                            f"{_sym_block.get('regime','?')})")
    except Exception: pass
    effective_lot = round(base_lot, 2)
    if effective_lot < 0.01: effective_lot = 0.01   # broker min

    # ── Cycle 25 SAFETY: drawdown-recovery blocks_new_entries gate ──
    # CRITICAL BUG FOUND: drawdown_recovery agent writes blocks_new_entries=true
    # at severity 3+ but NOBODY was reading the flag. System bled $19 today
    # because the "DD lockout" did nothing. This honors the flag.
    try:
        from pathlib import Path as _P
        import json as _j
        _ddfile = _P(r"C:\Users\Radhi\MT5\data\r_native\dd_recovery_state.json")
        if _ddfile.exists():
            _ddstate = _j.loads(_ddfile.read_text(encoding="utf-8"))
            if _ddstate.get("blocks_new_entries"):
                _ddpct = _ddstate.get("drawdown_pct", 0)
                state["last_action"] = (f"BLOCKED by drawdown_recovery "
                                         f"(DD {_ddpct:.1f}%)")
                _log(state, f"  🛑 DD-BLOCK: new entries blocked "
                            f"(DD {_ddpct:.1f}%, action={_ddstate.get('action','?')})")
                return
    except Exception: pass

    # ── Cycle 39 RECOVERY MODE gate ── (2026-05-27)
    # Active until equity ≥ $105. Blocks every symbol+side combo that
    # wasn't a proven 7-day winner, caps lot to 0.01, max 2 positions.
    # See r_native/agents/recovery_mode.py for the whitelist + reasoning.
    try:
        from r_native.agents.recovery_mode import (
            filter_entry as _rec_filter, max_positions as _rec_max_pos,
            is_recovery_active as _rec_active,
        )
        if _rec_active():
            if r_count >= _rec_max_pos():
                state["last_action"] = (f"RECOVERY: at max {_rec_max_pos()} "
                                          f"positions ({r_count})")
                _log(state, f"  🛟 recovery cap: {r_count}/{_rec_max_pos()}")
                return
            _rec_ok, _rec_lot, _rec_reason = _rec_filter(
                trade_symbol, side or "?", effective_lot)
            if not _rec_ok:
                state["last_action"] = f"RECOVERY blocks {trade_symbol} {side}: {_rec_reason}"
                _log(state, f"  🛟 recovery blocks {trade_symbol} {side}: {_rec_reason}")
                return
            if _rec_lot < effective_lot:
                _log(state, f"  🛟 recovery lot cap: {effective_lot}→{_rec_lot}")
                effective_lot = _rec_lot
    except Exception as _rec_e:
        _log(state, f"  [recovery_mode err: {_rec_e}]")

    # ── Cycle 24 SAFETY: max-loss-per-trade cap ──
    # Compute potential SL distance × pip value × lot. If it would risk
    # more than MAX_SL_LOSS_PCT of account equity, REJECT this entry.
    # This caught a XAGUSDm SELL that had $10.30 SL loss = 8% of $120
    # account — way over our 3% per-trade limit.
    try:
        import MetaTrader5 as _mt5_safety
        _acc = _mt5_safety.account_info()
        _si  = _mt5_safety.symbol_info(trade_symbol)
        if _acc and _si and sl and entry:
            _equity = float(_acc.equity)
            _sl_distance = abs(float(entry) - float(sl))
            # tick_value tells us $ per point per 1.0 lot
            _per_point  = float(_si.trade_tick_value) / max(float(_si.trade_tick_size), 1e-9)
            _max_loss = _sl_distance * _per_point * effective_lot
            _max_loss_pct = (_max_loss / _equity * 100) if _equity > 0 else 0
            MAX_LOSS_PCT = 3.0
            if _max_loss_pct > MAX_LOSS_PCT:
                state["last_action"] = (f"REJECT {trade_symbol} {side}: "
                                         f"SL loss ${_max_loss:.2f} = "
                                         f"{_max_loss_pct:.1f}% > {MAX_LOSS_PCT}% cap")
                _log(state, f"  🛑 SAFETY: rejected — SL loss ${_max_loss:.2f} "
                            f"({_max_loss_pct:.1f}%) > {MAX_LOSS_PCT}% cap")
                return
    except Exception as _safety_e:
        _log(state, f"  [safety check err: {_safety_e}]")

    # ── Exposure Guard: stop churn / DD spirals / stacking ──
    try:
        from r_native.exposure_guard import can_open as _expo_can
        _ok, _why = _expo_can(trade_symbol, side or "?")
        if not _ok:
            state["last_action"] = f"exposure blocks {trade_symbol}: {_why}"
            _log(state, f"  🛡 exposure_guard blocks {trade_symbol} {side}: {_why}")
            return
    except Exception: pass

    if mode == "LIVE":
        ok, res = _send_order(trade_symbol, side, effective_lot, sl, far_tp, comment)
        if ok:
            state["last_ticket"] = res.get("order")
            state.setdefault("ticket_symbols", {})[str(res.get("order"))] = trade_symbol
            _log(state, f"🚀 LIVE [{trade_symbol}] {side} {R_LOT_FIXED} @ {res.get('price')} SL={sl} TP={far_tp} ticket={res.get('order')}")
            # Adaptive trailing baseline — capture entry confidence so trail can
            # detect conviction-decay later.
            try:
                from r_native.adaptive_trailing import record_entry_confidence
                record_entry_confidence(
                    ticket=int(res.get("order") or 0),
                    confidence=int(gate.get("confidence") or 0),
                    symbol=trade_symbol, side=side or "?",
                    entry=float(res.get("price") or 0),
                    tp=float(far_tp or 0),
                )
            except Exception: pass
            # Exposure guard — remember this open so guards fire next cycle
            try:
                from r_native.exposure_guard import record_open as _expo_open
                _expo_open(trade_symbol, side or "?", int(res.get("order") or 0))
            except Exception: pass
            # ── Learning: record origin so we can detect manual overrides later
            try:
                from datetime import datetime as _dt
                # Pull H1 ATR + bias for context
                bias_h1 = ""; atr_h1 = 0.0
                try:
                    h1 = mt5.copy_rates_from_pos(R_SYMBOL, mt5.TIMEFRAME_H1, 0, 20)
                    if h1 is not None and len(h1) >= 14:
                        import numpy as _np
                        tr = [max(float(h1["high"][i])-float(h1["low"][i]),
                                  abs(float(h1["high"][i])-float(h1["close"][i-1])),
                                  abs(float(h1["low"][i])-float(h1["close"][i-1]))) for i in range(1,len(h1))]
                        atr_h1 = sum(tr[-14:]) / 14
                        c = h1["close"]
                        slope = (float(c[-1]) - float(c[0])) / max(1e-9, atr_h1)
                        bias_h1 = "UP" if slope > 0.5 else "DOWN" if slope < -0.5 else "RANGE"
                except Exception: pass
                record_trade_origin(
                    ticket=res.get("order"),
                    archetype=arch or "UNKNOWN",
                    side=side, entry=res.get("price"),
                    sl=sl, tp=far_tp,
                    atr_h1=atr_h1,
                    hour_utc=_dt.utcnow().hour,
                    bias_h1=bias_h1,
                )
            except Exception as e:
                _log(state, f"  [learning origin err: {e}]")
            # ── Decision log: persist WHY this trade opened (fail-soft) ──
            try:
                if HAS_DECISION_LOG and _decision_log is not None:
                    # Fetch fresh snapshot for indicator context (best-effort, 1s)
                    snap_url = f"http://localhost:5055/api/snapshot?symbol={trade_symbol}"
                    snap = {}
                    try:
                        with urllib.request.urlopen(snap_url, timeout=1) as _r:
                            snap = json.loads(_r.read().decode("utf-8"))
                    except Exception:
                        snap = {}
                    _tfs = ((snap.get("multi_tf") or {}).get("tfs") or {})
                    _lvl = ((snap.get("chart") or {}).get("levels") or {})
                    def _tf_pick(d):
                        d = d or {}
                        return {
                            "current":     d.get("current"),
                            "atr":         d.get("atr"),
                            "rsi":         d.get("rsi"),
                            "swing_high":  d.get("swing_high"),
                            "swing_low":   d.get("swing_low"),
                            "range_size":  d.get("range_size"),
                            "bias":        d.get("bias"),
                            "slope_atr":   d.get("slope_atr"),
                        }
                    indicators = {
                        "h1":        _tf_pick(_tfs.get("H1")),
                        "h4":        _tf_pick(_tfs.get("H4")),
                        "m15":       _tf_pick(_tfs.get("M15")),
                        "bid":       _lvl.get("bid"),
                        "ask":       _lvl.get("ask"),
                        "spread_pt": _lvl.get("spread_points"),
                    }
                    _gate_payload = {
                        "signals_fired":    gate.get("genome_signals_fired")    or gate.get("signals_fired")    or [],
                        "biases_aligned":   gate.get("genome_biases_aligned")   or gate.get("biases_aligned")   or [],
                        "filters_blocking": gate.get("genome_filters_blocking") or gate.get("filters_blocking") or [],
                    }
                    _decision_log.record_open(
                        ticket=res.get("order"),
                        genome_id=gate.get("deployed_genome_id"),
                        symbol=trade_symbol,
                        side=side,
                        entry=res.get("price"),
                        sl=sl,
                        tp=far_tp,
                        lot=effective_lot,
                        confidence=gate.get("confidence"),
                        archetype=gate.get("archetype"),
                        gate_verdict_dict=_gate_payload,
                        indicators_dict=indicators,
                    )
            except Exception as e:
                _log(state, f"  [decision_log open err: {e}]")
        else:
            _log(state, f"   LIVE send FAILED: {res}")
            state["last_action"] = f"send_failed: {res.get('reason') or res.get('comment')}"
            return
    else:
        state["last_ticket"] = 0
        state["paper_open"] = {
            "side": side, "entry": float(entry), "sl": float(sl),
            "near_tp": float(gate.get("near_tp") or far_tp),
            "far_tp": float(far_tp),
            "open_ts": _now_iso(), "archetype": arch, "lot": R_LOT_FIXED,
        }
        _log(state, f"📝 PAPER {side} {R_LOT_FIXED} @ {entry} SL={sl} TP={far_tp} arch={arch} conf={conf}%")

    _append_trade_csv({
        "ts": _now_iso(), "mode": mode, "action": "OPEN",
        "ticket": state.get("last_ticket"), "symbol": R_SYMBOL,
        "side": side, "lot": R_LOT_FIXED, "entry": entry,
        "sl": sl, "near_tp": gate.get("near_tp"), "far_tp": far_tp,
        "archetype": arch, "confidence": conf,
        "exit_price": "", "exit_reason": "", "profit_usd": "",
        "r_consec_losses": state["consec_losses"],
        "r_today_pl": state["today_pl"],
    })


def loop(mode: str, interval: int = 30):
    print(f"=== R EXECUTOR — mode={mode}  magic={R_MAGIC}  symbol={R_SYMBOL} ===")
    print(f"Safety: lot={R_LOT_FIXED}  max_pos={R_MAX_POSITIONS}  "
          f"daily_cap=${R_DAILY_CAP_USD}  consec_loss_limit={R_CONSEC_LOSS_LIMIT}  "
          f"min_bal=${R_MIN_BALANCE_USD}")
    print()

    if not _mt5_init():
        print("MT5 init failed"); return

    state = _load_state()
    state["mode"]  = mode
    state["armed"] = True
    _save_state(state)

    while True:
        try:
            # Kill switch
            if KILL_SWITCH.exists():
                _log(state, "🛑 kill_switch.txt exists — exiting")
                state["armed"] = False
                _save_state(state); return

            # Balance gate
            info = mt5.account_info()
            if info and info.balance < R_MIN_BALANCE_USD:
                _log(state, f"💸 balance ${info.balance:.2f} < ${R_MIN_BALANCE_USD} — exiting")
                state["armed"] = False
                _save_state(state); return

            # Reconcile closed positions
            reconcile_closed_positions(state, mode)

            # Trail SL on all open R positions (lock profit aggressively)
            try:
                manage_trailing(state, mode)
            except Exception as e:
                _log(state, f"⚠ trailing err: {e}")

            # Freeze checks (also resets day counters)
            if check_freeze(state):
                state["last_action"] = "FROZEN"
                _save_state(state)
                time.sleep(interval); continue

            # Try to open
            try_enter_trade(state, mode)
            _save_state(state)

        except KeyboardInterrupt:
            print("stopped."); state["armed"] = False; _save_state(state); break
        except Exception as e:
            import traceback; traceback.print_exc()
            _log(state, f"⚠ exception: {e}")
            _save_state(state)
        time.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="REAL execution (default: paper)")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--no-brain-json", action="store_true",
                    help="don't write Brain JSON (use when EA isn't running)")
    args = ap.parse_args()
    if args.no_brain_json:
        # Disable JSON write by replacing _write_brain_json with no-op
        _write_brain_json = lambda *a, **k: None  # type: ignore
        globals()["_write_brain_json"] = _write_brain_json
    mode = "LIVE" if args.live else "PAPER"
    loop(mode, args.interval)
