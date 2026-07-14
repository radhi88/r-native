"""manual_copilot.py — manage + LEARN FROM Radhi's manual trades (magic 0).

Radhi: "manage my manual trades as if the bot entered them, record them with the
% and values — I might be more accurate than it."  (And our research agrees:
his manual edge was ~72% WR.)

So this:
  1. RECORDS every manual entry (magic 0) with the live signal snapshot at that
     moment — action/confidence/components + the RAW (pre-fade) signal — so we can
     measure: was Radhi RIGHT when he traded WITH the signal vs AGAINST it?
  2. PROTECTS each manual position like the bot protects its own: ratchet SL to
     lock profit / breakeven (never widens; never cuts the user's thesis).
  3. On close, records the OUTCOME and builds manual_review.md:
        Radhi's win-rate  vs  the signal's — IS RADHI MORE ACCURATE?
        and how he does AGREEING vs DISAGREEING with the bot.

Read-only to the bot's magics; only touches magic-0 SL (ratchet up).
Run:  python -m runtime.manual_copilot --loop   (--dry to not modify SL)
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
DATA = _V2 / "data"
LOG = DATA / "manual_trades.jsonl"
SEEN = DATA / "manual_seen.json"
REVIEW = DATA / "manual_review.md"
MANUAL_MAGIC = 0
POLL = 10


def _log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}Z] [MANUAL-COPILOT] {m}", flush=True)


def _read_signal(symbol):
    f = COMMON / f"signal_{symbol}.json"
    try:
        if not f.exists() or time.time() - f.stat().st_mtime > 120:
            return {}
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if d.get("symbol") == symbol else {}
    except Exception:
        return {}


def _atr(mt5, symbol, n=14):
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, n + 2)
    if r is None or len(r) < n + 1:
        return 0.0
    import numpy as np
    h = np.array([x["high"] for x in r]); l = np.array([x["low"] for x in r])
    c = np.array([x["close"] for x in r]); pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return float(np.mean(tr[-n:]))


def _manual(mt5):
    return [p for p in (mt5.positions_get() or []) if p.magic == MANUAL_MAGIC]


def _load_seen():
    try:
        return json.loads(SEEN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(d):
    try:
        SEEN.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def _append(rec):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _ratchet_sl(mt5, pos, new_sl, armed):
    """Move SL only in the protective direction (lock profit). Never widen."""
    is_buy = pos.type == 0
    cur = float(pos.sl) if pos.sl else 0.0
    if cur:
        if is_buy and new_sl <= cur + 1e-9: return
        if (not is_buy) and new_sl >= cur - 1e-9: return
    if not armed:
        _log(f"DRY ratchet {pos.symbol} SL -> {new_sl:.3f}"); return
    req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol,
           "position": pos.ticket, "sl": float(new_sl), "tp": float(pos.tp)}
    mt5.order_send(req)
    _log(f"{pos.symbol} manual SL ratched -> {new_sl:.3f} (lock profit)")


def cycle(mt5, armed):
    seen = _load_seen()
    cur = _manual(mt5)
    cur_tickets = {str(p.ticket) for p in cur}

    # 1) RECORD new manual entries with the live signal snapshot
    for p in cur:
        tk = str(p.ticket)
        if tk in seen:
            continue
        sig = _read_signal(p.symbol)
        side = "BUY" if p.type == 0 else "SELL"
        sig_final = sig.get("action", "?")
        sig_raw = sig.get("orig_action", sig_final)   # pre-fade raw
        rec = {"ticket": int(p.ticket), "symbol": p.symbol, "side": side,
               "lot": float(p.volume), "entry": float(p.price_open),
               "ts": int(p.time), "iso": datetime.now(timezone.utc).isoformat(),
               "sig_action": sig_final, "sig_raw": sig_raw,
               "sig_conf": sig.get("confidence"), "sig_mode": sig.get("mode_learned"),
               "components": sig.get("components", {}),
               "agree_final": (side == sig_final), "agree_raw": (side == sig_raw),
               "outcome": None}
        _append(rec)
        seen[tk] = {"symbol": p.symbol, "side": side, "entry": float(p.price_open),
                    "sig_action": sig_final, "sig_raw": sig_raw, "agree_raw": (side == sig_raw)}
        _log(f"recorded manual {side} {p.symbol} @ {p.price_open:.3f} "
             f"(signal said {sig_final}, raw {sig_raw}, conf {sig.get('confidence')})")

    # 2a) CATASTROPHIC BACKSTOP — the edge research showed Radhi's losses RUN
    # (avg loss $16.85 vs win $6.11) because manual trades often have NO stop.
    # The bot's mandate is to enforce the discipline he can't hold: if a manual
    # position has NO SL, set a WIDE one (2.5xATR) — far enough not to choke a
    # scalp, but caps the account-blowing tail. Never tightens an existing SL.
    for p in cur:
        if p.sl and p.sl > 0:
            continue                                   # respect a user-set stop
        atr = _atr(mt5, p.symbol) or 0.0
        info = mt5.symbol_info(p.symbol)
        if atr <= 0 or not info:
            continue
        dg = info.digits or 2
        is_buy = p.type == 0
        backstop = round(p.price_open - 2.5 * atr, dg) if is_buy else round(p.price_open + 2.5 * atr, dg)
        if not armed:
            _log(f"DRY backstop {p.symbol} {'BUY' if is_buy else 'SELL'} SL -> {backstop:.{dg}f}")
            continue
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
               "position": p.ticket, "sl": float(backstop), "tp": float(p.tp)}
        mt5.order_send(req)
        _log(f"{p.symbol} manual {'BUY' if is_buy else 'SELL'} had NO SL -> backstop {backstop:.{dg}f} (2.5xATR)")

    # 2b) PROTECT open manual positions — SECURE THE BIGGEST PROFIT.
    # As soon as a trade shows real profit, the stop is pulled to LOCK profit
    # (never sits at entry or worse), then TRAILS to ride the move for the
    # biggest possible win. (Radhi: "أمّن أكبر ربح، ولا يتوقف عند الدخول وأقل منه".)
    for p in cur:
        if p.profit <= 0:
            continue
        atr = _atr(mt5, p.symbol) or 0.0
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick or atr <= 0:
            continue
        is_buy = p.type == 0
        px = tick.bid if is_buy else tick.ask
        gain = (px - p.price_open) if is_buy else (p.price_open - px)
        if gain < 0.20 * atr:
            continue                                   # tiny — let it breathe a touch first
        # candidate 1 — breakeven+ : always LOCK >=25% of the gain (SL past entry)
        lock_be = p.price_open + (0.25 * gain if is_buy else -0.25 * gain)
        # candidate 2 — ATR trail (rides the move once >=1 ATR in profit)
        if gain >= 1.0 * atr:
            trail = (px - 0.6 * atr) if is_buy else (px + 0.6 * atr)
        else:
            trail = lock_be
        # take the MORE protective (closer-to-locking-more) of the two
        new_sl = max(lock_be, trail) if is_buy else min(lock_be, trail)
        _ratchet_sl(mt5, p, new_sl, armed)             # never moves backward

    # 3) DETECT closed manual trades -> record outcome
    closed = [tk for tk in seen if tk not in cur_tickets]
    if closed:
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(days=2), now) or []
        bypos = defaultdict(list)
        for d in deals:
            if d.magic == MANUAL_MAGIC:
                bypos[str(d.position_id)].append(d)
        for tk in closed:
            ds = bypos.get(tk, [])
            net = sum(d.profit + d.commission + d.swap for d in ds) if ds else 0.0
            info = seen.pop(tk)
            _append({"ticket": int(tk), "symbol": info["symbol"], "side": info["side"],
                     "closed": True, "net": round(net, 2), "won": net > 0,
                     "sig_raw": info.get("sig_raw"), "agree_raw": info.get("agree_raw"),
                     "ts": int(time.time())})
            _log(f"manual {info['symbol']} {info['side']} CLOSED net ${net:+.2f} ({'win' if net>0 else 'loss'})")
    _save_seen(seen)
    _build_review()


def _build_review():
    rows = []
    if LOG.exists():
        for ln in LOG.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try: rows.append(json.loads(ln))
                except Exception: pass
    closed = [r for r in rows if r.get("closed")]
    n = len(closed); wins = sum(1 for r in closed if r.get("won"))
    net = sum(r.get("net", 0) for r in closed)
    # Radhi when AGREEING with the RAW signal vs DISAGREEING
    agree = [r for r in closed if r.get("agree_raw")]
    disag = [r for r in closed if r.get("agree_raw") is False]

    def wr(rs):
        return (100 * sum(1 for r in rs if r.get("won")) / len(rs)) if rs else 0.0
    L = ["# تداولك اليدوي — هل أنت أصدق من الإشارة؟\n",
         f"_تحديث {datetime.now(timezone.utc).isoformat()}_  ·  magic 0\n",
         f"## إجمالي: {n} صفقة مغلقة · فوز {wins} ({wr(closed):.0f}%) · صافي ${net:+.2f}\n",
         "## متى تكون أصدق:",
         f"- لما تتّفق مع الإشارة الخام: {len(agree)} صفقة · فوز {wr(agree):.0f}%",
         f"- لما **تخالف** الإشارة الخام: {len(disag)} صفقة · فوز {wr(disag):.0f}%",
         "",
         "> لو فوزك وأنت **تخالف** الإشارة أعلى → حدسك أصدق، والنظام يتعلّم من دخلاتك.",
         "",
         "## آخر صفقاتك المغلقة"]
    L.append("| رمز | اتجاه | صافي$ | وافق الإشارة؟ |")
    L.append("|----|-------|------|--------------|")
    for r in sorted(closed, key=lambda x: x.get("ts", 0), reverse=True)[:12]:
        L.append(f"| {r['symbol']} | {r['side']} | {r.get('net',0):+.2f} | {'نعم' if r.get('agree_raw') else 'لا'} |")
    REVIEW.write_text("\n".join(L), encoding="utf-8")
    return {"n": n, "wins": wins, "wr": round(wr(closed), 1), "net": round(net, 2),
            "wr_agree": round(wr(agree), 1), "wr_disagree": round(wr(disag), 1)}


_HB = [0.0]     # heartbeat: last time a cycle completed


def _watchdog(mt5):
    """If the cycle stalls (a blocking MT5 call hangs under multi-process
    contention — what left manual trades unprotected for 47min), reset the MT5
    link from this thread to break the hang so protection resumes. Critical:
    this is the SAFETY layer that puts backstops on Radhi's manual trades."""
    import time as _t
    while True:
        _t.sleep(25)
        if _HB[0] and (_t.time() - _HB[0]) > 70:
            _log("⚠️ watchdog: cycle stalled >70s — resetting MT5 link to recover")
            try:
                mt5.shutdown()
            except Exception:
                pass
            try:
                mt5.initialize()
            except Exception:
                pass
            _HB[0] = _t.time()


def main(argv=None):
    import MetaTrader5 as mt5
    import threading
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args(argv)
    if not mt5.initialize():
        _log("MT5 init failed"); return 1
    armed = not args.dry
    _log(f"start — managing+recording manual trades (magic 0), armed={armed}")
    if args.loop and not args.once:
        _HB[0] = time.time()
        threading.Thread(target=_watchdog, args=(mt5,), daemon=True).start()
    try:
        while True:
            try:
                cycle(mt5, armed)
                _HB[0] = time.time()       # heartbeat — cycle completed
            except Exception as e:
                _log(f"cycle error: {e}")
                _HB[0] = time.time()
            if not (args.loop and not args.once):
                break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
