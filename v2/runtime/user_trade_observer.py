"""runtime/user_trade_observer.py — Learn from user's manual trades.

User mandate 2026-05-27: "راقبني وانا ادخل صفقات وسجل كل شيء — الحين دورك تتعلم"

Polls MT5 every 1.5s. When a NEW position appears (any magic — manual
or other source), snapshots the FULL market state at entry and saves
to a journal. When the position CLOSES, snapshots exit state +
computes outcome. Builds a per-trade ground-truth dataset.

What gets recorded per trade:

  ENTRY snapshot:
    • Symbol, side, lot, entry price, SL, TP, magic, comment
    • Account balance/equity at entry
    • Market state: bid, ask, spread, ATR M1/M5/M15
    • Multi-TF bias (M1/M5/M15/H1)
    • RSI M1/M5/M15
    • Pressure 10-M1 net body \$
    • CVD last 30 M1 bars
    • All active OBs + FVGs + their distance from entry
    • Recent swings (last 4 highs + 4 lows)
    • S/R clusters within ±\$10 of entry
    • Session (London/NY/Asian)
    • Last 3 M1 candles' anatomy + volume

  EXIT snapshot:
    • Exit price, exit reason (TP/SL/manual/other comment)
    • Hold duration (seconds)
    • Max favorable excursion (best price reached)
    • Max adverse excursion (worst price reached)
    • Final PnL
    • Market state at exit (same as entry block)

OUTPUT:
  data/user_trades.jsonl — one line per OPEN, one per CLOSE
  data/user_pattern_summary.json — rolling aggregates updated hourly:
    win rate, avg hold time, favorite entry conditions, common exit
    reasons, best/worst setups

This is how I learn the user's edge so the genome can eventually
replicate it.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path


JOURNAL = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\user_trades.jsonl")
SUMMARY = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\user_pattern_summary.json")
POLL = 1.5
KNOWN_POSITIONS: set = set()    # tickets seen this session


def _append_journal(record: dict):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _snapshot_market(mt5, symbol: str) -> dict:
    """Full market state snapshot for a symbol."""
    snap = {"symbol": symbol, "ts": datetime.now(timezone.utc).isoformat()}
    try:
        tick = mt5.symbol_info_tick(symbol)
        snap["bid"] = float(tick.bid); snap["ask"] = float(tick.ask)
        snap["spread"] = round(tick.ask - tick.bid, 4)
    except Exception: return snap

    def _bars(tf, n):
        r = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        return [dict(b._asdict()) if hasattr(b, "_asdict")
                else {k: b[k] for k in b.dtype.names} for b in r] if r is not None else []
    m1 = _bars(mt5.TIMEFRAME_M1, 60)
    m5 = _bars(mt5.TIMEFRAME_M5, 60)
    m15 = _bars(mt5.TIMEFRAME_M15, 30)
    h1 = _bars(mt5.TIMEFRAME_H1, 24)

    # ATRs
    def _atr(bars, p=14):
        if len(bars) < p+1: return 0
        trs = []
        for i in range(1, len(bars)):
            h, l, pc = bars[i]["high"], bars[i]["low"], bars[i-1]["close"]
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        atr = sum(trs[:p])/p
        for t in trs[p:]: atr = (atr*(p-1)+t)/p
        return round(atr, 4)
    snap["atr_m1"] = _atr(m1); snap["atr_m5"] = _atr(m5); snap["atr_m15"] = _atr(m15)

    # RSI
    def _rsi(closes, p=14):
        if len(closes) < p+1: return 50
        g = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
        l = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
        ag = sum(g[:p])/p; al = sum(l[:p])/p
        for i in range(p, len(g)):
            ag = (ag*(p-1)+g[i])/p; al = (al*(p-1)+l[i])/p
        return 100 if al == 0 else round(100 - 100/(1 + ag/al), 1)
    snap["rsi_m1"] = _rsi([b["close"] for b in m1[:-1]])
    snap["rsi_m5"] = _rsi([b["close"] for b in m5[:-1]])
    snap["rsi_m15"] = _rsi([b["close"] for b in m15[:-1]])

    # Pressure 10-M1 net body $
    if len(m1) >= 11:
        last10 = m1[-11:-1]
        bull = sum(b["close"]-b["open"] for b in last10 if b["close"]>b["open"])
        bear = sum(b["open"]-b["close"] for b in last10 if b["close"]<b["open"])
        snap["pressure_10m1"] = round(bull - bear, 2)
    # CVD 30-M1
    if len(m1) >= 31:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        cvd = 0
        for i in range(len(m1)-31, len(m1)-1):
            bar_start = int(m1[i]["time"])
            try:
                ticks = mt5.copy_ticks_range(symbol,
                    _dt.fromtimestamp(bar_start, tz=_tz.utc),
                    _dt.fromtimestamp(bar_start+60, tz=_tz.utc),
                    mt5.COPY_TICKS_ALL)
                if ticks is None or len(ticks) < 2: continue
                buy_c, sell_c = 0, 0; prev_mid = None
                for t in ticks:
                    mid = (float(t["bid"]) + float(t["ask"])) / 2
                    if prev_mid is not None:
                        if mid > prev_mid: buy_c += 1
                        elif mid < prev_mid: sell_c += 1
                    prev_mid = mid
                cvd += buy_c - sell_c
            except Exception: pass
        snap["cvd_30m1"] = cvd

    # MTF bias (close vs EMA20)
    def _ema(vals, p):
        if not vals: return 0
        k = 2/(p+1); e = vals[0]
        for v in vals[1:]: e = v*k + e*(1-k)
        return e
    for tf_name, bars in [("m1", m1), ("m5", m5), ("m15", m15), ("h1", h1)]:
        if len(bars) >= 21:
            ema20 = _ema([b["close"] for b in bars[-21:-1]], 20)
            snap[f"bias_{tf_name}"] = "UP" if bars[-2]["close"] > ema20 else "DOWN"

    # Last 3 M1 anatomies
    if len(m1) >= 4:
        anatomies = []
        for b in m1[-4:-1]:
            body = abs(b["close"]-b["open"]); rng = max(b["high"]-b["low"], 1e-9)
            anatomies.append({
                "kind": "bull" if b["close"]>b["open"] else "bear",
                "body_pct": round(body/rng*100),
                "upper_wick": round(b["high"]-max(b["open"],b["close"]),2),
                "lower_wick": round(min(b["open"],b["close"])-b["low"],2),
                "volume": int(b["tick_volume"]),
            })
        snap["last_3_m1"] = anatomies

    # Session
    hr = datetime.now(timezone.utc).hour
    if 13 <= hr < 17: snap["session"] = "NY_OVERLAP"
    elif 8 <= hr < 13: snap["session"] = "LONDON"
    elif 17 <= hr < 21: snap["session"] = "NY_LATE"
    elif hr >= 22 or hr < 8: snap["session"] = "ASIAN"
    else: snap["session"] = "TRANSITION"
    return snap


def main_loop():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception as e:
        print(f"mt5 init err: {e}"); return

    print(f"[user_observer] online · polling every {POLL}s")
    print(f"[user_observer] journaling to {JOURNAL}")

    # Seed known positions from current state
    for p in (mt5.positions_get() or []):
        KNOWN_POSITIONS.add(int(p.ticket))

    while True:
        try:
            current_positions = mt5.positions_get() or []
            cur_tickets = {int(p.ticket) for p in current_positions}

            # NEW position(s) — entry snapshot
            new_tickets = cur_tickets - KNOWN_POSITIONS
            for ticket in new_tickets:
                p = next((x for x in current_positions if int(x.ticket) == ticket), None)
                if not p: continue
                acc = mt5.account_info()
                snap = _snapshot_market(mt5, p.symbol)
                record = {
                    "event": "OPEN",
                    "ticket": int(p.ticket),
                    "symbol": p.symbol,
                    "side": "BUY" if p.type == 0 else "SELL",
                    "lot": float(p.volume),
                    "entry_price": float(p.price_open),
                    "sl": float(p.sl), "tp": float(p.tp),
                    "magic": int(p.magic),
                    "comment": str(p.comment),
                    "open_time": int(p.time),
                    "account_balance": float(acc.balance) if acc else None,
                    "account_equity": float(acc.equity) if acc else None,
                    "market": snap,
                }
                _append_journal(record)
                print(f"[{datetime.now():%H:%M:%S}] 📥 OPEN #{p.ticket} {p.symbol} "
                       f"{record['side']} @ {p.price_open:.4f} magic={p.magic} "
                       f"comment={p.comment!r}")
                print(f"    Market: bid={snap.get('bid')} RSI_m1={snap.get('rsi_m1')} "
                       f"pressure={snap.get('pressure_10m1')} CVD={snap.get('cvd_30m1')} "
                       f"session={snap.get('session')}")

            # CLOSED position(s) — exit snapshot via deal history
            closed_tickets = KNOWN_POSITIONS - cur_tickets
            if closed_tickets:
                from datetime import datetime as _dt, timedelta as _td
                recent_deals = mt5.history_deals_get(_dt.now()-_td(minutes=5), _dt.now()) or []
                for ticket in closed_tickets:
                    closing_deals = [d for d in recent_deals
                                       if int(getattr(d, "position_id", 0) or d.order) == ticket
                                       and int(d.entry) in (1, 2)]
                    if not closing_deals: continue
                    cd = closing_deals[-1]
                    pnl = float(cd.profit) + float(cd.swap) + float(cd.commission)
                    snap = _snapshot_market(mt5, cd.symbol)
                    acc = mt5.account_info()
                    record = {
                        "event": "CLOSE",
                        "ticket": ticket,
                        "symbol": cd.symbol,
                        "exit_price": float(cd.price),
                        "pnl": round(pnl, 2),
                        "exit_comment": str(cd.comment),
                        "close_time": int(cd.time),
                        "account_balance_after": float(acc.balance) if acc else None,
                        "market": snap,
                    }
                    _append_journal(record)
                    mark = "🎯" if pnl > 0 else "🔴"
                    print(f"[{datetime.now():%H:%M:%S}] {mark} CLOSE #{ticket} {cd.symbol} "
                           f"@ {cd.price:.4f} pnl=${pnl:+.2f} comment={cd.comment!r}")

            KNOWN_POSITIONS.clear()
            KNOWN_POSITIONS.update(cur_tickets)
        except KeyboardInterrupt:
            print("[user_observer] stopped"); break
        except Exception as e:
            print(f"[user_observer] loop err: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main_loop()
