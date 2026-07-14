# -*- coding: utf-8 -*-
"""conflict_resolver.py — 🧩 المُعالِج الذاتيّ لتعارض القرارات (لا يكتفي بالكشف — يحلّ بنفسه).

يقرأ ما هو مترابطٌ في المخّ: اتجاه الدولار DXY + قرارات المجلس لكل رمز + مراكز محرّكاتنا المفتوحة.
يكشف نوعين من عدم-التماسك ويعالجهما ذاتيّاً:
  (أ) تعارض اقتصاديّ مع الدولار: زوجٌ دولاريّ إشارته ضدّ اتجاه DXY (دولار↑ ⇒ USDxxx شراء، xxxUSD بيع).
  (ب) تحوّط ذاتيّ: محرّكان لنا متعاكسان على نفس الرمز (غسل سبريد مزدوج).

المعالجة (آمنة، محافظة):
  1) 🛡️ وقائيّ (صفر خطر): يكتب coherence.json — الاتّجاه المتعارض «ممنوع»؛ المحرّكات تقرؤه فتتخطّى
     الدخول المتعارض قبل أن يكلّف مالاً. هذا هو الحلّ الأساسيّ (يمنع التعارض قبل أن يصير صفقة).
  2) ✂️ علاجيّ (config-gated): يقصّ مراكزنا المتعارضة **الخاسرة فقط** (عائم<عتبة). لا يمسّ الرابحة أبداً
     (السوق يخالف الاستدلال ⇒ نثق بالربح)، ولا يمسّ اليدويّ magic 0 ولا أيّ EA خارجيّة.

الخطّ المقدّس: لا يمسّ master_floor/kill_switch. ديمو فقط. windowless. يكتب resolutions للمخّ (/rt/coherence).
Run: pythonw conflict_resolver.py
"""
from __future__ import annotations
import sys, os, json, time
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LOG = RN / "conflict_resolver.out.log"
COH_F = RN / "coherence.json"              # التوجيه الوقائيّ: {sym: {veto_dir, reason, ...}}
STATUS_F = RN / "conflict_resolver_status.json"
RESOLVE_F = RN / "conflict_resolutions.jsonl"
CFG_F = RN / "conflict_resolver_config.json"
COUNCIL_F = RN / "agent_council.json"

# نافذة-آمن
try:
    RN.mkdir(parents=True, exist_ok=True)
    _lf = open(LOG, "a", buffering=1, encoding="utf-8"); sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass
if str(MT5DIR) not in sys.path:
    sys.path.insert(0, str(MT5DIR))

import MetaTrader5 as mt5
try:
    import engine_lock
except Exception:
    engine_lock = None

# 🛡️ محرّكاتنا فقط — اليدويّ 0 و EA الخارجيّة {2447,20250418,20250421,20250422,20250618,20240707} ليست هنا أبداً
OUR_MAGICS = frozenset({20260701, 20260706, 20260707, 20260709, 20260703, 20260631, 20260600})
DXY = "DXYm"
POLL_S = 5
# الدولار أساسٌ (صعوده ⇒ الزوج↑) مقابل مقوّم (صعوده ⇒ الزوج↓)
USD_BASE = {"USDJPYm", "USDCADm", "USDCHFm", "USDSGDm", "USDNOKm", "USDSEKm"}
USD_QUOTE = {"EURUSDm", "GBPUSDm", "AUDUSDm", "NZDUSDm"}


def _cfg():
    d = {"enabled": True, "veto_enabled": True, "close_losers": True,
         "min_loss_usd": 0.30,          # لا يقصّ إلا مركزاً خاسراً بأكثر من هذا (لا يلمس الرابح ولا القريب من الصفر)
         "dxy_lookback": 4, "dxy_tf": "M15", "council_min_pct": 60.0}
    try:
        d.update(json.load(open(CFG_F, encoding="utf-8")))
    except Exception:
        pass
    return d


def _is_demo():
    try:
        a = mt5.account_info(); s = (a.server or "").lower() if a else ""
        return ("demo" in s) or ("trial" in s)
    except Exception:
        return False


def _killed():
    return (MT5DIR / "data" / "r_native" / "kill_switch.txt").exists() or (MT5DIR / "kill_switch.txt").exists()


def _dxy_dir(cfg):
    """اتجاه الدولار: ميل DXY على الفريم المختار (+1 قويّ، -1 ضعيف، 0 مسطّح). None إن غاب الرمز."""
    tf = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}.get(cfg.get("dxy_tf", "M15"), mt5.TIMEFRAME_M15)
    n = int(cfg.get("dxy_lookback", 4)) + 1
    mt5.symbol_select(DXY, True)
    r = mt5.copy_rates_from_pos(DXY, tf, 0, n)
    if r is None or len(r) < n:
        return None
    now, prev = float(r[-1]["close"]), float(r[0]["close"])
    band = abs(prev) * 0.0006                    # نطاق ميت صغير (تجاهل الضجيج)
    if now > prev + band:
        return 1
    if now < prev - band:
        return -1
    return 0


def _council():
    """قرارات المجلس لكل رمز: {sym: (dir, pct)}. يقرأ agent_council.json (fail-soft)."""
    out = {}
    try:
        d = json.load(open(COUNCIL_F, encoding="utf-8"))
        syms = d.get("symbols") or {}
        for s, o in syms.items():
            if not isinstance(o, dict):
                continue
            dirn = o.get("dir")
            if dirn is None:
                v = str(o.get("verdict", ""))
                dirn = 1 if ("شراء" in v or "buy" in v.lower()) else (-1 if ("بيع" in v or "sell" in v.lower()) else 0)
            pct = float(o.get("agreement_pct", o.get("pct", 0)) or 0)
            out[s] = (int(dirn or 0), pct)
    except Exception:
        pass
    return out


def _expected(sym, dxy):
    """الاتجاه المتوقّع للزوج من اتجاه الدولار (0 لغير الدولاريّة)."""
    if dxy == 0:
        return 0
    if sym in USD_BASE:
        return dxy            # دولار↑ ⇒ USDxxx↑
    if sym in USD_QUOTE:
        return -dxy           # دولار↑ ⇒ xxxUSD↓
    return 0


def _atomic(path, obj):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _log_resolution(rec):
    try:
        with open(RESOLVE_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _close(p, reason):
    """يقصّ مركزاً لمحرّكاتنا (ديمو، وقفٌ فوريّ بالسوق). يرجع True عند النجاح."""
    t = mt5.symbol_info_tick(p.symbol)
    if not t:
        return False
    price = t.bid if p.type == 0 else t.ask
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": float(p.volume),
           "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
           "position": p.ticket, "price": float(price), "deviation": 40, "magic": p.magic,
           "comment": "coherence-cut", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    ok = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
    print(f"   {'✂️ قُصّ' if ok else '⏭️ فشل قصّ'} {p.symbol} mag={p.magic} عائم={p.profit:+.2f} — {reason}", flush=True)
    return ok


def cycle(cfg):
    dxy = _dxy_dir(cfg)
    council = _council()
    pos = [p for p in (mt5.positions_get() or []) if p.magic in OUR_MAGICS]   # 🛡️ محرّكاتنا فقط
    coherence, conflicts, resolutions = {}, [], []

    # ── (أ) تعارض اقتصاديّ: إشارة مجلسٍ لزوجٍ دولاريّ ضدّ DXY ⇒ امنع ذلك الاتّجاه ──
    if dxy is not None and dxy != 0 and cfg.get("veto_enabled", True):
        minp = float(cfg.get("council_min_pct", 60.0))
        for sym, (cdir, pct) in council.items():
            exp = _expected(sym, dxy)
            if exp == 0 or cdir == 0 or pct < minp:
                continue
            if cdir == -exp:                          # المجلس يعاكس المتوقّع من الدولار
                coherence[sym] = {"veto_dir": cdir, "expected": exp, "reason": "ضدّ الدولار",
                                  "dxy": dxy, "pct": round(pct, 1)}
                conflicts.append(f"{sym} ضدّ الدولار")

    # ── (ب) تحوّط ذاتيّ: محرّكان لنا متعاكسان على نفس الرمز ──
    by_sym = {}
    for p in pos:
        by_sym.setdefault(p.symbol, []).append(p)
    for sym, ps in by_sym.items():
        dirs = {(0 if x.type == 0 else 1) for x in ps}
        if len(dirs) > 1:                             # شراء+بيع لنا على نفس الرمز
            conflicts.append(f"{sym} (تحوّط ذاتيّ)")
            # عالِج: اقصّ الساق الخاسرة (الأصغر عائماً) — يوقف غسل السبريد
            if cfg.get("close_losers", True):
                loser = min(ps, key=lambda x: x.profit)
                if loser.profit < -abs(float(cfg.get("min_loss_usd", 0.30))):
                    if _close(loser, "تحوّط ذاتيّ — قصّ الساق الخاسرة"):
                        resolutions.append({"sym": sym, "action": "close", "magic": loser.magic,
                                            "kind": "self_hedge", "floating": round(loser.profit, 2)})

    # ── علاج المراكز الخاسرة المتعارضة مع الدولار (محافظ: خاسرة فقط) ──
    if cfg.get("close_losers", True) and dxy is not None and dxy != 0:
        for p in pos:
            exp = _expected(p.symbol, dxy)
            pdir = 1 if p.type == 0 else -1
            if exp != 0 and pdir == -exp and p.profit < -abs(float(cfg.get("min_loss_usd", 0.30))):
                if _close(p, f"ضدّ الدولار وخاسر (عائم {p.profit:+.2f})"):
                    resolutions.append({"sym": p.symbol, "action": "close", "magic": p.magic,
                                        "kind": "vs_dxy", "floating": round(p.profit, 2)})

    # ── انشر التوجيه الوقائيّ + الحالة (يقرؤه المحرّكات والمخّ) ──
    if cfg.get("veto_enabled", True):
        _atomic(COH_F, coherence)
    for r in resolutions:
        r["ts"] = time.time(); r["iso"] = time.strftime("%H:%M:%S"); _log_resolution(r)
    _atomic(STATUS_F, {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "engine": "المُعالِج",
                       "dxy_dir": dxy, "n_council": len(council), "n_our_pos": len(pos),
                       "conflicts": conflicts, "vetoed": list(coherence.keys()),
                       "resolved_now": len(resolutions), "read_only": not cfg.get("close_losers", True)})
    if conflicts or resolutions:
        print(f"🧩 تعارضات={conflicts} · مُنع={list(coherence.keys())} · عولج الآن={len(resolutions)}", flush=True)


def main():
    if engine_lock:
        try:
            engine_lock.claim("conflict_resolver")
        except Exception:
            pass
    for _ in range(6):
        if mt5.initialize():
            break
        time.sleep(10)
    print(f"🧩 المُعالِج الذاتيّ لتعارض القرارات بدأ — poll={POLL_S}s (وقائيّ + قصّ الخاسر المتعارض فقط)", flush=True)
    while True:
        try:
            cfg = _cfg()
            if not cfg.get("enabled", True):
                _atomic(STATUS_F, {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "engine": "المُعالِج", "disabled": True})
                time.sleep(POLL_S); continue
            if _killed() or not _is_demo():           # الخطّ المقدّس: لا فعلَ خارج الديمو أو مع مفتاح القتل
                _atomic(STATUS_F, {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "engine": "المُعالِج", "halted": "kill/live"})
                time.sleep(POLL_S); continue
            cycle(cfg)
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
