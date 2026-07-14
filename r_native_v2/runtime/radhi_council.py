"""runtime/radhi_council.py — the council that trades like Radhi (الأب الروحي).

Born 2026-05-31. Each cycle, a council of agents looks at the live market and
DELIBERATES out loud — every agent references Radhi's decoded DNA
(data/radhi_dna.json) and asks: "لو راضي شاف هذي الصفقة، وش يسوي؟" then adds the
quant numbers Radhi couldn't see, and a risk gate protects from his known
mistakes (night trading, buying knives). Produces a human-readable transcript
(printed + data/radhi_council_live.json) so Radhi can WATCH them think.

This is the visible brain of the clone. Read-only / advisory — it writes a
verdict file; the executor (unified_trader) still places the trade behind the
governance gate.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
SNAP = DATA / "brain_live__XAUUSDm.json"
DNA  = DATA / "radhi_dna.json"
OUT  = DATA / "radhi_council_live.json"


def _read(p):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


def deliberate() -> dict:
    s = _read(SNAP)
    if not s:
        return {"verdict": "NO_DATA", "transcript": ["لا توجد بيانات سوق"]}

    sess   = s.get("session", "?")
    regime = s.get("regime", "?")
    rsi    = (s.get("rsi") or {})
    rsi_m1 = rsi.get("m1", 50); rsi_m5 = rsi.get("m5", 50)
    bias   = s.get("bias", {})
    dn = sum(1 for v in bias.values() if v == "DOWN")
    up = sum(1 for v in bias.values() if v == "UP")
    adx_m5 = (s.get("adx") or {}).get("m5", 0)
    pressure = float(s.get("pressure_10m1", 0))
    bid = s.get("bid", 0)
    _vw = s.get("vwap_m5") or s.get("vwap_m1") or {}
    vwap = (_vw.get("vwap") if isinstance(_vw, dict) else _vw) or bid
    above_mean = bid > vwap

    T = []   # transcript: (agent, line, ok)
    score = 0   # +ve → lean SELL, gate can veto

    # ── 1) راضي-المُحاكي — does it match Radhi's proven edge? ────────────────
    edge_bits = []
    sess_ok = sess == "NY_OVERLAP"
    edge_bits.append(("جلسة نيويورك", sess_ok, f"الجلسة={sess}"))
    rsi_ok = rsi_m1 > 50
    edge_bits.append(("RSI>50 (بيع القوة)", rsi_ok, f"RSI(m1)={rsi_m1:.0f}"))
    mean_ok = above_mean
    edge_bits.append(("السعر فوق المتوسط (VWAP)", mean_ok, f"bid {bid:.0f} {'فوق' if above_mean else 'تحت'} {vwap:.0f}"))
    matches = sum(1 for _, ok, _ in edge_bits if ok)
    radhi_says = "بِيع" if matches >= 2 else "ينتظر"
    T.append(("🧔 راضي-المُحاكي",
              f"بصمتك: تبيع الارتدادات فوق المتوسط بـ RSI>50 في نيويورك. "
              f"المطابقة الآن {matches}/3 → راضي **{radhi_says}**.", matches >= 2))
    for name, ok, detail in edge_bits:
        T.append(("   •", f"{'✅' if ok else '❌'} {name} ({detail})", ok))
    if matches >= 2: score += 2

    # ── 2) المحلل-الكمّي — the numbers Radhi didn't watch ─────────────────────
    q_ok = (dn >= 2 and pressure < 0)
    T.append(("📊 المحلل-الكمّي",
              f"أرقام ما شفتها: اتجاه MTF {dn}↓/{up}↑، ضغط التدفق {pressure:+.2f}, ADX(m5) {adx_m5:.0f}. "
              f"{'يؤكّد البيع' if q_ok else 'لا يؤكّد البيع بعد'}.", q_ok))
    if q_ok: score += 1

    # ── 3) حارس-المخاطر — protect from Radhi's known mistakes ─────────────────
    vetoes = []
    if sess in ("ASIAN", "TRANSITION") or sess not in ("NY_OVERLAP", "LONDON", "NY_LATE"):
        vetoes.append("جلسة ليلية/آسيا — تاريخياً تخسرك (-$671)")
    if rsi_m1 < 30:
        vetoes.append("RSI<30 — فخ شراء السكين الساقط (-$830)")
    if vetoes:
        T.append(("🛡️ حارس-المخاطر", "فيتو: " + " | ".join(vetoes), False))
    else:
        T.append(("🛡️ حارس-المخاطر", "لا مخاطر معروفة — الجلسة والمنطقة سليمة.", True))

    # ── 4) القرار ─────────────────────────────────────────────────────────────
    if vetoes:
        verdict = "WAIT"; why = "فيتو الحارس — ظروف تخسرك تاريخياً"
    elif score >= 3:
        verdict = "SELL"; why = "بصمتك + الأرقام تتفق على البيع"
    elif matches >= 2:
        verdict = "SELL?"; why = "بصمتك تتفق لكن الأرقام لسه ما تؤكّد بالكامل"
    else:
        verdict = "WAIT"; why = "ما تطابقت شروط دخولك بعد"
    T.append(("⚖️ القرار", f"**{verdict}** — {why}", verdict.startswith("SELL")))

    return {"ts": datetime.now(timezone.utc).isoformat(), "symbol": "XAUUSDm",
            "session": sess, "regime": regime, "verdict": verdict, "why": why,
            "edge_match": f"{matches}/3", "transcript": [f"{a}  {line}" for a, line, _ in T]}


def main(loop=False):
    import time
    while True:
        d = deliberate()
        OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n" + "═" * 64)
        print(f"  مجلس راضي · {datetime.now():%H:%M:%S} · الذهب · {d.get('session')} · {d.get('regime')}")
        print("═" * 64)
        for line in d["transcript"]:
            print("  " + line)
        print("─" * 64)
        print(f"  القرار النهائي: {d['verdict']}  ({d['why']})  |  مطابقة بصمتك: {d.get('edge_match')}")
        print("═" * 64)
        if not loop: break
        time.sleep(5)


if __name__ == "__main__":
    import sys
    main(loop="--loop" in sys.argv)
