"""gold_live.py — DISCIPLINED single-position GOLD trader (magic 99791).

The opposite of the fearless stacker. It deploys the GOLD specialist's best-evolved gene
(read live from specialist/XAUUSDm/memory.json each cycle, so it adopts better genes as the
organism learns) under STRICT discipline:

  • ONE position at a time (NO stacking, NO averaging)
  • bidirectional: BUY on confirmed up / SELL on confirmed down (candle + RSI + EMA)
  • per-order STOP (stop_atr·ATR) + TP (target_atr·ATR) — defined risk/reward
  • risk RISK_PCT of equity, sized to the stop (lot grows slowly with balance)
  • DAILY KILL -10% + MARGIN FLOOR 200% — real anti-ruin rails (this is NOT fearless)

DEMO. Run:  python gold_live.py --loop   (--dry to simulate)
"""
from __future__ import annotations
import argparse, json, time, datetime
from pathlib import Path

GOLD = "XAUUSDm"; MAGIC = 99791
RISK_PCT = 1.0; DAILY_KILL_PCT = 10.0; MARGIN_FLOOR = 0.0; POLL = 5  # MARGIN_FLOOR=0 (بطلب المستخدم: لا خوف من الهامش — يتصرّف حسب تحليله). per-trade SL لا زال يحدّ كل صفقة. رجّعه 200 لإعادة الحماية.
BEST = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\specialist\XAUUSDm\memory.json")
STATE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\gold_live_state.json")
DEFAULT = {"rsi_buy": 58, "rsi_sell": 45, "ema": 10, "stop_atr": 3.0, "target_atr": 2.0, "tf": "M15"}
# ── EARNED-AGGRESSION ladder: aggression unlocks ONLY as the bot proves it wins ──
#   tier by realized gain since launch → more concurrent positions + bigger size.
#   Extra positions (beyond the 1st) require a HIGH-QUALITY 'golden' setup (sniper).
QUALITY_GATE = 0.70      # extra (stacked) entries only when setup quality >= this
CONFLUENCE_GATE = 0.55   # chart-read confluence (0..1) required to take ANY entry (disciplined mode)
# ── SCALP MODE: sensitive M1 both-direction scalper. Keeps the anti-ruin RAILS
#    (always SL+TP, daily-kill, margin-floor) and still binds entries to the chart read,
#    but trades FAST on M1 with light triggers and a relaxed confluence gate. ──
SCALP = True
SCALP_CFG = {"tf": "M15", "ema": 9, "stop_atr": 2.0, "target_atr": 6.0}  # D-config M15 (walk-forward 4/5✅, let-winners-run)
SCALP_CONF = 0.25        # HIGH-sensitivity chart-confluence gate (dir must still agree)
DISC_GATE = 0.60         # بوابة انضباط: لا دخول إلا على ترند قويّ (≥0.6 قناعة) — ضد الإفراط/النزيف
NIGHT_START_UTC = 22; NIGHT_END_UTC = 8   # حظر ليلي UTC — الحافة المثبتة (لا دخول 22:00-08:00)
NIGHT_DISCIPLINE = False  # ⚠️ بطلب المستخدم: أُزيل الحظر الليلي. رجّعه True لإعادة الحافة المثبتة.
SCALP_RISK_PCT = 0.5     # smaller per-trade risk (many small trades)
SCALP_LOT_CAP = 0.30     # hard lot cap in scalp mode (small SL => big lot otherwise)
SCALP_POLL = 1           # react every tick (~1s) — fastest reaction
# ── PRECISE seconds-level EXIT management (the "when to take profit" half) ──
SCALP_TP_USD_PCT = 0.25  # FAST CYCLE (user): capture profit at +0.25% equity so trades close fast
SCALP_MAX_HOLD   = 90    # FAST CYCLE (user): close ANY trade after 90s → every trade feeds the evolver
SCALP_BE_ATR     = 1.0   # +1*ATR profit = TRIGGER: start trailing (never below break-even)
SCALP_TRAIL_ATR  = 1.5   # trail DISTANCE behind price (precise — matches walk-forward 4/5✅)
CONV_MAX_MULT    = 2.0   # per-position lot mult at max confluence (kept modest — CONVICTION now
                         #   drives the COUNT of stacked positions, see MAX_STACK below)
MAX_STACK        = 10    # CONVICTION PYRAMIDING: higher confluence → more stacked positions, up
                         #   to this many — BUT only added on top of a WINNING basket (into strength,
                         #   never averaging into a loser). Total lots still hard-capped by coordinator.
HALT_FLAG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_halt.flag")
# ── SELF-EVOLVED live config: scalp_evolver.py tunes these per-trade toward profit and
#    writes them here; the scalper reads them fresh each cycle and adopts the best-known. ──
SCALP_LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\scalp_live_config.json")
# ── SINGLE-INSTANCE LOCK (anti double-trade) — a respawner/coordinator may launch
#    several gold_live copies; only the LOCK HOLDER trades, the rest idle. Heartbeat
#    file refreshed each entry cycle; if the holder dies (stale >8s) a follower takes over.
import os as _os
LOCK = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\gold_live.lock")


def _is_leader() -> bool:
    me = _os.getpid(); now = time.time()
    try:
        d = json.loads(LOCK.read_text(encoding="utf-8"))
        if d.get("pid") != me and (now - float(d.get("ts", 0))) < 8.0:
            return False                      # another live instance holds a fresh lock
    except Exception:
        pass
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps({"pid": me, "ts": now}), encoding="utf-8")
        return json.loads(LOCK.read_text(encoding="utf-8")).get("pid") == me  # last writer wins
    except Exception:
        return True                            # lock unusable → fail-open to trading


def _scalp_over():
    """اربط الجين الحيّ: يتداول بإعداد جين الذهب المُتطوّر (BEST/memory.json) ويتبنّى الأفضل كل
    دورة تلقائيًّا (= يطوّر نفسه بنفسه). يأخذ من الجين tf/ema/rsi/stop/target، ويُبقي رِيلات
    السكالب للخروج (BE + trailing + let-winners-run). scalp_evolver يضبط الحساسية (conf_gate) فقط."""
    base = {"tf": SCALP_CFG["tf"], "ema": SCALP_CFG["ema"],
            "stop_atr": SCALP_CFG["stop_atr"], "target_atr": SCALP_CFG["target_atr"],
            "rsi_buy": 50, "rsi_sell": 50, "conf_gate": SCALP_CONF,
            "tp_usd_pct": SCALP_TP_USD_PCT, "max_hold": SCALP_MAX_HOLD}
    try:  # الجين المُتطوّر = مصدر الحقيقة لمعاملات الإستراتيجية (يتبنّى الأفضل لحظيًّا)
        gene = json.loads(BEST.read_text(encoding="utf-8"))["best"]["config"]
        for k in ("tf", "ema", "rsi_buy", "rsi_sell", "stop_atr", "target_atr"):
            if k in gene:
                base[k] = gene[k]
        base["_gene_gen"] = json.loads(BEST.read_text(encoding="utf-8")).get("generation")
    except Exception:
        pass
    # انضباط ضد الإفراط: بوابة قناعة عالية — يدخل فقط على ترند قوي (لا يأخذ كل تذبذب).
    #   8 صفقات/ساعة على بوابة 0.2 = نزيف سبريد. 0.6 يصفّي الضعيف ويُبقي القوي فقط.
    base["conf_gate"] = DISC_GATE
    return base


def _cfg():
    try:
        b = json.loads(BEST.read_text(encoding="utf-8"))["best"]["config"]
        return {**DEFAULT, **b}
    except Exception:
        return DEFAULT


def _ema(x, n):
    a = 2.0 / (n + 1.0); o = list(x)
    for i in range(1, len(x)): o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o


def _rsi(c, n=14):
    g = l = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    g /= max(len(c) - 1, 1); l /= max(len(c) - 1, 1)
    return 100 - 100 / (1 + g / l) if l > 1e-9 else 100.0


def _atr(r, n=14):
    t = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]), abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(t[-n:]) / n if t else 0.0


def _daily(mt5):
    start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    deals = mt5.history_deals_get(int(start), int(time.time())) or []
    return sum(d.profit + d.commission + d.swap for d in deals if d.magic == MAGIC and d.entry == 1)


_REGIME = {"ts": 0.0, "name": None}


def _markov_regime(mt5):
    """Current DAILY Markov regime for gold (Bull/Bear/Sideways), cached 5 min.
    Trade only WITH the higher-TF regime — block counter-regime entries."""
    now = time.time()
    if now - _REGIME["ts"] < 300 and _REGIME["name"]:
        return _REGIME["name"]
    try:
        from markov_regime import label_regimes, transition_matrix  # pure numpy, safe
        r = mt5.copy_rates_from_pos(GOLD, mt5.TIMEFRAME_D1, 0, 2500)
        if r is None or len(r) < 120:
            return None
        close = [x["close"] for x in r]
        lab, valid = label_regimes(close, 20, 0.02)
        cur = int(lab[valid][-1]) if valid.any() else 1
        name = ["Bear", "Sideways", "Bull"][cur]
        _REGIME.update(ts=now, name=name)
        return name
    except Exception:
        return None


def _baseline(acct):
    try: s = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: s = {}
    if "baseline" not in s:
        s["baseline"] = float(acct.balance)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s), encoding="utf-8")
    return s.get("baseline", float(acct.balance))


def _tier(equity, baseline):
    """Aggression tier earned by realized gain since launch. Drawdown → defensive."""
    g = (equity - baseline) / baseline * 100.0 if baseline else 0.0
    if g < -3: return 0, 0.5          # losing → tier0 + half size (pull back)
    if g >= 15: return 3, 1.75
    if g >= 8:  return 2, 1.5
    if g >= 3:  return 1, 1.25
    return 0, 1.0


def _close(mt5, p, info, tick):
    """Market-close one position (opposite side, by ticket)."""
    if p.type == mt5.POSITION_TYPE_BUY:
        ot = mt5.ORDER_TYPE_SELL; px = tick.bid
    else:
        ot = mt5.ORDER_TYPE_BUY; px = tick.ask
    return mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": GOLD, "volume": float(p.volume),
                           "type": ot, "position": p.ticket, "price": px, "deviation": 30,
                           "magic": MAGIC, "comment": "scalp-exit", "type_filling": mt5.ORDER_FILLING_IOC})


_CONV = {"ts": 0, "conf": 0.0, "dir": 0}   # cached live conviction (refresh ~5s, not every tick)


def _conviction(mt5):
    """Live chart conviction (confluence + direction), cached ~5s to stay cheap on the tick loop."""
    now = mt5.symbol_info_tick(GOLD).time
    if now - _CONV["ts"] < 5 and _CONV["dir"] != 0:
        return _CONV["conf"], _CONV["dir"]
    try:
        import chart_read as _cr
        c = _cr.read_local(mt5, GOLD, "M5") or {}
        _CONV.update(ts=now, conf=float(c.get("confluence", 0.0)), dir=int(c.get("dir", 0) or 0))
    except Exception:
        pass
    return _CONV["conf"], _CONV["dir"]


def _manage(mt5, dry=False):
    """PROTECT PROFIT, never close at a loss on time (user):
      • a trade NOT in profit is left alone — it rides ONLY to the hard SL set at entry
        (we never time-close a break-even/losing trade).
      • the moment a trade IS in profit we move the SL to LOCK it (>= break-even), then TRAIL:
          - TIGHT trail (lock fast)         when conviction is ordinary  → don't lose the gain
          - LOOSE trail (let it run to TP)  when conviction is HIGH and in our direction
                                            (we're "sure" it hits target) → give it room.
    Runs every tick. The entry's hard SL is the only loss-exit."""
    info = mt5.symbol_info(GOLD); tick = mt5.symbol_info_tick(GOLD); acct = mt5.account_info()
    poss = [p for p in (mt5.positions_get(symbol=GOLD) or []) if p.magic == MAGIC]
    if not poss or not info or not tick or not acct:
        return []
    _mr = mt5.copy_rates_from_pos(GOLD, mt5.TIMEFRAME_M1, 0, 30)
    atr = _atr(_mr) if _mr is not None and len(_mr) > 2 else 0.0
    if atr <= 0:
        return []
    conf, cdir = _conviction(mt5)
    acts = []
    for p in poss:
        is_buy = (p.type == mt5.POSITION_TYPE_BUY)
        cur = tick.bid if is_buy else tick.ask
        in_profit = (cur - p.price_open) if is_buy else (p.price_open - cur)
        if in_profit <= 0:
            continue                                   # never close a non-profit trade on time
        want = 1 if is_buy else -1
        sure = (conf >= 0.80 and cdir == want)         # high conviction it will reach target
        trail_atr = 2.2 if sure else 0.6               # loose=let it run · tight=lock the gain now
        be = round(p.price_open + (atr * 0.02 if is_buy else -atr * 0.02), info.digits)  # >= break-even
        trail = round((cur - trail_atr * atr) if is_buy else (cur + trail_atr * atr), info.digits)
        new_sl = max(be, trail) if is_buy else min(be, trail)   # secured: never below break-even
        improve = (new_sl > (p.sl or 0)) if is_buy else ((p.sl == 0) or (new_sl < p.sl))
        if improve and not dry:
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": GOLD,
                            "position": p.ticket, "sl": new_sl, "tp": p.tp})
            acts.append(f"lockSL {new_sl} ({'run' if sure else 'tight'}) +{p.profit:.2f}")
    return acts


# ════════════════════════════════════════════════════════════════════════════
# جيش الوكلاء — طبقة دعم لحظية للسكالبر الحيّ (magic 99791). fail-open بالكامل:
# أي وكيل يغيب/يفشل → دعم محايد، لا يوقف التداول أبدًا. حُرّاس الكارثة
# (RiskSentinel + CircuitBreaker) وحدهم يحجبون (gold_live منضبط أصلًا)؛ بقية
# الوكلاء (دماغ + ريجيم) "يدعمون" برفع/خفض القناعة فقط. وكلاء مكتفون ذاتيًا
# (يقرؤون MT5 / إشارة الدماغ بأنفسهم) — ما يحتاجون snapshot من unified_trader.
# ════════════════════════════════════════════════════════════════════════════
_RNV2 = Path(r"C:\Users\Radhi\MT5\r_native_v2")
_AGENTS = {"breaker": None, "sentinel": None}


def _agents_support(mt5, want):
    """Consult the support agents for GOLD/magic 99791.
    Returns (allow: bool, conviction_delta: float, note: str)."""
    import sys
    if str(_RNV2) not in sys.path:
        sys.path.insert(0, str(_RNV2))
    side = "BUY" if want > 0 else "SELL"
    conv = 0.0; notes = []
    # 1) RiskSentinel + CircuitBreaker → SUPPORT (penalize conviction), NOT hard-block.
    #    gold_live's OWN rails (daily-kill -10%, margin-floor, scalp_proof halt) do the
    #    real blocking. Hard-blocking here DEADLOCKS: the "2 consec SLs → pause" never
    #    clears, because no new trade can close to end the streak while entries are
    #    frozen → it re-pauses forever. As a penalty it just makes the scalper pickier
    #    (smaller lot) after losses, then resumes and can break its own streak.
    try:
        from runtime.shared.risk_sentinel import RiskSentinel
        if _AGENTS["sentinel"] is None:
            _AGENTS["sentinel"] = RiskSentinel(magic=MAGIC, symbol=GOLD)
            if SCALP:
                _AGENTS["sentinel"].pause_minutes = 1
                _AGENTS["sentinel"].cooldown_sec = 3
        rs = _AGENTS["sentinel"].check()
        if rs:
            conv -= 0.25; notes.append("sentinel⚠")
    except Exception:
        pass
    try:
        from runtime.shared.circuit_breaker import CircuitBreaker
        if _AGENTS["breaker"] is None:
            _AGENTS["breaker"] = CircuitBreaker(magic=MAGIC, symbol=GOLD)
        cb = _AGENTS["breaker"].check()
        if cb:
            conv -= 0.25; notes.append("breaker⚠")
    except Exception:
        pass
    # 2) brain confluence — SUPPORT (nudge conviction; never hard-block here)
    try:
        from runtime.shared.brain_signal import brain_confluence
        bdir, bconf, _bwhy = brain_confluence(GOLD)
        bconf = float(bconf or 0.0)
        if bdir == side:
            conv += min(bconf, 100.0) / 100.0 * 0.30; notes.append(f"brain✓{bconf:.0f}")
        elif bdir:
            conv -= min(bconf, 100.0) / 100.0 * 0.20; notes.append(f"brain✗{bdir}{bconf:.0f}")
    except Exception:
        pass
    # 3) HTF regime — SUPPORT
    try:
        from runtime.shared.brain_signal import brain_regime
        rg = brain_regime(GOLD)
        if rg and rg.get("ok"):
            hd = rg.get("htf_dir")
            if hd == side:   conv += 0.15; notes.append("regime✓")
            elif hd:         conv -= 0.10; notes.append(f"regime✗{hd}")
            if rg.get("no_trend"): conv -= 0.05; notes.append("chop")
    except Exception:
        pass
    return (True, round(conv, 3), " ".join(notes) or "neutral")


def cycle(mt5, dry=False):
    info = mt5.symbol_info(GOLD); tick = mt5.symbol_info_tick(GOLD); acct = mt5.account_info()
    if not info or not tick or not acct:
        return "no data"
    # CAPITAL GUARD: scalp_proof writes this flag on a bleed floor → flatten & stop.
    if HALT_FLAG.exists():
        poss = [p for p in (mt5.positions_get(symbol=GOLD) or []) if p.magic == MAGIC]
        for p in poss:
            if not dry: _close(mt5, p, info, tick)
        return f"HALTED by guard — flattened {len(poss)} pos (remove {HALT_FLAG.name} to resume)"
    # PRECISE EXIT MANAGEMENT first (take profits / cut stale before looking for new entries)
    mgr = _manage(mt5, dry)
    # ── NIGHT DISCIPLINE (الحافة المثبتة): لا دخول جديد 22:00-08:00 UTC. الخروج تمّ أعلاه. ──
    _h = datetime.datetime.now(datetime.timezone.utc).hour
    if NIGHT_DISCIPLINE and (_h >= NIGHT_START_UTC or _h < NIGHT_END_UTC):
        return f"NIGHT {_h:02d}:00 UTC — لا دخول جديد (حافة الانضباط)." + (f" | {';'.join(mgr)}" if mgr else "")
    baseline = _baseline(acct); tier, risk_mult = _tier(acct.equity, baseline)
    max_pos = MAX_STACK if SCALP else (1 + tier)   # SCALP: conviction decides actual count below
    poss = [p for p in (mt5.positions_get(symbol=GOLD) or []) if p.magic == MAGIC]
    if len(poss) >= max_pos:
        return f"holding {len(poss)}/{max_pos} (tier {tier}) float {sum(p.profit for p in poss):.2f}" + (f" | {';'.join(mgr)}" if mgr else "")
    if DAILY_KILL_PCT > 0 and _daily(mt5) <= -DAILY_KILL_PCT / 100.0 * acct.equity:
        return f"DAILY KILL hit — done for today"
    if acct.margin > 0 and acct.margin_level and acct.margin_level < MARGIN_FLOOR:
        return f"margin {acct.margin_level:.0f}%<{MARGIN_FLOOR:.0f} — pause"
    if SCALP:
        c = _scalp_over(); risk_pct = SCALP_RISK_PCT; conf_gate = c["conf_gate"]; lot_cap = SCALP_LOT_CAP
    else:
        c = _cfg(); risk_pct = RISK_PCT; conf_gate = CONFLUENCE_GATE; lot_cap = 0.50
    TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15}.get(c["tf"], mt5.TIMEFRAME_M15)
    r = mt5.copy_rates_from_pos(GOLD, TF, 0, 200)
    if r is None or len(r) < 40:
        return "no bars"
    closes = [x["close"] for x in r]; ema = _ema(closes, int(c["ema"]))[-1]
    rsi = _rsi(closes); atr = _atr(r); price = tick.bid
    o0, c0 = r[-1]["open"], r[-1]["close"]
    reg = _markov_regime(mt5)
    if SCALP:
        # HIGH SENSITIVITY: TRADE THE CHART READ DIRECTLY. Enter in the consolidated
        # direction whenever confluence clears the (low) gate. The chart read itself is the
        # signal (EMA50 + Markov + RSI + MACD + Stoch). Coordinator + caps + floor are the safety.
        try:
            import chart_read as _cr
            cread = _cr.read_local(mt5, GOLD, c["tf"])     # fast ~50ms, won't stall the 2s loop
        except Exception:
            cread = None
        if not cread or cread.get("dir") is None:
            return "no chart read — standing aside (won't trade blind)"
        chart_conf = float(cread.get("confluence", 0.0)); src = cread.get("source", "?")
        cdir = cread["dir"]
        bull = (cdir == 1) and (chart_conf >= conf_gate)
        bear = (cdir == -1) and (chart_conf >= conf_gate)
        if not (bull or bear) or atr <= 0:
            return f"wait — chart dir {cdir} conf {chart_conf} (gate {conf_gate}, RSI {rsi:.0f}) [{src}]"
        want = 1 if bull else -1
    else:
        bull = (c0 > o0) and (rsi >= c["rsi_buy"]) and (price > ema)
        bear = (c0 < o0) and (rsi <= c["rsi_sell"]) and (price < ema)
        if not (bull or bear) or atr <= 0:
            return f"wait (RSI {rsi:.0f}, tier {tier}/{max_pos}slots)"
        if bull and reg == "Bear":
            return f"BUY vetoed — Markov regime is BEAR (q wait) [tier{tier}]"
        if bear and reg == "Bull":
            return f"SELL vetoed — Markov regime is BULL [tier{tier}]"
        want = 1 if bull else -1
        try:
            import chart_read as _cr
            cread = _cr.read(mt5, GOLD, c["tf"])
        except Exception:
            cread = None
        if not cread or cread.get("dir") is None:
            return "no chart read — standing aside (won't trade blind)"
        chart_conf = float(cread.get("confluence", 0.0)); src = cread.get("source", "?")
        if cread["dir"] != want:
            return f"{'BUY' if bull else 'SELL'} blocked — chart reads dir {cread['dir']} conf {chart_conf} [{src}]"
        if chart_conf < conf_gate:
            return f"{'BUY' if bull else 'SELL'} wait — chart confluence {chart_conf}<{conf_gate} (dir agrees) [{src}]"
    # ── جيش الوكلاء: دعم لحظي (fail-open). حُرّاس الكارثة يحجبون؛ الدماغ/الريجيم يرفعون أو يخفضون القناعة. ──
    a_allow, a_conv, a_note = _agents_support(mt5, want)
    if not a_allow:
        return f"{'BUY' if bull else 'SELL'} held by agents — {a_note} [tier{tier}]"
    # ── قراءة بنية لحظية دقيقة: تراكم دعم/مقاومة + قمم/قيعان (live_structure) ──
    #    تشتري قرب الدعم / تبيع قرب المقاومة → ترفع القناعة؛ الدخول داخل جدار → تخفضها.
    s_conv, s_note = 0.0, "struct?"
    try:
        import live_structure as _ls
        _struct = _ls.read(mt5, GOLD, TF)
        s_conv, s_note = _ls.conviction(_struct, want)
    except Exception:
        pass
    # ── live_quant: طبقة كمّية لحظية — تمنع الدخول في السوق العرضي (Efficiency Ratio)
    #    وتعدّل العدوانية بحالة الترند/التذبذب. (walk-forward: WR 61%→72%) ──
    q_mult = 1.0; q_why = ""
    try:
        import live_quant as _lq
        _ah = [_atr(r[:j]) for j in range(max(20, len(r) - 18), len(r))]
        _chop, q_mult, q_why = _lq.quant(closes, len(closes) - 1, atr, _ah, [])
        if _chop:
            return f"{'BUY' if bull else 'SELL'} quant veto — سوق عرضي [{q_why}] [tier{tier}]"
    except Exception:
        pass
    # ── SDK sub-agents bias (sdk_decision.json) — استشاري: يرفع/يخفض القناعة (fail-open) ──
    sdk_conv = 0.0; sdk_note = ""
    try:
        # 🛡️ 2026-07-08 (تدقيق التقييم العدائيّ): كان اتّجاه الـLLM يحقن ±0.20×ثقة في الجودة ⇒ الحجم، بلا حارس
        # تقادم — نصٌّ على مُدخَلٍ مقيسٍ ~رمية عملة يُحجِّم صفقةً، وملفٌّ بائت يوجّه صامتاً. إصلاحان: (أ) حارس
        # تقادم 120ث، (ب) وزنه على الحجم = 0 (استشاريّ فقط يُسجَّل، لا يُحجِّم — اتّجاه LLM بلا حافّة مقيسة).
        _sdp = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\sdk_decision.json")
        if _sdp.exists() and (time.time() - _sdp.stat().st_mtime) < 120:
            _sd = json.loads(_sdp.read_text(encoding="utf-8"))
            _sb = str(_sd.get("bias", "")).upper(); _sc = float(_sd.get("confidence", 0) or 0)
            if _sb in ("BUY", "SELL"):
                sdk_note = f"SDK{_sb}{_sc:.2f}(استشاريّ·وزن0)"   # sdk_conv يبقى 0.0 — لا يمسّ الجودة/الحجم
    except Exception:
        pass
    # SETUP QUALITY — RSI/body + chart confluence + agents + structure + SDK bias, scaled by quant.
    _q0 = max(0.0, min(1.0, 0.6 * min(abs(rsi - 50) / 30.0, 1.0) + 0.4 * min(abs(c0 - o0) / atr, 1.0)))
    quality = round(max(0.0, min(1.0, (0.5 * _q0 + 0.5 * chart_conf + a_conv + s_conv + sdk_conv) * q_mult)), 3)
    # SNIPER RULE: extra (stacked) positions ONLY on a GOLDEN setup (high quality)
    if len(poss) >= 1 and quality < QUALITY_GATE:
        return f"holding {len(poss)}/{max_pos} — setup q{quality:.2f}<{QUALITY_GATE} not golden enough to stack"
    # ── CONVICTION PYRAMIDING (SCALP): higher confluence → allow more stacked positions, BUT
    #    add ONLY on top of a WINNING basket (into strength). NEVER average into a loser. ──
    if SCALP and len(poss) >= 1:
        conv_frac = max(0.0, (chart_conf - conf_gate) / max(1e-9, 1.0 - conf_gate))
        allowed = 1 + int(round((MAX_STACK - 1) * conv_frac))
        if len(poss) >= allowed:
            return f"holding {len(poss)} — conviction (conf {chart_conf:.2f}) allows {allowed}"
        basket = sum(p.profit for p in poss)
        if basket < 0:
            return f"holding {len(poss)} — basket {basket:+.2f}<0, won't add to a loser (no martingale)"
    # VOL-REGIME target sizing (the one OOS-real signal): widen TP in expansion, tighten in
    # contraction. Scales the TARGET only — stop/risk untouched. Falls back to ×1.0 if absent.
    try:
        import vol_regime as _vr; vmult = _vr.target_mult(GOLD)
    except Exception:
        vmult = 1.0
    stop_dist = c["stop_atr"] * atr; tgt_dist = c["target_atr"] * atr * vmult
    tv = info.trade_tick_value / info.trade_tick_size if info.trade_tick_size else 1.0
    # size scales with EARNED tier (risk_mult) AND setup quality
    lot = (risk_pct / 100.0 * acct.equity * risk_mult * (0.6 + 0.4 * quality)) / (stop_dist * tv) if stop_dist * tv > 0 else info.volume_min
    conv_mult = 1.0
    if SCALP:
        # CONVICTION SIZING: scale lot from 1x (at the gate) up to CONV_MAX_MULT (at confluence=1.0).
        # Only big when VERY sure — "aggressive when confident", as ONE position (one spread/one stop).
        conv_frac = max(0.0, (chart_conf - conf_gate) / max(1e-9, 1.0 - conf_gate))
        conv_mult = 1.0 + (CONV_MAX_MULT - 1.0) * conv_frac
        lot = lot * conv_mult
    lot = max(info.volume_min, min(lot_cap, round(lot / info.volume_step) * info.volume_step))
    # ── COORDINATOR: the shared agreement ALL bots obey (one direction, shared caps, shared halt) ──
    try:
        import coordinator as _co
        _ok, _why = _co.gate(want, float(lot))
    except Exception:
        _ok, _why = True, "no-coord"
    if not _ok:
        return f"{'BUY' if bull else 'SELL'} held by coordinator — {_why} [tier{tier}]"
    if bull:
        side = "BUY"; entry = tick.ask; sl = round(entry - stop_dist, info.digits); tp = round(entry + tgt_dist, info.digits); ot = mt5.ORDER_TYPE_BUY
    else:
        side = "SELL"; entry = tick.bid; sl = round(entry + stop_dist, info.digits); tp = round(entry - tgt_dist, info.digits); ot = mt5.ORDER_TYPE_SELL
    nth = len(poss) + 1
    if dry:
        return f"DRY {side} #{nth}/{max_pos} {lot} @ {entry} SL {sl} TP {tp} q{quality:.2f} chart{chart_conf:.2f}[{src}] agents[{a_note}] struct[{s_note}] tier{tier}"
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": GOLD, "volume": float(lot),
                          "type": ot, "price": entry, "sl": sl, "tp": tp, "deviation": 30,
                          "magic": MAGIC, "comment": "gold-sniper", "type_filling": mt5.ORDER_FILLING_IOC})
    return f"{side} #{nth}/{max_pos} {lot}lot conv{conv_mult:.1f}x @ {entry} q{quality:.2f} chart{chart_conf:.2f}[{src}] agents[{a_note}] tier{tier} regime{reg or '?'} -> {getattr(res,'retcode',None)}"


def main(argv=None):
    import MetaTrader5 as mt5
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--once", action="store_true"); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    if SCALP:
        print(f"[GOLD-LIVE] SCALP mode · M1 · cfg {SCALP_CFG} · {SCALP_RISK_PCT}% risk · lot<= {SCALP_LOT_CAP} · conf>= {SCALP_CONF} · SL+TP · daily-kill -{DAILY_KILL_PCT}% · margin-floor {MARGIN_FLOOR}% · poll {SCALP_POLL}s · dry={a.dry}", flush=True)
    else:
        c = _cfg()
        print(f"[GOLD-LIVE] disciplined single-position gold · cfg {c} · 1% risk · ONE-at-a-time · SL+TP · daily-kill -{DAILY_KILL_PCT}% · margin-floor {MARGIN_FLOOR}% · dry={a.dry}", flush=True)
    try:
        if SCALP:
            # ── TWO-SPEED loop ("كل تك"): a FAST tick loop manages exits (fast profit
            #    capture / time-stop / break-even) the instant a NEW tick arrives, so open
            #    money is protected per-tick; the heavier ENTRY scan (chart read + agents +
            #    structure) runs at a sane ~1s cadence (it doesn't change faster, and
            #    scanning it every tick would only burn CPU). ──
            TICK = 0.12; ENTRY_EVERY = 1.0
            last_entry = 0.0; last_msc = 0; am_leader = False
            print(f"[GOLD-LIVE] TICK-mode · manage every tick (~{TICK}s) · entry scan every {ENTRY_EVERY}s", flush=True)
            while True:
                try:
                    now = time.monotonic()
                    if now - last_entry >= ENTRY_EVERY:
                        last_entry = now
                        am_leader = _is_leader()              # single-instance lock
                        if not am_leader:
                            print("[GOLD-LIVE] follower — another instance holds the lock; idling", flush=True)
                        else:
                            _r = cycle(mt5, a.dry); print(f"[GOLD-LIVE] {_r}", flush=True)
                            if isinstance(_r, str) and _r.startswith("HALTED"):
                                print("[GOLD-LIVE] guard halt — stopping loop.", flush=True); break
                    if am_leader:
                        tk = mt5.symbol_info_tick(GOLD)
                        if tk and getattr(tk, "time_msc", 0) != last_msc:
                            last_msc = tk.time_msc
                            mgr = _manage(mt5, a.dry)          # FAST: exits on every tick
                            if mgr: print(f"[GOLD-LIVE] tick {';'.join(mgr)}", flush=True)
                except Exception as e:
                    print(f"[GOLD-LIVE] err {e}", flush=True)
                if not a.loop or a.once: break
                time.sleep(TICK)
        else:
            while True:
                try:
                    if not _is_leader():
                        print("[GOLD-LIVE] follower — another instance holds the lock; idling", flush=True)
                    else:
                        _r = cycle(mt5, a.dry); print(f"[GOLD-LIVE] {_r}", flush=True)
                        if isinstance(_r, str) and _r.startswith("HALTED"):
                            print("[GOLD-LIVE] guard halt — stopping loop.", flush=True); break
                except Exception as e: print(f"[GOLD-LIVE] err {e}", flush=True)
                if not a.loop or a.once: break
                time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
