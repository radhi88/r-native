# -*- coding: utf-8 -*-
"""session_profiler.py — وكيل لكل جلسة يبني data/r_native/session_profiles.json.

قراءة-فقط · بلا order_send · بلا لانشرات · صدق صارم (Bonferroni).

لكل جلسة (asia 0-7 · london 7-12 · ny 12-21 · off 21-24 UTC — نفس حدود
`session_gate.py`) يحلّل صفقاتنا الآلية (`friday.db` source='bot'، باستثناء
اليدوي/المرفوع ومكتب الجيومتري 20260626) خلال 30 يوماً، ويُخرِج بصمة الجلسة:

    {weights, best_symbols, worst_symbols, genes:{stop_atr,target_atr,conf_gate},
     live_or_shadow, honest_verdict, n, expR, t}

قاعدة الحيّ: `live` فقط إذا expR>0 و |t| فوق عتبة Bonferroni (4 اختبارات،
alpha=0.05 ⇒ z≈2.50) و n≥50. وإلا `shadow`. لا overfitting.
"""
from __future__ import annotations

import json
import sqlite3
import statistics as st
import time
from pathlib import Path

DB = Path(r"C:\Users\Radhi\MT5\data\friday.db")
OUT = Path(r"C:\Users\Radhi\MT5\data\r_native\session_profiles.json")
DOSSIER = Path(r"C:\Users\Radhi\MT5\data\r_native\deep_dossier.json")

LOOKBACK_DAYS = 30
BONFERRONI_T = 2.50          # 4 sessions, alpha 0.05 → per-test 0.0125 → z≈2.50
MIN_LIVE_N = 50
SESSIONS = ("asia", "london", "ny", "off")
EXCLUDE_MAGIC = {20260626}   # geometric desk (forward-test noise) excluded


def session_of(ts: float) -> str:
    """Map an epoch timestamp to a session key (gate's UTC boundaries)."""
    h = time.gmtime(ts).tm_hour
    return "asia" if h < 7 else "london" if h < 12 else "ny" if h < 21 else "off"


def load_bot_trades() -> list[dict]:
    """Load our automated closed trades over the look-back window."""
    cut = time.time() - LOOKBACK_DAYS * 86400
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT ticket, ts, symbol, magic, net, win FROM trades "
        "WHERE ts>=? AND closed=1 AND source='bot'", (cut,)).fetchall()
    c.close()
    return [dict(r) for r in rows if r["magic"] not in EXCLUDE_MAGIC]


def load_features_by_session() -> dict[str, list[dict]]:
    """Recorded feature rows grouped by the gate's session boundaries.

    Note: the features table is not engine-tagged (src=backfill/live) and joins
    poorly to bot tickets, so condition weights derived here are ADVISORY/mixed
    context — they do not drive the live/shadow verdict (that uses clean bot
    P&L only).
    """
    cut = time.time() - LOOKBACK_DAYS * 86400
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    out: dict[str, list[dict]] = {s: [] for s in SESSIONS}
    for r in c.execute("SELECT ts, trend, htf_trend, rsi, atr_pctile, "
                       "dist_ema_atr, net FROM features WHERE ts>=? "
                       "AND net IS NOT NULL", (cut,)).fetchall():
        out[session_of(r["ts"])].append(dict(r))
    c.close()
    return out


def _stats(nets: list[float]) -> tuple[int, float, float, float, float]:
    """Return (n, total_net, win_rate, expR, t) with R = net / median|loss|."""
    n = len(nets)
    if n == 0:
        return 0, 0.0, 0.0, 0.0, 0.0
    losses = [-x for x in nets if x < 0]
    ru = st.median(losses) if losses else 1.0
    ru = ru or 1.0
    rs = [x / ru for x in nets]
    m = st.mean(rs)
    sd = st.pstdev(rs) or 1e-9
    t = m / (sd / (n ** 0.5))
    wr = sum(1 for x in nets if x > 0) / n
    return n, round(sum(nets), 2), round(wr, 3), round(m, 4), round(t, 2)


def _condition_weights(feat_rows: list[dict]) -> dict[str, float]:
    """Advisory per-condition mean-R from recorded features for a session."""
    if len(feat_rows) < 40:
        return {}
    losses = [-r["net"] for r in feat_rows if r["net"] < 0]
    ru = (st.median(losses) if losses else 1.0) or 1.0
    conds = {
        "trend_htf_aligned": lambda f: f["trend"] == f["htf_trend"],
        "counter_htf": lambda f: f["trend"] != f["htf_trend"],
        "rsi_oversold": lambda f: (f["rsi"] or 50) < 35,
        "rsi_overbought": lambda f: (f["rsi"] or 50) > 65,
        "high_atr": lambda f: (f["atr_pctile"] or 50) > 60,
        "low_atr": lambda f: (f["atr_pctile"] or 50) < 40,
        "near_ema": lambda f: abs(f["dist_ema_atr"] or 0) < 0.5,
    }
    buckets: dict[str, list[float]] = {k: [] for k in conds}
    for f in feat_rows:
        for name, fn in conds.items():
            try:
                if fn(f):
                    buckets[name].append(f["net"] / ru)
            except Exception:
                pass
    return {k: round(st.mean(v), 3) for k, v in buckets.items() if len(v) >= 30}


def _symbols_split(trades: list[dict], k: int = 5) -> tuple[list[str], list[str]]:
    """Disjoint best/worst symbols by net (min 10 trades each)."""
    agg: dict[str, list[float]] = {}
    for tr in trades:
        agg.setdefault(tr["symbol"], []).append(tr["net"])
    ranked = sorted(((s, round(sum(v), 2)) for s, v in agg.items() if len(v) >= 10),
                    key=lambda x: x[1], reverse=True)
    best = [s for s, _ in ranked[:k]]
    worst = [s for s, _ in reversed(ranked) if s not in best][:k]
    return best, worst


def _genes(expR: float) -> dict[str, float]:
    """Heuristic session genes (data-light): defensive when the session bleeds.

    Honest: without per-bar MFE/MAE we cannot optimise stop/target, so these are
    conservative shadow-mode starters that tighten the confluence gate on weak
    sessions. Refine once excursion data exists.
    """
    if expR > 0:
        return {"stop_atr": 1.5, "target_atr": 2.0, "conf_gate": 0.55}
    if expR > -0.3:
        return {"stop_atr": 1.4, "target_atr": 2.2, "conf_gate": 0.65}
    return {"stop_atr": 1.3, "target_atr": 2.5, "conf_gate": 0.75}


def build_profile(sess: str, trades: list[dict], feat_rows: list[dict]) -> dict:
    """Build one session's honest profile."""
    nets = [t["net"] for t in trades]
    n, net, wr, expR, t = _stats(nets)
    best, worst = _symbols_split(trades)
    live = bool(expR > 0 and t > BONFERRONI_T and n >= MIN_LIVE_N)
    if live:
        verdict = f"حيّ: expR={expR:+.3f} t={t:+.2f} اجتاز Bonferroni (n={n})."
    elif n < MIN_LIVE_N:
        verdict = f"ظلّ: عيّنة صغيرة (n={n}) لا تكفي للحُكم."
    elif expR <= 0:
        verdict = f"ظلّ: expR سالب ({expR:+.3f}, t={t:+.2f}) — الجلسة خاسرة لبوتاتنا."
    else:
        verdict = f"ظلّ: expR موجب لكن t={t:+.2f} دون عتبة Bonferroni {BONFERRONI_T}."
    return {
        "n": n, "net": net, "win_rate": wr, "expR": expR, "t": t,
        "weights": _condition_weights(feat_rows),
        "best_symbols": best, "worst_symbols": worst,
        "genes": _genes(expR),
        "live_or_shadow": "live" if live else "shadow",
        "honest_verdict": verdict,
    }


def main() -> None:
    """Build session_profiles.json from bot trades and print a summary."""
    trades = load_bot_trades()
    feat_by_sess = load_features_by_session()
    by_sess: dict[str, list[dict]] = {s: [] for s in SESSIONS}
    for tr in trades:
        by_sess[session_of(tr["ts"])].append(tr)

    sessions = {s: build_profile(s, by_sess[s], feat_by_sess[s]) for s in SESSIONS}
    live = [s for s, p in sessions.items() if p["live_or_shadow"] == "live"]
    out = {
        "_meta": {
            "built_by": "Instance B / session_profiler.py",
            "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "population": "friday.db trades source='bot', excl manual/user_ea/20260626",
            "lookback_days": LOOKBACK_DAYS, "total_trades": len(trades),
            "bonferroni_t": BONFERRONI_T, "min_live_n": MIN_LIVE_N,
            "note": ("صدق صارم: live فقط إذا صمدت لـBonferroni. ملاحظة: تحليل "
                     "البوتات يُظهر لندن كأسوأ جلسة (t≈-8) عكس خطة-أ المبنية على "
                     "population يشمل اليدوي — البوّابة تحكم البوتات فقط. "
                     "weights استشارية من جدول features (غير مُوسَّم بالمحرّك، "
                     "backfill/live) ولا تقرّر live/shadow — القرار من P&L البوتات فقط."),
        },
        "sessions": sessions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} | live sessions: {live or 'none (all shadow)'}")
    for s in SESSIONS:
        p = sessions[s]
        print(f"  {s:7} n={p['n']:5} net={p['net']:9.2f} expR={p['expR']:+.3f} "
              f"t={p['t']:+.2f} → {p['live_or_shadow']}")


if __name__ == "__main__":
    main()
