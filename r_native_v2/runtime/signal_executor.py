"""signal_executor.py — trade the brain signal + track WAS IT RIGHT.

Closed loop the user asked for ("خله يدخل صفقات على هذه النسبه ... واعرف وين قال
بيع او اشتر وهل صدق ولا لا"):

  1. Read signal_<SYMBOL>.json (the blended BUY/SELL + confidence from
     chart_signal_writer.py).
  2. When confidence >= MIN_CONF and FLAT on our magic for that symbol -> enter a
     DEMO trade (own magic 99784, SL = ATR*mult, TP = SL*RR).
  3. Log EVERY call (where it said BUY/SELL, at what price, what confidence).
  4. When the position closes (SL/TP), record the OUTCOME -> won/lost = "did the
     signal tell the truth?".
  5. Write data/signal_accuracy.md: per-symbol & overall hit-rate, and hit-rate
     BY CONFIDENCE BUCKET -> tells us how to TUNE (raise/lower threshold).

Isolation/safety: own magic 99784 (never touches 99782/99783/0), DEMO only,
singleton lock, one position per symbol, max concurrent cap, daily-loss stop.

Run:  python -m runtime.signal_executor --loop
      python -m runtime.signal_executor --once --dry
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
DATA = _V2 / "data"
CALLS = DATA / "signal_calls.jsonl"
REPORT = DATA / "signal_accuracy.md"
LOCK = DATA / "signal_executor.pid"

MAGIC = 99784
SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "XAGUSDm"]
MIN_CONF = 50.0          # entry floor (used only when TRADE_ALL is off)
TRADE_ALL = True         # trade EVERY BUY/SELL signal at ANY confidence (max learning data)
REVERSE_SCORE = 22.0     # |score| beyond which the signal counts as flipped to the opposite side
MAX_AGE_S = 90           # ignore stale signals
ATR_MULT_SL = 1.5
RR = 1.6                 # TP = RR * SL distance
LOT = 0.01
MAX_OPEN_TOTAL = 5       # cap concurrent positions (trade-all mode = one per symbol)
DAILY_LOSS_STOP = -30.0   # stop entering new trades after this realized today (raised per user)
SIGNAL_DD_STOP = -45.0    # daily circuit breaker (raised -15→-30→-45 per user: more room).
POLL = 10
# ── DEVELOPED ("نسخة مطوّرة") QUALITY GATE — only take scalps that can beat costs ──
# The mechanical M1 scalper bled because tight scalps lose to the spread and dead
# hours have wide spreads. This gate keeps only HIGH-QUALITY entries:
QUALITY_GATE        = True
LIQUID_HOURS        = set(range(0, 24))   # 24h — bot trades anytime so the user relies on it instead of manual night-tilting. (Research: night is weak for DISCRETIONARY trading; the bot's disciplined 0.01-lot+SL+daily-stop night scalps are far less destructive than the user's manual night averaging. Harm-reduction.)
MIN_TP_SPREAD_MULT  = 1.8                 # target must be >= 1.8x the live spread (loosened 2.5→1.8 for more entries; still cost-aware)
REQUIRE_STOCH_CONF  = True                # only the user's confirmed Stoch extremes


def _log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}Z] [SIG-EXEC] {m}", flush=True)


# ---- singleton -------------------------------------------------------------
def _acquire():
    try:
        if LOCK.exists():
            old = LOCK.read_text().strip()
            if old.isdigit() and int(old) != os.getpid():
                try:
                    os.kill(int(old), 0); return False
                except Exception:
                    pass
        DATA.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(os.getpid())); return True
    except Exception:
        return True


def _release():
    try:
        if LOCK.exists() and LOCK.read_text().strip() == str(os.getpid()):
            LOCK.unlink()
    except Exception:
        pass


# ---- signal + indicators ---------------------------------------------------
def _read_signal(symbol):
    f = COMMON / f"signal_{symbol}.json"
    try:
        if not f.exists() or time.time() - f.stat().st_mtime > MAX_AGE_S:
            return None
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("symbol") != symbol:
            return None
        return d
    except Exception:
        return None


def _atr(mt5, symbol, n=14):
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, n + 2)
    if r is None or len(r) < n + 1:
        return None
    import numpy as np
    h = np.array([x["high"] for x in r]); l = np.array([x["low"] for x in r])
    c = np.array([x["close"] for x in r]); pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return float(np.mean(tr[-n:]))


def _my_positions(mt5, symbol=None):
    poss = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return [p for p in (poss or []) if p.magic == MAGIC]


def _conf_bucket(c):
    if c >= 90: return "90-100"
    if c >= 80: return "80-90"
    if c >= 70: return "70-80"
    if c >= 60: return "60-70"
    return "<60"


# ---- entry -----------------------------------------------------------------
def _record_call(rec):
    with CALLS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _enter(mt5, symbol, sig, armed):
    action = sig.get("action")
    conf = float(sig.get("confidence") or 0)
    atr = _atr(mt5, symbol)
    if not atr or atr <= 0:
        return
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return
    sl_dist = ATR_MULT_SL * atr
    if action == "BUY":
        entry = tick.ask; sl = entry - sl_dist
        tp = _better_tp(mt5, symbol, "BUY", entry, sl_dist, sig)
        otype = mt5.ORDER_TYPE_BUY
    else:
        entry = tick.bid; sl = entry + sl_dist
        tp = _better_tp(mt5, symbol, "SELL", entry, sl_dist, sig)
        otype = mt5.ORDER_TYPE_SELL
    call = {"ts": int(time.time()), "iso": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol, "action": action, "confidence": conf,
            "score": sig.get("score"), "entry": round(entry, 5),
            "sl": round(sl, 5), "tp": round(tp, 5), "bucket": _conf_bucket(conf),
            "reason": sig.get("reason", "")}
    if not armed:
        _log(f"DRY {symbol} {action} {conf:.0f}% @ {entry:.2f} sl {sl:.2f} tp {tp:.2f} — NO ORDER")
        call["ticket"] = 0; call["dry"] = True
        _record_call(call)
        return
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": LOT,
           "type": otype, "price": entry, "sl": float(sl), "tp": float(tp),
           "deviation": 30, "magic": MAGIC, "comment": f"SIGEXEC {action} {conf:.0f}",
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_FOK}
    r = mt5.order_send(req)
    if not r or r.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    call["ticket"] = int(getattr(r, "order", 0) or 0)
    call["ok"] = ok
    _record_call(call)
    _log(f"{'OPENED' if ok else 'FAILED'} {symbol} {action} {conf:.0f}% @ {entry:.2f} "
         f"sl {sl:.2f} tp {tp:.2f} ret={getattr(r,'retcode',None)}")


# ---- level-based TP (POC / pivots / SMC zones, not a flat multiple) --------
def _pivots(mt5, symbol):
    """Classic daily pivots from the previous D1 bar."""
    try:
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 1, 1)
        if r is None or len(r) < 1:
            return {}
        h, l, c = float(r[0]["high"]), float(r[0]["low"]), float(r[0]["close"])
        pp = (h + l + c) / 3.0
        return {"PP": pp, "R1": 2 * pp - l, "S1": 2 * pp - h,
                "R2": pp + (h - l), "S2": pp - (h - l)}
    except Exception:
        return {}


def _learn_mature():
    """Has the learning proven an edge yet? Until then we keep targets TIGHT
    (small profit) per the user's rule; once mature we let them run to levels."""
    try:
        t = json.loads((DATA / "signal_tuning.json").read_text(encoding="utf-8"))
        return bool(t.get("mature", False))
    except Exception:
        return False


def _better_tp(mt5, symbol, action, entry, sl_dist, sig):
    """TP at the NEAREST meaningful level (SMC zones + footprint POC + daily
    pivots). UNTIL learning is mature, keep the target TIGHT (small profit):
    pick the closest level in a narrow band; widen only once the edge is proven."""
    mature = _learn_mature()
    if mature:
        min_d, max_d, fb_rr = 1.0 * sl_dist, 5.0 * sl_dist, RR        # let it run to levels
    else:
        min_d, max_d, fb_rr = 0.5 * sl_dist, 1.3 * sl_dist, 1.0       # small profit while learning
    sig["tp_mode"] = "MATURE-wide" if mature else "LEARNING-tight"
    cands = []  # (price, tag)
    try:
        # SMC zones from the signal (opposing zone = natural target)
        for z in (sig.get("zones") or []):
            for lvl in (z.get("top"), z.get("bot")):
                if lvl:
                    cands.append((float(lvl), f"zone-{z.get('kind','')}"))
        # footprint POC
        from runtime.shared import footprint_features as _ffmod
        raw = _ffmod._load(symbol)
        if raw and raw.get("svp_poc"):
            cands.append((float(raw["svp_poc"]), "POC"))
        # daily pivots
        for k, v in _pivots(mt5, symbol).items():
            cands.append((float(v), f"piv-{k}"))
    except Exception:
        pass
    # keep only levels in the profit direction within the [min,max] band
    good = []
    for price, tag in cands:
        d = (entry - price) if action == "SELL" else (price - entry)
        if min_d <= d <= max_d:
            good.append((d, price, tag))
    if good:
        good.sort()                         # nearest meaningful level first
        d, price, tag = good[0]
        sig["tp_basis"] = tag               # record WHY this TP
        return round(price, 5)
    sig["tp_basis"] = f"RR{fb_rr}xSL (no level in band)"
    return round(entry - sl_dist * fb_rr, 5) if action == "SELL" else round(entry + sl_dist * fb_rr, 5)


# ---- POSITION MANAGEMENT: protect profit when the % reverses ---------------
def _modify_sl(mt5, pos, new_sl, armed, why):
    cur = float(pos.sl) if pos.sl else 0.0
    is_buy = pos.type == 0
    # only ratchet in the protective direction (up for BUY, down for SELL)
    if cur:
        if is_buy and new_sl <= cur + 1e-9: return
        if (not is_buy) and new_sl >= cur - 1e-9: return
    if not armed:
        _log(f"DRY {pos.symbol} move SL -> {new_sl:.2f} ({why})"); return
    req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol,
           "position": pos.ticket, "sl": float(new_sl), "tp": float(pos.tp), "magic": MAGIC}
    mt5.order_send(req)
    _log(f"{pos.symbol} SL -> {new_sl:.2f} ({why})")


def _close(mt5, pos, armed, why):
    if not armed:
        _log(f"DRY close {pos.symbol} ticket {pos.ticket} ({why}) profit {pos.profit:+.2f}"); return
    # try both supported filling modes with a FRESH tick each attempt; log errors
    for fm in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC):
        tick = mt5.symbol_info_tick(pos.symbol)
        if not tick:
            continue
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": float(pos.volume),
               "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
               "position": pos.ticket, "price": tick.bid if pos.type == 0 else tick.ask,
               "deviation": 50, "magic": MAGIC, "comment": "PROTECT"[:31],
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": fm}
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            _log(f"CLOSED {pos.symbol} ({why}) profit {pos.profit:+.2f} retcode={r.retcode}")
            return
        _log(f"close attempt {pos.symbol} fm={fm} retcode={getattr(r,'retcode',None)} "
             f"err={mt5.last_error()}")
    _log(f"CLOSE FAILED {pos.symbol} ({why}) — will retry next cycle")


def _manage_positions(mt5, armed):
    """For each open signal-trade: if the % REVERSED, protect — lock profit /
    move to breakeven / cut early — instead of waiting for price to crawl back."""
    for pos in _my_positions(mt5):
        sig = _read_signal(pos.symbol)
        if not sig:
            continue
        act = sig.get("action")          # FINAL direction (writer already applied FADE)
        conf = float(sig.get("confidence") or 0)
        is_buy = pos.type == 0
        pos_dir = "BUY" if is_buy else "SELL"
        desired = act if act in ("BUY", "SELL") else "FLAT"
        # reversal = the signal now (corrected dir) wants the OPPOSITE of what we hold
        reversed_ = desired not in ("FLAT", pos_dir) and conf >= 40.0
        weakened = desired not in ("FLAT", pos_dir)
        profit = float(pos.profit)

        if reversed_:
            # thesis invalidated — lock the profit (or cut the loss) NOW
            _close(mt5, pos, armed, f"signal now wants {desired} ({conf:.0f}%)")
            continue
        if profit > 0 and weakened:
            # in profit + momentum fading -> move SL to breakeven (lock it)
            be = float(pos.price_open)
            _modify_sl(mt5, pos, be, armed, f"profit + % faded (score {score:+.0f}) -> breakeven lock")
            continue
        if profit > 0:
            # trail: lock half the open gain behind price as it runs our way
            tick = mt5.symbol_info_tick(pos.symbol)
            px = (tick.bid if is_buy else tick.ask)
            gain = (px - pos.price_open) if is_buy else (pos.price_open - px)
            lock = pos.price_open + (gain * 0.5 if is_buy else -gain * 0.5)
            _modify_sl(mt5, pos, lock, armed, "trail: lock 50% of open gain")


# ---- accuracy report from closed deals -------------------------------------
def _build_report(mt5):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=7), now) or []
    # pair our magic deals into round trips by position_id
    byp = defaultdict(list)
    for d in deals:
        if d.magic == MAGIC:
            byp[d.position_id].append(d)
    trades = []
    for pid, ds in byp.items():
        ds = sorted(ds, key=lambda x: x.time)
        ins = [d for d in ds if d.entry == 0]
        outs = [d for d in ds if d.entry == 1]
        if not ins or not outs:
            continue
        en = ins[0]
        net = sum(d.profit + d.commission + d.swap for d in ds)
        side = "BUY" if en.type == 0 else "SELL"
        # recover confidence from the comment "SIGEXEC BUY 75"
        conf = 0.0
        try:
            parts = (en.comment or "").split()
            conf = float(parts[-1]) if parts else 0.0
        except Exception:
            pass
        trades.append({"sym": en.symbol, "side": side, "net": net,
                       "won": net > 0, "conf": conf, "t": int(en.time)})
    # aggregate
    n = len(trades)
    wins = sum(1 for t in trades if t["won"])
    net = sum(t["net"] for t in trades)
    by_bucket = defaultdict(lambda: [0, 0, 0.0])  # bucket -> [n, wins, net]
    by_sym = defaultdict(lambda: [0, 0, 0.0])
    for t in trades:
        b = _conf_bucket(t["conf"])
        by_bucket[b][0] += 1; by_bucket[b][1] += int(t["won"]); by_bucket[b][2] += t["net"]
        by_sym[t["sym"]][0] += 1; by_sym[t["sym"]][1] += int(t["won"]); by_sym[t["sym"]][2] += t["net"]
    L = []
    L.append("# Signal Executor — هل صدق ولا لا (accuracy)")
    L.append(f"\n_تحديث: {now.isoformat()}_  ·  magic {MAGIC}  ·  عتبة الدخول ≥ {MIN_CONF:.0f}%\n")
    wr = 100 * wins / n if n else 0
    L.append(f"## الإجمالي: {n} صفقة · صدق {wins} ({wr:.0f}%) · صافي ${net:+.2f}\n")
    L.append("## دقة حسب نسبة الثقة (الأهم للضبط)")
    L.append("| الثقة | صفقات | صدق | نسبة الصدق | صافي$ |")
    L.append("|------|------|-----|-----------|------|")
    for b in ["90-100", "80-90", "70-80", "60-70", "<60"]:
        if b in by_bucket:
            nn, ww, net_b = by_bucket[b]
            L.append(f"| {b}% | {nn} | {ww} | {100*ww/nn:.0f}% | {net_b:+.2f} |")
    L.append("\n## حسب الرمز")
    L.append("| الرمز | صفقات | صدق | نسبة | صافي$ |")
    L.append("|------|------|-----|------|------|")
    for sym, (nn, ww, net_s) in sorted(by_sym.items()):
        L.append(f"| {sym} | {nn} | {ww} | {100*ww/nn:.0f}% | {net_s:+.2f} |")
    L.append("\n## آخر 12 نداء")
    L.append("| وقت | رمز | اتجاه | ثقة | نتيجة | صافي$ |")
    L.append("|----|-----|-------|-----|-------|------|")
    for t in sorted(trades, key=lambda x: x["t"], reverse=True)[:12]:
        ts = datetime.fromtimestamp(t["t"], tz=timezone.utc).strftime("%m-%d %H:%M")
        verdict = "✅ صدق" if t["won"] else "❌ غلط"
        L.append(f"| {ts} | {t['sym']} | {t['side']} | {t['conf']:.0f}% | {verdict} | {t['net']:+.2f} |")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    return {"n": n, "wins": wins, "wr": round(wr, 1), "net": round(net, 2)}


def _realized_today(mt5):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(hours=24), now) or []
    return sum(d.profit + d.commission + d.swap for d in deals
               if d.magic == MAGIC and d.entry == 1)


def _tuned_min_conf(default):
    """SELF-TUNING: read the learned threshold from signal_learn (signal_tuning.json).
    If shadow-tracking found a lower bucket that actually wins >=55%, trade it."""
    try:
        t = json.loads((DATA / "signal_tuning.json").read_text(encoding="utf-8"))
        return max(45.0, min(90.0, float(t.get("recommended_min_conf", default))))
    except Exception:
        return default


def _trade_mode():
    """FOLLOW or FADE — learned. If the signal is inverse-predictive (loses
    consistently), the learner says FADE and we flip BUY<->SELL."""
    try:
        t = json.loads((DATA / "signal_tuning.json").read_text(encoding="utf-8"))
        return t.get("mode", "FOLLOW")
    except Exception:
        return "FOLLOW"


def _flip(action):
    return "SELL" if action == "BUY" else "BUY" if action == "SELL" else action


def _load_scale():
    """Read SCALE-UP config the 15-min review writes when accuracy is confirmed:
    {lot, max_open}. Lets us grow size/positions without restarting."""
    lot, mx = LOT, MAX_OPEN_TOTAL
    try:
        c = json.loads((DATA / "signal_exec_config.json").read_text(encoding="utf-8"))
        lot = max(0.01, min(1.0, float(c.get("lot", lot))))
        mx = max(1, min(8, int(c.get("max_open", mx))))
    except Exception:
        pass
    return lot, mx


def _quality_ok(mt5, symbol, sig):
    """DEVELOPED quality gate — take a scalp only if it can realistically beat
    the spread cost. Returns (ok, reason)."""
    if not QUALITY_GATE:
        return True, ""
    from datetime import datetime as _dt, timezone as _tz
    h = _dt.now(_tz.utc).hour
    if h not in LIQUID_HOURS:
        return False, f"خارج جلسة السيولة ({h}UTC)"
    if REQUIRE_STOCH_CONF and not sig.get("stoch_confirmed"):
        return False, "ستوكاستك غير مؤكَّد"
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False, "no tick"
    spread = float(tick.ask) - float(tick.bid)
    lv = sig.get("levels") or {}
    tp = lv.get("tp") or lv.get("tp1")
    entry = lv.get("entry") or float(tick.bid)
    if tp and spread > 0:
        tp_dist = abs(float(tp) - float(entry))
        if tp_dist < MIN_TP_SPREAD_MULT * spread:
            return False, f"هدف صغير ({tp_dist:.2f}<{MIN_TP_SPREAD_MULT}×فرق {spread:.2f})"
    return True, "جودة عالية"


def run_cycle(mt5, armed):
    # MOMENT-BY-MOMENT SAFETY: track the SIGNAL SYSTEM'S OWN P&L only (magic 99784,
    # realized today + current floating) — independent of the user's manual trades.
    sys_realized = _realized_today(mt5)
    sys_floating = sum(float(p.profit) for p in _my_positions(mt5))
    sys_pnl = sys_realized + sys_floating
    if sys_pnl <= SIGNAL_DD_STOP:
        for pos in _my_positions(mt5):
            _close(mt5, pos, armed, f"signal DD ${sys_pnl:.2f}")
        _log(f"⛔ SIGNAL DRAWDOWN ${sys_pnl:.2f} <= ${SIGNAL_DD_STOP} (our own) — closed all, pausing")
        return
    # FIRST: protect/manage open positions (lock profit on % reversal) BEFORE new entries
    _manage_positions(mt5, armed)
    globals()["LOT"], max_open = _load_scale()
    open_total = len(_my_positions(mt5))
    realized = _realized_today(mt5)
    daily_block = realized <= DAILY_LOSS_STOP
    eff_min_conf = _tuned_min_conf(MIN_CONF)   # auto-tuned each cycle from measured hit-rates
    mode = _trade_mode()                       # FOLLOW or FADE (learned)
    for symbol in SYMBOLS:
        sig = _read_signal(symbol)
        if not sig:
            continue
        action = sig.get("action")        # FINAL direction (FADE already applied by the writer)
        conf = float(sig.get("confidence") or 0)
        if action not in ("BUY", "SELL"):
            continue
        if not TRADE_ALL and conf < eff_min_conf:   # TRADE_ALL = enter at ANY confidence
            continue
        # already in a position on this symbol? skip (one per symbol)
        if _my_positions(mt5, symbol):
            continue
        if open_total >= max_open:
            continue
        if daily_block:
            _log(f"daily loss stop hit (${realized:.2f}) — no new entries")
            break
        ok, why = _quality_ok(mt5, symbol, sig)   # DEVELOPED quality gate
        if not ok:
            continue                              # skip low-quality scalp (cost/session/confirmation)
        _enter(mt5, symbol, sig, armed)
        _log(f"ENTER {symbol} {action} [جودة: {why}]")
        open_total += 1
    rep = _build_report(mt5)
    _log(f"calls={rep['n']} truth={rep['wr']}% net=${rep['net']} open={len(_my_positions(mt5))} realized24h=${realized:.2f}")


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--min-conf", type=float, default=MIN_CONF)
    ap.add_argument("--symbols", nargs="*", default=None,
                    help="restrict to these symbols (default: all in SYMBOLS)")
    args = ap.parse_args(argv)
    globals()["MIN_CONF"] = args.min_conf
    if args.symbols:
        globals()["SYMBOLS"] = list(args.symbols)

    if not mt5.initialize():
        _log("MT5 init failed"); return 1
    ai = mt5.account_info()
    if ai and ai.trade_mode != 0 and not args.dry:
        _log(f"REFUSED — account trade_mode={ai.trade_mode} is NOT demo. Use --dry."); mt5.shutdown(); return 2
    armed = (not args.dry)
    _log(f"start magic={MAGIC} symbols={SYMBOLS} min_conf={args.min_conf} armed={armed} "
         f"(account {ai.login} bal ${ai.balance:.2f})")

    loop = args.loop and not args.once
    if loop and not _acquire():
        _log("another instance holds the lock — exiting"); mt5.shutdown(); return 3
    try:
        while True:
            try:
                run_cycle(mt5, armed)
            except Exception as e:
                _log(f"cycle error: {e}")
            if not loop:
                break
            time.sleep(POLL)
    finally:
        _release()
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
