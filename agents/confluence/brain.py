#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محرك التقاطع (Confluence Engine) — Mujammi v2
وضع مزدوج: Scalp (جريء، 2+ أصوات) + Swing (يقين 100%، 4+ أصوات اتجاهية)
"""
import json, datetime, requests
from pathlib import Path

AGENT_DIR         = Path(__file__).parent
MEMORY_FILE       = AGENT_DIR / "memory.json"
REPORT_FILE       = AGENT_DIR / "report.md"
LOG_FILE          = AGENT_DIR / "log.jsonl"
AGENTS_DIR        = Path(__file__).parent.parent
CONFLUENCE_SIGNAL = AGENTS_DIR / "confluence_signal.json"
# Mirror to MT5 Common\Files so EA can read it via FILE_COMMON
COMMON_FILES      = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
CONFLUENCE_COMMON = COMMON_FILES / "confluence_signal.json"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

# ── Thresholds ──────────────────────────────────────────────────────────────
SCALP_MIN_VOTES   = 1   # 1+ directional votes → scalp entry (only 2 agents give direction)
SWING_MIN_VOTES   = 2   # 2+ directional votes same direction → swing entry
SWING_LLM_MIN     = 6   # LLM coherence score ≥ 6/10 required for swing
# ────────────────────────────────────────────────────────────────────────────

def load_memory():
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except: pass
    return {"agent": "محرك التقاطع", "name": "Mujammi", "role": "Confluence Engine v2",
            "runs": 0, "scalp_approved": 0, "swing_approved": 0, "rejected": 0,
            "scalp_wins": 0, "scalp_losses": 0, "history": []}

def save_memory(m):
    MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def read_agent_votes():
    """جمع الأصوات من كل الوكلاء مع تفاصيل SMC"""
    votes = {}
    smc_details = {}

    # ── 1. SMC (من EA) ───────────────────────────────────────────────────────
    try:
        common = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
        st = json.loads((common / "ea_realtime_status.json").read_text(encoding="utf-8"))
        bias    = st.get("smc_bias", "NEUTRAL")
        bos     = st.get("smc_has_bos", False)
        choch   = st.get("smc_has_choch", False)
        ob      = int(st.get("smc_ob_count", 0))
        fvg     = int(st.get("smc_fvg_count", 0))
        ema     = st.get("ema_dir", "NEUTRAL")
        rsi     = float(st.get("rsi", 50))
        # حساب قوة إشارة SMC
        smc_strength = ob + fvg + (2 if bos else 0) + (3 if choch else 0)
        # يصوت 1: إذا كان هناك انحياز واضح (BOS أو CHoCH أو OB أو FVG)
        # يصوت 1 أيضاً بمجرد BOS/CHoCH حتى بدون OB/FVG (كسر هيكل مهم)
        smc_vote = 1 if (bias in ["BUY","SELL"] and (ob > 0 or fvg > 0 or bos or choch)) else 0
        # مكافأة: OB + BOS معاً = إشارة عالية الجودة
        smc_confluence_label = ""
        if ob > 0 and bos:   smc_confluence_label = "OB+BOS"
        elif choch:           smc_confluence_label = "CHoCH"
        elif bos:             smc_confluence_label = "BOS"
        elif ob > 0:          smc_confluence_label = "OB"
        elif fvg > 0:         smc_confluence_label = "FVG"
        # S/R من swing levels
        swing_high = float(st.get("smc_swing_high", 0))
        swing_low  = float(st.get("smc_swing_low",  0))
        price      = float(st.get("close", st.get("bid", 0)))
        pdh        = float(st.get("prev_day_high", 0))
        pdl        = float(st.get("prev_day_low",  0))
        sr_near = ""
        if price > 0:
            if pdh > 0 and abs(price - pdh) / price < 0.002:  sr_near = "NEAR_PDH"
            elif pdl > 0 and abs(price - pdl) / price < 0.002: sr_near = "NEAR_PDL"
            elif swing_high > 0 and abs(price - swing_high) / price < 0.003: sr_near = "NEAR_SWING_H"
            elif swing_low  > 0 and abs(price - swing_low)  / price < 0.003: sr_near = "NEAR_SWING_L"
        smc_details = {"bias": bias, "bos": bos, "choch": choch, "ob": ob, "fvg": fvg,
                       "ema": ema, "rsi": rsi, "confluence": smc_confluence_label,
                       "sr_near": sr_near, "swing_high": swing_high, "swing_low": swing_low,
                       "pdh": pdh, "pdl": pdl}
        votes["smc"] = {"vote": smc_vote, "direction": bias if bias in ["BUY","SELL"] else "NEUTRAL",
                        "strength": smc_strength, "confluence": smc_confluence_label, "sr_near": sr_near}
    except:
        votes["smc"] = {"vote": 0, "direction": "NEUTRAL", "strength": 0}

    # ── 2. Volume Profile ────────────────────────────────────────────────────
    try:
        vp = json.loads((AGENTS_DIR / "volume_profile_signal.json").read_text(encoding="utf-8"))
        sig  = vp.get("trade_signal", "NEUTRAL")
        bias = vp.get("bias", "NEUTRAL")
        # جريء: AT_POC مع انحياز → صوت 1 (قرار مهم عند POC)
        if sig in ["BUY_ZONE", "SELL_ZONE"]:
            vdir = "BUY" if sig == "BUY_ZONE" else "SELL"
            vvote = 1
        elif sig == "AT_POC" and bias in ["BULLISH","BEARISH"]:
            vdir  = "BUY" if bias == "BULLISH" else "SELL"
            vvote = 1
        else:
            vdir, vvote = "NEUTRAL", 0
        votes["volume_profile"] = {"vote": vvote, "direction": vdir, "signal": sig}
    except:
        votes["volume_profile"] = {"vote": 0, "direction": "NEUTRAL"}

    # ── 3. Risk Manager (حارس رأس المال) ────────────────────────────────────
    try:
        rm_mem = json.loads((AGENTS_DIR / "risk_manager" / "memory.json").read_text(encoding="utf-8"))
        risk_ok = rm_mem.get("risk_level","RED") not in ["RED"]
        votes["risk"] = {"vote": 1 if risk_ok else 0, "direction": "RISK_OK" if risk_ok else "RISK_WARN"}
    except:
        votes["risk"] = {"vote": 0, "direction": "NEUTRAL"}

    # ── 4. Guard (حارس المخاطر) ──────────────────────────────────────────────
    try:
        g_mem = json.loads((AGENTS_DIR / "guard" / "memory.json").read_text(encoding="utf-8"))
        safe  = g_mem.get("risk_level","RED") == "GREEN"
        votes["guard"] = {"vote": 1 if safe else 0, "direction": "SAFE" if safe else "RISK_WARN"}
    except:
        votes["guard"] = {"vote": 0, "direction": "NEUTRAL"}

    # ── 5. LLM Interrogator (تماسك منطقي) ───────────────────────────────────
    try:
        llm_mem = json.loads((AGENTS_DIR / "llm_interrogator" / "memory.json").read_text(encoding="utf-8"))
        last = llm_mem.get("interrogations", [{}])[-1]
        score = last.get("score", 0)
        llm_vote = 1 if score >= 6 else 0
        votes["llm"] = {"vote": llm_vote, "direction": "LLM_OK" if llm_vote else "LLM_WEAK",
                        "score": score}
    except:
        votes["llm"] = {"vote": 0, "direction": "NEUTRAL", "score": 0}

    # ── 6. Experience / Khabir (أنماط تاريخية) ──────────────────────────────
    try:
        kh_mem = json.loads((AGENTS_DIR / "experience" / "memory.json").read_text(encoding="utf-8"))
        bad_pattern = kh_mem.get("bad_pattern_flag", False)
        win_rate    = kh_mem.get("win_rate", 50)
        exp_vote    = 0 if bad_pattern else (1 if win_rate >= 45 else 0)
        votes["experience"] = {"vote": exp_vote, "direction": "EXP_OK" if exp_vote else "BAD_PATTERN",
                               "win_rate": win_rate}
    except:
        votes["experience"] = {"vote": 1, "direction": "EXP_OK"}  # افتراضي: مرور

    # ── 7. Analyst ────────────────────────────────────────────────────────────
    try:
        an_mem = json.loads((AGENTS_DIR / "analyst" / "memory.json").read_text(encoding="utf-8"))
        positive = an_mem.get("last_sentiment", "neutral") not in ["negative","bearish_extreme"]
        votes["analyst"] = {"vote": 1 if positive else 0, "direction": "PATTERN_OK" if positive else "NEUTRAL"}
    except:
        votes["analyst"] = {"vote": 1, "direction": "PATTERN_OK"}  # افتراضي

    # ── 8. Multi-TF Analyst (Musharrik) — تقاطع مستويات متعددة ──────────────
    try:
        mtf = json.loads((AGENTS_DIR / "multi_tf_signal.json").read_text(encoding="utf-8"))
        mtf_dir  = mtf.get("direction", "NEUTRAL")
        mtf_vote = mtf.get("vote", 0)
        sup_cnt  = mtf.get("strong_support_count", 0)
        res_cnt  = mtf.get("strong_resistance_count", 0)
        # إذا كان هناك دعم قوي (3+) والاتجاه BUY → وزن إضافي
        # إذا كان هناك مقاومة قوية (3+) والاتجاه SELL → وزن إضافي
        sr_bonus = (sup_cnt >= 3 and mtf_dir == "BUY") or (res_cnt >= 3 and mtf_dir == "SELL")
        sr_label = f"SUP×{sup_cnt}" if mtf_dir == "BUY" else f"RES×{res_cnt}"
        votes["multi_tf"] = {"vote": mtf_vote, "direction": mtf_dir if mtf_vote else "NEUTRAL",
                             "strong_sup": sup_cnt, "strong_res": res_cnt,
                             "sr_bonus": sr_bonus, "sr_label": sr_label}
    except:
        votes["multi_tf"] = {"vote": 0, "direction": "NEUTRAL"}

    return votes, smc_details

def calc_pending_levels(smc_details, status, vp_data):
    """
    حساب مستويات الأوامر المعلقة — أوامر انتظار عند مناطق رئيسية:
    Volume Profile (POC/VAH/VAL) + Pivot Points + FVG fill + Swing H/L + PDH/PDL
    إرجاع قائمة قصوى 4 أوامر مرتبة حسب الثقة
    """
    pending = []
    price = float(status.get("close", status.get("bid", 0)))
    if price <= 0:
        return pending

    # Volume Profile
    poc = float(vp_data.get("poc", 0))
    vah = float(vp_data.get("vah", 0))
    val = float(vp_data.get("val", 0))

    # S/R levels
    pdh = float(smc_details.get("pdh", 0))
    pdl = float(smc_details.get("pdl", 0))
    sh  = float(smc_details.get("swing_high", 0))
    sl  = float(smc_details.get("swing_low",  0))

    # Pivot Points (Classical: PP = (PrevH + PrevL + PrevC) / 3)
    pdc = float(status.get("prev_day_close", 0))
    pp = r1 = s1 = r2 = s2 = 0.0
    if pdh > 0 and pdl > 0:
        pclose = pdc if pdc > 0 else (pdh + pdl) / 2.0
        pp = (pdh + pdl + pclose) / 3.0
        r1 = 2.0 * pp - pdl
        s1 = 2.0 * pp - pdh
        r2 = pp + (pdh - pdl)
        s2 = pp - (pdh - pdl)

    # FVG levels — bull FVG below price (BUY_LIMIT fill), bear FVG above price (SELL_LIMIT fill)
    fvg_bull_hi = float(status.get("smc_fvg_bull_high", 0))  # nearest bullish FVG top
    fvg_bull_lo = float(status.get("smc_fvg_bull_low",  0))  # nearest bullish FVG bottom
    fvg_bear_hi = float(status.get("smc_fvg_bear_high", 0))  # nearest bearish FVG top
    fvg_bear_lo = float(status.get("smc_fvg_bear_low",  0))  # nearest bearish FVG bottom
    fvg_count   = int(smc_details.get("fvg", 0))

    # Min distance: at least 1.5$ or 0.04% of price (whichever is larger)
    min_dist = max(1.5, price * 0.0004)

    def add(otype, tprice, reason, conf, expiry=4):
        if tprice <= 0:
            return
        if abs(tprice - price) < min_dist:
            return  # too close
        if otype == "BUY_LIMIT"  and tprice >= price:
            return  # BUY_LIMIT must be below price
        if otype == "SELL_LIMIT" and tprice <= price:
            return  # SELL_LIMIT must be above price
        pending.append({"type": otype, "price": round(tprice, 2),
                        "reason": reason, "confidence": conf, "expiry_hours": expiry})

    # ── BUY_LIMIT: عند الدعم — السعر ينزل ثم يرتد ──────────────────────────
    if val > 0:
        add("BUY_LIMIT", val + 0.30,  "VAL_SUP",    80)
    if pdl > 0:
        add("BUY_LIMIT", pdl + 0.20,  "PDL_SUP",    82)
    if sl > 0:
        add("BUY_LIMIT", sl  + 0.15,  "SWING_LOW",  78)
    if s1 > 0:
        add("BUY_LIMIT", s1  + 0.20,  "S1_PIVOT",   76)
    if poc > 0:
        add("BUY_LIMIT", poc + 0.50,  "POC_SUP",    72)
    if s2 > 0:
        add("BUY_LIMIT", s2  + 0.20,  "S2_PIVOT",   68)
    # FVG fill (bullish FVG below price): price may dip back to fill the gap
    if fvg_bull_hi > 0 and fvg_bull_lo > 0:
        fvg_bull_mid = (fvg_bull_hi + fvg_bull_lo) * 0.5
        add("BUY_LIMIT", round(fvg_bull_mid, 2), "FVG_FILL_B", 71)

    # ── SELL_LIMIT: عند المقاومة — السعر يصعد ثم ينعكس ─────────────────────
    if vah > 0:
        add("SELL_LIMIT", vah - 0.30, "VAH_RES",    80)
    if pdh > 0:
        add("SELL_LIMIT", pdh - 0.20, "PDH_RES",    82)
    if sh > 0:
        add("SELL_LIMIT", sh  - 0.15, "SWING_HIGH", 78)
    if r1 > 0:
        add("SELL_LIMIT", r1  - 0.20, "R1_PIVOT",   76)
    if poc > 0:
        add("SELL_LIMIT", poc - 0.50, "POC_RES",    72)
    if r2 > 0:
        add("SELL_LIMIT", r2  - 0.20, "R2_PIVOT",   68)
    # FVG fill: price is below FVG → it may rally to fill the gap
     # Bearish FVG above price — SELL_LIMIT at FVG midpoint (price may rise to fill it)
    if fvg_bear_hi > 0 and fvg_bear_lo > 0:
        fvg_bear_mid = (fvg_bear_hi + fvg_bear_lo) * 0.5
        add("SELL_LIMIT", round(fvg_bear_mid, 2), "FVG_FILL_S", 71)

    # Sort by confidence descending, keep top 4
    pending.sort(key=lambda x: x["confidence"], reverse=True)
    return pending[:4]


def get_consensus_direction(votes):
    """احسب الاتجاه من الأصوات الاتجاهية فقط (BUY/SELL)
    عند التعادل: استخدم multi_tf كمرجّح (أكثر موثوقية)"""
    buy_count = sell_count = 0
    for v in votes.values():
        d = v.get("direction","")
        if d == "BUY":   buy_count  += 1
        if d == "SELL":  sell_count += 1
    if buy_count > sell_count:   return "BUY",  buy_count,  sell_count
    if sell_count > buy_count:   return "SELL", buy_count,  sell_count
    # تعادل — استخدم multi_tf كمرجّح
    mtf_dir = votes.get("multi_tf", {}).get("direction", "")
    if mtf_dir == "BUY":   return "BUY",  buy_count,  sell_count
    if mtf_dir == "SELL":  return "SELL", buy_count,  sell_count
    return "NEUTRAL", buy_count, sell_count

def ask_ollama(prompt):
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2, "num_predict": 100}, "keep_alive": "10m"}, timeout=8)
        return r.json().get("response","").strip() if r.ok else "[Ollama offline]"
    except: return "[Ollama offline]"

def run():
    mem   = load_memory()
    mem["runs"] += 1
    now   = datetime.datetime.now().isoformat()

    votes, smc = read_agent_votes()

    # بيانات إضافية لحساب المستويات المعلقة
    _vp_data  = {}
    _st_data  = {}
    try:
        _vp_data = json.loads((AGENTS_DIR / "volume_profile_signal.json").read_text(encoding="utf-8"))
    except: pass
    try:
        _st_data = json.loads((COMMON_FILES / "ea_realtime_status.json").read_text(encoding="utf-8"))
    except: pass

    total_votes    = len(votes)
    positive_votes = sum(1 for v in votes.values() if v.get("vote",0) == 1)
    consensus, buy_cnt, sell_cnt = get_consensus_direction(votes)

    # Directional votes only (BUY/SELL) — for swing requirement
    dir_votes = buy_cnt + sell_cnt
    dir_agreement = max(buy_cnt, sell_cnt)  # how many agree on one direction

    llm_score = votes.get("llm", {}).get("score", 0)
    risk_ok   = votes.get("risk", {}).get("vote", 0) == 1
    guard_ok  = votes.get("guard", {}).get("vote", 0) == 1

    # ── SCALP MODE: جريء وسريع ───────────────────────────────────────────────
    # يحتاج 2+ أصوات اتجاهية + الحارس لا يقول RED خطر شديد
    scalp_approved = (
        dir_agreement >= SCALP_MIN_VOTES
        and consensus in ["BUY","SELL"]
    )

    # ── SWING MODE: يقين 100% ────────────────────────────────────────────────
    # يحتاج 4+ أصوات اتجاهية نفس الاتجاه + LLM ≥ 7 + حارس آمن
    swing_approved = (
        dir_agreement >= SWING_MIN_VOTES
        and consensus in ["BUY","SELL"]
        and llm_score >= SWING_LLM_MIN
        and (risk_ok or guard_ok)  # على الأقل واحد منهم موافق
    )

    # ── لا تدخل أبداً إذا الحارس يصرخ DANGER شديد ─────────────────────────────
    guard_mem_path = AGENTS_DIR / "guard" / "memory.json"
    try:
        raw_g = guard_mem_path.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace")
        g = json.loads(raw_g)
        g_score = g.get("risk_score", 0)
        if g_score >= 70:          # خطر حقيقي شديد → وقف الكل
            scalp_approved = False
            swing_approved = False
        elif g_score >= 50:        # خطر متوسط → يمنع Swing فقط، يسمح Scalp صغير
            swing_approved = False
    except: pass

    # الاتجاه النهائي
    final_dir = consensus if (scalp_approved or swing_approved) else "BLOCKED"

    # تحديث الذاكرة
    if swing_approved:
        mem["swing_approved"] += 1
    elif scalp_approved:
        mem["scalp_approved"] += 1
    else:
        mem["rejected"] += 1

    mem["history"].append({
        "t": now[:16], "votes": positive_votes, "dir_agreement": dir_agreement,
        "scalp": scalp_approved, "swing": swing_approved, "direction": consensus
    })
    mem["history"] = mem["history"][-200:]

    # استخراج معلومات S/R و OB/BOS من SMC
    smc_confluence = smc.get("confluence", "")
    sr_near        = smc.get("sr_near", "")
    sr_bonus       = votes.get("multi_tf", {}).get("sr_bonus", False)
    sr_label_mtf   = votes.get("multi_tf", {}).get("sr_label", "")
    ob_bos_alert   = smc_confluence == "OB+BOS"  # أعلى جودة دخول
    choch_alert    = smc_confluence == "CHoCH"    # انعكاس هيكل

    # LLM تقييم سريع
    mode = "SWING 🐋" if swing_approved else ("SCALP ⚡" if scalp_approved else "BLOCKED 🚫")
    sr_info = f"S/R: {sr_near or 'none'} | MTF S/R: {sr_label_mtf or 'none'}"
    prompt = f"""تداول الذهب XAUUSD — قرار التقاطع:
الوضع: {mode} | الاتجاه: {consensus}
أصوات اتجاهية: BUY={buy_cnt} SELL={sell_cnt} | LLM={llm_score}/10
SMC: OB={smc.get('ob',0)} FVG={smc.get('fvg',0)} BOS={smc.get('bos',False)} CHoCH={smc.get('choch',False)}
تقاطع SMC: {smc_confluence or 'none'} | {sr_info}
في جملة واحدة: هل هذا القرار صحيح؟"""

    analysis = ask_ollama(prompt)

    # كتابة إشارة التقاطع للـ EA
    confluence_out = {
        "time":           now,
        "approved":       scalp_approved,
        "swing_approved": swing_approved,
        "scalp_approved": scalp_approved,
        "votes":          positive_votes,
        "dir_agreement":  dir_agreement,
        "total":          total_votes,
        "scalp_required": SCALP_MIN_VOTES,
        "swing_required": SWING_MIN_VOTES,
        "direction":      final_dir,
        "swing_direction": consensus if swing_approved else "NONE",
        "scalp_direction": consensus if scalp_approved else "NONE",
        "llm_score":      llm_score,
        "mode":           "SWING" if swing_approved else ("SCALP" if scalp_approved else "BLOCKED"),
        "agent_votes":    {k: {"vote": v.get("vote",0), "dir": v.get("direction","?")} for k,v in votes.items()},
        "smc":            smc,
        "sr_analysis": {
            "smc_confluence": smc_confluence,
            "sr_near":        sr_near,
            "ob_bos_alert":   ob_bos_alert,
            "choch_alert":    choch_alert,
            "mtf_sr_bonus":   sr_bonus,
            "swing_high":     smc.get("swing_high", 0),
            "swing_low":      smc.get("swing_low",  0),
            "pdh":            smc.get("pdh", 0),
            "pdl":            smc.get("pdl", 0)
        },
        "approval_stats": {"scalp": mem["scalp_approved"], "swing": mem["swing_approved"], "rejected": mem["rejected"]}
    }

    # ── Pending Orders: مستويات الأوامر المعلقة ────────────────────────────────
    pending_levels = calc_pending_levels(smc, _st_data, _vp_data)
    confluence_out["pending_count"] = len(pending_levels)
    for _i, _p in enumerate(pending_levels):
        confluence_out[f"pending_{_i}_type"]   = _p["type"]
        confluence_out[f"pending_{_i}_price"]  = _p["price"]
        confluence_out[f"pending_{_i}_reason"] = _p["reason"]
        confluence_out[f"pending_{_i}_conf"]   = _p["confidence"]
        confluence_out[f"pending_{_i}_expiry"] = _p.get("expiry_hours", 4)
    # Pivot Point levels (للـ EA)
    _pdh = float(_st_data.get("prev_day_high", 0))
    _pdl = float(_st_data.get("prev_day_low",  0))
    _pdc = float(_st_data.get("prev_day_close", 0))
    if _pdh > 0 and _pdl > 0:
        _pc = _pdc if _pdc > 0 else (_pdh + _pdl) / 2.0
        _pp = (_pdh + _pdl + _pc) / 3.0
        confluence_out["sr_analysis"]["pp"]  = round(_pp, 2)
        confluence_out["sr_analysis"]["r1"]  = round(2*_pp - _pdl, 2)
        confluence_out["sr_analysis"]["s1"]  = round(2*_pp - _pdh, 2)
        confluence_out["sr_analysis"]["r2"]  = round(_pp + (_pdh-_pdl), 2)
        confluence_out["sr_analysis"]["s2"]  = round(_pp - (_pdh-_pdl), 2)
    signal_json = json.dumps(confluence_out, ensure_ascii=False, indent=2)
    CONFLUENCE_SIGNAL.write_text(signal_json, encoding="utf-8")
    try:
        COMMON_FILES.mkdir(parents=True, exist_ok=True)
        CONFLUENCE_COMMON.write_text(signal_json, encoding="utf-8")
    except Exception:
        pass

    mode_emoji = "SWING" if swing_approved else ("SCALP" if scalp_approved else "BLOCKED")
    sr_alert = ""
    if ob_bos_alert: sr_alert += "OB+BOS CONFLUENCE — highest quality entry!\n"
    if choch_alert:  sr_alert += "CHoCH DETECTED — structure reversal!\n"
    if sr_near:      sr_alert += "S/R NEAR: " + sr_near + "\n"

    votes_table = "\n".join(
        "| " + k + " | " + ("YES" if v.get("vote",0)==1 else "NO") + " | " + v.get("direction","?") + " |"
        for k, v in votes.items()
    )
    report = (
        "# Confluence Report | " + now[:16] + "\n\n"
        "## " + mode_emoji + " — " + final_dir + "\n\n"
        + sr_alert + "\n"
        "BUY=" + str(buy_cnt) + " SELL=" + str(sell_cnt) +
        " dir_agree=" + str(dir_agreement) + " llm=" + str(llm_score) + "/10\n\n"
        "| Agent | Vote | Dir |\n|--------|------|-----|\n"
        + votes_table + "\n\n"
        "## Analysis\n" + analysis + "\n\n"
        "Scalp approved: " + str(mem["scalp_approved"]) +
        " | Swing: " + str(mem["swing_approved"]) +
        " | Rejected: " + str(mem["rejected"]) + "\n"
    )
    REPORT_FILE.write_text(report, encoding="utf-8")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": now, "scalp": scalp_approved, "swing": swing_approved,
                            "dir": consensus, "dir_agreement": dir_agreement}, ensure_ascii=False) + "\n")
    save_memory(mem)
    return confluence_out

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
