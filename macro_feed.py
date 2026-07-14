"""macro_feed.py — محرّك الاستخبارات الكلّية (طبقة المؤسسات، مصادر مجانية بالكامل).

ما يميّز الأنظمة الاحترافية: سياق ماكرو/عبر-أصول حيّ (Risk-On/Risk-Off) يوجّه القرار. نسحبه
مجاناً عبر yfinance: DXY (الدولار) · VIX (الخوف) · عائد 10س · S&P · ناسداك · نفط · ذهب · BTC.
نشتقّ منه: (1) نظام المخاطرة العالمي risk_on/off/neutral، (2) ميل ماكرو لكل رمز نتداوله.

صفر تكلفة · صفر مفتاح مدفوع. يكتب macro_state.json. multi_trader + war_room يستهلكانه.
Run:  pythonw macro_feed.py
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from pathlib import Path

RN = Path(r"C:\Users\Radhi\MT5") / "data" / "r_native"
OUT = RN / "macro_state.json"
POLL_S = 600          # كل 10 دقائق (yfinance لطيف مع هذا)
TICKERS = {"DXY": "DX-Y.NYB", "VIX": "^VIX", "US10Y": "^TNX", "SPX": "^GSPC",
           "NDX": "^IXIC", "OIL": "CL=F", "GOLD": "GC=F", "BTC": "BTC-USD"}


def _pull():
    import yfinance as yf
    out = {}
    for k, t in TICKERS.items():
        try:
            d = yf.Ticker(t).history(period="10d", interval="1d")
            if len(d) >= 3:
                c = [float(x) for x in d["Close"].tolist()]
                out[k] = {"last": round(c[-1], 3),
                          "chg1": round((c[-1] / c[-2] - 1) * 100, 2),
                          "chg5": round((c[-1] / c[-6] - 1) * 100, 2) if len(c) >= 6 else 0.0,
                          "trend": 1 if c[-1] > c[-min(5, len(c))] else -1}
        except Exception:
            pass
    return out


def _regime(m):
    """نظام المخاطرة العالمي من VIX + العوائد + الأسهم."""
    score = 0
    vix = m.get("VIX", {})
    if vix:
        if vix["last"] > 22 or vix["chg1"] > 8:
            score -= 2                      # خوف مرتفع/صاعد = risk-off
        elif vix["last"] < 15 and vix["chg1"] < 0:
            score += 2                      # هدوء = risk-on
    spx = m.get("SPX", {})
    if spx:
        score += 1 if spx["trend"] > 0 else -1
    ndx = m.get("NDX", {})
    if ndx:
        score += 1 if ndx["trend"] > 0 else -1
    reg = "risk_on" if score >= 2 else "risk_off" if score <= -2 else "neutral"
    return reg, score


def _bias(m, reg):
    """ميل ماكرو لكل رمز (−1..+1) من علاقات عبر-الأصول المعروفة."""
    dxy = m.get("DXY", {}).get("trend", 0)
    dxy5 = m.get("DXY", {}).get("chg5", 0)
    y = m.get("US10Y", {}).get("trend", 0)
    vix_off = reg == "risk_off"
    vix_on = reg == "risk_on"
    b = {}
    # الذهب: ملاذ — يصعد مع الخوف/ضعف الدولار/هبوط العوائد
    g = 0
    g += -dxy                       # دولار قوي = ذهب ضعيف
    g += -y                         # عوائد صاعدة = ذهب ضعيف
    g += 1 if vix_off else (-1 if vix_on else 0)
    b["XAUUSDm"] = max(-1, min(1, g / 2))
    b["XAGUSDm"] = b["XAUUSDm"]
    b["XAUEURm"] = b["XAUUSDm"]; b["XAUGBPm"] = b["XAUUSDm"]
    # أزواج الدولار: اتجاه DXY (USDJPY يصعد مع قوة الدولار؛ لكن الين ملاذ وقت الخوف)
    b["USDJPYm"] = max(-1, min(1, dxy + (-1 if vix_off else 0)))
    for s in ("EURUSDm", "GBPUSDm", "AUDUSDm", "NZDUSDm"):
        b[s] = -dxy                 # دولار قوي = هذه تنزل
    b["USDCHFm"] = dxy; b["USDCADm"] = dxy
    # المؤشرات والأسهم: risk-on صعود
    eq = 1 if vix_on else (-1 if vix_off else 0)
    for s in ("US500m", "USTECm", "US30m", "DE30m", "UK100m", "JP225m", "NVDAm", "TSLAm",
              "GOOGLm", "MSFTm", "AMGNm", "MCDm", "INTUm", "UNHm", "ORCLm", "IBMm", "LLYm"):
        b[s] = eq
    # كريبتو: يتبع ناسداك + المخاطرة
    nd = m.get("NDX", {}).get("trend", 0)
    cb = max(-1, min(1, (nd + (1 if vix_on else -1 if vix_off else 0))))
    for s in ("BTCUSDm", "ETHUSDm", "SOLUSDm", "BNBUSDm", "XRPUSDm", "LTCUSDm"):
        b[s] = cb
    # النفط: risk-on + نمو
    b["USOILm"] = eq; b["UKOILm"] = eq; b["XNGUSDm"] = eq
    return {k: round(float(v), 2) for k, v in b.items()}


def cycle():
    m = _pull()
    if not m:
        return None
    reg, score = _regime(m)
    bias = _bias(m, reg)
    out = {"ts": time.time(), "iso": datetime.now(timezone.utc).isoformat(),
           "instruments": m, "regime": reg, "regime_score": score, "bias": bias,
           "headline": f"{reg.upper()} · DXY {m.get('DXY',{}).get('last','?')} "
                       f"· VIX {m.get('VIX',{}).get('last','?')} · 10Y {m.get('US10Y',{}).get('last','?')}%"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT)
    return out


def main():
    print("[MACRO] محرّك الاستخبارات الكلّية حيّ — Risk-On/Off + ميل ماكرو (مجاني)", flush=True)
    while True:
        try:
            o = cycle()
            if o:
                print(f"[MACRO] {o['headline']} · ميل ذهب {o['bias'].get('XAUUSDm')} "
                      f"· أسهم {o['bias'].get('US500m')} · كريبتو {o['bias'].get('BTCUSDm')}", flush=True)
        except Exception as e:
            print(f"[MACRO] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
