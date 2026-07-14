"""
stage_promoter.py — المُرقّي الآليّ: يقيس عتبات رودماب النضج وينفّذ الانتقالات.

المرجع: r_desktop/MATURITY_ROADMAP.md. يُستدعى من learning_pulse كل ساعة.

⚕️ عقيدة المستشفى (أمر المستخدم 2026-07-14): لا إعدام ولا توقّف أبديّ —
   الفاشل يدخل وحدة العناية 🏥 (أدنى تعرّض، يواصل القياس) وله بوّابة شفاء 💚
   رقمية للعودة. الدفن ⚰️ فقط بعد علاجين متتاليين فاشلين، ويُستبدل لا يُوقَف.
👹 مرحلة الوحوش: لوت عالٍ + سرعة قصوى — للرابحين المُثبتين فقط، والسقوط فوريّ.

قواعد صلبة: ديمو فقط · الترقية بالبوّابة الكاملة والخفض فوريّ ·
كل انتقال يُعاد معه تصفير عيّنة القياس (تحديث علامة التجميد) ويُدوَّن في السجلّ.
"""
from __future__ import annotations
import json
import hashlib
import math
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RN = ROOT / "data" / "r_native"
STATUS_F = RN / "maturity_status.json"      # لوحة الحالة (تُكتب كل دورة)
STATE_F = RN / "maturity_state.json"        # ذاكرة المراحل الدائمة (rehab counts...)
JOURNAL = RN / "r_trade_journal.jsonl"
FREEZE_F = RN / "newground_freeze.json"
SENT_CFG = RN / "gold_sentinel_config.json"
PILOT_CFG = RN / "r_hybrid_pilot_config.json"
ENTRIES_F = RN / "gold_sentinel_entries.jsonl"
KNOWLEDGE = RN / "market_knowledge.json"
EVOLOG = ROOT / "data" / "r_evolution_log.jsonl"

SENT_MAGIC, PILOT_MAGIC = 20260701, 20260713
ACCOUNT_ALARM = 425.0

# سلّم الحارس: عناية → أرضية → قياس → مُثبَت → توسيع → وحش
REHAB_RISK, FLOOR_RISK = 0.02, 0.03
LADDER = [0.05, 0.075, 0.10]
MONSTER_RISK = 0.20
MONSTER_COOLDOWN_MIN, REHAB_COOLDOWN_MIN, NORMAL_COOLDOWN_MIN = 1, 60, 5


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load(f, default):
    try:
        return json.loads(Path(f).read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(f, obj):
    Path(f).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _log_transition(track, to, why, action):
    rec = {"ts": _now_iso(), "iteration": "stage-transition",
           "item": f"{track} -> {to}", "status": "DONE",
           "notes": f"{why} | action: {action}", "files_changed": []}
    try:
        with open(EVOLOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _tstat(nets):
    n = len(nets)
    if n < 2:
        return 0.0
    mean = sum(nets) / n
    var = sum((x - mean) ** 2 for x in nets) / (n - 1)
    return mean / math.sqrt(var / n) if var > 0 else 0.0


def _stats(nets):
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_w = sum(wins); gross_l = abs(sum(losses))
    return {
        "n": n, "net": round(sum(nets), 2),
        "wr": round(100 * len(wins) / n, 1) if n else None,
        "pf": round(gross_w / gross_l, 2) if gross_l else (None if not wins else 99.0),
        "t": round(_tstat(nets), 2),
        "rr": round(abs((gross_w / max(1, len(wins))) / (gross_l / max(1, len(losses)))), 2)
              if losses and wins else None,
    }


def _journal_recs(magic, since_ts=0.0):
    out = []
    try:
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("magic") == magic and r.get("entry_ts", 0) >= since_ts:
                out.append(r)
    except Exception:
        pass
    return out


def _is_demo():
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        a = mt5.account_info()
        return bool(a and ("Trial" in a.server or "Demo" in a.server)), a
    except Exception:
        return False, None


def _state():
    d = _load(STATE_F, {})
    d.setdefault("sentinel", {"stage": "S0", "since_ts": _load(FREEZE_F, {}).get("ts_epoch", time.time()),
                              "rehab_count": 0, "rehab_streak": 0})
    d.setdefault("pilot", {})
    for m in ("B", "E"):
        d["pilot"].setdefault(m, {"stage": "S0", "since_ts": 0.0,
                                  "rehab_count": 0, "rehab_streak": 0})
    return d


def _reset_freeze(note):
    """كل انتقال = عيّنة جديدة: تحديث علامة التجميد (ts + hash)."""
    m = _load(FREEZE_F, {})
    c = _load(SENT_CFG, {})
    keys = list((m.get("frozen_config") or {}).keys()) or ["risk_cap"]
    frozen = {k: c.get(k) for k in keys}
    m.update({"ts_epoch": time.time(), "ts_utc": _now_iso(), "frozen_config": frozen,
              "config_hash": hashlib.sha1(json.dumps(frozen, sort_keys=True).encode()).hexdigest()[:12],
              "v": f"auto-{note}"})
    _save(FREEZE_F, m)
    return m["ts_epoch"]


# ── المسار 1: الحارس (مستشفى + وحوش) ────────────────────────────
def track_sentinel(apply, st):
    s = st["sentinel"]
    since = float(s.get("since_ts", 0))
    x = _stats([r["net_usd"] for r in _journal_recs(SENT_MAGIC, since)])
    cfg = _load(SENT_CFG, {})
    stage = s.get("stage", "S0")
    action = None   # (وصف، دالة تطبيق على cfg، المرحلة الجديدة)

    def _set(risk, cd):
        def f(c):
            c["risk_cap"] = risk
            c["exec_cooldown_min"] = cd
            c["execute"] = True
        return f

    if stage == "REHAB":
        # 💚 شفاء؟ | ⚰️ دفن بعد علاجين؟ | استمرار العلاج
        if x["n"] >= 20 and x["net"] > 0 and (x["pf"] or 0) >= 1.2:
            action = (f"شفاء 💚: n={x['n']} net=+{x['net']} PF={x['pf']}",
                      _set(LADDER[0], NORMAL_COOLDOWN_MIN), "S0")
            s["rehab_streak"] = 0
        elif x["n"] >= 30 and x["net"] <= 0:
            s["rehab_streak"] = s.get("rehab_streak", 0) + 1
            if s["rehab_streak"] >= 2:
                stage = "BURIED_HYPOTHESIS"   # ⚰️ الفرضية تُدفن — يبقى المحرّك تنبيهات + أدنى قياس
                action = (f"⚰️ علاجان فاشلان (الأخير n={x['n']} net={x['net']}) — الفرضية تُدفن، "
                          "تبقى وحدة قياس دنيا حتى تُستبدل الفرضية",
                          _set(REHAB_RISK, 240), "BURIED_HYPOTHESIS")
            else:
                action = (f"علاج ثانٍ 🏥: العلاج الأول فشل (n={x['n']} net={x['net']})",
                          _set(REHAB_RISK, REHAB_COOLDOWN_MIN), "REHAB")
    elif stage == "MONSTER":
        # 🔻 سقوط الوحش: فوريّ وبلا نقاش
        eq = 500.0
        if (x["rr"] is not None and x["rr"] < 0.8 and x["n"] >= 10) or x["net"] < -0.05 * eq:
            action = (f"سقوط الوحش 🔻: RR={x['rr']} net={x['net']}",
                      _set(LADDER[0], NORMAL_COOLDOWN_MIN), "S0")
    else:
        # خفض فوريّ (RR منهار) → أرضية
        if x["n"] >= 15 and x["rr"] is not None and x["rr"] < 0.5 \
                and float(cfg.get("risk_cap", 0.05)) > FLOOR_RISK:
            action = (f"خفض ⚠️: RR={x['rr']} < 0.5 بعد n={x['n']}",
                      _set(FLOOR_RISK, NORMAL_COOLDOWN_MIN), stage)
        elif x["n"] >= 30:
            if x["net"] <= 0:
                action = (f"وحدة العناية 🏥: n={x['n']} net={x['net']} ≤ 0 — لا إيقاف، أدنى تعرّض",
                          _set(REHAB_RISK, REHAB_COOLDOWN_MIN), "REHAB")
                s["rehab_count"] = s.get("rehab_count", 0) + 1
            elif x["t"] >= 2.0:
                risk = float(cfg.get("risk_cap", 0.05))
                if stage in ("S0", "S1") and risk < LADDER[1]:
                    action = (f"ترقية ✅: net=+{x['net']} t={x['t']}", _set(LADDER[1], NORMAL_COOLDOWN_MIN), "S2")
                elif stage == "S2":
                    action = (f"توسيع ✅: net=+{x['net']} t={x['t']}", _set(LADDER[2], NORMAL_COOLDOWN_MIN), "S3")
                elif stage == "S3" and x["t"] >= 2.5 and (x["pf"] or 0) >= 1.4:
                    action = (f"👹 دخول الوحوش: n={x['n']} t={x['t']} PF={x['pf']}",
                              _set(MONSTER_RISK, MONSTER_COOLDOWN_MIN), "MONSTER")

    applied = None
    if apply and action:
        why, fn, new_stage = action
        cfg2 = _load(SENT_CFG, {})
        try:
            fn(cfg2)
            _save(SENT_CFG, cfg2)
            s["stage"] = new_stage
            s["since_ts"] = _reset_freeze(new_stage)
            applied = why
            _log_transition("sentinel-20260701", new_stage, why,
                            f"risk={cfg2.get('risk_cap')} cd={cfg2.get('exec_cooldown_min')}")
        except Exception as e:
            applied = f"فشل: {e}"
    nxt = {"S0": "n≥30 ثم net>0 وt≥2", "S1": "net>0 وt≥2", "S2": "30 أخرى بt≥2",
           "S3": "30 أخرى بt≥2.5 وPF≥1.4 → 👹", "MONSTER": "حافظ على RR≥0.8",
           "REHAB": "n≥20 وnet>0 وPF≥1.2 → 💚", "BURIED_HYPOTHESIS": "فرضية جديدة تُستبدل"}
    return {"stage": s.get("stage", stage), **x,
            "progress_to_next": f"{min(100, round(100 * x['n'] / 30))}% (n={x['n']}/30)",
            "next_gate": nxt.get(s.get("stage", stage), "?"),
            "rehab_count": s.get("rehab_count", 0), "applied": applied}


# ── المسار 2: الهجين B/E (مستشفى لكل نموذج) ─────────────────────
def track_pilot(apply, st):
    model_by_ticket = {}
    try:
        for line in ENTRIES_F.read_text(encoding="utf-8").splitlines():
            try:
                c = json.loads(line)
            except Exception:
                continue
            if c.get("engine") == "r_hybrid_pilot" and c.get("ticket"):
                model_by_ticket[int(c["ticket"])] = c.get("model", "?")
    except Exception:
        pass
    cfg = _load(PILOT_CFG, {})
    cfg.setdefault("models", ["B", "E"])
    cfg.setdefault("models_rehab", [])
    out = {}
    changed = False
    for m in ("B", "E"):
        ms = st["pilot"][m]
        recs = [r["net_usd"] for r in _journal_recs(PILOT_MAGIC, ms.get("since_ts", 0))
                if model_by_ticket.get(int(r if isinstance(r, int) else 0), None) == m] \
            if False else \
            [r["net_usd"] for r in _journal_recs(PILOT_MAGIC, ms.get("since_ts", 0))
             if model_by_ticket.get(int(r.get("position_id", 0))) == m]
        x = _stats(recs)
        stage = ms.get("stage", "S0")
        if stage == "REHAB":
            if x["n"] >= 20 and x["net"] > 0 and (x["pf"] or 0) >= 1.2:
                if m in cfg["models_rehab"]:
                    cfg["models_rehab"].remove(m)
                if m not in cfg["models"]:
                    cfg["models"].append(m)
                ms.update({"stage": "S0", "since_ts": time.time(), "rehab_streak": 0})
                changed = True
                _log_transition(f"pilot-{m}", "S0", f"شفاء 💚 n={x['n']} PF={x['pf']}", "restored")
            elif x["n"] >= 30 and x["net"] <= 0:
                ms["rehab_streak"] = ms.get("rehab_streak", 0) + 1
                ms["since_ts"] = time.time()
                changed = True
                if ms["rehab_streak"] >= 2:
                    ms["stage"] = "BURIED"
                    _log_transition(f"pilot-{m}", "BURIED",
                                    "⚰️ علاجان فاشلان — يُستبدل بنموذج جديد من المختبر", "buried")
        elif stage != "BURIED" and x["n"] >= 30:
            if (x["pf"] or 0) < 1.0 or x["net"] <= 0:
                if m in cfg["models"]:
                    cfg["models"].remove(m)
                if m not in cfg["models_rehab"]:
                    cfg["models_rehab"].append(m)
                ms.update({"stage": "REHAB", "since_ts": time.time(),
                           "rehab_count": ms.get("rehab_count", 0) + 1})
                changed = True
                _log_transition(f"pilot-{m}", "REHAB",
                                f"🏥 n={x['n']} PF={x['pf']} net={x['net']} — تبريد 4س، لا حذف", "rehab")
            elif (x["pf"] or 0) >= 1.5 and x["t"] >= 2.5 and x["n"] >= 60:
                ms["stage"] = "MONSTER"
                cfg["monster_models"] = sorted(set(cfg.get("monster_models", []) + [m]))
                changed = True
                _log_transition(f"pilot-{m}", "MONSTER", f"👹 PF={x['pf']} t={x['t']} n={x['n']}", "lot 0.02 + نافذة أوسع")
            elif (x["pf"] or 0) >= 1.3 and x["t"] >= 2:
                ms["stage"] = "S2"
        out[m] = {"stage": ms.get("stage"), **x,
                  "progress_to_next": f"{min(100, round(100 * x['n'] / 30))}% (n={x['n']}/30)"}
    if apply and changed:
        _save(PILOT_CFG, cfg)
    return {"models": out, "active": cfg.get("models"), "rehab": cfg.get("models_rehab"),
            "monster": cfg.get("monster_models", [])}


# ── المسار 3: أنماط الماسح ───────────────────────────────────────
def track_sweeper():
    k = _load(KNOWLEDGE, {})
    rows = [(x, v) for x, v in k.items() if isinstance(v, dict) and not x.startswith("_")]
    sig = [{"key": x, "n": v.get("n"), "t": round(v.get("t_stat", 0), 2),
            "fwd_r": round(v.get("mean_fwd_r", 0), 2)}
           for x, v in rows if v.get("trust") == "SIGNIFICANT"]
    near = sorted([(x, v.get("n", 0)) for x, v in rows if 20 <= v.get("n", 0) < 30],
                  key=lambda kv: -kv[1])[:5]
    # 🗡️ معرفة صيّاد اللحظات (الافتتاحات + قبيل الأخبار) — نفس بوّابة الأمانة
    bk = _load(RN / "boundary_knowledge.json", {})
    brows = [(x, v) for x, v in bk.items() if isinstance(v, dict) and not x.startswith("_")]
    bsig = [{"key": x, "n": v.get("n"), "t": v.get("t_stat"),
             "with_mom": v.get("mean_with_mom_atr")}
            for x, v in brows if v.get("trust") == "SIGNIFICANT"]
    return {"stage": "S1_معنويّ" if (sig or bsig) else "S0_تجميع",
            "patterns": len(rows), "samples": sum(v.get("n", 0) for _, v in rows),
            "significant": sig[:10], "build_candidates": [s["key"] for s in sig[:5]],
            "nearest_to_threshold": [{"key": x, "n": n} for x, n in near],
            "boundary_hunter": {"patterns": len(brows),
                                "significant": bsig[:10],
                                "build_candidates": [s["key"] for s in bsig[:5]]},
            "progress_to_next": f"أقرب نمط: n={near[0][1]}/30" if near else "0%"}


# ── المسار 5: الحساب ─────────────────────────────────────────────
def track_account(acct):
    if not acct:
        return {"stage": "؟", "note": "MT5 غير متاح"}
    eq = float(acct.equity)
    stage = ("⛔_إنذار(−15%)" if eq < ACCOUNT_ALARM else
             "M3_البرهان" if eq >= 1000 else "M2_الجدّية" if eq >= 650 else
             "M1_أول-دليل" if eq >= 550 else "M0_البداية")
    nxt = 550 if eq < 550 else (650 if eq < 650 else 1000)
    return {"stage": stage, "equity": round(eq, 2),
            "progress_to_next": f"{round(100 * eq / nxt)}% نحو ${nxt}"}


def run(apply: bool = True) -> dict:
    demo, acct = _is_demo()
    if not demo:
        apply = False
    st = _state()
    status = {
        "ts": time.time(), "iso": _now_iso(), "demo": demo, "auto_apply": apply,
        "doctrine": "⚕️ مستشفى لا مقبرة: لا يتوقّف شيء — عناية وشفاء ودفن-بالاستبدال فقط. 👹 الوحوش للرابحين.",
        "roadmap": "r_desktop/MATURITY_ROADMAP.md",
        "track1_sentinel": track_sentinel(apply, st),
        "track2_pilot": track_pilot(apply, st),
        "track3_sweeper": track_sweeper(),
        "track5_account": track_account(acct),
    }
    if apply:
        _save(STATE_F, st)
    try:
        _save(STATUS_F, status)
    except Exception:
        pass
    return status


if __name__ == "__main__":
    print(json.dumps(run(apply=True), ensure_ascii=False, indent=1))
