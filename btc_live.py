"""btc_live.py — disciplined BTCUSDm scalper (magic 99792), 24/7 crypto market.

Mirrors gold_live's CORE behaviors to TEST the modifications on the open weekend market:
  • entry bound to chart_read consolidated decision (dir + confluence)
  • conviction sizing (lot scales with confluence)
  • PROTECT-PROFIT exit: once in profit, trail SL to lock (loose if high-conviction → run to target);
    never time-close a non-profit trade — it rides ONLY to the hard SL set at entry
  • hard SL+TP every trade · daily-kill -10% · NO margin floor · NO night (fearless, by user)
DEMO. Run:  python btc_live.py --loop
"""
from __future__ import annotations
import argparse, json, time, datetime
from pathlib import Path

SYM = "BTCUSDm"
# daily-kill 10→5%: مراقبة 2026-06-15 — هذا البوت (99792) هو الوحيد النازف (-17 بـ40 إغلاق
# churn) ويعاكس مركز BTC الرابح للبوت 20260612. -10% (~$150) كان أكبر مخاطرة ذيلية في النظام.
# 5% (~$75) يبقى كريماً للتقلّب لكنه ينفّذ انضباط المستخدم «خفّف العدوانية وقت النزف».
DAILY_KILL_PCT = 5.0; POLL = 2
RISK_PCT = 0.5             # per-trade risk
CONV_MAX_MULT = 5.0        # AGGRESSIVE: lot up to 5x base at full confluence


def _risk_gov():
    """توحيد الحوكمة: هذا المنفّذ يطيع risk_register (مضاعف اللوت + وقف الدخول عند الطوارئ)."""
    try:
        import json as _j, time as _t
        d = _j.loads(open("C:/Users/Radhi/MT5/data/r_native/risk_register.json", encoding="utf-8").read())
        if _t.time() - float(d.get("ts", 0)) > 300:
            return 1.0, False
        return float(d.get("lot_mult", 1.0)), bool(d.get("emergency"))
    except Exception:
        return 1.0, False
LOT_CAP = 1.0
CONF_HIGH = 0.80           # "very high confidence" — unlocks aggressive pyramiding
MAX_STACK = 5              # max pyramided positions (into STRENGTH only, never a loser)
ADD_STEP_ATR = 0.6         # price must advance this far (×ATR) in our favor before adding
# ── TWO STYLES: scalp (fast M5, tight) + swing (slower H1, big targets, holds the trend) ──
DEF_SCALP = {"conf_gate": 0.55, "stop_atr": 3.0, "target_atr": 8.0, "be_atr": 0.3, "trail_tight": 0.8, "trail_loose": 3.0}
DEF_SWING = {"conf_gate": 0.60, "stop_atr": 4.0, "target_atr": 15.0, "be_atr": 0.8, "trail_tight": 1.5, "trail_loose": 4.5}
_DD = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
_COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")


def _panel_signal(max_age: int = 180):
    """Read the on-chart CLAUDE_SIGNAL panel's verdict (signal_<SYM>.json) — the same signal the
    user watches. Returns the dict, or None if missing/stale. Used to VETO trades that fight it."""
    try:
        d = json.loads((_COMMON / f"signal_{SYM}.json").read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) > max_age:
            return None
        return d
    except Exception:
        return None


def _panel_veto(cdir):
    """True if the panel's non-WAIT action contradicts the bot's intended direction.
    The panel only says BUY when oversold / SELL when overbought, so this also blocks
    buying into overbought (exactly the user's complaint)."""
    p = _panel_signal()
    if not p:
        return False, None
    act = p.get("action")
    if act in ("BUY", "SELL"):
        pdir = 1 if act == "BUY" else -1
        if pdir != cdir:
            return True, act
    return False, act
# mode-aware globals (set in main() per --mode):
MODE = "scalp"; MAGIC = 99792; TF_STR = "M5"; DEF = DEF_SCALP
CFG = _DD / "btc_live_config.json"          # scalp config (btc_evolver writes this)


def _tf(mt5):
    return {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4}.get(TF_STR, mt5.TIMEFRAME_M5)


def _over():
    """Merge defaults with the evolver's best-known live values (self-tuning)."""
    base = dict(DEF)
    try:
        d = json.loads(CFG.read_text(encoding="utf-8")).get("config", {})
        for k in base:
            if k in d: base[k] = d[k]
    except Exception:
        pass
    return base


def _ema(x, n):
    a = 2.0 / (n + 1.0); o = list(x)
    for i in range(1, len(x)): o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o[-1]


def _atr(r, n=14):
    t = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
            abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(t[-n:]) / n if t else 0.0


STATE = _DD / "btc_state.json"              # scalp state (hub dashboard reads this)


def _daily(mt5):
    start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    deals = mt5.history_deals_get(int(start), int(time.time())) or []
    return sum(d.profit + d.commission + d.swap for d in deals if d.magic == MAGIC and d.entry == 1)


def _rolling(mt5, hours=72):
    """نزف متعدّد-الأيام: صافي + WR على نافذة متدحرجة (يفلت من DAILY_KILL المُصفَّر منتصف الليل)."""
    deals = mt5.history_deals_get(int(time.time() - hours * 3600), int(time.time())) or []
    dl = [d for d in deals if d.magic == MAGIC and d.entry == 1]
    net = sum(d.profit + d.commission + d.swap for d in dl)
    wins = sum(1 for d in dl if (d.profit + d.commission + d.swap) > 0)
    return net, len(dl), (wins / len(dl) if dl else 1.0)


def _write_state(mt5):
    """Write BTC PnL/positions to a file the MT5-free hub can read (no MT5 in hub)."""
    try:
        start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        dl = [d for d in (mt5.history_deals_get(int(start), int(time.time())) or []) if d.magic == MAGIC and d.entry == 1]
        net = round(sum(d.profit + d.commission + d.swap for d in dl), 2)
        wins = sum(1 for d in dl if (d.profit + d.commission + d.swap) > 0)
        poss = [p for p in (mt5.positions_get(symbol=SYM) or []) if p.magic == MAGIC]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "symbol": SYM, "magic": MAGIC, "ts": time.time(),
            "closed_today": len(dl), "net_today": net, "wins_today": wins,
            "open": len(poss), "float": round(sum(p.profit for p in poss), 2)}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _close(mt5, p, info, tick):
    ot = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    px = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    return mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": float(p.volume),
                           "type": ot, "position": p.ticket, "price": px, "deviation": 50,
                           "magic": MAGIC, "comment": "btc-exit", "type_filling": mt5.ORDER_FILLING_IOC})


def _manage(mt5, conf, cdir):
    info = mt5.symbol_info(SYM); tick = mt5.symbol_info_tick(SYM)
    poss = [p for p in (mt5.positions_get(symbol=SYM) or []) if p.magic == MAGIC]
    if not poss or not info or not tick:
        return []
    r = mt5.copy_rates_from_pos(SYM, _tf(mt5), 0, 30)
    atr = _atr(r) if r is not None and len(r) > 2 else 0.0
    if atr <= 0:
        return []
    o = _over(); acts = []
    for p in poss:
        is_buy = (p.type == mt5.POSITION_TYPE_BUY)
        cur = tick.bid if is_buy else tick.ask
        in_profit = (cur - p.price_open) if is_buy else (p.price_open - cur)
        # FAST PROFIT-SECURING: lock breakeven the moment it's ~0.1 ATR green (don't wait for
        # be_atr) — secures profit quickly as the user asked. Never time-closes a loser.
        secure_trig = min(o["be_atr"], 0.10) * atr
        if in_profit < secure_trig:
            continue
        want = 1 if is_buy else -1
        sure = (conf >= 0.80 and cdir == want)
        trail_atr = o["trail_loose"] if sure else o["trail_tight"]
        be = round(p.price_open, info.digits)
        trail = round((cur - trail_atr * atr) if is_buy else (cur + trail_atr * atr), info.digits)
        new_sl = max(be, trail) if is_buy else min(be, trail)
        improve = (new_sl > (p.sl or 0)) if is_buy else ((p.sl == 0) or (new_sl < p.sl))
        if improve:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": SYM,
                            "position": p.ticket, "sl": new_sl, "tp": p.tp})
            acts.append(f"lockSL {new_sl} ({'run' if sure else 'tight'}) +{p.profit:.2f}")
    return acts


def _vol_state():
    try:
        import vol_regime as _vr; return _vr.read_advisory(SYM).get("state", "?")
    except Exception:
        return "?"


def _log_entry(side, lot, entry, sl, tp, conf, cread, htf, conv_mult, vmult, vol_state, kind):
    """Record EXACTLY why we entered — every indicator vote, the MTF agreement, confidence,
    conviction size, vol regime. Appends to a ledger + writes the last reason for quick view."""
    votes = cread.get("votes", {}) or {}
    bull = [k for k, v in votes.items() if v == 1]
    bear = [k for k, v in votes.items() if v == -1]
    rec = {"ts": time.time(), "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "symbol": SYM, "kind": kind, "side": side, "lot": lot, "entry": entry, "sl": sl, "tp": tp,
           "conf": round(conf, 3), "dir": cread.get("dir"), "mtf_M15_H1": htf,
           "vol_regime": vol_state, "conv_mult": round(conv_mult, 2), "target_mult": vmult,
           "bull_votes": bull, "bear_votes": bear, "all_votes": votes}
    try:
        _DD.mkdir(parents=True, exist_ok=True)
        with open(_DD / "btc_entry_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        (_DD / "btc_last_entry.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return (f"{kind} {side} {lot}@{entry} conf{conf:.2f} conv{conv_mult:.1f}x [{vol_state}] "
            f"TP{tp} SL{sl} | bull={bull} bear={bear} mtf={htf}")


def _pyramid(mt5, info, tick, acct, poss, conf, cdir, htf, cread, vmult):
    """AGGRESSIVE add into a winning, very-high-confidence, MTF-aligned position. Never adds
    to a loser, never against direction. Adds only as price RUNS in our favor. Capped by stack."""
    if conf < CONF_HIGH or cdir == 0:
        return None
    if any(hd != cdir for hd in htf):
        return None
    want_buy = (cdir > 0)
    if any((p.type == mt5.POSITION_TYPE_BUY) != want_buy for p in poss):
        return None
    if sum(p.profit for p in poss) <= 0 or len(poss) >= MAX_STACK:
        return None
    if _panel_veto(cdir)[0]:                            # don't pyramid against the chart signal
        return None
    r = mt5.copy_rates_from_pos(SYM, _tf(mt5), 0, 100)
    if r is None or len(r) < 30:
        return None
    atr = _atr(r)
    if atr <= 0:
        return None
    cur = tick.ask if want_buy else tick.bid
    last_entry = max(p.price_open for p in poss) if want_buy else min(p.price_open for p in poss)
    advanced = (cur - last_entry) if want_buy else (last_entry - cur)
    if advanced < ADD_STEP_ATR * atr:
        return None                                    # only add as it keeps running our way
    o = _over()
    stop_dist = o["stop_atr"] * atr; tgt_dist = o["target_atr"] * atr * vmult
    tv = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size else 1.0
    conv_frac = max(0.0, (conf - o["conf_gate"]) / max(1e-9, 1.0 - o["conf_gate"]))
    conv_mult = 1.0 + (CONV_MAX_MULT - 1.0) * conv_frac
    _rm, _em = _risk_gov()
    if _em:
        return None                      # طوارئ: لا دخول جديد
    base = (_rm * RISK_PCT / 100.0 * acct.equity * conv_mult) / (stop_dist * tv) if stop_dist * tv > 0 else info.volume_min
    lot = max(info.volume_min, min(LOT_CAP, round(base * 0.6 / info.volume_step) * info.volume_step))
    if want_buy:
        entry = tick.ask; sl = round(entry - stop_dist, info.digits); tp = round(entry + tgt_dist, info.digits); ot = mt5.ORDER_TYPE_BUY; side = "BUY"
    else:
        entry = tick.bid; sl = round(entry + stop_dist, info.digits); tp = round(entry - tgt_dist, info.digits); ot = mt5.ORDER_TYPE_SELL; side = "SELL"
    mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": float(lot),
                    "type": ot, "price": entry, "sl": sl, "tp": tp, "deviation": 50,
                    "magic": MAGIC, "comment": "btc-pyramid", "type_filling": mt5.ORDER_FILLING_IOC})
    return _log_entry(side, lot, entry, sl, tp, conf, cread, htf, conv_mult, vmult, _vol_state(), "PYRAMID")


def cycle(mt5):
    info = mt5.symbol_info(SYM); tick = mt5.symbol_info_tick(SYM); acct = mt5.account_info()
    if not info or not tick or not acct:
        return "no data"
    import chart_read as cr
    cread = cr.read_local(mt5, SYM, TF_STR) or {}        # M5 = timing/confirmation
    m5dir = int(cread.get("dir", 0) or 0); m5conf = float(cread.get("confluence", 0.0))
    # TRADE WITH THE HIGHER-TF TREND: macro = M15+H1 consensus. The noisy M5 is used for timing,
    # it does NOT veto the macro trend (that was making it sit out valid higher-TF moves).
    htf = []; htf_conf = []
    for _h in ("M15", "H1"):
        _hr = cr.read_local(mt5, SYM, _h) or {}
        htf.append(int(_hr.get("dir", 0) or 0)); htf_conf.append(float(_hr.get("confluence", 0.0)))
    macro = htf[0] if (htf and all(h == htf[0] and h != 0 for h in htf)) else 0
    cdir = macro
    conf = (sum(htf_conf) / len(htf_conf)) if htf_conf else 0.0
    try:
        import vol_regime as _vr; vmult = _vr.target_mult(SYM)
    except Exception:
        vmult = 1.0
    mgr = _manage(mt5, conf, cdir)
    poss = [p for p in (mt5.positions_get(symbol=SYM) or []) if p.magic == MAGIC]
    if poss:
        add = _pyramid(mt5, info, tick, acct, poss, conf, cdir, htf, cread, vmult)
        base = f"holding {len(poss)} float {sum(p.profit for p in poss):.2f}"
        extra = " | ".join(x for x in [(';'.join(mgr) if mgr else ''), (add or '')] if x)
        return base + (f" | {extra}" if extra else "")
    if DAILY_KILL_PCT > 0 and _daily(mt5) <= -DAILY_KILL_PCT / 100.0 * acct.equity:
        return "DAILY KILL — done for today"
    # 🩸 بوابة نزف متعدّد-الأيام (تدقيق 2026-06-15: 99792 = −$126/7d بـ WR 27% على رمز يربح فيه
    # اليدوي). لو 72س ≤ −3% حقوق أو WR<30% على ≥40 صفقة → أوقف الدخول الجديد (الإدارة تكمل،
    # ويُستأنف تلقائياً حين تتعافى النافذة). يفلت هذا النزف البطيء من DAILY_KILL المُصفَّر منتصف الليل.
    _rnet, _rn, _rwr = _rolling(mt5, 72)
    if _rnet <= -0.03 * acct.equity or (_rn >= 40 and _rwr < 0.30):
        return f"ROLLING-KILL 72h: net {_rnet:.0f} wr {_rwr:.0%} n{_rn} — paused (الإدارة تكمل)"
    o = _over()
    if cdir == 0 or conf < o["conf_gate"]:
        return f"wait — HTF macro {cdir} conf {conf:.2f} (gate {o['conf_gate']}, M5 {m5dir})"
    # macro IS the M15+H1 consensus (focus built-in); M5 disagreement allowed (noisy TF).
    # PANEL RESPECT: never trade against the on-chart CLAUDE_SIGNAL the user watches, and never
    # buy into overbought / sell into oversold (the panel's stochastic gate enforces this).
    vetoed, pact = _panel_veto(cdir)
    if vetoed:
        return f"veto — panel(CLAUDE_SIGNAL)={pact} vs bot {'BUY' if cdir > 0 else 'SELL'} — not fighting the chart signal"
    r = mt5.copy_rates_from_pos(SYM, _tf(mt5), 0, 100)
    if r is None or len(r) < 30:
        return "no bars"
    atr = _atr(r); price = tick.bid
    if atr <= 0:
        return "atr0"
    stop_dist = o["stop_atr"] * atr; tgt_dist = o["target_atr"] * atr * vmult
    tv = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size else 1.0
    conv_frac = max(0.0, (conf - o["conf_gate"]) / max(1e-9, 1.0 - o["conf_gate"]))
    conv_mult = 1.0 + (CONV_MAX_MULT - 1.0) * conv_frac
    lot = (RISK_PCT / 100.0 * acct.equity * conv_mult) / (stop_dist * tv) if stop_dist * tv > 0 else info.volume_min
    lot = max(info.volume_min, min(LOT_CAP, round(lot / info.volume_step) * info.volume_step))
    if cdir > 0:
        side = "BUY"; entry = tick.ask; sl = round(entry - stop_dist, info.digits); tp = round(entry + tgt_dist, info.digits); ot = mt5.ORDER_TYPE_BUY
    else:
        side = "SELL"; entry = tick.bid; sl = round(entry + stop_dist, info.digits); tp = round(entry - tgt_dist, info.digits); ot = mt5.ORDER_TYPE_SELL
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYM, "volume": float(lot),
                          "type": ot, "price": entry, "sl": sl, "tp": tp, "deviation": 50,
                          "magic": MAGIC, "comment": "btc-scalp", "type_filling": mt5.ORDER_FILLING_IOC})
    reason = _log_entry(side, lot, entry, sl, tp, conf, cread, htf, conv_mult, vmult, _vol_state(), "ENTRY")
    return f"{reason} -> {getattr(res, 'retcode', None)}"


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--mode", choices=["scalp", "swing"], default="scalp")
    a = ap.parse_args(argv)
    global MODE, MAGIC, TF_STR, DEF, CFG, STATE
    MODE = a.mode
    if MODE == "swing":
        MAGIC = 99793; TF_STR = "H1"; DEF = DEF_SWING
        CFG = _DD / "btc_live_config_swing.json"; STATE = _DD / "btc_state_swing.json"
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    if not mt5.symbol_select(SYM, True):
        print(f"cannot select {SYM}")
    tag = "SWING H1" if MODE == "swing" else "SCALP M5"
    print(f"[BTC-{MODE.upper()}] {SYM} magic {MAGIC} · {tag} · self-tuned cfg {_over()} · conviction · protect-profit · hard SL · daily-kill {DAILY_KILL_PCT}% · DEMO", flush=True)
    try:
        while True:
            try: print(f"[BTC-LIVE] {cycle(mt5)}", flush=True); _write_state(mt5)
            except Exception as e: print(f"[BTC-LIVE] err {e}", flush=True)
            if not a.loop or a.once: break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
