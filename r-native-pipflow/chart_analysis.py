"""chart_analysis.py — AI chart analysis (Claude Call B).

Sends recent OHLC candles + live indicator values to the LLM and returns a
single trade setup (ChartAnalysis). Then renders Entry / Stop / T1·T2·T3 on
the MT5 chart by appending drawings to the brain JSON via chart_drawings.

Strict-JSON contract; retries once; falls back to a deterministic
structure-only read (from smc_engine + indicators) if the LLM is unavailable
so the panel always shows *something* actionable.
"""
from __future__ import annotations

import json
from typing import Optional

from r_native.strategy_types import ChartAnalysis, TF_TO_MT5_NAME
from r_native import live_indicators as li


ANALYZE_SYSTEM_PROMPT = """You are an expert price-action and smart-money \
analyst. Analyze the given chart data (recent OHLC candles + indicator values) \
and return a single trade setup as STRICT JSON only (no prose, no markdown).

Method:
- Read trend and market structure (break of structure / CHOCH), order blocks, \
and liquidity (BSL/SSL sweeps).
- Cross-check with the indicator votes provided.
- Only produce a setup if confidence >= 70; otherwise set direction to "NONE".
- Use ATR for levels: stop ~1xATR beyond invalidation; targets T1/T2/T3 at \
~1/2/3 xATR (or at the next liquidity levels).

Return JSON exactly:
{
  "direction": "LONG"|"SHORT"|"NONE",
  "entry": number, "stop": number,
  "targets": [number, number, number],
  "riskPct": number, "rr": number, "confidence": number,
  "structure": string, "rationale": string
}"""


def analyze_chart(symbol: str, tf: str = "15m", n_candles: int = 60) -> dict:
    """Run Claude Call B for one symbol/timeframe.

    Returns {ok, analysis: ChartAnalysis.to_dict(), backend, fallback}.
    """
    bars = _fetch_bars(symbol, tf, max(n_candles + 40, 100))
    if not bars:
        return {"ok": False, "reason": "no bars", "analysis":
                ChartAnalysis(symbol, tf).to_dict()}

    indicators = li.compute_indicators(bars)
    ind_summary = {i.key: i.status for i in indicators}
    payload = _build_llm_payload(symbol, tf, bars[-n_candles:], indicators)

    parsed, backend = _call_llm(payload)
    if parsed is None:
        analysis = _fallback_analysis(symbol, tf, bars, indicators)
        return {"ok": False, "analysis": analysis.to_dict(),
                "backend": backend, "fallback": True,
                "indicators": ind_summary,
                "reason": "LLM unavailable or invalid JSON"}

    analysis = ChartAnalysis.from_dict({**parsed, "symbol": symbol,
                                        "timeframe": tf})
    return {"ok": True, "analysis": analysis.to_dict(),
            "backend": backend, "fallback": False,
            "indicators": ind_summary}


def analyze_and_draw(symbol: str, tf: str = "15m", n_candles: int = 60) -> dict:
    """analyze_chart + push Entry/Stop/T1·T2·T3 onto the MT5 chart."""
    res = analyze_chart(symbol, tf, n_candles)
    a = res.get("analysis") or {}
    if a.get("direction") in ("LONG", "SHORT") and a.get("entry"):
        try:
            drawings = build_analysis_drawings(symbol, a)
            res["drawings"] = drawings
            _publish_drawings(symbol, drawings)
        except Exception as e:
            res["draw_error"] = str(e)
    return res


# ─── Drawing the setup on MT5 ────────────────────────────────────
def build_analysis_drawings(symbol: str, analysis: dict) -> list:
    """Build hline + label drawings for entry/stop/targets."""
    try:
        from r_native import chart_drawings as cd
    except Exception:
        import chart_drawings as cd
    import time as _t
    ts = int(_t.time())
    side = "long" if analysis["direction"] == "LONG" else "short"
    entry = float(analysis["entry"])
    stop  = float(analysis["stop"])
    targets = analysis.get("targets") or [0, 0, 0]
    out = []
    # Entry + SL using the existing helper (entry, sl, tp=first target)
    out.extend(cd.draw_sl_tp_zone(symbol, entry=entry, sl=stop,
                                  tp=float(targets[0] or entry), side=side, ts=ts))
    # Extra targets T2 / T3 as their own labelled hlines
    for idx, tp in enumerate(targets[1:], start=2):
        if not tp:
            continue
        d = cd._envelope(cd._id("h_tp", symbol, side, ts, idx), "hline", symbol)
        d["price"] = float(tp); d["label"] = f"T{idx}"
        d["style"] = {"color": "#00E676", "width": 1, "line_style": "dot",
                      "zorder": 4}
        d["meta"] = {"category": "tp", "tier": idx}
        out.append(d)
    # Narrative label at entry
    note = (f"{analysis['direction']} · conf {analysis.get('confidence', 0):.0f}% · "
            f"R:R {analysis.get('rr', 0):.1f}")
    out.append(cd.draw_narrative_label(symbol, ts, entry, note))
    return out


def _publish_drawings(symbol: str, drawings: list) -> None:
    """Append drawings to a sidecar JSON the EA reads (decoupled from the
    main brain JSON so analysis overlays don't fight the live executor)."""
    from pathlib import Path
    p = Path(r"C:\Users\Radhi\MT5\data\r_native\chart_analysis_drawings.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"symbol": symbol, "drawings": drawings}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


# ─── LLM plumbing ────────────────────────────────────────────────
def _build_llm_payload(symbol, tf, candles, indicators) -> dict:
    o, h, l, c = li._ohlc(candles)
    ema20 = li._ema(c, 20)[-1] if len(c) else 0
    ema50 = li._ema(c, 50)[-1] if len(c) else 0
    rsi14 = li._rsi(c, 14)
    atr14 = float(li._atr(h, l, c, 14)[-1])
    return {
        "symbol": symbol, "timeframe": tf,
        "candles": [{"o": float(b["open"]) if isinstance(b, dict) else float(b[1]),
                     "h": float(b["high"]) if isinstance(b, dict) else float(b[2]),
                     "l": float(b["low"])  if isinstance(b, dict) else float(b[3]),
                     "c": float(b["close"]) if isinstance(b, dict) else float(b[4]),
                     "t": int(b["time"]) if isinstance(b, dict) else int(b[0])}
                    for b in candles],
        "indicators": {
            "ema20": round(float(ema20), 5), "ema50": round(float(ema50), 5),
            "rsi14": round(rsi14, 1), "atr14": round(atr14, 5),
            **{i.key: i.status for i in indicators},
        },
    }


def _call_llm(payload: dict):
    try:
        from r_native.agents.llm import ask, extract_json
    except Exception:
        return None, None
    user = json.dumps(payload, ensure_ascii=False)
    out = ask(prompt=user, system=ANALYZE_SYSTEM_PROMPT,
              preferred_backend="auto", temperature=0.2)
    if out.get("ok"):
        parsed = extract_json(out.get("text") or "")
        if _valid(parsed):
            return parsed, out.get("backend")
    out2 = ask(prompt=user + "\n\nReturn VALID JSON ONLY.",
               system=ANALYZE_SYSTEM_PROMPT, preferred_backend="auto",
               temperature=0.1)
    if out2.get("ok"):
        parsed = extract_json(out2.get("text") or "")
        if _valid(parsed):
            return parsed, out2.get("backend")
    return None, (out.get("backend") if out else None)


def _valid(p) -> bool:
    return bool(p and isinstance(p, dict) and "direction" in p)


# ─── Deterministic fallback (no LLM) ────────────────────────────
def _fallback_analysis(symbol, tf, bars, indicators) -> ChartAnalysis:
    """Structure-only read so the panel still shows a setup if the LLM is down."""
    from r_native.strategy_types import Strategy
    from r_native import signal_engine as se
    strat = Strategy.default(f"{symbol} fallback")
    decision = se.evaluate_entry(strat, bars)
    direction = decision["decision"]
    if direction == "NONE":
        return ChartAnalysis(symbol, tf, direction="NONE",
                             confidence=decision.get("confidence", 0),
                             structure=(decision.get("structure") or {}).get("note", ""),
                             rationale="No confluence + structure agreement.")
    return ChartAnalysis(
        symbol=symbol, timeframe=tf, direction=direction,
        entry=decision["entry"], stop=decision["stop"],
        targets=decision["targets"], rr=decision["rr"],
        riskPct=strat.risk.maxPerTradePct,
        confidence=decision.get("confidence", 0),
        structure=(decision.get("structure") or {}).get("note", ""),
        rationale="Deterministic confluence+structure read (LLM offline).",
    )


def _fetch_bars(symbol: str, tf: str, n: int) -> list:
    try:
        import MetaTrader5 as mt5
    except Exception:
        return []
    try:
        if not mt5.initialize():
            mt5.initialize()
        tf_name = TF_TO_MT5_NAME.get(tf, "M15")
        tf_const = getattr(mt5, f"TIMEFRAME_{tf_name}", None)
        if tf_const is None:
            return []
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, n)
        if rates is None:
            return []
        return [{"time": int(r["time"]), "open": float(r["open"]),
                 "high": float(r["high"]), "low": float(r["low"]),
                 "close": float(r["close"])} for r in rates]
    except Exception:
        return []
