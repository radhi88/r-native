# -*- coding: utf-8 -*-
"""manual_manager.py — حارس كتابك اليدويّ (magic 0): منهجك مُطبّقاً على صفقاتك أنت.

طلب المستخدم: «دير صفقاتي اليدوية ووريني إبداعك» — أذِن صراحةً بإدارة مراكزه اليدوية.

الفلسفة (قاعدتك حرفياً):
  • **لا نُغلق على خسارة أبداً** — الكتاب الأحمر يُمسَك (تُعدّل أنت متوسطك، نصبر).
  • **نحرس الأخضر**: حين يعود الكتاب رابحاً (متوسطك نجح) نُلاحق قمّته ونقفلها قبل أن تنقلب أحمر
    ثانيةً — هذا بالضبط ما كاد يحدث اليوم (−$401 → −$123). نلتقط التعافي قبل ضياعه.
  • عكس بربح: إن انقلب الزخم ضدّ الكتاب وهو أخضر ⇒ نقفل (نُؤمّن).
  • هدف كبير: إن بلغ الكتاب ربحاً كبيراً ⇒ نقفله (لا نطمع فيعود أحمر).

أمان صارم:
  • magic 0 فقط (يدويّك). نتجاهل خبراء خارجيّين (2447/20250418/21/22/20250618) تماماً.
  • يحترم kill_switch + علامة تعطيل فوريّة (manual_manager_enabled.txt = "0").
  • لا يفتح صفقات أبداً — يُغلق رابحاً فقط (لا يُنشئ مخاطرة، لا يكسر قاعدتك).
Read-mostly + إغلاق رابح فقط. Windowless.  Run: pythonw manual_manager.py
"""
from __future__ import annotations
import json, time
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
KILL = ROOT / "kill_switch.txt"
DISABLE = RN / "manual_manager_enabled.txt"        # اكتب "0" لتعطيل الحارس فوراً
STATUS = RN / "manual_manager_status.json"
LOG = RN / "manual_manager.log"

MAGIC = 0                                          # كتابك اليدويّ
EXTERNAL = {2447, 20250418, 20250421, 20250422, 20250618}   # خبراء خارجيّون — لا نلمسهم أبداً
POLL_S = 2.0
ARM_USD = 15.0                                     # الكتاب يجب أن يبلغ هذا الأخضر قبل تسليح القفل
GIVEBACK = 0.55                                    # نقفل إن تراجع الربح إلى 55% من قمّته (نلتقط التعافي)
BIG_LOCK_USD = 90.0                                # ربح كبير ⇒ اقفل فوراً (لا نطمع فيعود أحمر)
REV_SPEED = 0.6                                    # انعكاس الزخم (×ATR) ضدّ الكتاب الأخضر ⇒ اقفل
_peak = {}                                         # {sym: قمّة ربح الكتاب} للقفل المتحرّك


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _enabled():
    if KILL.exists():
        return False
    try:
        if DISABLE.exists() and DISABLE.read_text(encoding="utf-8").strip() in ("0", "false", "off"):
            return False
    except Exception:
        pass
    return True


def _atr(sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n + 1)
    if r is None or len(r) < n:
        return 0.0
    import numpy as np
    h, l, c = r["high"], r["low"], r["close"]
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr.mean()) if len(tr) else 0.0


def _close_cluster(sym, reason):
    """يُغلق كل مراكز magic-0 لهذا الرمز (الكتاب رابح ⇒ نُؤمّن). يتجاهل أيّ ماجيك آخر."""
    closed, freed = 0, 0.0
    for p in (mt5.positions_get(symbol=sym) or []):
        if p.magic != MAGIC or p.magic in EXTERNAL:
            continue
        tk = mt5.symbol_info_tick(sym)
        if not tk:
            continue
        px = tk.bid if p.type == 0 else tk.ask
        r = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": p.volume,
                            "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                            "position": p.ticket, "price": px, "deviation": 50, "magic": 0,
                            "comment": f"mm-{reason}"[:31], "type_filling": mt5.ORDER_FILLING_IOC})
        if getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            closed += 1; freed += p.profit
    if closed:
        _log(f"🔒 قفل {sym}: {closed} مركز يدويّ، أمّنّا ${freed:+.2f} ({reason})")
    return closed


def _manage(sym, positions):
    """يحرس كتاب الرمز اليدويّ: يُمسك الأحمر، يقفل الأخضر بقفل متحرّك/انعكاس/هدف كبير."""
    mine = [p for p in positions if p.magic == MAGIC]
    if not mine:
        _peak.pop(sym, None)
        return None
    net = sum(p.profit for p in mine)
    if net <= 0:                                   # 🚫 قاعدتك: لا نُغلق على خسارة — نُمسك (تُعدّل متوسطك)
        _peak.pop(sym, None)
        return {"n": len(mine), "net": round(net, 2), "action": "أمسك (أحمر — لا نُغلق خاسراً)"}
    pk = _peak.get(sym, 0.0)
    if net > pk:
        _peak[sym] = pk = net
    # هدف كبير ⇒ اقفل فوراً
    if net >= BIG_LOCK_USD:
        _close_cluster(sym, f"هدف-كبير ${net:.0f}"); _peak.pop(sym, None)
        return {"n": len(mine), "net": round(net, 2), "action": f"🔒 قفل (هدف كبير ${net:.0f})"}
    # قفل متحرّك: تراجَع الربح عن قمّته ⇒ التقط التعافي
    if pk >= ARM_USD and net <= pk * GIVEBACK:
        _close_cluster(sym, f"قفل-متحرّك ${net:.0f}/قمّة ${pk:.0f}"); _peak.pop(sym, None)
        return {"n": len(mine), "net": round(net, 2), "action": f"🔒 قفل (متحرّك من قمّة ${pk:.0f})"}
    # انعكاس بربح: الزخم ينقلب ضدّ الكتاب وهو أخضر ⇒ أمّن
    atr1 = _atr(sym)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 4)
    if pk >= ARM_USD and atr1 > 0 and r is not None and len(r) >= 3:
        netdir = 1 if sum((1 if p.type == 0 else -1) for p in mine) >= 0 else -1
        move = float(r["close"][-1] - r["close"][-3]); mdir = 1 if move > 0 else -1
        if abs(move) / atr1 >= REV_SPEED and mdir != netdir:
            _close_cluster(sym, f"انعكاس-بربح ${net:.0f}"); _peak.pop(sym, None)
            return {"n": len(mine), "net": round(net, 2), "action": f"🔒 قفل (انعكاس بربح ${net:.0f})"}
    return {"n": len(mine), "net": round(net, 2), "peak": round(pk, 2),
            "action": f"أحرس أخضر ${net:.0f} (قمّة ${pk:.0f}، أقفل عند ${pk*GIVEBACK:.0f})"}


def main():
    mt5.initialize()
    RN.mkdir(parents=True, exist_ok=True)
    _log("manual_manager start — حارس الكتاب اليدويّ (magic 0): يُمسك الأحمر، يحرس الأخضر")
    while True:
        try:
            st = {"ts": time.time(), "enabled": _enabled(), "symbols": {}}
            if not _enabled():
                st["state"] = "معطّل (kill_switch أو علامة التعطيل)"; _save(st); time.sleep(POLL_S); continue
            pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
            syms = sorted({p.symbol for p in pos})
            tot = sum(p.profit for p in pos)
            st["book_net"] = round(tot, 2); st["book_n"] = len(pos)
            for sym in syms:
                info = _manage(sym, [p for p in pos if p.symbol == sym])
                if info:
                    st["symbols"][sym] = info
            st["state"] = f"يحرس {len(pos)} مركز يدويّ، صافي ${tot:+.2f}"
            _save(st)
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


def _save(st):
    try:
        STATUS.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        mt5.initialize()
        pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
        syms = sorted({p.symbol for p in pos})
        print(f"كتاب يدويّ: {len(pos)} مركز، صافي ${sum(p.profit for p in pos):+.2f}، تمكين={_enabled()}")
        for s in syms:
            print(f"  {s}: {_manage(s, [p for p in pos if p.symbol==s])}")
    else:
        main()
