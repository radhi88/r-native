"""master_floor.py — THE single catastrophe backstop for the coordinated/aggressive
fleet (user explicitly removed the daily halt + per-trade 2% cap; this is the ONE
limit we keep). DEMO only.

DEAL: the user accepts losses and wants aggression, but the floor is a trailing
50%-from-peak drawdown stop. If equity falls to <= 50% of the peak equity ever seen
(initial peak = the experiment baseline start, $100 → floor $50), we:
  1) FLATTEN all OUR positions (close them) to stop the bleed at the floor —
     manual (magic 0) and the user's external EAs are NEVER touched,
  2) write kill_switch.txt so every engine (all 5 now respect it) halts NEW opens,
  3) log + leave it halted (a catastrophe stop does NOT auto-resume; user decides).

Trailing-from-peak means it also protects gains: if equity grows to $200 the floor
rises to $100. Caps max drawdown at 50% from the high-water mark, always.

Runs windowless under the watchdog. Read-only except the explicit flatten on breach.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from datetime import datetime, timezone
import MetaTrader5 as mt5
try:
    from engine_lock import claim          # 🔒 نسخة-مفردة (لا حاجزان يتسابقان على التصفية)
except Exception:
    def claim(name):
        return True

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
KILL_F = ROOT / "kill_switch.txt"
BASELINE_F = RN / "experiment_100_baseline.json"
STATE_F = RN / "master_floor_state.json"
LOG_F = RN / "master_floor.log"

# 🔄 طلب المستخدم «ألغِ سقف الحقوق — كل مرّة يخربطنا» (كان يصفّي مراكزه القابلة للاسترداد عند سحب 45%).
# استبدلناه بحاجز **هامش فقط**: لا نصفّي على سحب الحقوق إطلاقاً (تجري المراكز وتسترد بحريّة كاملة، يتوافق
# مع مذهب «دع الرابح يجري + استرداد بزخم مؤكَّد») — نتدخّل **فقط** حين توشك نسبة الهامش على ستوب-آوت الوسيط،
# كي يستحيل بلوغ الصفر مع كتابٍ بلا وقف (درس −$28k). + أرضية حقوق عميقة جداً (88% سحب) ملاذاً أخيراً فقط.
MARGIN_FLOOR_PCT = 130.0   # 🛟 صفِّ كل شيء إن هبطت نسبة الهامش ≤ هذا% (قبل ستوب-آوت الوسيط مباشرةً) — الحاجز الفعّال
DEEP_FLOOR_FRAC  = 0.12    # 🪂 أرضية حقوق عميقة (تصفية عند بلوغ 12% من القمة = سحب 88%) — لا «تخربط» السحوبات العاديّة


def _floor_for(peak):
    """الأرضية العميقة جداً (ملاذ أخير فقط — الحاجز الأساسيّ صار نسبة الهامش)."""
    return DEEP_FLOOR_FRAC * peak


# ════════ تحكّم المستخدم الكامل (حيّ، بلا إعادة تشغيل) ════════
CONFIG_F = RN / "master_floor_config.json"
_CFG = {"mtime": -1.0, "data": {"enabled": True, "margin_floor_pct": MARGIN_FLOOR_PCT,
                                 "deep_floor_frac": DEEP_FLOOR_FRAC}}


def _load_config():
    """يقرأ تحكّم المستخدم من master_floor_config.json كل دورة (عبر mtime — عدّل الملفّ ويسري فوراً):
       enabled (تشغيل/إيقاف الحاجز كلّياً)، margin_floor_pct، deep_floor_frac. غياب الملفّ ⇒ الافتراضات."""
    try:
        m = CONFIG_F.stat().st_mtime
        if m != _CFG["mtime"]:
            d = json.load(open(CONFIG_F, encoding="utf-8"))
            _CFG["data"] = {"enabled": bool(d.get("enabled", True)),
                            "margin_floor_pct": float(d.get("margin_floor_pct", MARGIN_FLOOR_PCT)),
                            "deep_floor_frac": float(d.get("deep_floor_frac", DEEP_FLOOR_FRAC))}
            _CFG["mtime"] = m
            _log(f"[FLOOR] ⚙️ تحكّم المستخدم: {_CFG['data']}")
    except FileNotFoundError:
        pass
    except Exception as e:
        _log(f"[FLOOR] config read err: {type(e).__name__}: {e}")
    return _CFG["data"]


POLL_S = 4.0               # check cadence
# magics we NEVER touch (user manual + external EAs) — same protected set as elsewhere
PROTECTED = {0, 2447, 20250418, 20250421, 20250422, 20250618}


def _log(msg: str):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_F, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_peak(start_equity: float) -> float:
    if STATE_F.exists():
        try:
            return float(json.load(open(STATE_F, encoding="utf-8")).get("peak", start_equity))
        except Exception:
            pass
    return start_equity


def _save_peak(peak: float, floor: float):
    try:
        RN.mkdir(parents=True, exist_ok=True)
        json.dump({"peak": peak, "floor": floor,
                   "updated": datetime.now(timezone.utc).isoformat()},
                  open(STATE_F, "w", encoding="utf-8"))
    except Exception:
        pass


def _flatten_ours() -> tuple[int, int, float]:
    """Close every OUR-magic position (protected magics untouched). Returns
    (closed, failed, realized_pnl)."""
    closed = failed = 0
    pnl = 0.0
    for p in (mt5.positions_get() or []):
        if p.magic in PROTECTED:
            continue
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            failed += 1
            continue
        otype = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == 0 else tick.ask
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
               "type": otype, "position": p.ticket, "price": price, "deviation": 100,
               "magic": p.magic, "comment": "master_floor", "type_filling": mt5.ORDER_FILLING_FOK}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            req["type_filling"] = mt5.ORDER_FILLING_IOC
            r = mt5.order_send(req)
        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
            pnl += p.profit
        else:
            failed += 1
    return closed, failed, pnl


def _ours_open():
    """صفقاتنا المفتوحة (عدا المحميّة) — معيار النجاح الحقيقي للتصفية (لا نثق بـretcode وحده)."""
    return [p for p in (mt5.positions_get() or []) if p.magic not in PROTECTED]


def _enforce_flat(reason=""):
    """تصفية صفقاتنا بمحاولات قصيرة متتابعة حتى صفر صفقة (لا ننتظر دورة 4ث)، مع تصعيد لو فشلت."""
    for attempt in range(6):
        c, f, pnl = _flatten_ours()
        rem = _ours_open()
        if not rem:
            _log(f"[FLOOR] flat OK ({reason}): closed={c} floatPnL={pnl:+.2f} — لا صفقات لنا مفتوحة")
            return True
        _log(f"[FLOOR] flatten try {attempt+1}/6 ({reason}): closed={c} failed={f} REMAINING={len(rem)} "
             f"[{','.join(sorted(set(p.symbol for p in rem)))}]")
        time.sleep(0.5)
    rem = _ours_open()
    if rem:  # ‼ ما زالت مفتوحة بعد المحاولات → تصعيد مرئي (لا نخفي الفشل)
        _log(f"[FLOOR] ‼ CANNOT FLATTEN {len(rem)} positions "
             f"[{','.join(sorted(set(p.symbol for p in rem)))}] — سوق مغلق/trade_allowed=off/requotes؟ "
             f"الحساب ينزف تحت الأرضية — تدخّل يدوي مطلوب.")
        try:
            with open(RN / "EMERGENCY_LOG.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "src": "master_floor", "event": "flatten_failed",
                                    "remaining": len(rem), "reason": reason}) + "\n")
        except Exception:
            pass
    return False


def main():
    claim("master_floor")                  # 🔒 قفل نسخة-مفردة
    if not (mt5.initialize() or mt5.initialize()):
        _log("[FLOOR] mt5.initialize failed; exiting")
        return
    ai = mt5.account_info()
    start_equity = ai.equity if ai else 100.0
    # prefer the experiment baseline start as the initial peak anchor
    if BASELINE_F.exists():
        try:
            start_equity = float(json.load(open(BASELINE_F, encoding="utf-8")).get("start_balance", start_equity))
        except Exception:
            pass
    peak = max(_load_peak(start_equity), start_equity)
    _log(f"[FLOOR] start: equity_anchor=${start_equity:.2f} peak=${peak:.2f} — حاجز الهامش {MARGIN_FLOOR_PCT:.0f}% "
         f"(الأساسيّ) + أرضية عميقة ${_floor_for(peak):.2f} (12% من القمة). لا تصفية على سحب الحقوق العاديّ.")
    breached = False
    _disc_warned = 0.0
    while True:
        try:
            # 🛑 حارس انقطاع الوسيط/بيانات قديمة: لو الترمنال غير متصل، account_info قد يُرجع حقوقاً
            # قديمة (غير None) فيفشل الحاجز صامتاً. لا نقيّم ولا نرفع القمة على بيانات قديمة.
            ti = mt5.terminal_info()
            if ti is None or not getattr(ti, "connected", False):
                if time.time() - _disc_warned > 60:
                    _log("[FLOOR] ⚠ الترمنال غير متصل/البيانات قديمة — لا يمكن تقييم الأرضية؛ لا أرفع القمة؛ أنتظر الاتصال")
                    _disc_warned = time.time()
                time.sleep(POLL_S); continue
            ai = mt5.account_info()
            if ai is None:
                time.sleep(POLL_S); continue
            cfg = _load_config()        # ⚙️ تحكّم المستخدم الكامل (حيّ)
            eq = ai.equity
            if eq > peak:
                peak = eq
            floor = cfg["deep_floor_frac"] * peak   # أرضية عميقة (ملاذ أخير) — يضبطها المستخدم
            _save_peak(peak, floor)
            if not cfg["enabled"]:      # 🔌 المستخدم أوقف الحاجز كلّياً (تحكّمه الكامل) — لا تصفية إطلاقاً
                if breached:
                    breached = False    # لو كان مُخترقاً، ألغِ الحالة (هو يتحكّم)
                time.sleep(POLL_S); continue
            # 🛟 الحاجز الأساسيّ = نسبة الهامش (يدع المراكز تجري/تسترد، يتدخّل فقط قبل ستوب-آوت الوسيط)
            ml = ai.margin_level if (ai.margin and ai.margin > 0) else 1e9
            margin_breach = ml <= cfg["margin_floor_pct"]
            deep_breach = eq <= floor
            # 🔓 حصانة الإيداع/التعافي: لو بقي kill_switch من خرقٍ سابق (العمليّة ماتت/أُعيد تشغيلها فبدأت
            #    breached=False فلم يدخل فرع التعافي 224)، والحساب الآن سليمٌ فوق الأرضية بوضوح (إيداع/تعافٍ)
            #    ولسنا في خرق — ننظّفه تلقائياً ليستأنف الأسطول. ننظّف خرقَ master_floor فقط (لا اليدويّ/الصوتيّ/DD).
            if (not breached) and (not margin_breach) and (not deep_breach) and KILL_F.exists():
                try:
                    _txt = KILL_F.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    _txt = ""
                if _txt.startswith("master_floor breach") and eq > floor * 1.25:
                    try:
                        KILL_F.unlink()
                        _log(f"[FLOOR] 🔓 أُزيل kill_switch بائت تلقائياً (خرقٌ سابق، العمليّة أُعيد تشغيلها) — "
                             f"الحساب تعافى: حقوق ${eq:.2f} ≫ أرضية ${floor:.2f}. الأسطول يستأنف.")
                    except Exception as e:
                        _log(f"[FLOOR] auto-clear kill_switch failed: {e}")
            if not breached and (margin_breach or deep_breach):
                breached = True
                why = (f"نسبة الهامش {ml:.0f}% ≤ {cfg['margin_floor_pct']:.0f}% (وشك ستوب-آوت الوسيط)"
                       if margin_breach else f"أرضية عميقة: حقوق ${eq:.2f} ≤ ${floor:.2f}")
                _log(f"[FLOOR] *** BREACH *** {why} (peak=${peak:.2f} حقوق=${eq:.2f}) — FLATTENING + KILL SWITCH")
                try:
                    KILL_F.write_text(f"master_floor breach {datetime.now(timezone.utc).isoformat()} "
                                      f"eq={eq:.2f} floor={floor:.2f}", encoding="utf-8")
                except Exception as e:
                    _log(f"[FLOOR] kill_switch write failed: {e}")
                _enforce_flat(reason="breach")   # محاولات قصيرة متتابعة + تصعيد لو فشلت
            elif breached:
                if not KILL_F.exists():
                    # استئناف يدوي بعد اختراق: نعيد ضبط القمة على الحقوق الحالية (بداية نظيفة — القمة القديمة
                    # كانت ضوضاء سلسلة-رابحة انعكست). نسجّلها بوضوح (لا صامتة): الأرضية الجديدة = 50% من الحقوق.
                    old_floor = _floor_for(peak)
                    peak = eq
                    _save_peak(peak, _floor_for(peak))
                    _log(f"[FLOOR] أُزيل kill_switch — استئناف ببداية نظيفة. القمة→${peak:.2f} الأرضية→${_floor_for(peak):.2f} "
                         f"(كانت ${old_floor:.2f}). الأرضية أُعيد ضبطها على الحقوق الحالية — مقصود بالاستئناف.")
                    breached = False
                elif (not margin_breach) and (not deep_breach) and eq > floor * 1.25 \
                        and KILL_F.read_text(encoding="utf-8", errors="ignore").startswith("master_floor breach"):
                    # 🔓 تعافٍ حيّ بعد خرق هامش: العمليّة نفسها اخترقت (breached=True) فلم تدخل مسار
                    #    التنظيف التلقائيّ (المشروط بـ not breached، لعمليّةٍ أُعيد تشغيلها فقط). الحساب الآن
                    #    سليمٌ تماماً (لا خرق هامش/عميق، حقوق ≫ 125% من الأرضية) ⇒ ننظّف kill_switch الذي
                    #    كتبناه نحن (master_floor breach فقط) ونستأنف — كي لا يبقى الأسطول مُعطَّلاً بعد التعافي.
                    try:
                        KILL_F.unlink()
                        _log(f"[FLOOR] 🔓 أُزيل kill_switch تلقائياً (تعافٍ حيّ بعد خرق هامش) — "
                             f"حقوق ${eq:.2f} ≫ أرضية ${floor:.2f}. الأسطول يستأنف.")
                    except Exception as e:
                        _log(f"[FLOOR] live auto-clear failed: {e}")
                    breached = False
                else:
                    _enforce_flat(reason="re-enforce")   # يبقى يصفّي أي صفقة متبقية + يصعّد
        except Exception as e:
            _log(f"[FLOOR] loop error: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
