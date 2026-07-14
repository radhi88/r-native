"""runtime/trailing_stop_manager.py — Universal trailing SL for ALL open positions.

Born 2026-05-28 after user manually closed 6 bot trades for +$17.86 because
the bots set fixed TPs that never triggered. This module fixes that for good.

LADDER LOGIC (per position):
  +3 pt profit:  ──→ move SL to breakeven (entry price)
  +5 pt profit:  ──→ trail SL behind price by 4 pt (lock in 1 pt min)
  +8 pt profit:  ──→ trail SL behind price by 3 pt (lock in 5 pt min)
  +12 pt profit: ──→ trail SL behind price by 2 pt (lock in 10 pt min)

NEVER MOVES SL BACKWARDS — only ever in the favorable direction.

Runs in its own process every 2s. Operates on R-NATIVE BOT positions only —
EXCLUDE_MAGICS skips the user's own trades (manual magic 0 + his QuantumShark EA)
so HE rides them for bigger profits; we never auto-close his discretionary trades.
(Changed 2026-06-16 — previously trailed every magic, hijacking the user's gold
trades at small profit; he asked to take bigger profits, this was the cause.)

Idempotent: writes a small state file remembering which positions
have been touched, so it never re-issues the same SLTP modification.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

from runtime.shared.tokens import PATHS

POLL_S = 2.0
STATE_FILE = PATHS["brain_decisions"].parent / "trailing_state.json"

# 🛑 لا تُدِر صفقات المستخدم — اتركه يركب أرباحه. نُدير بوتات R Native فقط.
# magic 0 = يدوي المستخدم/أداة خارجية · 20250421/22 = إكسبيرت QuantumShark تبعه (trailing خاص).
EXCLUDE_MAGICS = {0, 20250421, 20250422}

# Ladder: (profit_pts, sl_distance_from_price_pts)
# Special value 0 for sl_distance means "move to entry (breakeven)"
LADDER = [
    (12.0, 2.0),   # lock in ≥ 10pt
    ( 8.0, 3.0),   # lock in ≥ 5pt
    ( 5.0, 4.0),   # lock in ≥ 1pt
    ( 3.0, 0.0),   # breakeven only
]

# Symbols we manage (point size matters for "pt" conversion)
# For XAU: 1 "pt" in our config = 1.0 in price
POINT_PER_PT = {
    "XAUUSDm": 1.0,
    "XAGUSDm": 0.10,
    "BTCUSDm": 100.0,
    "EURUSDm": 0.0001,
}


def _load_state() -> dict:
    if not STATE_FILE.exists(): return {}
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except: return {}


def _save_state(s: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, default=str, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _profit_pts(pos, tick) -> float:
    """Current floating profit in price-pts (positive = favorable)."""
    pt = POINT_PER_PT.get(pos.symbol, 1.0)
    if pos.type == 0:   # BUY — profit when tick.bid > entry
        return (tick.bid - pos.price_open) / pt
    else:               # SELL — profit when tick.ask < entry
        return (pos.price_open - tick.ask) / pt


def _ideal_sl(pos, tick) -> tuple[float, str] | None:
    """Return (new_sl_price, rung_label) if SL should advance, else None."""
    pt = POINT_PER_PT.get(pos.symbol, 1.0)
    p_pts = _profit_pts(pos, tick)
    for trigger_pts, sl_dist_pts in LADDER:
        if p_pts >= trigger_pts:
            if sl_dist_pts == 0.0:
                # Breakeven
                new_sl = pos.price_open
                rung = f"BE@{trigger_pts:.0f}"
            else:
                if pos.type == 0:   # BUY: SL below current bid
                    new_sl = tick.bid - sl_dist_pts * pt
                else:               # SELL: SL above current ask
                    new_sl = tick.ask + sl_dist_pts * pt
                rung = f"trail{sl_dist_pts:.0f}pt@{trigger_pts:.0f}"
            return (round(new_sl, 2), rung)
    return None


def _better_sl(pos, candidate_sl: float) -> bool:
    """True if candidate is strictly favorable to current SL."""
    # SL=0 means no SL set
    if pos.sl == 0:
        return True
    if pos.type == 0:   # BUY: higher SL = better (closer to entry, locking profit)
        return candidate_sl > pos.sl + 0.01
    else:               # SELL: lower SL = better
        return candidate_sl < pos.sl - 0.01


def _move_sl(pos, new_sl: float) -> bool:
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(pos.ticket),
        "symbol": pos.symbol,
        "sl": float(new_sl),
        "tp": float(pos.tp),     # keep existing TP
        "magic": int(pos.magic),
    }
    r = mt5.order_send(req)
    return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)


def cycle() -> int:
    """One management pass. Returns number of SL modifications applied."""
    positions = mt5.positions_get() or []
    if not positions: return 0

    state = _load_state()
    moved = 0
    now = datetime.now(timezone.utc).isoformat()

    for pos in positions:
        if int(pos.magic) in EXCLUDE_MAGICS:   # 🛑 صفقات المستخدم — لا نلمسها، يركبها بنفسه
            continue
        tick = mt5.symbol_info_tick(pos.symbol)
        if not tick: continue
        ideal = _ideal_sl(pos, tick)
        if ideal is None: continue
        new_sl, rung = ideal
        if not _better_sl(pos, new_sl): continue

        if _move_sl(pos, new_sl):
            moved += 1
            key = str(pos.ticket)
            history = state.setdefault(key, [])
            history.append({
                "ts": now, "rung": rung,
                "old_sl": pos.sl, "new_sl": new_sl,
                "entry": pos.price_open, "current": tick.bid if pos.type == 0 else tick.ask,
                "profit": pos.profit,
            })
            side = "BUY " if pos.type == 0 else "SELL"
            print(f"[{datetime.now():%H:%M:%S}] 🪜 #{pos.ticket} {side} mag {pos.magic} "
                  f"{rung}  SL {pos.sl:.2f} → {new_sl:.2f}  (P/L ${pos.profit:+.2f})")

    if moved:
        _save_state(state)
    return moved


def main():
    if not mt5.initialize() and not mt5.initialize():
        print("[trailing] mt5 init failed"); return
    print(f"╔══════════════════════════════════════════════╗")
    print(f"║ [trailing_stop_manager] ONLINE              ║")
    print(f"║ Trails SL on EVERY open position every {POLL_S}s ║")
    print(f"║ Ladder: BE@3pt → +1@5pt → +5@8pt → +10@12pt  ║")
    print(f"╚══════════════════════════════════════════════╝")
    while True:
        try:
            n = cycle()
            if n == 0:
                # Quiet tick — just sleep
                pass
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            mt5.shutdown()
            print("\n[trailing_stop_manager] stopped"); break
        except Exception as e:
            print(f"err: {e}")
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
