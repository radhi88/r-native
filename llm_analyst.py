"""llm_analyst.py — the market brain the agents OBEY: synthesizes ALL signals per symbol
(genome quality + news + intermarket + volatility regime) into a single DIRECTIVE, overlaid with
a Claude-written macro read. Its primary job is DISCIPLINE — it only greenlights a symbol when
MULTIPLE independent signals agree, so the trader stops machine-gunning low-conviction setups
(the over-trading that bleeds the account). The real edge is fewer, higher-conviction trades.

Tiering (honest about cost): the continuous engine is a LOCAL $0 synthesis (always runs). A real
Claude macro overlay is read from market_directive_macro.json (written by the Claude layer / this
session); when API credits exist it can be regenerated autonomously, else the macro is curated.

Writes:  data/r_native/market_directive.json   (multi_trader + agents read & obey this)
Read-only. Windowless.  Run:  python llm_analyst.py --loop
"""
from __future__ import annotations
import argparse, json, time, glob
from datetime import datetime, timezone
from pathlib import Path

V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
GENO = V2 / "genomes"
OUT = RN / "market_directive.json"
MACRO = RN / "market_directive_macro.json"   # ← Claude-written macro read (regime/risk)
INTERVAL = 90


def _load(p, d=None):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d


def synthesize() -> dict:
    # 🕒 طزاجة الإشارات: الديركتيف الناتج تطيعه البوتات كبوابة تحيّز — فلا نُغذّيه بإشارة بايتة لو
    # مات كاتبها صامتاً. (الترابط يُحدَّث ~45ث، الأخبار أبطأ.) نستخدم عمر الملف للفحص.
    import os as _os
    def _fresh(p, maxage):
        try: return (time.time() - _os.path.getmtime(p)) <= maxage
        except Exception: return False
    _np = RN / "agents" / "news_signals.json"; _ip = V2 / "intermarket_signals.json"
    news = (_load(_np, {}) or {}).get("symbols", {}) if _fresh(_np, 3600) else {}
    im = (_load(_ip, {}) or {}).get("signals", {}) if _fresh(_ip, 600) else {}
    macro = _load(MACRO, {}) or {}
    # ⏳ نظرة الماكرو تكتبها طبقة Claude، وهي لا تتحدّث الآن (رصيد API صفر). كل الإشارات الأخرى
    # تنتهي صلاحيتها (الترابط/الأخبار 300ث) — والماكرو يجب أن ينتهي أيضاً: نظرة عمرها 6 أيام
    # (مثلاً «قلّل قبل CPI 10 يونيو») تعاكس الترند الحيّ. >36 ساعة ⇒ نُسقط تحيّز الماكرو كصوت حيّ.
    _macro_stale = True
    try:
        import os as _os
        _macro_stale = (time.time() - _os.path.getmtime(MACRO)) > 36 * 3600
    except Exception:
        pass
    macro_bias = {} if _macro_stale else (macro.get("symbols", {}) or {})
    syms = [Path(f).stem for f in glob.glob(str(GENO / "*.json"))]
    out = {}
    for s in syms:
        g = _load(GENO / f"{s}.json", {}) or {}
        oos_pf = float((g.get("oos", {}) or {}).get("pf", 0) or 0)
        vol = _load(V2 / f"vol_regime_{s}.json", {}) or {}
        # collect independent directional signals
        sig = []
        nd = int((news.get(s) or {}).get("news_dir", 0) or 0);
        if nd: sig.append(("news", nd, float((news.get(s) or {}).get("conviction", 0.3))))
        xd = int((im.get(s) or {}).get("dir", 0) or 0)
        if xd: sig.append(("intermarket", xd, float((im.get(s) or {}).get("conf", 0.3))))
        md = int((macro_bias.get(s) or {}).get("dir", 0) or 0)
        if md: sig.append(("macro", md, float((macro_bias.get(s) or {}).get("conviction", 0.6))))
        veto = bool((news.get(s) or {}).get("veto", False))
        # agreement: net directional weight + count of agreeing independent sources
        net = sum(d * w for _, d, w in sig)
        bias = 1 if net > 0 else -1 if net < 0 else 0
        agree = sum(1 for _, d, _ in sig if d == bias and bias != 0)
        conviction = round(min(1.0, abs(net) / 2.0 + 0.15 * agree), 2)
        # genome quality gate: a weak gene (PF<1.3) needs MORE agreement to trade
        quality = "robust" if oos_pf >= 1.6 else "ok" if oos_pf >= 1.3 else "weak"
        # Having a genome = this symbol PASSED the deep 50k + real-spread test → it is a proven
        # survivor. Trust it to trade on its OWN validated edge (the trader's conf_gate times entries).
        # Discipline now comes from the strict cull (only survivors exist), not from blocking them.
        if veto:
            action, reason = "AVOID", "🛑 فيتو أخبار (حدث عالي الأثر)"
        elif len(sig) >= 2 and agree == 0:
            action, reason = "TRADE_LIGHT", "إشارات خارجية متضاربة — لوت أصغر"
        elif agree >= 1:
            action, reason = "TRADE", f"جين مُثبت + {agree} إشارة تؤكّد ({'/'.join(n for n,_,_ in sig)})"
        else:
            action, reason = "TRADE", "جين مُثبت — يتداول على حافته الصامدة"
        out[s] = {"bias": bias, "conviction": conviction, "action": action,
                  "quality": quality, "vol": vol.get("state", "?"), "reason": reason,
                  "sources": [n for n, _, _ in sig]}
    n_trade = sum(1 for v in out.values() if v["action"] == "TRADE")
    return {"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
            "macro_note": (("⚠️ ماكرو بائت (غير مطبّق) · " if _macro_stale else "") + macro.get("note", "")),
            "macro_applied": not _macro_stale, "macro_as_of": macro.get("as_of", "?"),
            "n_symbols": len(out), "n_greenlit": n_trade, "symbols": out}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    while True:
        try:
            o = synthesize()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            tmp = OUT.with_suffix(".json.tmp"); tmp.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
            import os; os.replace(tmp, OUT)
            gl = [s for s, v in o["symbols"].items() if v["action"] == "TRADE"]
            print(f"[LLM] {o['n_symbols']} رمز · أخضر (اتفاق قوي) {o['n_greenlit']}: {gl[:8]}", flush=True)
        except Exception as e:
            print(f"[LLM] err {e}", flush=True)
        if not a.loop:
            break
        time.sleep(INTERVAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
