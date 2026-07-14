"""friday_sdk_agents.py — جيش FRIDAY عبر Claude Agent SDK (منسّق + sub-agents).

معماريّة آمنة (راجع AGENTS_SDK_PLAN.md):
  • أدوات MT5 للقراءة فقط + write_decision (يكتب JSON يقرأه gold_live) — لا order_send من LLM.
  • منسّق رئيسي يفوّض لـsub-agents تحليليين (strategist + risk_analyst).
  • استشاري: يكتب قرارًا/انحيازًا فقط؛ التنفيذ يبقى في gold_live المحمي.

تشغيل:  python agents_sdk/friday_sdk_agents.py
يلزم: ANTHROPIC_API_KEY في .env + claude CLI مثبّت (موجود مع Claude Code).
"""
from __future__ import annotations
import os, json, asyncio
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
DECISION = ROOT / "r_native_v2" / "data" / "sdk_decision.json"

# ── حمّل المفتاح من .env ──
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())

import MetaTrader5 as mt5
from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions, AgentDefinition,
    tool, create_sdk_mcp_server, AssistantMessage, TextBlock,
)

GOLD = "XAUUSDm"

# ── أدوات MT5 (قراءة فقط) + قرار (كتابة JSON، لا تنفيذ) ──
@tool("read_account", "الحساب: رصيد/إكويتي/هامش", {})
async def read_account(args):
    mt5.initialize(); a = mt5.account_info()
    d = {"balance": a.balance, "equity": a.equity, "margin_level": a.margin_level,
         "demo": a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO} if a else {}
    return {"content": [{"type": "text", "text": json.dumps(d)}]}

@tool("read_positions", "الصفقات المفتوحة", {})
async def read_positions(args):
    mt5.initialize()
    ps = [{"symbol": p.symbol, "side": "BUY" if p.type == 0 else "SELL",
           "vol": p.volume, "open": p.price_open, "sl": p.sl, "tp": p.tp,
           "float": p.profit, "magic": p.magic} for p in (mt5.positions_get() or [])]
    return {"content": [{"type": "text", "text": json.dumps(ps)}]}

@tool("read_gold", "ملخّص ذهب M15: سعر + EMA + RSI + ATR + آخر 5 شموع", {})
async def read_gold(args):
    mt5.initialize()
    r = mt5.copy_rates_from_pos(GOLD, mt5.TIMEFRAME_M15, 0, 60)
    c = [x["close"] for x in r]
    def ema(x, n):
        a = 2/(n+1); o = list(x)
        for i in range(1, len(x)): o[i] = a*x[i]+(1-a)*o[i-1]
        return o[-1]
    g = l = 0.0
    for i in range(len(c)-14, len(c)): d = c[i]-c[i-1]; g += max(d, 0); l += max(-d, 0)
    rsi = 100-100/(1+(g/14)/(l/14)) if l > 0 else 100
    last5 = [{"o": x["open"], "h": x["high"], "l": x["low"], "c": x["close"]} for x in r[-5:]]
    out = {"price": c[-1], "ema9": ema(c, 9), "ema50": ema(c, 50), "rsi": round(rsi, 1), "last5": last5}
    return {"content": [{"type": "text", "text": json.dumps(out)}]}

@tool("write_decision", "اكتب القرار النهائي (انحياز + سبب). لا ينفّذ — gold_live يقرأه.",
      {"bias": str, "confidence": float, "reason": str})
async def write_decision(args):
    DECISION.parent.mkdir(parents=True, exist_ok=True)
    DECISION.write_text(json.dumps({"bias": args["bias"], "confidence": args["confidence"],
                                    "reason": args["reason"]}, ensure_ascii=False), encoding="utf-8")
    return {"content": [{"type": "text", "text": f"saved → {DECISION.name}"}]}

@tool("read_history", "آخر صفقات مغلقة (gold_live 99791) خلال 24س + الصافي", {})
async def read_history(args):
    import datetime as _dt
    mt5.initialize()
    s = _dt.datetime.now() - _dt.timedelta(hours=24)
    ds = [d for d in (mt5.history_deals_get(s, _dt.datetime.now()) or []) if d.magic == 99791 and d.entry == 1]
    net = sum(d.profit + d.commission + d.swap for d in ds)
    out = {"closed_24h": len(ds), "net": round(net, 2),
           "wins": sum(1 for d in ds if d.profit > 0), "last": [round(d.profit, 2) for d in ds[-8:]]}
    return {"content": [{"type": "text", "text": json.dumps(out)}]}

server = create_sdk_mcp_server(name="friday", version="1.0",
    tools=[read_account, read_positions, read_gold, read_history, write_decision])

T = ["mcp__friday__read_account", "mcp__friday__read_positions", "mcp__friday__read_gold", "mcp__friday__read_history"]

# ── sub-agents تحليليون ──
SUBAGENTS = {
    "strategist": AgentDefinition(
        description="محلّل اتجاه الذهب M15", tools=["mcp__friday__read_gold"], model="sonnet",
        prompt="أنت محلّل سكالبينج ذهب M15. اقرأ read_gold. الحافة = الانضباط + الترند (لا تتداول العرضي). "
               "أعطِ انحياز BUY/SELL/WAIT + سبب قصير. الترند: السعر فوق/تحت EMA9 وEMA50 مع RSI يميل."),
    "risk_analyst": AgentDefinition(
        description="محلّل مخاطر الحساب", tools=["mcp__friday__read_account", "mcp__friday__read_positions"],
        model="sonnet",
        prompt="أنت حارس مخاطر. اقرأ الحساب والصفقات. احذّر لو هامش منخفض/تعرّض زائد/خسارة كبيرة. "
               "أعطِ موافقة RISK_OK أو RISK_BLOCK + سبب. الحساب ديمو صغير — تحفّظ."),
    "regime_reader": AgentDefinition(
        description="قارئ نظام السوق (ترند/عرضي)", tools=["mcp__friday__read_gold"], model="sonnet",
        prompt="أنت قارئ ريجيم. اقرأ read_gold. صنّف السوق: TREND (السعر يبتعد عن EMA50 باتجاه واضح) "
               "أو CHOP (متذبذب قرب EMA، آخر ٥ شموع متداخلة). الحافة فقط في TREND — في CHOP أعطِ "
               "REGIME_CHOP (لا تداول). أعطِ TREND_UP/TREND_DOWN/REGIME_CHOP + سبب قصير."),
    "auditor": AgentDefinition(
        description="مدقّق الأداء", tools=["mcp__friday__read_history", "mcp__friday__read_account"], model="sonnet",
        prompt="أنت مدقّق أداء. اقرأ read_history (صفقات 24س + الصافي) وread_account. لخّص: صافي اليوم، "
               "نسبة الفوز، وهل في نزيف؟ لو الصافي سالب بوضوح أو خسائر متتالية → أعطِ تحذير AUDIT_WARN "
               "(يخفّض الثقة). وإلا AUDIT_OK + ملخّص رقم واحد."),
}

ORCH_PROMPT = (
    "أنت منسّق جيش FRIDAY (عقل واحد). فوّض للوكلاء الأربعة: regime_reader (نظام السوق)، "
    "strategist (اتجاه الذهب)، risk_analyst (مخاطر)، auditor (أداء 24س). القاعدة: "
    "لو regime_reader=REGIME_CHOP أو risk_analyst=RISK_BLOCK → القرار WAIT. "
    "لو auditor=AUDIT_WARN → خفّض الثقة. وإلا ادمج اتجاه strategist مع الريجيم. "
    "ثم استدعِ write_decision (bias, confidence 0-1, reason). "
    "استشاري فقط — gold_live المحمي ينفّذ. لا تطلب تنفيذ أوامر."
)

async def main():
    opts = ClaudeAgentOptions(
        mcp_servers={"friday": server},
        allowed_tools=T + ["mcp__friday__write_decision"],
        agents=SUBAGENTS,
        system_prompt=ORCH_PROMPT,
        permission_mode="acceptEdits",
    )
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("حلّل الذهب الآن وافحص المخاطر واكتب القرار النهائي.")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        print(b.text)
    print(f"\n→ القرار في {DECISION}")

if __name__ == "__main__":
    asyncio.run(main())
