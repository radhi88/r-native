"""nr7_scan.py — run the NR7 edge across the WHOLE symbol universe (fresh OOS).

Answers "does NR7 work on all symbols, or just USTECm?" — honestly, by MEASURING
each on the most-recent M15 data with the exact prover rule. Reuses backtest()
from nr7_backtest.py so the logic is identical.

MULTIPLE-TESTING GUARD: scanning N symbols, ~1-2 pass t>=2 by pure luck. So the
deploy bar is STRICT — t>=3 AND expR>0 AND n>=30 — Bonferroni-aware. Everything
else is reported but is NOISE, not an edge. Only passers earn the magic-111111 prover.
"""
from __future__ import annotations
import MetaTrader5 as mt5
from nr7_backtest import backtest, stats, N_BARS

# strict deploy bar (multiple-testing aware)
MIN_N, MIN_T, MIN_EXPR = 30, 3.0, 0.0


def universe():
    syms = mt5.symbols_get() or []
    out = []
    for s in syms:
        name = s.name
        # Exness micro instruments; skip obvious non-tradeables
        if not name.endswith("m"):
            continue
        out.append(name)
    return sorted(set(out))


def main():
    if not mt5.initialize():
        print("mt5 init failed"); return
    syms = universe()
    print(f"scanning {len(syms)} symbols on M15 (NR7, fresh OOS, cost 3idx-pts)...\n")
    rows = []
    for name in syms:
        try:
            mt5.symbol_select(name, True)
            bars = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M15, 0, N_BARS)
            if bars is None or len(bars) < 300:
                continue
            st = stats([t[1] for t in backtest(bars)])
            if st.get("n", 0) >= 1:
                rows.append((name, st))
        except Exception:
            continue
    # sort by t-stat desc
    rows.sort(key=lambda r: (r[1].get("t") or -99), reverse=True)
    print(f"{'symbol':<12}{'n':>5}{'expR':>9}{'t':>7}{'WR%':>7}{'netR':>8}{'ddR':>8}  verdict")
    print("-" * 72)
    passers = []
    for name, st in rows:
        n, e, t = st.get("n", 0), st.get("expR", 0), st.get("t", 0)
        wr, net, dd = st.get("wr", 0), st.get("net_R", 0), st.get("max_dd_R", 0)
        ok = (n >= MIN_N and t >= MIN_T and e > MIN_EXPR)
        tag = "✅ PASS (strict)" if ok else ("• +ev" if e > 0 and t >= 2 else "✗")
        if ok: passers.append(name)
        print(f"{name:<12}{n:>5}{e:>9.3f}{t:>7.2f}{wr:>7.1f}{net:>8.1f}{dd:>8.1f}  {tag}")
    print("-" * 72)
    print(f"\nPASS strict bar (t>={MIN_T}, expR>0, n>={MIN_N}): {passers or 'NONE'}")
    print("→ deploy magic 111111 ONLY on these. Others = multiple-testing noise.")


if __name__ == "__main__":
    main()
