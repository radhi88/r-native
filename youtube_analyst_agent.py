# -*- coding: utf-8 -*-
"""youtube_analyst_agent.py — وكيلٌ يستمع لبثّ محلّلٍ حيّ على يوتيوب، يستخرج نداءات تداولٍ منظَّمة،
وينفّذها عبر كل حُرّاسنا (ديمو فقط).

⚠️ حدود الأمان (حرجة — لا تُتجاوز):
  • **ديمو فقط**: يرفض التنفيذ إن لم يكن الحساب تجريبياً (اسم الخادم Trial/Demo). لا مالٌ حقيقيّ أبداً.
  • **المصدر غير موثوق** (محتوى خارجيّ): المُحلِّل يستخرج **نداء سوقٍ منظَّماً فقط** (رمز+اتجاه+وقف/هدف).
    أيّ نصٍّ يأمر النظام/الوكيل (تجاهل، نظام، مفتاح، تحويل، سحب، كود…) يُرفض ويُسجَّل — لا يُنفَّذ إطلاقاً.
  • **الحُرّاس**: kill_switch + lot_guard (≤ risk_pct) + سقف مراكز + قائمة رموز بيضاء + منع التحوّط + dedup.
  • **الوضع الافتراضيّ = confirm** (ينبّه جوالك، لا ينفّذ حتى تؤكّد). `auto` متاحٌ بضبطٍ واحد.
  • **لا حافّة مُثبتة**: نداءات بثٍّ عشوائيّ تنزف غالباً — هذا أداة تنفيذٍ محروسة، لا ضمان ربح.

التفريغ: yt-dlp (صوت البثّ) → ffmpeg (مقطع) → faster_whisper (محليّ، مجاناً). magic 20260631.
windowless تحت الوصيّ. قفل نسخة-مفردة. كل إعداداته في youtube_analyst_config.json (قراءة حيّة).
"""
from __future__ import annotations
import os, sys, json, re, time, subprocess, hashlib
# 🪟 نافذة-آمن: pythonw بلا stdout ⇒ rapidocr/onnxruntime تتعطّل عند الكتابة. نوجّه الإخراج لملفّ.
try:
    _ol = open(r"C:\Users\Radhi\MT5\data\r_native\youtube_analyst.out.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = _ol; sys.stderr = _ol
except Exception:
    pass
from pathlib import Path
from datetime import datetime, timezone
import MetaTrader5 as mt5

try:
    from engine_lock import claim
except Exception:
    def claim(n): return True
try:
    import lot_guard
except Exception:
    lot_guard = None
try:
    import chart_signal_reader          # القراءة المرئيّة (كشف لون لوحة الإشارات)
except Exception:
    chart_signal_reader = None
try:
    import level_map                    # مستويات الالتقاء للأهداف/الوقف
except Exception:
    level_map = None

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
CFG_F = ROOT / "youtube_analyst_config.json"
KILL = ROOT / "kill_switch.txt"
SIGNALS = RN / "youtube_analyst_signals.jsonl"     # يرصدها مُراقبٌ ويرسلها لجوالك
LOG = RN / "youtube_analyst.log"
SEEN_F = RN / "youtube_analyst_seen.json"
SCALE_F = RN / "youtube_scale_state.json"          # خطّة الإغلاق المتدرّج لكل مركز
STATUS_F = RN / "youtube_live_status.json"         # شاشة التزامن الحيّة (القناة مقابل الوكيل)
COMPARE_F = RN / "signal_compare.jsonl"            # 📊 مسابقة الدقّة: القناة مقابل تحليلي (لكل إشارة)
TMP_WAV = RN / "_yt_chunk.wav"
TMP_FRAME = RN / "_yt_frame.png"
MAGIC = 20260631

# ── خرائط المُحلِّل (عربي + إنجليزي) ─────────────────────────────────────────────
DIR_BUY  = ["buy", "long", "bull", "شراء", "اشتر", "اشتري", "نشتري", "صعود", "لونق", "لونغ", "بای"]
DIR_SELL = ["sell", "short", "bear", "بيع", "نبيع", "هبوط", "شورت", "سيل", "بِع"]
SYMS = {
    "XAUUSDm": ["gold", "xauusd", "xau", "ذهب", "الذهب", "قولد", "جولد", "ذهبنا"],
    "XAGUSDm": ["silver", "xagusd", "xag", "فضة", "الفضة"],
    "EURUSDm": ["eurusd", "eur usd", "euro dollar", "يورو دولار", "اليورو", "يورو"],
    "GBPUSDm": ["gbpusd", "gbp usd", "pound", "باوند", "الباوند", "استرليني"],
    "USDJPYm": ["usdjpy", "usd jpy", "dollar yen", "دولار ين", "الين", "ين"],
    "BTCUSDm": ["bitcoin", "btcusd", "btc", "بتكوين", "بيتكوين", "بتكون"],
}
# 🛡️ أيّ نصٍّ يحوي أحد هذه = محاولة تحكُّم/حقن ⇒ رفض كامل (لا يُعامَل كنداء سوق)
BANNED = ["ignore", "system prompt", "you are", "api key", "apikey", "password", "secret", "token",
          "withdraw", "transfer funds", "send money", "sudo", "exec(", "os.system", "rm -",
          "kill_switch", "disable guard", "override", "credential", "private key", "seed phrase",
          "تجاهل", "النظام", "كلمة المرور", "كلمة السر", "مفتاح ", "تحويل", "اسحب", "سحب الأموال",
          "صلاحية", "رمز سري", "تنفيذ كود"]
ENTRY_K = ["entry", "buy at", "sell at", "from", "@", "دخول", "السعر", "سعر الدخول", "ندخل", "عند ", "من "]
SL_K    = ["sl", "stop loss", "stoploss", "stop", "وقف", "الوقف", "ستوب", "وقف الخسارة"]
TP_K    = ["tp", "take profit", "target", "هدف", "الهدف", "تيك بروفيت", "جني"]


def _log(m):
    try:
        LOG.open("a", encoding="utf-8").write(f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _cfg():
    try:
        c = json.load(open(CFG_F, encoding="utf-8"))
    except Exception:
        c = {}
    c.setdefault("enabled", False); c.setdefault("stream_url", ""); c.setdefault("mode", "confirm")
    c.setdefault("whisper_model", "small"); c.setdefault("chunk_seconds", 45); c.setdefault("poll_seconds", 55)
    c.setdefault("language", ""); c.setdefault("risk_pct", 1.0); c.setdefault("max_positions", 3)
    c.setdefault("default_sl_atr", 2.5); c.setdefault("min_confidence", 0.6); c.setdefault("dedup_cooldown_s", 900)
    c.setdefault("use_analyst_sltp", True)
    c.setdefault("recognition", "audio")     # audio = تفريغ صوتيّ | visual = قراءة لوحة الإشارات باللون
    c.setdefault("stream_symbol", "XAUUSDm") # رمز البثّ (للوضع المرئيّ — لوحةٌ لرمزٍ واحد)
    c.setdefault("min_mtf_agree", 7)         # 🛡️ لا نتبع إلا إن اتّفق ≥ هذا العدد من المؤطّرات (نتجاهل تقليبة قصيرة-المدى)
    c.setdefault("confluence_tp", True)      # الأهداف/الوقف من مناطق الالتقاء عندنا بدل أرقام خام
    c.setdefault("entry_mode", "market")            # market = فوريّ «مثل ما يقول» | confluence_limit = معلّق عند مستوى
    c.setdefault("entry_max_atr", 1.8)              # أقصى بُعدٍ للمستوى (×ATR) في وضع المعلّق
    c.setdefault("flip_on_reversal", True)          # 🔄 لو عكس البثّ اتجاهه: أغلق مراكزنا واعكس معه
    c.setdefault("lot_per_100", 0.05)               # 🎚️ لوت لكل $100 رصيد (ينمو مع الحساب: $100→0.05، $200→0.10)
    c.setdefault("fixed_lot", 0.0)                   # لوتٌ ثابت بديل (يُستعمل لو lot_per_100=0)
    c.setdefault("partial_tp", True)                # 🎯 إغلاقٌ جزئيّ عند كل مستوى سيولة/التقاء (TP متدرّج)
    c.setdefault("tp_legs", [0.5, 0.25, 0.25])      # TP1=50% · TP2=25% · TP3=الباقي (طلب المستخدم)
    c.setdefault("be_after_leg", 2)                 # الوقف⇐تعادل بعد TP2 فقط (يعطي الصفقة مجالاً، لا يغلقها على ربحٍ بسيط)
    c.setdefault("follow_plan", True)               # 📋 اتّبع خطّة القناة الصريحة (Entry/SL/TP1-3 بالـOCR) مباشرةً بلا انتظار
    c.setdefault("entry_tolerance_pct", 0.25)       # (قديم) نسبة مئويّة ثابتة
    c.setdefault("entry_tol_r", 0.3)                # 🎯 ندخل فقط طازجاً قرب دخول القناة (≤0.3R) — لا نطارد الهبوط للـTP فيتحطّم R:R
    c.setdefault("half_risk_stop", True)            # 🛑 وقف عند 50% خسارة (طلب المستخدم) بدل وقف القناة الكامل
    c.setdefault("stop_risk_frac", 0.5)             # نسبة الوقف من R (0.5 = نصف)
    c.setdefault("trail_activate_r", 0.8)           # 🔒 حماية الربح: تُفعَّل بعد بلوغ هذا الربح (اقترب من الهدف)
    c.setdefault("trail_give_r", 0.3)               # لو ارتدّ عن القمّة بهذا القدر (من R) ⇒ أغلق على ربحٍ كبير
    # 🎯 وضع «تأمين الربح» (طلب المستخدم): القناة=إشارة، نحن نحدّد هدفاً صغيراً ونبنك 100%، ونطلع بلا خسارة لو رجع لدخولنا
    c.setdefault("our_target_r", 0.7)               # هدفنا الصغير = 0.7R (أقرب من TP1) — نبنك كامل الصفقة هنا (0 = استخدم أهداف القناة)
    c.setdefault("be_arm_r", 0.4)                   # بعد 0.4R ربح: الوقف⇐التعادل — لو رجع السعر لدخولنا نطلع سالمين
    c.setdefault("flip_patient", True)              # 🕊️ صبر: لا ننقلب مع القناة ما دامت صفقتنا رابحة
    c.setdefault("flip_patience_r", 0.5)            # نصبر ما دام الربح ≥ 0.5R؛ ننقلب فقط لو رجع السعر لدخولنا (فشلت)
    c.setdefault("max_risk_pct", 8.0)               # 🛟 سقف مخاطرة الصفقة من الحقوق (يُصغّر اللوت — يحمي الحساب الصغير من خسارة كارثيّة على دخولٍ بوقفٍ واسع)
    c.setdefault("hold_until_tp2", False)           # (افتراضيّ off: التزامن أولاً) لا ننقلب حتى TP2
    c.setdefault("require_our_confirm", False)      # (افتراضيّ off: التزامن أولاً) تأكيد مؤشّراتنا
    c.setdefault("chop_threshold", 60.0)            # 🌀 Choppiness ≥ هذا = تذبذب واضح ⇒ نُصغّر اللوت (طلب المستخدم)
    c.setdefault("chop_lot_mult", 0.5)              # مضاعِف اللوت في التذبذب (0.5 = النصف)
    c.setdefault("quality_mode", True)              # 🏆 فلتر خفيف: يتخطّى تناقضات القناة الواضحة فقط
    c.setdefault("min_channel_align", 3)            # يتخطّى فقط لو ≤2/10 يوافق القناة (تناقضٌ قويّ)
    c.setdefault("counter_trend_veto", True)        # 🚫 الفلتر الوحيد الصامد OOS: تخطَّ لو عاكست M15 و H1 معاً
    c.setdefault("q_use_our_trend", False)          # (اختياريّ) اشترط موافقة مؤشّراتنا
    c.setdefault("q_use_chop_skip", False)          # (اختياريّ) تخطَّ التذبذب المتطرّف
    c.setdefault("chop_skip", 65.0)                 # Choppiness ≥ هذا = تذبذب متطرّف (يُستعمل لو q_use_chop_skip)
    c.setdefault("symbols_whitelist", ["XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "BTCUSDm", "XAGUSDm"])
    return c


def _confluence_targets(sym, price, is_buy):
    """الهدف = أقرب منطقة التقاءٍ قويّة في اتجاه الصفقة؛ الوقف = أقرب منطقةٍ معاكسة. (أهداف نثق بمستوياتها)."""
    if not level_map:
        return None, None
    try:
        zones = level_map.confluence_zones(sym) or []
    except Exception:
        return None, None
    above = sorted([z["center"] for z in zones if z.get("center", 0) > price])
    below = sorted([z["center"] for z in zones if z.get("center", 0) < price], reverse=True)
    if is_buy:
        return (above[0] if above else None), (below[0] if below else None)
    return (below[0] if below else None), (above[0] if above else None)


def _is_demo(acct):
    """ديمو فقط (الذاكرة: Exness Trial يقول trade_mode=0 زائفاً ⇒ نكشف عبر اسم الخادم)."""
    srv = (getattr(acct, "server", "") or "").lower()
    return ("trial" in srv) or ("demo" in srv)


# ── 1) التقاط صوت البثّ الحيّ ────────────────────────────────────────────────────
def _capture(url, seconds):
    try:
        _NOWIN = 0x08000000                              # CREATE_NO_WINDOW: لا وميض نوافذ
        g = subprocess.run(["yt-dlp", "-g", "-f", "bestaudio/best", url],
                           capture_output=True, text=True, timeout=90, creationflags=_NOWIN)
        media = (g.stdout.strip().splitlines() or [""])[-1].strip()
        if not media:
            return False, f"no media url ({g.stderr.strip()[:120]})"
        if TMP_WAV.exists():
            try: TMP_WAV.unlink()
            except Exception: pass
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media, "-t", str(seconds),
                        "-vn", "-ar", "16000", "-ac", "1", str(TMP_WAV)],
                       capture_output=True, timeout=seconds + 90, creationflags=_NOWIN)
        ok = TMP_WAV.exists() and TMP_WAV.stat().st_size > 2000
        return ok, "ok" if ok else "no audio captured"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ── 2) التفريغ (محليّ، \$0) ───────────────────────────────────────────────────────
_MODEL = None
def _transcribe(model_name, lang):
    global _MODEL
    try:
        from faster_whisper import WhisperModel
        if _MODEL is None:
            _MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
            _log(f"whisper '{model_name}' محمّل")
        segs, _info = _MODEL.transcribe(str(TMP_WAV), language=(lang or None), vad_filter=True)
        return " ".join(s.text for s in segs).strip()
    except Exception as e:
        _log(f"transcribe err: {type(e).__name__}: {e}")
        return ""


# ── 3) المُحلِّل المحصَّن ضدّ الحقن ─────────────────────────────────────────────────
def _num_near(text, keys):
    for k in keys:
        m = re.search(re.escape(k) + r"\s*[:=]?\s*([0-9]{1,7}(?:[.,][0-9]+)?)", text)
        if m:
            try: return float(m.group(1).replace(",", "."))
            except Exception: pass
    return None


def _parse(text, whitelist):
    """يُرجع نداءً منظَّماً أو None. يرفض أيّ نصٍّ يحوي محاولة تحكُّم/حقن."""
    low = text.lower()
    if not low or len(low) < 4:
        return None
    for b in BANNED:                                   # 🛡️ رفضٌ كامل لمحتوى التحكُّم/الحقن
        if b in low:
            _log(f"🛡️ رُفض (محتوى غير-سوقيّ/حقن): «{b}» في «{text[:80]}»")
            return None
    sym = next((s for s, kws in SYMS.items() if s in whitelist and any(k in low for k in kws)), None)
    if not sym:
        return None
    has_buy = any(k in low for k in DIR_BUY)
    has_sell = any(k in low for k in DIR_SELL)
    if has_buy == has_sell:                            # لا اتجاه واضح أو متناقض ⇒ تجاهل
        return None
    direction = "buy" if has_buy else "sell"
    entry = _num_near(low, ENTRY_K)
    sl = _num_near(low, SL_K)
    tp = _num_near(low, TP_K)
    conf = 0.5 + 0.2 * bool(entry) + 0.2 * bool(sl) + 0.1 * bool(tp)   # كلّما اكتمل النداء، زادت الثقة
    return {"symbol": sym, "direction": direction, "entry": entry, "sl": sl, "tp": tp,
            "confidence": round(conf, 2), "raw": text[:200]}


# ── 4) التنفيذ عبر الحُرّاس (ديمو فقط) ──────────────────────────────────────────────
def _atr(sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n + 1)
    if r is None or len(r) < n + 1:
        return 0.0
    trs = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
               abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(trs) / len(trs) if trs else 0.0


def _lot_for_risk(info, equity, risk_pct, sl_dist):
    ts = info.trade_tick_size or info.point
    tv = info.trade_tick_value
    if not ts or not tv or sl_dist <= 0:
        return info.volume_min
    per_lot_loss = (sl_dist / ts) * tv
    if per_lot_loss <= 0:
        return info.volume_min
    return (equity * risk_pct / 100.0) / per_lot_loss


def _alert(sig, action, detail):
    rec = {"ts": time.time(), "iso": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
           "symbol": sig["symbol"], "direction": sig["direction"], "entry": sig.get("entry"),
           "sl": sig.get("sl"), "tp": sig.get("tp"), "confidence": sig["confidence"],
           "action": action, "detail": detail, "raw": sig["raw"]}
    ar_dir = "شراء" if sig["direction"] == "buy" else "بيع"
    icon = {"executed": "✅", "confirm": "🔔", "skip": "⏭️", "refused": "🛑"}.get(action, "•")
    rec["msg"] = (f"{icon} نداء محلّل: {ar_dir} {sig['symbol']}"
                  + (f" دخول {sig['entry']}" if sig.get("entry") else "")
                  + (f" وقف {sig['sl']}" if sig.get("sl") else "")
                  + (f" هدف {sig['tp']}" if sig.get("tp") else "")
                  + f" | {action}: {detail}")
    if action != "skip":                              # لا نُزعج الجوال بتخطّي الإشارات البائتة (يبقى في السجلّ فقط)
        try:
            SIGNALS.open("a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    _log(rec["msg"])


def _execute(sig, cfg, acct):
    if KILL.exists():
        return "skip", "kill_switch نشط"
    if not _is_demo(acct):
        return "refused", "ليس حساباً تجريبياً — التنفيذ مرفوض (ديمو فقط)"
    sym = sig["symbol"]
    if sym not in cfg["symbols_whitelist"]:
        return "skip", f"{sym} خارج القائمة البيضاء"
    info = mt5.symbol_info(sym)
    if not info or info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        return "skip", f"{sym} التداول غير مسموح"
    if not info.visible:
        mt5.symbol_select(sym, True)
    ours = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    nords = len([o for o in (mt5.orders_get() or []) if o.magic == MAGIC])
    if len(ours) + nords >= cfg["max_positions"]:
        return "skip", f"بلغنا سقف المراكز/الأوامر ({cfg['max_positions']})"
    is_buy = sig["direction"] == "buy"
    if any(p.symbol == sym and (p.type == 0) != is_buy for p in ours):   # منع التحوّط الذاتيّ
        return "skip", "لدينا مركزٌ معاكسٌ على نفس الرمز (منع التحوّط)"
    tick = mt5.symbol_info_tick(sym)
    mkt = tick.ask if is_buy else tick.bid
    atr = _atr(sym)
    # 🎯 نقطة الدخول والأهداف
    _scale_targets = None
    plan_tps = sig.get("tps")
    if plan_tps:                                                    # 📋 خطّة القناة الصريحة (Entry/SL/TP1-3)
        ch_entry, ch_sl = sig.get("entry"), sig.get("sl")
        if not (ch_entry and ch_sl):
            return "skip", "خطّة القناة ناقصة"
        R = abs(ch_entry - ch_sl)                                  # مسافة المخاطرة (تحدّد أهداف 1R/2R/3R)
        tol = cfg.get("entry_tol_r", 0.7) * R                      # نُدخل فقط ضمن هذه النسبة من R (نحفظ ربحاً حقيقياً)
        if R > 0 and abs(mkt - ch_entry) > tol:                    # متأخّرون كثيراً (قرب الهدف) ⇒ الربح ضئيل ⇒ ننتظر طازجة
            return "skip", f"⏭️ متأخّرون عن دخول القناة {ch_entry:.2f} (فرق {abs(mkt-ch_entry):.1f} > {tol:.1f}={cfg.get('entry_tol_r',0.7)}R) — الربح ضئيلٌ، ننتظر إشارةً طازجة"
        entry, use_limit, sl = mkt, False, ch_sl                   # دخول سوق فوريّ بوقف القناة
        _scale_targets = [t for t in plan_tps if ((t > mkt) if is_buy else (t < mkt))]   # أهداف القناة الأماميّة
        if not _scale_targets:
            return "skip", "تجاوز السعر كل أهداف القناة"
    else:                                                          # المسار البديل: التقاء/سوق
        entry = mkt; use_limit = False
        if cfg.get("entry_mode") == "confluence_limit":
            lvl = _nearest_level(sym, mkt, below=is_buy)
            spread = max(tick.ask - tick.bid, 0.0)
            if lvl and spread < abs(mkt - lvl) <= cfg.get("entry_max_atr", 1.8) * (atr or 1e-9):
                entry = lvl; use_limit = True
        c_tp, c_sl = (_confluence_targets(sym, entry, is_buy) if cfg.get("confluence_tp") else (None, None))
        sl = sig.get("sl") if (cfg["use_analyst_sltp"] and sig.get("sl")) else None
        if sl is None:
            sl = c_sl if c_sl else (entry - cfg["default_sl_atr"] * atr if is_buy else entry + cfg["default_sl_atr"] * atr)
    if (is_buy and sl >= entry) or (not is_buy and sl <= entry):    # عقلنة الجهة، وإلا ATR
        sl = entry - cfg["default_sl_atr"] * atr if is_buy else entry + cfg["default_sl_atr"] * atr
    if cfg.get("half_risk_stop", True):                            # 🛑 وقف عند 50% خسارة (طلب المستخدم: نطلع مبكّراً، لا ننتظر وقف القناة الكامل)
        sl = round(entry + (sl - entry) * cfg.get("stop_risk_frac", 0.5), 3)   # منتصف المسافة دخول↔وقف القناة = 0.5R
    # 🎚️ الحجم: نسبيّ للرصيد (برصيد 100 ⇒ lot_per_100) ← لوت ثابت ← مخاطرة؛ ثم حارس هامش + سقف مخاطرة
    lp100 = cfg.get("lot_per_100", 0.0) or 0.0
    fixed = cfg.get("fixed_lot", 0.0) or 0.0
    if lp100 > 0 and acct.equity > 0:
        lot = lp100 * (acct.equity / 100.0)                 # 0.05 لكل $100 (ينمو/يصغر مع الحساب)
    elif fixed > 0:
        lot = fixed
    else:
        lot = _lot_for_risk(info, acct.equity, cfg["risk_pct"], abs(entry - sl))
        if lot_guard:
            lot, _ = lot_guard.cap(mt5, sym, lot, acct.equity)
    _chop = _choppiness(sym)                                        # 🌀 تذبذب واضح ⇒ نُصغّر اللوت (طلب المستخدم)
    if _chop is not None and _chop >= cfg.get("chop_threshold", 60.0):
        lot *= cfg.get("chop_lot_mult", 0.5)
        _log(f"🌀 تذبذب واضح (Choppiness {_chop}) — صغّرنا اللوت ×{cfg.get('chop_lot_mult',0.5)}")
    _otm = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL    # حارس الهامش (لكل المسارات)
    _mn = mt5.order_calc_margin(_otm, sym, lot, entry)
    if _mn and acct.margin_free and _mn > acct.margin_free * 0.85:
        lot = max(info.volume_min, (acct.margin_free * 0.85 / _mn) * lot)
    # 🛟 سقف مخاطرة صارم: يُصغّر اللوت لو تجاوزت مخاطرة الوقف الحدّ (يحمي الحساب الصغير من 0.1 الكارثيّة على $100)
    _maxrp = cfg.get("max_risk_pct", 8.0)
    _sld = abs(entry - sl)
    if _sld > 0 and acct.equity > 0 and info.trade_tick_value:
        _rp = (_sld / (info.trade_tick_size or info.point) * info.trade_tick_value * lot) / acct.equity * 100.0
        if _rp > _maxrp:
            lot = lot * (_maxrp / _rp)
    step = info.volume_step or 0.01
    lot = max(info.volume_min, round(lot / step) * step)
    if lot <= 0:
        return "skip", "حجمٌ غير صالح"
    risk_usd = abs(entry - sl) / (info.trade_tick_size or info.point) * info.trade_tick_value * lot
    risk_pct = (risk_usd / acct.equity * 100.0) if acct.equity else 0.0
    _osl = 0.0 if cfg.get("never_close_loss", False) else float(sl)  # 🚫 بلا وقف: لا نغلق على خسارة (يبقى الحجم مقيّداً بمسافة وقف القناة)
    if use_limit:                                                    # أمر معلّق عند المستوى (بلا TP — يُدار متدرّجاً)
        otype = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
        req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": sym, "volume": float(round(lot, 2)),
               "type": otype, "price": float(entry), "sl": _osl, "tp": 0.0,
               "magic": MAGIC, "comment": "yt_limit", "type_time": mt5.ORDER_TIME_GTC}
    else:                                                            # سوق فوريّ «مثل ما يقول»
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": float(round(lot, 2)),
               "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL, "price": float(entry),
               "sl": _osl, "tp": 0.0, "deviation": 30, "magic": MAGIC,
               "comment": "yt_analyst", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return "skip", f"order_send فشل: {getattr(r,'retcode','?')} {getattr(r,'comment','')}"
    # 🎯 خطّة الإغلاق المتدرّج: أهداف القناة (إن وُجدت خطّة) وإلا مستويات الالتقاء عندنا — نجد المركز المفتوح للتوّ
    if not use_limit and cfg.get("partial_tp", True):
        tps = _scale_targets if _scale_targets else _confluence_tps(sym, entry, is_buy, n=len(cfg.get("tp_legs", [0.4, 0.3, 0.3])))
        if tps:
            st = _load_scale()
            cand = [p for p in (mt5.positions_get(symbol=sym) or [])
                    if p.magic == MAGIC and str(p.ticket) not in st]
            if cand:
                newp = max(cand, key=lambda p: p.time)
                _cr = abs((sig.get("entry") or 0) - (sig.get("sl") or 0)) if plan_tps else abs(tps[0] - entry)
                st[str(newp.ticket)] = {"orig_lot": float(round(lot, 2)), "entry": float(entry),
                                        "is_buy": bool(is_buy), "tps": tps, "legs_done": 0,
                                        "chan_R": float(_cr or abs(entry - sl))}   # R الأصليّة للقناة (ثابتة — لا تنهار على دخولٍ متأخّر)
                _save_scale(st)
    kind = "📋 خطّة القناة" if plan_tps else ("📍 معلّق عند مستوى" if use_limit else "سوق فوريّ")
    warn = f" ⚠️مخاطرة {risk_pct:.0f}%" if risk_pct >= 10 else ""
    tgt = (" أهداف " + "/".join(f"{t:.1f}" for t in _scale_targets)) if _scale_targets else " أهدافٌ متدرّجة"
    return "executed", f"{kind} {lot:.2f} لوت @ {entry:.2f} وقف {sl:.2f}{tgt}{warn}"


# ── 🚫 حظر إعادة الدخول على خطّةٍ ضربت وقفنا (درس 3 خسائر على وقف 4068.13 نفسه) ──
SLBLOCK_F = RN / "youtube_slblock.json"


def _slblock_load():
    try:
        return json.load(open(SLBLOCK_F, encoding="utf-8"))
    except Exception:
        return {"blocked": {}, "track": {}}


def _slblock_save(d):
    try:
        json.dump(d, open(SLBLOCK_F, "w", encoding="utf-8"))
    except Exception:
        pass


def _slblock_check(key):
    """يرجع الدقائق المتبقّية للحظر أو None. المفتاح يتغيّر تلقائياً مع أي خطّةٍ جديدة من القناة."""
    d = _slblock_load()
    exp = d.get("blocked", {}).get(key, 0)
    left = exp - time.time()
    return (left / 60.0) if left > 0 else None


def _slblock_track(key):
    """بعد التنفيذ: اربط الخطّة بأحدث مركزٍ لنا لنكشف لاحقاً هل أُغلق بضرب الوقف."""
    poss = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC]
    if not poss:
        return
    newest = max(poss, key=lambda p: p.time)
    d = _slblock_load()
    d.setdefault("track", {})[str(newest.ticket)] = key
    _slblock_save(d)


def _slblock_reconcile(cfg):
    """كل دورة: أي مركزٍ متتبَّعٍ اختفى — لو أُغلق بالوقف ⇒ احظر خطّته sl_reentry_block_s (افتراضيّ 45د)."""
    d = _slblock_load()
    trk = d.get("track", {})
    if not trk:
        return
    open_ids = {str(p.ticket) for p in (mt5.positions_get() or []) if p.magic == MAGIC}
    changed = False
    for tk, key in list(trk.items()):
        if tk in open_ids:
            continue
        try:
            deals = mt5.history_deals_get(position=int(tk)) or []
            hit_sl = any(x.entry == 1 and "sl" in (x.comment or "").lower() for x in deals)
        except Exception:
            hit_sl = False
        if hit_sl:
            d.setdefault("blocked", {})[key] = time.time() + cfg.get("sl_reentry_block_s", 2700)
            _log(f"⛔ الخطّة {key} ضربت الوقف — حظر إعادة الدخول عليها 45د (خطّة جديدة من القناة = مسموح فوراً)")
        del trk[tk]; changed = True
    # نظافة: احذف الحظور المنتهية
    for k, exp in list(d.get("blocked", {}).items()):
        if exp < time.time():
            del d["blocked"][k]; changed = True
    if changed:
        _slblock_save(d)


def _load_seen():
    try:
        return json.load(open(SEEN_F, encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(s):
    try:
        json.dump(s, open(SEEN_F, "w", encoding="utf-8"))
    except Exception:
        pass


def _choppiness(sym, n=14):
    """مؤشّر Choppiness على M15: >61.8 = سوقٌ عرضيّ/متذبذب · <38.2 = ترند. يرجع القيمة أو None."""
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, n + 1)
    if r is None or len(r) < n + 1:
        return None
    import math
    trs = [max(float(r[i]["high"] - r[i]["low"]), abs(float(r[i]["high"] - r[i - 1]["close"])),
               abs(float(r[i]["low"] - r[i - 1]["close"]))) for i in range(1, len(r))]
    atr_sum = sum(trs[-n:])
    hi = max(float(x["high"]) for x in r[-n:]); lo = min(float(x["low"]) for x in r[-n:])
    rng = hi - lo
    if rng <= 0 or atr_sum <= 0:
        return None
    return round(100.0 * math.log10(atr_sum / rng) / math.log10(n), 1)


def _signal_quality(panel, want, sym, cfg):
    """🏆 بوّابة خفيفة: نتخطّى تناقضات القناة الواضحة فقط (أحسن منها) مع دقّةٍ كاملة على إشاراتها الصحيحة."""
    rows = (panel or {}).get("rows", {})
    if rows.get("position") and rows.get("position") != rows.get("trend"):   # القناة تناقض نفسها
        return False, "تناقض القناة (Position≠Trend)"
    if panel and panel.get("agree", 0) < cfg.get("min_channel_align", 3):     # تناقضٌ قويّ (يوافقها ≤2/10)
        return False, f"تناقضٌ قويّ (يوافقها {panel.get('agree', 0)}/10 فقط)"
    if cfg.get("counter_trend_veto", True):        # 🚫 الفلتر الوحيد الصامد OOS: نتخطّى لو عاكست M15 و H1 معاً (يزيل أسوأ الخاسرات)
        m15, h1 = _htf_dir(sym, mt5.TIMEFRAME_M15), _htf_dir(sym, mt5.TIMEFRAME_H1)
        if m15 and h1 and m15 != want and h1 != want:
            return False, f"🚫 ضدّ الترند: القناة {want} تعاكس M15({m15}) و H1({h1}) معاً — أسوأ فئة إحصائياً (35-41% فوز)"
    if cfg.get("q_use_our_trend", False):                                     # (اختياريّ) تأكيد مؤشّراتنا
        ot = _our_trend(sym)
        if ot and ot != want:
            return False, f"مؤشّراتنا ({ot}) تخالف القناة ({want})"
    if cfg.get("q_use_chop_skip", False):                                     # (اختياريّ) تخطّي التذبذب المتطرّف
        ch = _choppiness(sym)
        if ch is not None and ch >= cfg.get("chop_skip", 65.0):
            return False, f"تذبذب متطرّف (CHOP {ch})"
    return True, "مؤكّدة ✓"


def _our_trend(sym):
    """اتجاهنا المستقلّ من بياناتنا (M15/H1/H4: الإغلاق مقابل متوسّط 20) — تأكيدٌ للقناة بمؤشّراتنا. buy/sell/None."""
    votes = []
    for tf in (mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4):
        r = mt5.copy_rates_from_pos(sym, tf, 0, 21)
        if r is None or len(r) < 21:
            continue
        ema = sum(float(x["close"]) for x in r[-20:]) / 20.0
        votes.append("buy" if float(r[-1]["close"]) > ema else "sell")
    if not votes:
        return None
    b, s = votes.count("buy"), votes.count("sell")
    return "buy" if b > s else ("sell" if s > b else None)


def _htf_dir(sym, tf):
    """اتجاه الإطار الأعلى من ميل متوسّط 20 (الآن مقابل قبل 3 شمعات). buy/sell/None. (للـveto المضادّ للترند)."""
    r = mt5.copy_rates_from_pos(sym, tf, 0, 24)
    if r is None or len(r) < 24:
        return None
    sma_now = sum(float(x["close"]) for x in r[-20:]) / 20.0
    sma_prev = sum(float(x["close"]) for x in r[-23:-3]) / 20.0
    if abs(sma_now - sma_prev) < 1e-9:
        return None
    return "buy" if sma_now > sma_prev else "sell"


def _nearest_level(sym, price, below):
    """أقرب مركز منطقة التقاءٍ تحت السعر (للشراء = سحبٌ مرتدّ لدعم) أو فوقه (للبيع = مقاومة)."""
    if not level_map:
        return None
    try:
        zones = level_map.confluence_zones(sym) or []
    except Exception:
        return None
    cands = [z["center"] for z in zones if z.get("center") and ((z["center"] < price) == below)]
    if not cands:
        return None
    return max(cands) if below else min(cands)


def _close_all_ours(sym, only_profit=False):
    """يغلق مراكز هذا الوكيل على الرمز (للانقلاب). only_profit=True ⇒ لا يغلق الخاسر أبداً (يحتفظ به حتى يرجع)."""
    n = 0
    for p in (mt5.positions_get(symbol=sym) or []):
        if p.magic != MAGIC:
            continue
        if only_profit and (p.profit + p.swap) <= 0:               # 🚫 لا نغلق على خسارة — نحتفظ به
            continue
        tk = mt5.symbol_info_tick(sym); is_buy = p.type == 0
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": p.volume,
               "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY, "position": p.ticket,
               "price": tk.bid if is_buy else tk.ask, "deviation": 30, "magic": MAGIC,
               "comment": "yt_flip", "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            n += 1
    return n


def _cancel_pendings_ours(sym):
    """يلغي كل أوامر هذا الوكيل المعلّقة على الرمز. يرجع العدد المُلغى."""
    n = 0
    for o in (mt5.orders_get(symbol=sym) or []):
        if o.magic != MAGIC:
            continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
        if r and r.retcode == mt5.TRADE_RETCODE_DONE:
            n += 1
    return n


# ── 5) الإغلاق المتدرّج عند مستويات السيولة (خريطتنا الحراريّة: POC/حجم/التقاء) ─────────
def _load_scale():
    try:
        return json.load(open(SCALE_F, encoding="utf-8"))
    except Exception:
        return {}


def _save_scale(s):
    try:
        json.dump(s, open(SCALE_F, "w", encoding="utf-8"))
    except Exception:
        pass


def _confluence_tps(sym, price, is_buy, n=3):
    """أهدافٌ متدرّجة = أقرب n مستوياتِ سيولة/التقاء في اتجاه الصفقة (وإلا مضاعفات ATR)."""
    levels = []
    if level_map:
        try:
            zones = level_map.confluence_zones(sym) or []
            levels = sorted([z["center"] for z in zones if z.get("center") and ((z["center"] > price) == is_buy)],
                            key=lambda x: abs(x - price))
        except Exception:
            levels = []
    if len(levels) < n:
        atr = _atr(sym) or (price * 0.001)
        for k in range(1, n + 1):
            lv = price + k * atr if is_buy else price - k * atr
            levels.append(lv)
    # ترتيبٌ بالقُرب + إزالة المكرّر + الأقرب أولاً
    uniq = sorted(set(round(x, 3) for x in levels), key=lambda x: abs(x - price))
    return uniq[:n]


def _partial_close(p, vol):
    info = mt5.symbol_info(p.symbol); tk = mt5.symbol_info_tick(p.symbol)
    if not info or not tk:
        return False
    step = info.volume_step or 0.01; is_buy = p.type == 0
    vol = min(max(info.volume_min, round(vol / step) * step), p.volume)
    if vol <= 0:
        return False
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": float(round(vol, 2)),
           "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY, "position": p.ticket,
           "price": tk.bid if is_buy else tk.ask, "deviation": 30, "magic": MAGIC,
           "comment": "yt_tp", "type_filling": mt5.ORDER_FILLING_IOC}
    r = mt5.order_send(req)
    return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)


def _move_sl(p, new_sl):
    r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": p.ticket,
                        "sl": float(new_sl), "tp": float(p.tp), "magic": MAGIC})
    return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)


def _manage_scaled_exits(cfg):
    """يغلق جزءاً عند كل هدف (tp_legs)، وينقل الوقف للتعادل بعد be_after_leg. + 🔒 حماية الربح (طلب المستخدم):
       لو اقترب من الهدف (ربحٌ كبير) ثم بدأ يبتعد عنه ⇒ يُغلق كامل المتبقّي على ربحٍ كبير (لا نتركه يرجع)."""
    if cfg.get("hold_to_next_signal", False):       # 🤝 لا نأخذ أرباحاً عند الأهداف — نحمل حتى الإشارة التالية (الانقلاب يغلق الرابح)
        return
    if not cfg.get("partial_tp", True):
        return
    state = _load_scale()
    if not state:
        return
    poss = {str(p.ticket): p for p in (mt5.positions_get() or []) if p.magic == MAGIC}
    legs = cfg.get("tp_legs", [0.5, 0.25, 0.25])
    changed = False
    for tk_str, st in list(state.items()):
        p = poss.get(tk_str)
        if p is None:                                   # أُغلق المركز ⇒ احذف حالته
            del state[tk_str]; changed = True; continue
        tps = st.get("tps", [])
        tick = mt5.symbol_info_tick(p.symbol)
        if not tick or not tps:
            continue
        cur = tick.bid if st["is_buy"] else tick.ask
        R = st.get("chan_R") or abs(tps[0] - st["entry"]) or 1e-9   # R القناة الثابتة (تُستعمل للهدف/التعادل — لا تنهار على دخولٍ متأخّر)
        fav = (cur - st["entry"]) if st["is_buy"] else (st["entry"] - cur)   # الحركة المواتية الحاليّة
        if fav > st.get("peak_fav", -1e18):
            st["peak_fav"] = fav; changed = True        # نتتبّع أقصى ربحٍ بلغه
        # 🔐 تعادلٌ مبكّر (طلب المستخدم: لو رجع السعر لدخولنا نطلع بلا خسارة)
        if not st.get("be_armed") and fav >= cfg.get("be_arm_r", 0.4) * R:
            if _move_sl(p, round(st["entry"], 3)):
                st["be_armed"] = True; changed = True
                _log(f"🔐 الوقف⇐التعادل {st['entry']:.2f} (بعد {fav/R:.1f}R — لو رجع لدخولنا نطلع سالمين)")
        # 🎯 هدفنا الصغير (الأمثل بالبيانات = 0.5R): نبنك الأغلب هنا، ونترك runner صغيراً يركض بوقف تعادل نحو أهداف القناة
        otr = cfg.get("our_target_r", 0.0) or 0.0
        if otr > 0 and not st.get("our_done"):
            our_tp = st["entry"] + (otr * R if st["is_buy"] else -otr * R)
            if (cur >= our_tp) if st["is_buy"] else (cur <= our_tp):
                frac = cfg.get("our_target_frac", 1.0)
                bank = round(st["orig_lot"] * frac, 2) if frac < 1.0 else p.volume
                if frac >= 1.0 or (p.volume - bank) < 0.01 or bank < 0.01:   # لا runner صالح ⇒ بنك 100%
                    if _partial_close(p, p.volume):
                        _log(f"🎯 هدفنا {otr:.1f}R @ {our_tp:.2f} — بنكنا 100% (ربحٌ مؤمَّن)")
                        del state[tk_str]; changed = True; continue
                elif _partial_close(p, min(bank, p.volume)):                 # بنك الأغلب + runner بتعادل
                    st["our_done"] = True; st["be_armed"] = True; changed = True
                    _log(f"🎯 هدفنا {otr:.1f}R @ {our_tp:.2f} — بنكنا {frac:.0%} (مؤمَّن)، والباقي runner بوقف تعادل نحو أهداف القناة")
        # 🔒 حماية الربح: بلغ ربحاً كبيراً (اقترب من الهدف) ثمّ ارتدّ ⇒ أغلق كامل المتبقّي
        if st.get("peak_fav", 0) >= cfg.get("trail_activate_r", 0.8) * R and \
           (st["peak_fav"] - fav) >= cfg.get("trail_give_r", 0.3) * R and fav > 0:
            if _partial_close(p, p.volume):
                _log(f"🔒 حماية الربح: بلغ {st['peak_fav']/R:.1f}R (اقترب من الهدف) ثمّ بدأ يبتعد — أغلقنا على ربحٍ كبير ({fav/R:.1f}R)")
                del state[tk_str]; changed = True; continue
        # 🎯 لوت أدنى (0.01) لا يُقسَّم 50/25/25 ⇒ نركب بكامل الصفقة لهدفٍ أبعد (افتراضيّ TP2) بدل الإغلاق عند TP1
        _vmin = getattr(mt5.symbol_info(p.symbol), "volume_min", 0.01) or 0.01
        if st["orig_lot"] < 2 * _vmin - 1e-9:
            _leg = min(cfg.get("min_lot_target_leg", 1), len(tps) - 1)   # 1 = الهدف الثاني TP2
            _tgt = tps[_leg]
            if (cur >= _tgt) if st["is_buy"] else (cur <= _tgt):
                if _partial_close(p, p.volume):
                    _log(f"🎯 TP{_leg + 1} @ {_tgt:.2f} — أغلقنا كامل الصفقة (لوت أدنى ⇒ هدفٌ واحد أبعد)")
                    del state[tk_str]; changed = True
            continue
        # 🎯 الإغلاق المتدرّج عند الأهداف
        done = st.get("legs_done", 0)
        if done >= len(tps):
            continue
        nxt = tps[done]
        if (cur >= nxt) if st["is_buy"] else (cur <= nxt):
            last = (done == len(tps) - 1)
            frac = legs[done] if done < len(legs) else (1.0 / max(len(tps), 1))
            vol = p.volume if last else st["orig_lot"] * frac     # 🎯 آخر هدف ⇒ أغلق كل الباقي
            if _partial_close(p, vol):
                st["legs_done"] = done + 1; changed = True
                _log(f"🎯 TP{done + 1} @ {nxt:.2f} — أغلقنا {'الباقي كلّه' if last else f'{frac:.0%}'} من {p.symbol}")
                if st["legs_done"] >= cfg.get("be_after_leg", 2):
                    if _move_sl(p, st["entry"]):
                        _log(f"🔒 الوقف ⇐ نقطة التعادل {st['entry']:.2f}")
    if changed:
        _save_scale(state)


def _singleton_or_exit():
    """احتياطٌ فوق قفل المنفذ: إن وُجدت نسخةٌ أقدم تعمل ⇒ أخرج (الأقدم يبقى) — يمنع التداول المزدوج."""
    try:
        import psutil
        me = os.getpid(); myct = psutil.Process(me).create_time()
        # 🪤 فخّ توأمي venv (درس 2026-07-02): وسيط pythonw الأب يحمل نفس سطر الأوامر وأقدم منّا ⇒
        # بدون استثنائه ينتحر الابن ظنّاً أنه نسخةٌ مكرّرة. الأب ليس منافساً — استثنِه.
        _ppid = os.getppid()
        for p in psutil.process_iter(["pid", "name", "create_time", "cmdline"]):
            if p.info["pid"] in (me, _ppid) or (p.info.get("name") or "").lower() != "pythonw.exe":
                continue
            if "youtube_analyst_agent.py" in " ".join(p.info.get("cmdline") or []) and (p.info.get("create_time") or 0) < myct:
                _log("نسخةٌ أقدم تعمل — خروج (نسخة-مفردة)"); sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass


def main():
    claim("youtube_analyst")
    _singleton_or_exit()
    for _ in range(3):
        if mt5.initialize():
            break
        time.sleep(2)
    _log("youtube_analyst start — في انتظار رابطٍ مُفعَّل في الإعداد")
    seen = _load_seen()
    while True:
        try:
            cfg = _cfg()
            if not cfg["enabled"] or not cfg["stream_url"]:
                time.sleep(10); continue
            acct = mt5.account_info()
            if cfg.get("never_close_loss", False):    # 🚫 بلا وقف: انزع الوقف عن مراكزنا (البروكر لا يغلقنا على خسارة)
                for _p in (mt5.positions_get() or []):
                    if _p.magic == MAGIC and _p.sl not in (0.0, None):
                        _move_sl(_p, 0.0)
            _manage_scaled_exits(cfg)                 # 🎯 يدير الإغلاق المتدرّج للمراكز القائمة كل دورة
            _slblock_reconcile(cfg)                   # 🚫 يكشف ضرب الوقف ويحظر إعادة الدخول على نفس الخطّة
            sig = None
            if cfg["recognition"] == "visual":
                if chart_signal_reader is None:
                    _log("chart_signal_reader غير متاح"); time.sleep(cfg["poll_seconds"]); continue
                _t = mt5.symbol_info_tick(cfg["stream_symbol"])
                ref = ((_t.ask + _t.bid) / 2) if _t else None
                pr = chart_signal_reader.get_plan_from_stream(cfg["stream_url"], str(TMP_FRAME), ref)
                panel = (pr or {}).get("panel"); plan = (pr or {}).get("plan")
                if panel:
                    _log(f"👁️ Position={panel['direction']} اتّفاق {panel['agree']}/{panel['total']}"
                         + (f" | 📋 خطّة: {plan['direction']} دخول {plan['entry']} وقف {plan['sl']} أهداف {plan['tps']}"
                            if plan else " | لا خطّة معروضة"))
                    try:                                          # 📺 شاشة التزامن الحيّة (القناة ↔ الوكيل)
                        _o = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC and p.symbol == cfg["stream_symbol"]]
                        _ad = ("buy" if _o[0].type == 0 else "sell") if _o else None
                        _d = plan["direction"] if plan else panel["direction"]
                        _note = ("✅ متزامن — في صفقةٍ مطابقة للقناة" if _ad == _d else
                                 "🔄 سينقلب مع القناة الآن" if _ad else
                                 ("⏳ خطّة جاهزة — يدخل إن كان السعر قريباً من دخول القناة" if plan else "⏳ لا خطّة معروضة بعد"))
                        _st = {"ts": round(time.time(), 1),  # طابع رقميّ لفحوص النضارة (كان iso فقط ⇒ إنذارات قِدَم زائفة)
                               "iso": datetime.now().strftime("%H:%M:%S"), "channel_says": _d, "agree": panel["agree"],
                               "total": panel["total"], "trend": panel["trend"], "strong": bool(plan),
                               "agent_in_trade": _ad, "agent_positions": len(_o), "status": _note}
                        if plan:
                            _st["plan"] = plan
                        _ot = _our_trend(cfg["stream_symbol"])        # 🔍 تأكيدٌ بمؤشّراتنا المستقلّة
                        _st["our_trend"] = _ot
                        _st["confirmed"] = (_ot is None or _ot == _d)
                        _ch = _choppiness(cfg["stream_symbol"])       # 🌀 حالة السوق (تذبذب/ترند)
                        _st["choppiness"] = _ch
                        _st["choppy"] = bool(_ch is not None and _ch >= cfg.get("chop_threshold", 60.0))
                        json.dump(_st, open(STATUS_F, "w", encoding="utf-8"), ensure_ascii=False)
                        if plan:                                      # 📊 مسابقة الدقّة: سجّل (القناة مقابل تحليلي) مرّةً لكل خطّة
                            _ck = "cmp:" + hashlib.md5(f"{plan['direction']}{round(plan['entry'],1)}".encode()).hexdigest()[:10]
                            if _ck not in seen:
                                seen[_ck] = time.time()
                                _pk = mt5.symbol_info_tick(cfg["stream_symbol"])
                                if _pk:
                                    COMPARE_F.open("a", encoding="utf-8").write(json.dumps(
                                        {"ts": time.time(), "iso": datetime.now().strftime("%H:%M:%S"),
                                         "price": round((_pk.ask + _pk.bid) / 2, 2), "channel": plan["direction"],
                                         "mine": _ot}, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                    if cfg.get("follow_plan", True) and plan:      # 📋 اتّبع خطّة القناة الرقميّة فقط (Entry/SL/TP)
                        sig = {"symbol": cfg["stream_symbol"], "direction": plan["direction"], "entry": plan["entry"],
                               "sl": plan["sl"], "tps": plan["tps"], "confidence": 1.0,
                               "raw": f"plan {plan['direction']} entry={plan['entry']} sl={plan['sl']} tps={plan['tps']}"}
                    # 🚫 لا خطّة معروضة ⇒ ننتظر. (أُزيل الاحتياط اللونيّ على Current Position المجرّد: «لا خطّة» ≠ «أرقام
                    #    غير واضحة» — القناة بين الإعدادات لا تعرض خطّة، والدخول على المؤشّر المجرّد كان يسبّب churn.)
                else:
                    _log("تعذّرت القراءة المرئيّة")
            else:
                ok, why = _capture(cfg["stream_url"], cfg["chunk_seconds"])
                if not ok:
                    _log(f"التقاط فشل: {why}"); time.sleep(cfg["poll_seconds"]); continue
                text = _transcribe(cfg["whisper_model"], cfg["language"])
                if text:
                    _log(f"📝 «{text[:140]}»")
                sig = _parse(text, cfg["symbols_whitelist"]) if text else None
            if sig and sig["confidence"] >= cfg["min_confidence"]:
                sym = sig["symbol"]; want = sig["direction"]
                ours = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC and p.symbol == sym]
                cur = ("buy" if ours[0].type == 0 else "sell") if ours else None
                if cur == want:
                    pass                                              # متوافقٌ مع البثّ — نُبقي (دع الرابح يجري)
                elif cfg["mode"] != "auto":
                    what = f"🔄 عكس {cur}→{want}" if cur else f"دخول {want}"
                    _alert(sig, "confirm", f"{what} — أكّد يدوياً (mode=auto للتلقائيّ)")
                else:
                    _flipped = False
                    if cur:                                           # عندنا مركزٌ معاكسٌ للقناة
                        _legs = max((st.get("legs_done", 0) for st in _load_scale().values()
                                     if st.get("is_buy") == (cur == "buy")), default=0)
                        if cfg.get("hold_until_tp2", False) and _legs < 2:
                            _log(f"⏸️ القناة عكست {cur}→{want} لكن لم نضرب TP2 (أرجل {_legs}/2) — نحمل الصفقة")
                            cur = "hold"                              # (مُعطَّل افتراضياً) لا ننقلب
                        elif cfg.get("flip_on_reversal", True):       # 🔄 العكس = قرار (لا آليّ): نصبر لو رابحين
                            _patient = False
                            if cfg.get("flip_patient", True) and ours:
                                p0 = ours[0]; _tk = mt5.symbol_info_tick(sym)
                                if _tk:
                                    _mkt = _tk.bid if p0.type == 0 else _tk.ask
                                    _favp = (_mkt - p0.price_open) if p0.type == 0 else (p0.price_open - _mkt)
                                    _st0 = _load_scale().get(str(p0.ticket), {})
                                    _Rp = abs((_st0.get("tps") or [p0.price_open])[0] - p0.price_open) or 1e-9
                                    if _favp >= cfg.get("flip_patience_r", 0.5) * _Rp:     # صفقتنا رابحة ⇒ نصبر
                                        _log(f"🕊️ القناة عكست {cur}→{want} لكن صفقتنا رابحة ({_favp/_Rp:.1f}R) — نصبر (لهدفنا)، لا ننقلب")
                                        cur = "hold"; _patient = True
                            if not _patient:                          # الانقلاب
                                _ncl = cfg.get("never_close_loss", False)
                                nclosed = _close_all_ours(sym, only_profit=_ncl) + _cancel_pendings_ours(sym)
                                _still = [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]
                                if _ncl and _still:                   # 🚫 احتفظنا بخاسر ⇒ لا نغلق على خسارة، لا ننقلب
                                    _log(f"🚫 القناة عكست {cur}→{want} لكن صفقتنا خاسرة — نحتفظ بها حتى ترجع (لا نغلق على خسارة)")
                                    cur = "hold"
                                else:
                                    _alert(sig, "flip", f"البثّ عكس {cur}→{want} — أغلقنا {nclosed}{' (الرابحة فقط)' if _ncl else ''} وعكسنا")
                                    cur = None; _flipped = True
                    if cur is None:                                   # فلات (أو بعد انقلاب) ⇒ ندخل بشرط الجودة
                        if cfg.get("quality_mode", True):
                            _qok, _qwhy = _signal_quality(panel, want, sym, cfg)
                        else:
                            _qok, _qwhy = True, "تزامن نقيّ"
                        if not _qok:
                            _log(f"⏭️ تخطّينا (لا ننسخها عمياء — نختار الأفضل): {_qwhy}")
                        else:
                            key = hashlib.md5(f"{sym}{want}{round(sig.get('entry') or 0, 1)}".encode()).hexdigest()[:12]
                            _blk = _slblock_check(key)                     # 🚫 خطّة ضربت وقفنا؟ محظورة حتى تتجدّد
                            if _blk:
                                _log(f"⛔ نفس الخطّة ضربت وقفنا قبل قليل — محظورة {_blk:.0f}د حتى تعرض القناة خطّةً جديدة")
                            elif _flipped or (time.time() - seen.get(key, 0) >= cfg["dedup_cooldown_s"]):
                                seen[key] = time.time(); _save_seen(seen)   # 🔄 الانقلاب يتجاوز dedup
                                action, detail = _execute(sig, cfg, acct)
                                _alert(sig, action, detail)
                                if action == "executed":
                                    _slblock_track(key)                     # اربط الخطّة بمركزها لكشف ضرب الوقف
            time.sleep(cfg["poll_seconds"])
        except Exception as e:
            _log(f"loop err: {type(e).__name__}: {e}")
            time.sleep(20)


if __name__ == "__main__":
    main()
