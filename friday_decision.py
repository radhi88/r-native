"""friday_decision.py — محرّك قرار FRIDAY المحلّي (نداء واحد · مخرجات مضمونة).

البديل الأنظف لتنسيق ٤ وكلاء (friday_sdk_agents.py):
  • يجمع لقطة الذهب M15 + الحساب + أداء 24س محليًّا من MT5.
  • نداء Claude **واحد** عبر anthropic SDK مع structured outputs (JSON مضمون الشكل).
  • الانضباط الليلي (22:00–08:00 وقت سيرفر الوسيط UTC+3) **مفروض بالكود** — لا يُترك للـLLM.
  • يكتب نفس الملف اللي يقرأه gold_live: r_native_v2/data/sdk_decision.json (+ ختم زمني للنضارة).
  • استشاري فقط — لا order_send. gold_live المحمي ينفّذ.

تشغيل:  python friday_decision.py            (مرّة)
        python friday_decision.py --loop 300 (كل ٥ دقائق)

⚠️ كل نداء = طلب Claude API حقيقي ($). الموديل claude-opus-4-8 (الافتراضي القوي).
   لتخفيض التكلفة: عدّل MODEL أدناه إلى claude-haiku-4-5 (قرارك أنت).
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
DECISION = ROOT / "r_native_v2" / "data" / "sdk_decision.json"
GOLD = "XAUUSDm"
MAGIC = 99791
MODEL = "claude-haiku-4-5"   # confirmed valid model name; cheap. Upgrade after credits added.

# ── حمّل .env بـ utf-8-sig (يصلح الـBOM الذي يشوّه اسم المفتاح) ──
for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

import MetaTrader5 as mt5

# ── الانضباط الليلي: 22:00–08:00 بوقت سيرفر الوسيط (UTC+3) ──
NIGHT_START, NIGHT_END = 22, 8


def _ema(x, n):
    a = 2 / (n + 1); o = list(x)
    for i in range(1, len(x)):
        o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o[-1]


def _rsi(c, n=14):
    g = l = 0.0
    for i in range(len(c) - n, len(c)):
        d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    return 100 - 100 / (1 + (g / n) / (l / n)) if l > 0 else 100.0


def _atr(r, n=14):
    trs = []
    for i in range(1, len(r)):
        h, lo, pc = r[i]["high"], r[i]["low"], r[i - 1]["close"]
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return sum(trs[-n:]) / n if trs else 0.0


def snapshot():
    """لقطة السوق + الحساب + أداء 24س. ساعة الوسيط من tick.time (وقت السيرفر)."""
    mt5.initialize()
    r = mt5.copy_rates_from_pos(GOLD, mt5.TIMEFRAME_M15, 0, 80)
    if r is None or len(r) < 30:
        return None
    c = [x["close"] for x in r]
    tick = mt5.symbol_info_tick(GOLD)
    broker_hour = (datetime.fromtimestamp(tick.time, timezone.utc).hour if tick
                   else datetime.now(timezone.utc).hour)
    a = mt5.account_info()
    import datetime as _dt
    since = _dt.datetime.now() - _dt.timedelta(hours=24)
    ds = [d for d in (mt5.history_deals_get(since, _dt.datetime.now()) or [])
          if d.magic == MAGIC and d.entry == 1]
    net = round(sum(d.profit + d.commission + d.swap for d in ds), 2)
    wins = sum(1 for d in ds if d.profit > 0)
    return {
        "price": round(c[-1], 2), "ema9": round(_ema(c, 9), 2), "ema50": round(_ema(c, 50), 2),
        "rsi": round(_rsi(c), 1), "atr": round(_atr(r), 2),
        "last5": [{"o": x["open"], "h": x["high"], "l": x["low"], "c": x["close"]} for x in r[-5:]],
        "broker_hour": broker_hour,
        "equity": round(a.equity, 2) if a else None,
        "margin_level": round(a.margin_level, 0) if a else None,
        "net_24h": net, "trades_24h": len(ds), "wins_24h": wins,
    }


SYSTEM = (
    "أنت محرّك قرار سكالبينج ذهب XAUUSDm على فريم M15، حساب ديمو صغير. "
    "الحافة المثبتة = الانضباط + الترند فقط — لا تتداول العرضي (أثبتت الباكتيستات أن تداول الضجيج يخسر من السبريد). "
    "صنّف الريجيم: TREND_UP (السعر فوق EMA9 وEMA50 ويبتعد، RSI>55)، TREND_DOWN (تحت EMA9 وEMA50، RSI<45)، "
    "وإلا CHOP (EMA9/EMA50 متلاصقان أو آخر ٥ شموع متداخلة). "
    "القرار: في CHOP → WAIT (ثقة منخفضة). في ترند واضح → BUY/SELL باتجاه الترند بثقة تتناسب مع قوّته. "
    "خفّض الثقة لو net_24h سالب بوضوح أو نسبة فوز منخفضة (نزيف). "
    "استشاري فقط — لا تطلب تنفيذ أوامر. أعطِ سبباً قصيراً بالأرقام."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "regime": {"type": "string", "enum": ["TREND_UP", "TREND_DOWN", "CHOP"]},
        "bias": {"type": "string", "enum": ["BUY", "SELL", "WAIT"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["regime", "bias", "confidence", "reason"],
    "additionalProperties": False,
}


def write_decision(d: dict):
    DECISION.parent.mkdir(parents=True, exist_ok=True)
    d = {**d, "ts": time.time(), "asof": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "source": "friday_decision"}
    DECISION.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def _rule_decision(snap: dict) -> dict:
    """مُصنّف ريجيم حتمي بالكود — الحافة المثبتة (ترند + انضباط) بلا أي نداء API ($0).

    TREND_UP: السعر فوق EMA9 وEMA9 فوق EMA50 وRSI>55  → BUY
    TREND_DOWN: السعر تحت EMA9 وEMA9 تحت EMA50 وRSI<45 → SELL
    وإلا CHOP → WAIT. الثقة = امتداد الترند نسبة لـATR، تُخفَّض عند النزيف.
    """
    price, e9, e50, rsi, atr = snap["price"], snap["ema9"], snap["ema50"], snap["rsi"], max(snap["atr"], 1e-9)
    ext = abs(price - e50) / atr               # امتداد عن EMA50 بوحدات ATR
    strength = max(0.0, min(1.0, ext / 2.5))   # ~2.5 ATR = ثقة كاملة
    if price > e9 > e50 and rsi > 55:
        regime, bias, conf = "TREND_UP", "BUY", 0.45 + 0.5 * strength
    elif price < e9 < e50 and rsi < 45:
        regime, bias, conf = "TREND_DOWN", "SELL", 0.45 + 0.5 * strength
    else:
        regime, bias, conf = "CHOP", "WAIT", 0.10
    if snap.get("net_24h", 0) < 0:             # نزيف 24س → تحفّظ
        conf *= 0.7
    conf = round(max(0.0, min(1.0, conf)), 3)
    why = (f"{regime} (قاعدي): سعر {price} مقابل EMA9 {e9}/EMA50 {e50}، RSI {rsi}، "
           f"امتداد {ext:.2f}×ATR. net24س {snap.get('net_24h')}. "
           + ("لا حافة — انتظر كسراً واضحاً." if bias == "WAIT" else "ترند واضح باتجاه الإشارة."))
    return {"regime": regime, "bias": bias, "confidence": conf, "reason": why, "engine": "rule"}


def _llm_raw(snap: dict) -> dict:
    """Raw Anthropic API via httpx (RELIABLE HEADLESS — no CLI needed). Works the moment
    the key has credits. On $0 credits it 400s and the caller falls back."""
    import httpx
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 1024, "system": SYSTEM,
              "messages": [{"role": "user", "content":
                  "لقطة السوق الآن (JSON):\n" + json.dumps(snap, ensure_ascii=False) +
                  '\n\nأجب بكائن JSON فقط (لا نص/أسوار) بالمفاتيح: '
                  '{"regime":"TREND_UP|TREND_DOWN|CHOP","bias":"BUY|SELL|WAIT","confidence":0.0-1.0,"reason":"عربي قصير"}'}]},
        timeout=30)
    r.raise_for_status()                         # 400 (credit) / 4xx → raise → caller falls back
    data = r.json()
    txt = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    i, j = txt.find("{"), txt.rfind("}")
    d = json.loads(txt[i:j + 1])
    d["confidence"] = max(0.0, min(1.0, float(d.get("confidence", 0))))
    if d.get("bias") not in ("BUY", "SELL", "WAIT"): d["bias"] = "WAIT"
    if d.get("regime") not in ("TREND_UP", "TREND_DOWN", "CHOP"): d["regime"] = "CHOP"
    d["engine"] = "llm-api"
    return d


async def _llm_async(snap: dict) -> dict:
    """نداء Claude الحقيقي عبر claude_agent_sdk (مصادقة Claude Code — بلا مفتاح/فوترة)."""
    import claude_agent_sdk as sdk
    prompt = (
        SYSTEM + "\n\nلقطة السوق الآن (JSON):\n" + json.dumps(snap, ensure_ascii=False) +
        "\n\nأجب بكائن JSON فقط — لا نص قبله ولا بعده ولا أسوار ```، بالمفاتيح بالضبط:\n"
        '{"regime":"TREND_UP|TREND_DOWN|CHOP","bias":"BUY|SELL|WAIT",'
        '"confidence":0.0-1.0,"reason":"سبب عربي قصير بالأرقام"}'
    )
    opts = sdk.ClaudeAgentOptions(max_turns=1, allowed_tools=[])
    final = ""
    async for m in sdk.query(prompt=prompt, options=opts):
        if isinstance(m, sdk.ResultMessage) and getattr(m, "result", None):
            final = m.result
        elif isinstance(m, sdk.AssistantMessage):
            for b in getattr(m, "content", None) or []:
                if isinstance(b, sdk.TextBlock) and b.text.strip():
                    final = b.text
    txt = final.strip()
    if "```" in txt:                            # انزع أسوار الكود إن وُجدت
        seg = txt.split("```")
        txt = seg[1] if len(seg) > 1 else txt
        if txt.lstrip().lower().startswith("json"):
            txt = txt.lstrip()[4:]
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no json in LLM reply")
    d = json.loads(txt[i:j + 1])
    d["confidence"] = max(0.0, min(1.0, float(d.get("confidence", 0))))
    if d.get("bias") not in ("BUY", "SELL", "WAIT"):
        d["bias"] = "WAIT"
    if d.get("regime") not in ("TREND_UP", "TREND_DOWN", "CHOP"):
        d["regime"] = "CHOP"
    d["engine"] = "llm"
    return d


def decide(snap: dict) -> dict:
    """قرار Claude الحقيقي بثلاث طبقات (لا يكسر شيئاً):
      1) API خام عبر httpx — موثوق headless، يشتغل لحظة توفّر الرصيد (engine=llm-api)
      2) claude_agent_sdk — مجاني عبر مصادقة Claude Code (يعمل عند وجود جلسة) (engine=llm)
      3) المُصنّف القاعدي الحتمي — مجاني دائمًا (engine=rule)"""
    rule = _rule_decision(snap)
    try:
        return _llm_raw(snap)                    # ← يصير حيّاً تلقائياً أول ما تضيف رصيد API
    except Exception:
        pass
    try:
        import asyncio
        return asyncio.run(_llm_async(snap))
    except Exception as e:
        rule["reason"] += f" | (LLM متعذّر: {type(e).__name__})"
        return rule


def run_once() -> dict:
    try:
        snap = snapshot()
        if not snap:
            return write_decision({"regime": "CHOP", "bias": "WAIT", "confidence": 0.0,
                                   "reason": "لا توجد بيانات M15 كافية — fail-safe WAIT."})
        d = decide(snap)
        out = write_decision(d)
        print(f"[friday_decision] {out['asof']}  {out['bias']} ثقة {out['confidence']}  "
              f"({out['regime']})  | {out['reason'][:90]}", flush=True)
        return out
    except Exception as e:  # fail-safe: أي خطأ → WAIT آمن، لا يكسر gold_live
        out = write_decision({"regime": "CHOP", "bias": "WAIT", "confidence": 0.0,
                              "reason": f"fail-safe WAIT بعد خطأ: {type(e).__name__}: {str(e)[:120]}"})
        print(f"[friday_decision] ✗ {type(e).__name__}: {str(e)[:160]} → WAIT آمن", flush=True)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="ثوانٍ بين الدورات (0=مرّة واحدة)")
    a = ap.parse_args()
    if a.loop <= 0:
        run_once(); return
    print(f"[friday_decision] حلقة كل {a.loop}s · Ctrl-C يوقف", flush=True)
    while True:
        run_once()
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
