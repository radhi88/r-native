"""
claude_confirm.py — طبقة تأكيد كلود (server-side) على بيانات حقيقية.
يلخّص شموع كل فريم إلى سياق مركّز ثم يطلب من كلود حُكم JSON منظّم.

ملاحظة FRIDAY: يتطلّب ANTHROPIC_API_KEY ذا رصيد. لو المفتاح غائب أو الرصيد $0 يرجّع خطأً
بأمان (لا يكسر باقي الجسر).
"""
import os
import json
import requests
import mt5_client as mt5c
import scanner

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

SYS = (
    "You are a senior multi-timeframe price-action analyst (ICT/SMC aware: Order Blocks, "
    "FVG, BOS, liquidity sweeps). Analyze the provided real OHLC summaries per timeframe and "
    "produce a confidence-scored confirmation. Respond with ONLY one valid JSON object — no "
    "markdown, no backticks, no preamble. Schema: {\"direction\":\"BUY|SELL|NEUTRAL\","
    "\"confidence\":<int 0-100>,\"summary_ar\":\"<short>\",\"summary_en\":\"<short>\","
    "\"timeframes\":[{\"tf\":\"<tf>\",\"bias\":\"BUY|SELL|NEUTRAL\",\"note_ar\":\"<max 10 words>\"}],"
    "\"levels\":{\"support\":[<nums>],\"resistance\":[<nums>]},"
    "\"trade\":{\"entry\":\"<str>\",\"sl\":\"<str>\",\"tp1\":\"<str>\",\"tp2\":\"<str>\",\"tp3\":\"<str>\"},"
    "\"warnings_ar\":[\"<short>\"]}. Keep notes concise."
)


def _summarize_tf(tf, candles):
    """يحوّل شموع فريم إلى سطر سياق مركّز بأرقام حقيقية."""
    if not candles:
        return f"{tf}: لا بيانات"
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    a = scanner.analyze_tf(candles)
    return (
        f"{tf}: close={closes[-1]:.2f} | swingHigh={max(highs[-30:]):.2f} "
        f"swingLow={min(lows[-30:]):.2f} | bias={a['bias']} ({a['note']})"
    )


def _get_key():
    """المفتاح من البيئة، وإلا من .env جذر المشروع (المفتاح الموجود أصلاً) — قراءة فقط."""
    k = os.getenv("ANTHROPIC_API_KEY", "")
    if k:
        return k
    try:
        for ln in open(r"C:\Users\Radhi\MT5\.env", encoding="utf-8-sig"):
            s = ln.strip()
            if s.startswith("ANTHROPIC_API_KEY=") and not s.startswith("#"):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def confirm(symbol, tfs):
    api_key = _get_key()
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY غير مضبوط"}

    lines = [_summarize_tf(tf, mt5c.rates(symbol, tf, 250)) for tf in tfs]
    t = mt5c.tick(symbol) or {}
    context = (
        f"Symbol: {symbol}\n"
        f"Live: bid={t.get('bid')} ask={t.get('ask')} spread={t.get('spread')}\n"
        f"Timeframes:\n" + "\n".join(lines)
    )

    try:
        res = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 1500,
                "system": SYS,
                "messages": [{"role": "user", "content": context}],
            },
            timeout=40,
        )
        data = res.json()
        if isinstance(data, dict) and data.get("error"):       # خطأ API (مصادقة/رصيد/نموذج)
            er = data["error"]
            return {"error": f"API: {er.get('type','')}: {er.get('message','')}"[:200]}
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if not text.strip():
            return {"error": f"رد فارغ (HTTP {res.status_code})"}
        s, e = text.find("{"), text.rfind("}")
        parsed = json.loads(text[s:e + 1])
        parsed["_symbol"] = symbol
        return parsed
    except Exception as ex:
        return {"error": f"تعذّر التأكيد: {ex}"}
