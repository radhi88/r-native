# -*- coding: utf-8 -*-
"""self_tuner.py — الحلقة المغلقة: يتعلّم من الندم المقاس ⇒ **يُشدّد** معاملات السكالب ⇒ يتحقّق من نفسه.

صُمِّم بعد تدقيق عدائيّ (3 مهاجمين) أثبت أنّ ضابطاً ساذجاً = **حلقة خراب**: على دفتر بلا وقف،
«أمسك أطول لتلتقط MFE» = «اترك MAE يركض للأرضية». الحلّ المُثبَت رياضياً: **تشديد-فقط**.

ما يفعله (ولا يفعله):
  • يكتب 5 مفاتيح فقط في scalper_params.json (giveback/arm/rev/spread/cooldown) — لا يلمس
    master_floor ولا kill_switch ولا AGGR_RISK/MAX_LOT/PAUSE_DD/PYRAMID/«لا وقف» (off-limits).
  • **تشديد-فقط**: giveback↑ (اقفل أبكر)، arm↓ (سلِّح أبكر)، rev↓ (اخرج أسرع من الانعكاس)،
    spread↓ (تكلفة أصرم)، cooldown↑ (تردّد أقلّ). الإرخاء **ممنوع كوداً** (يتطلّب يد إنسان).
  • بوّابة عيّنة صلبة n≥200 (و≥60 ربح و≥60 خسارة) — عند n الحاليّ (64) يُصدر «عيّنة غير كافية» ولا يغيّر.
  • خطوة واحدة كلّ 24س + تهيستيريسيس (إشارة تصمد دورتين) + حسّ-نسبة-الربح (عند تعادل 45-55٪
    تُسمح حركات التكلفة/التردّد فقط) + تجميد عند ضغط التراجع.
  • **تحقّق ذاتيّ (meta)**: قبل أيّ اقتراح جديد يُدقّق تغييره السابق — إن لم يُحسّن الصافي (أو ارتفع MAE)
    **يتراجع تلقائياً**. وبما أنّ كلّ حركة تشديد، أسوأ خطأ = تحفّظ زائد، لا تعميق خسارة.
Read-mostly (يكتب فقط scalper_params.json ذرّياً + سجلّ). Windowless.  Run: pythonw self_tuner.py
"""
from __future__ import annotations
import json, math, os, time
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
KILL = ROOT / "kill_switch.txt"
PARAMS = RN / "scalper_params.json"
REPORT = RN / "regret_report.json"
STATE = RN / "self_tuner_state.json"
CHANGELOG = RN / "self_tuner_changelog.jsonl"
ENABLED = RN / "self_tuner_enabled.txt"        # احذف الملفّ أو اكتب "0" لتجميد الضابط فوراً
LOG = RN / "self_tuner.log"
MAGIC = 20260628
POLL_S = 3600.0                                # دورة كلّ ساعة (التغيير الفعليّ محدود بـ24س)

DEFAULTS = {"lock_giveback": 0.45, "lock_arm_usd": 4.0, "rev_speed": 0.55, "spread_max_atr": 0.40, "cooldown_s": 6.0}
BANDS = {"lock_giveback": (0.45, 0.80), "lock_arm_usd": (2.0, 4.0), "rev_speed": (0.30, 0.55),
         "spread_max_atr": (0.20, 0.40), "cooldown_s": (6.0, 30.0)}
STEP = {"lock_giveback": 0.05, "lock_arm_usd": 0.5, "rev_speed": 0.05, "spread_max_atr": 0.05, "cooldown_s": 4.0}
TIGHTEN = {"lock_giveback": +1, "lock_arm_usd": -1, "rev_speed": -1, "spread_max_atr": -1, "cooldown_s": +1}  # اتجاه التشديد
COST_FREQ = ("cooldown_s", "spread_max_atr")   # حركات التكلفة/التردّد (مسموحة حتى عند التعادل)

MIN_N, MIN_W, MIN_L = 200, 60, 60              # بوّابة العيّنة الصلبة
CYCLE_S = 24 * 3600                            # تغيير واحد كحدّ أقصى كلّ 24س
DEADBAND = -5.0                                # capture يجب أن يكون < −5٪ (لا مجرّد سالب)
DD_FREEZE_PCT = 4.0                            # تجميد إن تجاوز التراجع العائم نصف PAUSE_DD (8%)


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _rj(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _clamp(k, v):
    lo, hi = BANDS[k]
    return max(lo, min(hi, v))


def _is_tighter(k, new, cur):
    """هل new أكثر تشديداً من cur في اتجاه k؟"""
    return (new > cur) if TIGHTEN[k] > 0 else (new < cur)


def _current():
    p = _rj(PARAMS, {})
    return {k: (p.get(k) if isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool)
                and math.isfinite(p.get(k)) and BANDS[k][0] <= p.get(k) <= BANDS[k][1] else DEFAULTS[k])
            for k in DEFAULTS}


def _write(params, why, before, metrics):
    """كتابة ذرّية (tmp+replace) + سجلّ. يكتب 5 مفاتيح فقط — لا مسار آخر."""
    assert set(params) == set(DEFAULTS), "whitelist breach"      # حارس: 5 مفاتيح فقط حصراً
    out = {"version": int(time.time()), "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           **{k: round(float(v), 4) for k, v in params.items()}}
    tmp = PARAMS.with_suffix(".json.tmp")
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, PARAMS)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why, "before": before,
           "after": {k: round(float(v), 4) for k, v in params.items()}, "metrics": metrics}
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _log(f"CHANGE {why}: {before} -> {params}")


def _drawdown_pct():
    """تراجع عائم حاليّ لمراكز السكالب (٪ من الحقوق)."""
    try:
        a = mt5.account_info()
        pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
        fl = sum(p.profit for p in pos)
        return (-fl / a.equity * 100.0) if (a and a.equity and fl < 0) else 0.0
    except Exception:
        return 0.0


def _frozen_reason(rep):
    """أسباب التجميد الصلبة (الأمان يسبق أيّ إشارة ندم)."""
    if ENABLED.exists() and (ENABLED.read_text(encoding="utf-8").strip() in ("0", "false", "off")):
        return "freeze flag"
    if KILL.exists():
        return "kill_switch/floor active"          # الأرضية تكتب kill_switch عند الكسر ⇒ سبق مطلق
    if _drawdown_pct() >= DD_FREEZE_PCT:
        return f"drawdown stress {_drawdown_pct():.1f}%>= {DD_FREEZE_PCT}%"
    return None


def _propose(rep, cur):
    """خريطة الاتجاه: كلّ فرع يُفضي إلى **تشديد**. يرجع (param, target) أو (None, سبب)."""
    cap = rep.get("capture_pct", 0.0); mfe = rep.get("avg_mfe", 0.0) or 0.0
    mae = abs(rep.get("avg_mae", 0.0) or 0.0); net = rep.get("net_total", 0.0); wr = rep.get("win_rate", 50)
    coin = 45 <= wr <= 55                          # تعادل ⇒ لا معلومة اتجاهية ⇒ تكلفة/تردّد فقط
    # أولوية الأمان: ذيل مرتفع أو صافي سالب ⇒ تشديد المخاطرة/التكلفة قبل أيّ «التقاط»
    if net < 0:
        for k in ("cooldown_s", "spread_max_atr"):        # قُصّ التكلفة/التردّد (الرافعة المُثبتة)
            tgt = _clamp(k, cur[k] + TIGHTEN[k] * STEP[k])
            if _is_tighter(k, tgt, cur[k]):
                return k, tgt
        return None, "net<0 لكن التكلفة/التردّد عند أصرم حدّ"
    if mae > 2.0 * mfe and mfe > 0:                       # ذيل خسارة مرتفع ⇒ اخرج أسرع/سلِّح أبكر/تردّد أقلّ
        for k in ("rev_speed", "lock_arm_usd", "cooldown_s"):
            tgt = _clamp(k, cur[k] + TIGHTEN[k] * STEP[k])
            if _is_tighter(k, tgt, cur[k]):
                return k, tgt
        return None, "ذيل مرتفع لكن مخارجه عند أصرم حدّ"
    if cap < DEADBAND:                                    # نُدوّر الأخضر أحمر، والذيل ليس مرتفعاً
        if coin:                                          # تعادل ⇒ لا نُحرّك giveback/speed على ضوضاء
            for k in COST_FREQ:
                tgt = _clamp(k, cur[k] + TIGHTEN[k] * STEP[k])
                if _is_tighter(k, tgt, cur[k]):
                    return k, tgt
            return None, "تعادل + التكلفة/التردّد عند الحدّ"
        tgt = _clamp("lock_giveback", cur["lock_giveback"] + STEP["lock_giveback"])   # اقفل أبكر
        if _is_tighter("lock_giveback", tgt, cur["lock_giveback"]):
            return "lock_giveback", tgt
        return None, "giveback عند أقصى تشديد"
    return None, "لا إشارة تستحقّ التشديد"


def _meta_check(state, rep, cur):
    """يُدقّق التغيير السابق: إن لم يُحسّن الصافي (أو ارتفع MAE) ⇒ تراجُع تلقائيّ. يرجع True إن تراجَع."""
    lc = state.get("last_change")
    if not lc:
        return False
    base = lc.get("metrics", {})
    net_now, net_was = rep.get("net_total", 0.0), base.get("net_total", 0.0)
    mae_now, mae_was = abs(rep.get("avg_mae", 0.0) or 0.0), abs(base.get("avg_mae", 0.0) or 0.0)
    cap_now, cap_was = rep.get("capture_pct", 0.0), base.get("capture_pct", 0.0)
    improved = (net_now >= net_was) and (mae_now <= mae_was * 1.05) and (cap_now >= cap_was - 1.0)
    if improved:
        return False
    # لم يُحسّن ⇒ تراجَع عن المفتاح الواحد لقيمته السابقة (إرخاء مسموح فقط ضمن التراجع الذاتيّ نحو الأصرم-سابقاً)
    k = lc["param"]; before_val = lc["before"][k]
    newp = dict(cur); newp[k] = before_val
    _write(newp, f"meta-revert {k} (لم يُحسّن: net {net_was}->{net_now}, mae {mae_was}->{mae_now})",
           cur, rep)
    return True


def cycle():
    rep = _rj(REPORT, {})
    cur = _current()
    state = _rj(STATE, {})
    fr = _frozen_reason(rep)
    if fr:
        _log(f"frozen: {fr}"); state["last_decision"] = f"frozen: {fr}"; _save_state(state); return
    n = rep.get("n", 0); wr = rep.get("win_rate", 50)
    wins = round(n * wr / 100.0); losses = n - wins
    # بوّابة العيّنة الصلبة
    if n < MIN_N or wins < MIN_W or losses < MIN_L:
        msg = f"insufficient_sample n={n} (≥{MIN_N}, ≥{MIN_W}W/{MIN_L}L مطلوب)"
        _log(msg); state["last_decision"] = msg; _save_state(state); return
    # تحقّق ذاتيّ من التغيير السابق (قد يتراجع)
    if time.time() - state.get("last_change", {}).get("ts_epoch", 0) >= CYCLE_S:
        if _meta_check(state, rep, cur):
            state["last_change"] = None; state["pending"] = None
            state["last_decision"] = "meta-revert"; _save_state(state); return
    # حدّ المعدّل: تغيير واحد كلّ 24س
    if time.time() - state.get("last_change", {}).get("ts_epoch", 0) < CYCLE_S:
        state["last_decision"] = "rate_limited (<24h)"; _save_state(state); return
    param, tgt = _propose(rep, cur)
    if not param:
        state["pending"] = None; state["last_decision"] = f"no_change: {tgt}"; _save_state(state); return
    # تهيستيريسيس: الإشارة نفسها يجب أن تصمد دورتين متتاليتين
    pend = state.get("pending")
    sig = f"{param}->{round(tgt,4)}"
    if not pend or pend.get("sig") != sig:
        state["pending"] = {"sig": sig}; state["last_decision"] = f"pending(1/2): {sig}"; _save_state(state); return
    # مؤكّدة ⇒ طبّق (تشديد-فقط، مقصوص، ذرّيّ)
    assert _is_tighter(param, tgt, cur[param]), "forbidden loosening blocked"   # حارس اتجاه نهائيّ
    newp = dict(cur); newp[param] = tgt
    _write(newp, f"tighten {param} {cur[param]}->{tgt} (cap={rep.get('capture_pct')} mae={rep.get('avg_mae')} n={n})", cur, rep)
    state["last_change"] = {"param": param, "before": cur, "ts_epoch": time.time(), "metrics": rep}
    state["pending"] = None; state["last_decision"] = f"applied {sig}"
    _save_state(state)


def _save_state(state):
    state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        tmp = STATE.with_suffix(".json.tmp")
        json.dump(state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)
    except Exception:
        pass


def main():
    mt5.initialize()
    RN.mkdir(parents=True, exist_ok=True)
    _log("self_tuner start (تشديد-فقط، بوّابة n≥200، تحقّق-ذاتيّ)")
    while True:
        try:
            cycle()
        except Exception as e:
            _log(f"err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        mt5.initialize()
        cycle()
        print(json.dumps(_rj(STATE, {}), ensure_ascii=False, indent=1))
    else:
        main()
