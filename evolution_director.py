"""evolution_director.py — مدير التطوّر: dynamic, hands-off evolution of strategies, genomes,
session-specialists, and the agents' tactics. The user's order: "تطوير كل شيء ديناميكياً دون تدخلي".

What it evolves, continuously, with NO human input:
  1. STRATEGY-MODE EVOLUTION (every 30min): attributes the trader's LIVE P&L to each entry MODE
     via deal comments (macro / xasset / wick-rev / dive / gap-pendings / S&R-limits). A mode that
     keeps losing live is DISABLED for 24h (written to mode_weights.json, multi_trader obeys);
     a mode that earns gets a lot boost. Strategies now compete on REAL results and the losers
     bench themselves — true survival of the fittest at the strategy level.
  2. SESSION-STABLE REFRESH (daily): re-validates every symbol's session specialists on fresh
     50k-bar real-spread data — decayed sessions drop out, improved ones update.
  3. DISCOVERY PROBE (daily): deep-tests a few liquid gate-eligible symbols that are NOT deployed;
     if a new real edge appears, it joins the roster automatically (keep-best guard applies).
  4. STRADDLE AUTO-ADVISOR: if straddle_hunter files a help request and no human answers, applies
     rule-based advice (widen/narrow distance, gold-only, cool-off) so its loop never starves.
Everything logged to evolution_log.jsonl. Windowless.  Run:  pythonw evolution_director.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
V2DIR = MT5DIR / "r_native_v2"
RN = MT5DIR / "data" / "r_native"
MODE_OUT = RN / "mode_weights.json"
STATE = RN / "evolution_state.json"
LOG = RN / "evolution_log.jsonl"
HELP_REQ = RN / "straddle_help_request.json"
ADVICE = RN / "agents" / "straddle_advice.json"

MAGIC = 20260608
CYCLE_S = 1800                  # mode evolution every 30 min
MODE_MIN_N = 8                  # judge a mode only after this many live trades
MODE_KILL_NET = -10.0           # mode net worse than this (48h) → disable 24h
MODE_BOOST_NET = 5.0            # mode net better than this → lot ×1.2
# 🩸 نافذة طويلة: الـ48h تفوت الخاسر البطيء (وضع يخسر ~صفقة/يوم لا يجمع ما يكفي أبداً).
# wick-rev (وضع ارتدادي/fade) خسر −$232 في 21 يوم بينما 48h يراه −$4 = حميد. هذا يسدّ الثغرة
# (نفس درس حارس الـ12h مع النفط). والدليل العلمي: كل اختبارات الـfade هذا الأسبوع خسرت OOS.
MODE_LONG_HOURS = 21 * 24       # نافذة بنيوية طويلة
MODE_LONG_MIN_N = 15            # عيّنة كافية للحكم البنيوي
MODE_LONG_KILL_NET = -40.0      # خسارة بنيوية على المدى الطويل → تعطيل أطول
MODE_LONG_DISABLE_H = 7 * 24    # تعطيل 7 أيام (خاسر بنيوي لا عابر)
for p in (str(MT5DIR), str(V2DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _log(kind, msg, data=None):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
                                "kind": kind, "msg": msg, "data": data or {}}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(f"[EVOLVE] {kind}: {msg}", flush=True)


def _mode_of(comment: str) -> str | None:
    """Map an ENTRY deal comment to its strategy mode."""
    c = (comment or "")
    if c.startswith("F2B-SRLIM"):
        return "srlim"
    if c.startswith("F2B-PEND"):
        return "gap_pend"
    if c.startswith("HYB-"):
        base = c[4:].split("+")[0].strip().lower()
        return base if base in ("macro", "xasset", "dive") else ("wick_rev" if base.startswith("wick") else None)
    if c.startswith("F2B-"):
        base = c[4:].split("+")[0].strip().lower()
        if base in ("macro", "xasset", "dive"):
            return base
        if base.startswith("wick"):
            return "wick_rev"
        return None                      # legacy comments (F2B-M15 etc.) — not attributable
    return None


def evolve_modes(mt5):
    """STRATEGY EVOLUTION: live P&L per entry mode → disable losers / boost winners."""
    now = int(time.time())
    deals = mt5.history_deals_get(now - 48 * 3600, now) or []
    entry_mode = {}                                  # position_id -> mode
    for d in deals:
        if d.magic in (MAGIC, 20260613) and d.entry == 0:
            m = _mode_of(d.comment)
            if m:
                entry_mode[d.position_id] = m
    stats = {}
    for d in deals:
        if d.magic in (MAGIC, 20260613) and d.entry == 1 and d.position_id in entry_mode:
            m = entry_mode[d.position_id]
            t = stats.setdefault(m, [0, 0.0])
            t[0] += 1; t[1] += d.profit + d.commission + d.swap
    # 🩸 نافذة طويلة (بنيوية): نفس الحساب على 21 يوماً لاصطياد الخاسر البطيء الذي تفوته الـ48h
    ldeals = mt5.history_deals_get(now - MODE_LONG_HOURS * 3600, now) or []
    lentry = {}
    for d in ldeals:
        if d.magic in (MAGIC, 20260613) and d.entry == 0:
            m = _mode_of(d.comment)
            if m:
                lentry[d.position_id] = m
    lstats = {}
    for d in ldeals:
        if d.magic in (MAGIC, 20260613) and d.entry == 1 and d.position_id in lentry:
            m = lentry[d.position_id]
            t = lstats.setdefault(m, [0, 0.0])
            t[0] += 1; t[1] += d.profit + d.commission + d.swap
    prev = (_load(MODE_OUT, {}) or {}).get("modes", {})
    modes = {}
    changes = []
    for m in ("macro", "xasset", "dive", "wick_rev", "gap_pend", "srlim"):
        n, net = stats.get(m, [0, 0.0])
        ln, lnet = lstats.get(m, [0, 0.0])
        old = prev.get(m, {})
        until = float(old.get("disabled_until", 0))
        disabled = until > now
        mult = 1.0
        long_loser = (ln >= MODE_LONG_MIN_N and lnet <= MODE_LONG_KILL_NET)
        if long_loser:
            # خاسر بنيوي (أولوية): يُعطّل 7 أيام ويُعاد تسليح النافذة كل دورة ما دام خاسراً
            if not disabled:
                changes.append(f"🛑 عطّلت وضع {m} بنيوياً (خسر ${lnet:+.0f} في {ln} صفقة/21ي) 7 أيام")
            disabled = True; until = now + MODE_LONG_DISABLE_H * 3600
        elif n >= MODE_MIN_N and net <= MODE_KILL_NET and not disabled:
            disabled = True; until = now + 24 * 3600
            changes.append(f"🛑 عطّلت وضع {m} (خسر ${net:+.0f} في {n} صفقة/48س) 24 ساعة")
        elif n >= MODE_MIN_N and net >= MODE_BOOST_NET and not (ln >= MODE_LONG_MIN_N and lnet < 0):
            mult = 1.2                                  # لا تعزّز وضعاً خاسراً على المدى الطويل
            if old.get("mult") != 1.2:
                changes.append(f"⤴️ عزّزت وضع {m} (ربح ${net:+.0f} في {n}) لوت ×1.2")
        elif disabled and until <= now:
            disabled = False
            changes.append(f"🔓 أعدت تفعيل وضع {m} بعد التهدئة")
        modes[m] = {"n": n, "net": round(net, 2), "long_n": ln, "long_net": round(lnet, 2),
                    "mult": mult, "disabled": disabled, "disabled_until": until if disabled else 0}
    _save(MODE_OUT, {"ts": time.time(), "modes": modes})
    for c in changes:
        _log("MODE", c, stats)
    if not changes:
        live = {m: f"{v['n']}t ${v['net']:+.0f}" for m, v in modes.items() if v["n"]}
        _log("MODE", f"لا تغيير — الأوضاع: {live or 'لا صفقات منسوبة بعد'}")


def refresh_session_stables(mt5):
    """Daily: re-validate every stable symbol's session specialists on fresh data."""
    import genome_factory as gf
    import glob as _g
    syms = sorted({Path(f).parent.name for f in _g.glob(str(gf.GENO / "*" / "stable.json"))})
    for s in syms:
        try:
            st = gf.build_session_specialists(mt5, s)
            _log("STABLE", f"{s}: {len(st)} متخصص بعد إعادة التحقق")
        except Exception as e:
            _log("STABLE", f"{s} err {e}")


def discovery_probe(mt5, max_new=2):
    """Daily: deep-probe liquid, gate-eligible, NOT-deployed symbols for new real edges."""
    import genome_factory as gf
    gate = _load(V2DIR / "data" / "market_gate.json", {}) or {}
    deployed = {Path(f).stem for f in __import__("glob").glob(str(gf.GENO / "*.json"))}
    cands = []
    for s, r in (gate.get("results", {}) or {}).items():
        base = s.replace("_x100m", "m").replace("_x10m", "m")
        if r.get("tier") in ("robust", "marginal") and base not in deployed:
            cands.append(base)
    import random
    random.shuffle(cands)
    found = 0
    for s in cands[:6]:
        if found >= max_new:
            break
        try:
            if not gf._liquid_ok(mt5, s):
                continue
            old_w = gf.BAR_WINDOWS
            gf.BAR_WINDOWS = [25000]
            try:
                best, _ = gf.optimize(mt5, s)
            finally:
                gf.BAR_WINDOWS = old_w
            if best and best.get("folds_pos", 0) >= 3 and best.get("pf", 0) >= 1.25:
                verdict = gf.write_best(s, {**best, "source": "discovery"})
                _log("DISCOVER", f"🌱 حافة جديدة: {s} PF {best['pf']} {best['net_R']}R → {verdict}")
                found += 1
            else:
                _log("DISCOVER", f"{s}: لا حافة حقيقية")
        except Exception as e:
            _log("DISCOVER", f"{s} err {e}")


def _general_vals(sym):
    g = _load(V2DIR / "data" / "genomes" / f"{sym}.json", {}) or {}
    c = g.get("config") or {}
    return {k: c.get(k) for k in ("tf", "stop_atr", "target_atr", "conf_gate")} if c else None


def merge_genes():
    """🧬 التهجين الاتجاهي (فكرة المستخدم): جين شاطر بالشراء + جين شاطر بالبيع = هجين واحد —
    جانب الشراء بقيم الأول وجانب البيع بقيم الثاني. والجانب الذي ثبت فشله يُغلق أو يُعطى
    قيم جين بديل ليُحاكم من جديد عبر السجل."""
    sk = (_load(RN / "gene_skills.json", {}) or {}).get("skills", {})
    if not sk:
        return
    hybrids = {"_ts": time.time()}
    for sym, sessions in sk.items():
        for sess, dirs in sessions.items():
            L, S = dirs.get("long"), dirs.get("short")
            if not (isinstance(L, dict) and isinstance(S, dict)):
                continue
            ln, sn = L.get("n", 0), S.get("n", 0)
            lnet, snet = L.get("net", 0.0), S.get("net", 0.0)
            # 🆕 إغلاق حلقة التعلّم الحيّ لجانب واحد: لو جانب مُثبت حيّاً (n>=8 وصافي>=3) والآخر
            # رفيع (n<5) أو خاسر → فضّل المُثبت. كانت حافات حيّة قوية تُهمَل لأن الشرط القديم طلب
            # n>=5 للطرفين معاً (مثال: ذهب NY_OVERLAP بيع +$222/32ص بينما الشراء 3ص فقط — أُهمِل).
            if not (ln >= 5 and sn >= 5):
                one = {}
                if ln >= 8 and lnet >= 3 and (sn < 5 or snet < 0):
                    one = {"allow": "long", "why": f"حيّ: شراء ${lnet:+.0f} ({ln}ص) قوي / بيع رفيع-أو-خاسر"}
                elif sn >= 8 and snet >= 3 and (ln < 5 or lnet < 0):
                    one = {"allow": "short", "why": f"حيّ: بيع ${snet:+.0f} ({sn}ص) قوي / شراء رفيع-أو-خاسر"}
                if one:
                    hybrids.setdefault(sym, {})[sess] = one
                    _log("HYBRID", f"🧬 هجين {sym}/{sess}: {one['why']}")
                continue                          # الطرفان ليسا كافيَين معاً — انتهى هذا الجانب

            def bestvals(cell):
                best = None
                for k, v in (cell.get("values_seen") or {}).items():
                    if v.get("n", 0) >= 3 and v.get("net", 0) > 0 and \
                       (best is None or v["net"] > best[1]["net"]):
                        best = (k, v)
                return json.loads(best[0]) if best else None

            entry = {}
            if L["net"] > 2 and S["net"] < -2:    # شاطر شراءً، فاشل بيعاً
                alt = bestvals(S) or _general_vals(sym)
                entry = {"allow": "both" if alt else "long",
                         "why": f"شراء ${L['net']:+} ({L['n']}ص) / بيع ${S['net']:+} → بيعه بقيم جين بديل"}
                if alt:
                    entry["short"] = alt
                lv = bestvals(L)
                if lv:
                    entry["long"] = lv
            elif S["net"] > 2 and L["net"] < -2:  # شاطر بيعاً، فاشل شراءً
                alt = bestvals(L) or _general_vals(sym)
                entry = {"allow": "both" if alt else "short",
                         "why": f"بيع ${S['net']:+} ({S['n']}ص) / شراء ${L['net']:+} → شراؤه بقيم جين بديل"}
                if alt:
                    entry["long"] = alt
                sv = bestvals(S)
                if sv:
                    entry["short"] = sv
            elif L["net"] > 2 and S["net"] > 2:   # شاطر بالاتجاهين → ثبّت أفضل قيم كل جانب
                e2 = {}
                lv, sv = bestvals(L), bestvals(S)
                if lv:
                    e2["long"] = lv
                if sv:
                    e2["short"] = sv
                if e2:
                    entry = {"allow": "both", "why": "شاطر بالاتجاهين — قيم كل جانب من أفضله", **e2}
            if entry:
                hybrids.setdefault(sym, {})[sess] = entry
                _log("HYBRID", f"🧬 هجين {sym}/{sess}: {entry['why']}")
    if len(hybrids) > 1:
        _save(RN / "gene_hybrids.json", hybrids)


def straddle_advisor():
    """Auto-answer the hunter's help request with rule-based advice (no human needed)."""
    req = _load(HELP_REQ)
    if not req or req.get("answered"):
        return
    stats = str(req.get("stats", ""))
    adv = {"ts": time.time(), "from": "evolution_director", "applied": False, "enabled": True}
    if "مصايد" in stats and any(f"مصايد {k}" in stats for k in ("3", "4", "5", "6")):
        adv.update({"dist_atr": 1.3, "tp_atr": 2.0,
                    "note": "مصايد كثيرة → وسّعت المسافة 1.3×ATR وقرّبت الهدف"})
    elif "بلا تنفيذ" in stats:
        adv.update({"dist_atr": 0.5, "note": "ما ينفّذ → قرّبت المسافة 0.5×ATR"})
    else:
        adv.update({"symbols": ["XAUUSDm"], "tp_atr": 2.0, "sl_atr": 1.2,
                    "note": "خسائر مع تنفيذ → الذهب فقط + وقف أوسع وهدف أقرب"})
    _save(ADVICE, adv)
    req["answered"] = True; req["answered_by"] = "evolution_director"; req["advice"] = adv.get("note")
    _save(HELP_REQ, req)
    _log("ADVISOR", f"🧠 أجبت طلب مساعدة الصياد: {adv.get('note')}")


# كل أزواج العملات السائلة (المحاكمة الدورية تغطّيها كلها بالتناوب؛ فلتر السيولة يُسقط الغالي)
TRIAL_CANDS = [
    # FX majors
    "EURUSDm", "GBPUSDm", "USDJPYm", "USDCHFm", "USDCADm", "AUDUSDm", "NZDUSDm",
    # FX crosses
    "EURJPYm", "GBPJPYm", "EURGBPm", "EURAUDm", "EURCADm", "EURCHFm", "EURNZDm",
    "GBPAUDm", "GBPCADm", "GBPCHFm", "GBPNZDm", "AUDJPYm", "AUDCADm", "AUDCHFm",
    "AUDNZDm", "CADJPYm", "CADCHFm", "CHFJPYm", "NZDJPYm", "NZDCADm",
    # metals + energy
    "XAUUSDm", "XAGUSDm", "XAUEURm", "XAUGBPm", "USOILm", "UKOILm", "XNGUSDm",
    # indices
    "US30m", "US500m", "USTECm", "DE30m", "UK100m", "JP225m", "AUS200m", "FRA40m", "HK50m",
    # major crypto
    "BTCUSDm", "ETHUSDm", "BNBUSDm", "SOLUSDm", "XRPUSDm", "LTCUSDm",
    # liquid US mega-caps
    "MSFTm", "Vm", "MAm", "AMGNm", "MCDm", "INTUm", "UNHm", "REGNm"]


def rotating_trial(mt5, st, per_day=10):
    """الجدولة الدائمة (طلب المستخدم): محاكمة جلسات متجدّدة لكل المرشّحين — 6 رموز يومياً
    بالتناوب (دورة كاملة ≈ 4 أيام، إلى الأبد). أي حافة جلسة تظهر مع تغيّر السوق تنضم تلقائياً،
    وأي مرشّح يفشل يُعاد فحصه بالدورة القادمة. يتخطّى لو البناء اليدوي شغال."""
    try:
        import psutil
        if any("_build_all_stables" in " ".join(pr.info.get("cmdline") or [])
               for pr in psutil.process_iter(["cmdline"])):
            return
    except Exception:
        pass
    import genome_factory as gf
    # مرشّحون ديناميكيون: القائمة الثابتة + كل مؤهّل سائل من البوّابة بلا مجموعة بعد
    cands = list(TRIAL_CANDS)
    gate = _load(V2DIR / "data" / "market_gate.json", {}) or {}
    have = {Path(f).parent.name for f in
            __import__("glob").glob(str(gf.GENO / "*" / "stable.json"))}
    for sym, r in (gate.get("results", {}) or {}).items():
        base = sym.replace("_x100m", "m").replace("_x10m", "m")
        if r.get("tier") in ("robust", "marginal") and base not in cands and base not in have:
            cands.append(base)
    ptr = int(st.get("trial_ptr", 0)) % max(1, len(cands))
    batch = [cands[(ptr + i) % len(cands)] for i in range(per_day)]
    st["trial_ptr"] = (ptr + per_day) % len(cands)
    for sym in batch:
        try:
            if not gf._liquid_ok(mt5, sym, thr=0.45):
                _log("TRIAL", f"{sym}: تخطٍ (سبريد عالٍ الآن)")
                continue
            specs = gf.build_session_specialists(mt5, sym)
            _log("TRIAL", f"{sym}: {len(specs)} متخصص بعد المحاكمة الدورية")
        except Exception as e:
            _log("TRIAL", f"{sym} err {e}")


def legendary_archive():
    """🏛️ DNA المرجعي (الخطة المتكاملة): جين يثبت حيّاً (>=20 صفقة بجلسته وصافي>0 و PF-OOS>=1.4)
    يُخلَّد في LEGENDARY_DNA/ ويُفضَّل أباً في التهجين القادم (نقل الخبرة عبر الأجيال)."""
    import glob as _g
    leg_dir = MT5DIR / "LEGENDARY_DNA"
    leg_dir.mkdir(exist_ok=True)
    sk = (_load(RN / "gene_skills.json", {}) or {}).get("skills", {})
    for sf in _g.glob(str(V2DIR / "data" / "genomes" / "*" / "stable.json")):
        st = _load(sf, {}) or {}
        sym = st.get("symbol") or Path(sf).parent.name
        for spec in st.get("specialists", []) or []:
            sess = spec.get("session")
            cell = (sk.get(sym, {}).get(sess, {}) or {})
            live_n = sum(int(c.get("n", 0)) for c in cell.values() if isinstance(c, dict))
            live_net = sum(float(c.get("net", 0)) for c in cell.values() if isinstance(c, dict))
            if live_n >= 20 and live_net > 0 and float(spec.get("pf", 0)) >= 1.4:
                fname = leg_dir / f"{sym}_{sess}_{int(time.time())}_{spec.get('pf')}.json"
                already = list(leg_dir.glob(f"{sym}_{sess}_*"))
                if not already:
                    _save(fname, {"symbol": sym, "session": sess, "values": spec,
                                  "live_n": live_n, "live_net": round(live_net, 2),
                                  "crowned": datetime.now(timezone.utc).isoformat()})
                    _log("LEGEND", f"🏛️ أسطورة جديدة: {sym}/{sess} PF{spec.get('pf')} · حي {live_n}ص ${live_net:+.0f}")


def nightly_digest():
    """التقرير الليلي: 'وش صار بغيابك' — ملخّص يومي مكتوب من اللوحات الحقيقية."""
    sc = _load(RN / "pnl_scoreboard.json", {}) or {}
    mw = (_load(MODE_OUT, {}) or {}).get("modes", {})
    sj = (_load(RN / "straddle_journal.json", {}) or {}).get("episodes", [])
    tc = _load(RN / "tournament_confirmed.json", {}) or {}
    lin = []
    try:
        lin = [json.loads(x) for x in
               Path(LOG).read_text(encoding="utf-8").strip().splitlines()[-30:]]
    except Exception:
        pass
    digest = {
        "iso": datetime.now(timezone.utc).isoformat(),
        "equity": sc.get("equity"), "today_net": sc.get("today_net"),
        "d7_net": sc.get("d7_net"), "verdict": sc.get("verdict"),
        "sources_today": sc.get("today_src", [])[:6],
        "modes": {m: {"n": v.get("n"), "net": v.get("net"),
                      "state": "معطّل" if v.get("disabled") else ("معزّز" if v.get("mult", 1) > 1 else "عادي")}
                  for m, v in mw.items()},
        "straddle": {"episodes": len(sj), "net": round(sum(e.get("net", 0) for e in sj), 2)},
        "tournament_confirmed": {s: ("شراء" if v.get("dir", 0) > 0 else "بيع") for s, v in tc.items()},
        "evolution_events": [{"kind": e.get("kind"), "msg": e.get("msg")} for e in lin[-12:]],
    }
    _save(RN / "night_summary.json", digest)
    _log("DIGEST", f"📋 التقرير الليلي: حقوق ${digest['equity']} · اليوم ${digest['today_net']} · "
                   f"صياد {digest['straddle']['episodes']} محاولة ${digest['straddle']['net']}")


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    _log("START", "مدير التطوّر حيّ — استراتيجيات/جينات/جلسات/وكلاء بدون تدخل بشري")
    while True:
        try:
            st = _load(STATE, {}) or {}
            now = time.time()
            evolve_modes(mt5)
            merge_genes()
            straddle_advisor()
            if now - float(st.get("last_stable_refresh", 0)) > 24 * 3600:
                _log("STABLE", "بدء إعادة التحقق اليومي لمتخصصي الجلسات (50k + سبريد حقيقي)…")
                refresh_session_stables(mt5)
                st["last_stable_refresh"] = now
            if now - float(st.get("last_discovery", 0)) > 24 * 3600:
                _log("DISCOVER", "مسبار الاكتشاف اليومي…")
                discovery_probe(mt5)
                st["last_discovery"] = now
            if now - float(st.get("last_digest", 0)) > 24 * 3600:
                nightly_digest()
                legendary_archive()
                st["last_digest"] = now
            if now - float(st.get("last_rot_trial", 0)) > 24 * 3600:
                _log("TRIAL", "المحاكمة الدورية اليومية (6 مرشحين بالتناوب)…")
                rotating_trial(mt5, st)
                st["last_rot_trial"] = now
            st["ts"] = now
            _save(STATE, st)
        except Exception as e:
            _log("ERR", str(e))
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    raise SystemExit(main())
