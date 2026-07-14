"""nr7_prover.py — forward-paper prover for the ONE edge that survived the deep hunt.

Edge (DEEP_EDGE_HUNT.md): NR7 volatility-expansion breakout, USTECm M15.
  * NR7 = the just-CLOSED M15 bar has the narrowest High-Low of the last 7 bars.
  * It arms a breakout for the NEXT (currently-forming) bar ONLY:
      break above that NR7 bar's HIGH -> BUY ; break below its LOW -> SELL.
    First cross wins; if a gap would trigger both -> skip the whipsaw.
  * SL = 1.0 x ATR14 (= 1R, hold to EXACTLY 1 ATR — never widen). TP = 3R.
  * Spread veto: skip if live spread > 9 index points.
  * ONE position at a time. DEMO ONLY. magic 20260715.

This is NOT a live edge yet — it is on FORWARD-PAPER trial. Promotion gate
(DEEP_EDGE_HUNT.md §3): reproduce expR >= +0.15R over >= 100 forward trades AND
DD <= -25R. Kill on spread breach or forward expR < 0 after n >= 50.
Its trades (magic 20260715) feed /api/r/proof_gate?magic=20260715 for the honest read.
"""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

SYMBOL      = "USTECm"
MAGIC       = 20260715
NR_LOOKBACK = 7           # narrowest of last 7 bars
ATR_LEN     = 14
TP_R        = 3.0
SL_ATR_MULT = 1.0
LOT         = 0.01
MAX_SPREAD_PTS = 9        # index points; auto-veto above this
POLL_S      = 6           # watch the forming bar for a breakout
STATE_FILE  = Path(r"C:\Users\Radhi\MT5\data\r_native\nr7_prover_status.json")
COMMENT     = "NR7-fwd-paper"


def _log(msg: str):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def _write_status(d: dict):
    try:
        d["ts"] = datetime.now(timezone.utc).isoformat()
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_demo() -> bool:
    try:
        a = mt5.account_info()
        srv = ((getattr(a, "server", "") or "") if a else "").lower()
        return "trial" in srv or "demo" in srv
    except Exception:
        return False


def _atr14(bars) -> float:
    # Wilder-ish simple ATR over the last ATR_LEN completed bars
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < ATR_LEN:
        return 0.0
    return sum(trs[-ATR_LEN:]) / ATR_LEN


def _has_position() -> bool:
    try:
        ps = mt5.positions_get(symbol=SYMBOL) or []
        return any(int(getattr(p, "magic", 0)) == MAGIC for p in ps)
    except Exception:
        return False


def _spread_pts(info, tick) -> float:
    # INDEX points = raw price difference (USTECm is quoted in index points;
    # the backtest's "9 pts" veto is in index points, NOT broker points).
    try:
        return round(tick.ask - tick.bid, 2)
    except Exception:
        return 999.0


def _send(side: str, entry_ref: float, atr: float, info):
    """Market order in the breakout direction with SL=1xATR, TP=3xATR."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return
    price = tick.ask if side == "BUY" else tick.bid
    risk = SL_ATR_MULT * atr
    if side == "BUY":
        sl, tp = price - risk, price + TP_R * risk
        otype = mt5.ORDER_TYPE_BUY
    else:
        sl, tp = price + risk, price - TP_R * risk
        otype = mt5.ORDER_TYPE_SELL
    d = info.digits
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOT,
        "type": otype, "price": price, "sl": round(sl, d), "tp": round(tp, d),
        "deviation": 20, "magic": MAGIC, "comment": COMMENT,
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    ok = r and r.retcode == mt5.TRADE_RETCODE_DONE
    _log(f"{'✅' if ok else '❌'} {side} {SYMBOL} @ {price} SL={req['sl']} TP={req['tp']} "
         f"ret={getattr(r,'retcode','?')}")
    return ok


def main():
    if not mt5.initialize():
        _log("mt5.initialize failed — abort"); return
    if not _is_demo():
        _log("🛡 NOT a demo account — refusing to trade. abort."); return
    mt5.symbol_select(SYMBOL, True)
    if mt5.symbol_info(SYMBOL) is None:
        _log(f"symbol {SYMBOL} unavailable on this broker — abort."); return
    _log(f"NR7 forward-paper prover LIVE (DEMO) — {SYMBOL} M15 magic {MAGIC}")

    armed = None            # {"hi":, "lo":, "atr":, "bar_time":}
    last_nr7_bar = 0        # open-time of the NR7 bar we already armed on

    while True:
        try:
            info = mt5.symbol_info(SYMBOL)
            tick = mt5.symbol_info_tick(SYMBOL)
            if not info or not tick:
                time.sleep(POLL_S); continue
            bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, NR_LOOKBACK + ATR_LEN + 5)
            if bars is None or len(bars) < NR_LOOKBACK + ATR_LEN + 2:
                time.sleep(POLL_S); continue
            closed = bars[:-1]                     # exclude the forming bar
            last = closed[-1]                      # the just-CLOSED bar (bar i)
            forming_time = int(bars[-1]["time"])   # current forming bar (i+1)
            spread = _spread_pts(info, tick)
            have_pos = _has_position()

            # ── arm on a fresh NR7 bar (only once per bar, only when flat) ──
            if not have_pos and int(last["time"]) != last_nr7_bar:
                rng = [b["high"] - b["low"] for b in closed[-NR_LOOKBACK:]]
                if rng and (last["high"] - last["low"]) <= min(rng) + 1e-9:
                    atr = _atr14(closed)
                    if atr > 0:
                        armed = {"hi": float(last["high"]), "lo": float(last["low"]),
                                 "atr": atr, "bar_time": forming_time}
                        last_nr7_bar = int(last["time"])
                        _log(f"🎯 NR7 armed: hi={armed['hi']} lo={armed['lo']} atr={atr:.1f}")

            # ── disarm if the forming bar advanced past the armed bar ──
            if armed and forming_time != armed["bar_time"]:
                armed = None

            # ── watch for breakout during the armed (forming) bar ──
            if armed and not have_pos:
                if spread > MAX_SPREAD_PTS:
                    pass  # spread veto — do not chase
                else:
                    up = tick.ask >= armed["hi"]
                    dn = tick.bid <= armed["lo"]
                    if up and dn:
                        _log("↔ both levels crossed (gap) — skip whipsaw")
                        armed = None
                    elif up:
                        _send("BUY", armed["hi"], armed["atr"], info); armed = None
                    elif dn:
                        _send("SELL", armed["lo"], armed["atr"], info); armed = None

            _write_status({
                "symbol": SYMBOL, "magic": MAGIC, "have_position": have_pos,
                "armed": armed is not None, "spread_pts": spread,
                "spread_ok": spread <= MAX_SPREAD_PTS,
                "arm_levels": {"hi": armed["hi"], "lo": armed["lo"]} if armed else None,
                "note": "NR7 forward-paper (DEMO) — feeds /api/r/proof_gate?magic=20260715",
            })
        except Exception as e:
            _log(f"loop err: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
