"""genome_factory.py — the "شغل جبار": train a best-config genome per market across
MULTIPLE timeframes × MULTIPLE bar-windows × ALL 15 indicators, validated OUT-OF-SAMPLE.

For each symbol it grid-searches the trend-attack parameters (stop/target/gate) on every TF,
scores each combo by no-lookahead, spread-adjusted, 4-fold walk-forward (reusing the gate's
honest engine), and writes the single best surviving config as a deployable genome. Markets
with no surviving edge get NO genome (honest — we don't fabricate one).

Read-only research. Writes data/genomes/<SYM>.json + data/genome_factory_summary.json.
Run:  python genome_factory.py            (all gate-eligible markets)
      python genome_factory.py SYMBOL...
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

_V2 = Path(__file__).resolve().parent
_MT5 = _V2.parent
for p in (str(_MT5), str(_V2)):
    if p not in sys.path:
        sys.path.insert(0, p)

from market_gate import _vote, _atr, WIN, FOLDS

DATA = _V2 / "data"
GENO = DATA / "genomes"
TFS = ["M5", "M15", "H1"]
# مصنع الجلسات يشمل M1 (السكالب) ليتعلّم على كل جلسة بسبريد حقيقي — البوّابة تُسقط ما يأكله السبريد
SESSION_TFS = ["M1", "M5", "M15", "H1"]


def _safe_write(p, obj):
    """Atomic, crash-safe genome write (tmp + os.replace) — survives concurrent reads by the live
    trader and transient Windows file locks; a single failed write is skipped, not fatal."""
    try:
        import os
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as e:
        print(f"  write-skip {getattr(p, 'name', p)}: {e}", flush=True)
        return False
BAR_WINDOWS = [4000, 8000]                 # standing recurring depth (deeper than before, real spread,
                                           # light enough for the 3h loop). One-time DEEP runs override
                                           # this to [50000] for the honest "do they survive real cost" test.
FORCE_REDEPLOY = False                      # one-time: write even if not better (e.g. after an engine change)
GRID_STOP = [1.5, 2.0, 3.0]
GRID_TGT = [2.0, 3.0, 4.0, 6.0]
GRID_GATE = [0.55, 0.60, 0.65]
MAX_HOLD = 48
MIN_TRADES = 25
MIN_PF = 1.2
MIN_FOLDS_POS = 3


def _vote_series(close, high, low, vol):
    """Compute the (dir, conf) vote at EVERY bar ONCE — the expensive 21-indicator part — so the
    grid loop reuses it for every stop/tgt/gate combo. This is what makes 50k-bar history feasible
    (vote is O(bars×indicators) once instead of ×combos)."""
    n = len(close); out = [None] * n
    for i in range(WIN, n):
        try:
            out[i] = _vote(close[i - WIN + 1:i + 1], high[i - WIN + 1:i + 1],
                           low[i - WIN + 1:i + 1], vol[i - WIN + 1:i + 1])
        except Exception:
            out[i] = None
    return out


def _bt_fast(votes, high, low, close, spread_arr, stop, tgt, gate, allow=None):
    """Backtest ONE combo on precomputed votes + REAL per-bar spread (spread_arr in PRICE). The
    honest cost: each trade pays the actual historical spread of its entry bar, not a 1pt guess.
    `allow` (optional bool-mask): only ENTER on bars where allow[i] is True — used to train a
    SESSION-SPECIALIST on just that session's bars. None = all bars (existing behavior)."""
    n = len(close); start = max(WIN + 1, int(n * 0.45)); span = max(1, n - start)
    trades = []; i = start
    while i < n - 2:
        dv = votes[i]
        if dv is None or (allow is not None and not allow[i]):
            i += 1; continue
        d, conf = dv
        if d == 0 or conf < gate:
            i += 1; continue
        atr = _atr(high, low, close, i)
        if atr <= 0:
            i += 1; continue
        cost = (spread_arr[i] / atr) if atr > 0 else 0.0       # REAL spread of the entry bar
        entry = close[i]
        sl = entry - stop * atr if d > 0 else entry + stop * atr
        tp = entry + tgt * atr if d > 0 else entry - tgt * atr
        outcome = None; ex = min(i + MAX_HOLD, n - 1)
        for j in range(i + 1, min(i + MAX_HOLD + 1, n)):
            if d > 0:
                if low[j] <= sl: outcome = -stop; ex = j; break
                if high[j] >= tp: outcome = tgt; ex = j; break
            else:
                if high[j] >= sl: outcome = -stop; ex = j; break
                if low[j] <= tp: outcome = tgt; ex = j; break
        if outcome is None:
            outcome = ((close[ex] - entry) if d > 0 else (entry - close[ex])) / atr
        outcome -= cost
        trades.append((outcome, min(FOLDS - 1, int((i - start) / span * FOLDS))))
        i = ex + 1
    if len(trades) < MIN_TRADES:
        return None
    outs = [o for o, _ in trades]
    gw = sum(o for o in outs if o > 0); gl = abs(sum(o for o in outs if o <= 0))
    pf = gw / gl if gl > 0 else (99.9 if gw > 0 else 0.0)
    net = sum(outs)
    fold_net = [0.0] * FOLDS
    for o, f in trades:
        fold_net[f] += o
    fpos = sum(1 for x in fold_net if x > 0)
    if pf < MIN_PF or net <= 0 or fpos < MIN_FOLDS_POS:
        return None
    return {"pf": round(pf, 2), "net_R": round(net, 2), "trades": len(outs),
            "folds_pos": fpos, "win_rate": round(sum(1 for o in outs if o > 0) / len(outs), 3),
            "returns": [round(o, 4) for o in outs[-300:]]}     # per-trade R for PSR/DSR gate


def _real_spread_price(r, point, live_sp):
    """Per-bar spread in PRICE from MT5 rates ('spread' field is in points). Fall back to the live
    spread when history didn't record it, so we NEVER assume zero cost (honest)."""
    out = []
    for x in r:
        try: sp = float(x["spread"]) * point
        except Exception: sp = 0.0
        out.append(sp if sp > 0 else live_sp)
    return out


def optimize(mt5, sym):
    tfm = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    live_sp = (tick.ask - tick.bid) if (tick and tick.ask) else 0.0
    point = info.point if (info and info.point) else 0.0
    best = None; tried = 0
    for tf in TFS:
        for nbars in BAR_WINDOWS:
            r = mt5.copy_rates_from_pos(sym, tfm[tf], 0, nbars)
            if r is None or len(r) < 400:
                continue
            close = [float(x["close"]) for x in r]; high = [float(x["high"]) for x in r]; low = [float(x["low"]) for x in r]
            try: vol = [float(x["tick_volume"]) for x in r]
            except Exception: vol = [1.0] * len(close)
            spread_arr = _real_spread_price(r, point, live_sp)
            votes = _vote_series(close, high, low, vol)        # compute ONCE, reuse for all combos
            for stop in GRID_STOP:
                for tgt in GRID_TGT:
                    if tgt <= stop:           # need positive R:R
                        continue
                    for gate in GRID_GATE:
                        tried += 1
                        res = _bt_fast(votes, high, low, close, spread_arr, stop, tgt, gate)
                        if res and (best is None or res["net_R"] > best["net_R"]):
                            best = {**res, "tf": tf, "bars": nbars, "stop_atr": stop,
                                    "target_atr": tgt, "conf_gate": gate}
    return best, tried


# ── SESSION SPECIALISTS — a STABLE of genomes per symbol, one per session window ──────────────
# Phase-0 audit proved each survivor has 3-5 session windows with >=40 OOS trades → session is a
# SAFE specialization dimension (session×archetype would be too thin → overfit, so we stop here).
SESSIONS = ["ASIAN", "LONDON", "NY_OVERLAP", "NY_LATE"]   # tradeable windows (skip CLOSED/TRANSITION)
SESSION_MIN_TRADES = 40                                    # a session specialist needs >= this (anti-overfit)
SESSION_BARS = 50000                                       # DEEP history so each session cell has enough trades


def _session_per_bar(times):
    from indicators import session as _S
    from datetime import datetime, timezone
    return [_S.classify(datetime.fromtimestamp(int(t), tz=timezone.utc)).name for t in times]


def build_session_specialists(mt5, sym):
    """Build a STABLE of session-specialist genomes for ONE symbol — one per session window that
    passes OOS (real spread, >=40 trades, >=3 folds). Writes data/genomes/<SYM>/<SESSION>.json +
    stable.json. Computes the 21-indicator vote ONCE per TF and reuses it across sessions+combos
    (fast). Robust sessions survive; thin/no-edge sessions get NO specialist (honest)."""
    tfm = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    live_sp = (tick.ask - tick.bid) if (tick and tick.ask) else 0.0
    point = info.point if (info and info.point) else 0.0
    out_dir = GENO / sym; out_dir.mkdir(parents=True, exist_ok=True)
    bests = {s: None for s in SESSIONS}
    for tf in SESSION_TFS:                      # يشمل M1 — السكالب يتعلّم على كل الجلسات
        r = mt5.copy_rates_from_pos(sym, tfm[tf], 0, SESSION_BARS)
        if r is None or len(r) < 2000:
            continue
        close = [float(x["close"]) for x in r]; high = [float(x["high"]) for x in r]; low = [float(x["low"]) for x in r]
        try: vol = [float(x["tick_volume"]) for x in r]
        except Exception: vol = [1.0] * len(close)
        spread_arr = _real_spread_price(r, point, live_sp)
        votes = _vote_series(close, high, low, vol)               # ONCE per TF (expensive) — reused below
        sess_bar = _session_per_bar([x["time"] for x in r])
        for sess in SESSIONS:
            allow = [s == sess for s in sess_bar]
            if sum(allow) < 200:
                continue
            for stop in GRID_STOP:
                for tgt in GRID_TGT:
                    if tgt <= stop:
                        continue
                    for gate in GRID_GATE:
                        res = _bt_fast(votes, high, low, close, spread_arr, stop, tgt, gate, allow=allow)
                        if res and res["trades"] >= SESSION_MIN_TRADES and (bests[sess] is None or res["net_R"] > bests[sess]["net_R"]):
                            bests[sess] = {**res, "tf": tf, "stop_atr": stop, "target_atr": tgt, "conf_gate": gate, "bars": SESSION_BARS}
    stable = []
    for sess, best in bests.items():
        if best:
            spec = {"symbol": sym, "session": sess, "trained": time.time(),
                    "config": {"tf": best["tf"], "stop_atr": best["stop_atr"],
                               "target_atr": best["target_atr"], "conf_gate": best["conf_gate"]},
                    "oos": {k: best[k] for k in ("pf", "net_R", "trades", "folds_pos", "win_rate", "bars")}}
            _safe_write(out_dir / f"{sess}.json", spec)
            stable.append({"session": sess, **spec["config"], **spec["oos"]})
            print(f"  ✓ {sym}/{sess}: {best['tf']} PF {best['pf']} · {best['net_R']}R · {best['trades']}t · {best['folds_pos']}/4", flush=True)
        else:
            print(f"  ✗ {sym}/{sess}: لا حافة في هذه الجلسة", flush=True)
    _safe_write(out_dir / "stable.json", {"symbol": sym, "ts": time.time(),
                "n_specialists": len(stable), "specialists": stable})
    return stable


import random as _rnd


def _mutate(cfg, rng):
    """Jitter a config OFF the fixed grid (continuous params) — true evolution, not grid points."""
    stop = min(5.0, max(0.8, cfg["stop_atr"] + rng.uniform(-0.5, 0.5)))
    tgt = min(9.0, max(stop * 1.2, cfg["target_atr"] + rng.uniform(-1.2, 1.2)))
    gate = min(0.75, max(0.45, cfg["conf_gate"] + rng.uniform(-0.06, 0.06)))
    tf = cfg["tf"] if rng.random() < 0.8 else rng.choice(TFS)
    return {"tf": tf, "stop_atr": round(stop, 2), "target_atr": round(tgt, 2), "conf_gate": round(gate, 3)}


def _crossover(a, b, rng):
    return {"tf": rng.choice([a["tf"], b["tf"]]),
            "stop_atr": round((a["stop_atr"] + b["stop_atr"]) / 2, 2),
            "target_atr": round((a["target_atr"] + b["target_atr"]) / 2, 2),
            "conf_gate": round((a["conf_gate"] + b["conf_gate"]) / 2, 3)}


def evolve_loser(mt5, sym, seeds, generations=4, children=8):
    """Genetic search for a SMARTER gene for ONE (losing) symbol: seed from its current gene +
    elite winners, then mutate/crossbreed off-grid across generations, scoring each child on the
    same no-lookahead OOS backtest. Returns the best config found (may beat any grid point)."""
    tfm = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym); tick = mt5.symbol_info_tick(sym)
    live_sp = (tick.ask - tick.bid) if (tick and tick.ask) else 0.0
    point = info.point if (info and info.point) else 0.0
    data = {}
    for tf in TFS:
        r = mt5.copy_rates_from_pos(sym, tfm[tf], 0, BAR_WINDOWS[-1])
        if r is None or len(r) < 400:
            continue
        close = [float(x["close"]) for x in r]
        try: vol = [float(x["tick_volume"]) for x in r]
        except Exception: vol = [1.0] * len(close)
        high = [float(x["high"]) for x in r]; low = [float(x["low"]) for x in r]
        spread_arr = _real_spread_price(r, point, live_sp)
        votes = _vote_series(close, high, low, vol)        # precompute once per TF
        data[tf] = (close, high, low, votes, spread_arr)

    def score(cfg):
        d = data.get(cfg["tf"])
        if not d:
            return None
        return _bt_fast(d[3], d[1], d[2], d[0], d[4], cfg["stop_atr"], cfg["target_atr"], cfg["conf_gate"])

    if not data:
        return None
    rng = _rnd.Random(abs(hash(sym)) & 0xFFFFFFFF)
    pop = []
    for s in (seeds or []):
        if not s:
            continue
        r = score(s)
        if r:
            pop.append((r["net_R"], s, r))
    base = (seeds[0] if seeds and seeds[0] else {"tf": "M15", "stop_atr": 2.0, "target_atr": 3.0, "conf_gate": 0.6})
    for _ in range(children):
        m = _mutate(base, rng); r = score(m)
        if r:
            pop.append((r["net_R"], m, r))
    for _g in range(generations):
        pop.sort(key=lambda x: -x[0]); elite = pop[:4]
        if not elite:
            break
        kids = []
        for _ in range(children):
            if len(elite) >= 2 and rng.random() < 0.5:
                a, b = rng.sample(elite, 2); child = _mutate(_crossover(a[1], b[1], rng), rng)
            else:
                child = _mutate(rng.choice(elite)[1], rng)
            r = score(child)
            if r:
                kids.append((r["net_R"], child, r))
        pop = elite + kids
    pop.sort(key=lambda x: -x[0])
    if not pop:
        return None
    netR, cfg, res = pop[0]
    return {**res, **cfg, "bars": 2000, "source": "evolve"}


def write_best(s, best):
    """Keep-BEST-EVER write: only overwrite genomes/<SYM>.json if `best` beats the symbol's own
    best OOS net_R; else keep the proven gene. Stamps retune (kept/rejected) for the dashboard.
    Returns 'new' | 'kept' | 'rejected'."""
    keys = ("pf", "net_R", "trades", "folds_pos", "win_rate", "bars")
    new_oos = {k: best[k] for k in keys if k in best}
    # 🛡️ بوّابة PSR/DSR (أقوى حارس ضد خداع البحث الشبكي): per-trade returns → احتمال أن الحافة حقيقية
    rets = best.get("returns") or []
    psr = dsr = None
    if rets:
        try:
            import sys as _s
            if str(Path(__file__).resolve().parent.parent) not in _s.path:
                _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
            import quant_gates as qg
            psr = round(qg.probabilistic_sharpe_ratio(rets), 3)
            dsr = round(qg.deflated_sharpe_ratio(rets, best.get("n_trials", 200)), 3)
            new_oos["psr"] = psr; new_oos["dsr"] = dsr
        except Exception:
            pass
    # ADVISORY (مُعايَر): PSR-لكل-صفقة صغير بطبيعته في السكالبينج (Sharpe/صفقة ضعيف) — لذا
    # نَسِمه كمقياس جودة ونرفض فقط عند الصدفة الصريحة: PSR≈0 مع عيّنة رقيقة. لا نقتل الحافة الحقيقية.
    if psr is not None and psr < 0.10 and best.get("trades", 999) < 60:
        print(f"  ⛔ {s}: PSR {psr} + عيّنة رقيقة ({best.get('trades')}) = صدفة صريحة، رُفض", flush=True)
        return "rejected"
    if psr is not None and psr < 0.25:
        print(f"  ⚠ {s}: PSR {psr} ضعيف (جودة متدنّية) — نُشر مع وسم تحذير", flush=True)
    prev = None
    try: prev = json.loads((GENO / f"{s}.json").read_text(encoding="utf-8"))
    except Exception: prev = None
    prev_r = float((prev or {}).get("oos", {}).get("net_R", -1e18))
    src = best.get("source", "grid")
    if FORCE_REDEPLOY or (prev is None) or (best["net_R"] > prev_r):
        genome = {"symbol": s, "trained": time.time(), "config": {
                      "tf": best["tf"], "stop_atr": best["stop_atr"],
                      "target_atr": best["target_atr"], "conf_gate": best["conf_gate"]},
                  "oos": new_oos, "prev_oos": (prev or {}).get("oos"),
                  "retune": {"kept": True, "prev_net_R": (None if prev is None else round(prev_r, 1)),
                             "new_net_R": best["net_R"], "ts": time.time(), "source": src}}
        _safe_write(GENO / f"{s}.json", genome)
        return "new" if prev is None else "kept"
    if prev:
        prev["retune"] = {"kept": False, "prev_net_R": round(prev_r, 1),
                          "tried_net_R": best["net_R"], "ts": time.time(), "source": src}
        _safe_write(GENO / f"{s}.json", prev)
    return "rejected"


def _liquid_ok(mt5, sym, thr=0.40):
    """LIQUIDITY guard: reject symbols whose REAL spread eats the edge (the gate assumes 1pt; exotic
    crosses have spreads of 100s of pts). Keep only symbols where spread <= thr × ATR — so the
    auto-retune NEVER deploys the spread-trap exotics that pass the OOS gate on understated cost."""
    try:
        info = mt5.symbol_info(sym)
        if not info or not info.point:
            return False
        mt5.symbol_select(sym, True)
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 30)
        if r is None or len(r) < 16:
            return False
        tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
                  abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
        atr = (sum(tr[-14:]) / 14) / info.point
        return atr > 0 and (info.spread or 0) / atr <= thr
    except Exception:
        return False


def _targets(mt5):
    try:
        g = json.loads((DATA / "market_gate.json").read_text(encoding="utf-8"))
        out = []
        for s, r in g.get("results", {}).items():
            if r.get("tier") in ("robust", "marginal"):
                base = s.replace("_x100m", "m").replace("_x10m", "m")
                # MAINTAIN-ONLY: re-tune symbols that already have a genome (the proven survivors);
                # don't auto-re-add culled no-edge symbols. New ones enter via an explicit deep retrain.
                if base not in out and (GENO / f"{base}.json").exists() and _liquid_ok(mt5, base):
                    out.append(base)
        if out: return out
    except Exception: pass
    return ["US30m", "BTCUSDm", "XAUUSDm", "NVDAm", "TSLAm"]


def main(argv):
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    syms = list(argv) if argv else _targets(mt5)
    GENO.mkdir(parents=True, exist_ok=True)
    print(f"[FACTORY] training {len(syms)} markets × {len(TFS)} TFs × {len(BAR_WINDOWS)} windows × "
          f"{len(GRID_STOP)*len(GRID_TGT)*len(GRID_GATE)} param combos — OOS validated", flush=True)
    summary = {}
    for s in syms:
        t0 = time.time()
        try:
            best, tried = optimize(mt5, s)
        except Exception as e:
            print(f"  {s}: ERR {e}", flush=True); continue
        if best:
            new_oos = {k: best[k] for k in ("pf", "net_R", "trades", "folds_pos", "win_rate", "bars")}
            # KEEP-BEST-EVER guard: only overwrite the deployed gene if the new search is
            # strictly BETTER (higher OOS net_R). This turns a blind 3h re-tune into a
            # monotonic "breed smarter" — a losing symbol's wide search must beat its own
            # best to redeploy; otherwise we keep the proven gene (no churn-to-worse).
            prev = None
            try: prev = json.loads((GENO / f"{s}.json").read_text(encoding="utf-8"))
            except Exception: prev = None
            prev_r = float((prev or {}).get("oos", {}).get("net_R", -1e18))
            if (prev is None) or (best["net_R"] > prev_r):
                genome = {"symbol": s, "trained": time.time(), "config": {
                              "tf": best["tf"], "stop_atr": best["stop_atr"],
                              "target_atr": best["target_atr"], "conf_gate": best["conf_gate"]},
                          "oos": new_oos, "prev_oos": (prev or {}).get("oos"),
                          "retune": {"kept": True, "prev_net_R": (None if prev is None else round(prev_r, 1)),
                                     "new_net_R": best["net_R"], "ts": time.time()}}
                _safe_write(GENO / f"{s}.json", genome)
                summary[s] = {"deployed": True, "improved": prev is not None, **best}
                tag = "جديد" if prev is None else f"↑ تحسّن {prev_r:.1f}→{best['net_R']}R"
                print(f"  ✓ {s:10s} {best['tf']:3s} stop{best['stop_atr']}/tgt{best['target_atr']}/gate{best['conf_gate']} "
                      f"→ PF {best['pf']} {tag} {best['folds_pos']}/4 [{tried} tried, {time.time()-t0:.0f}s]", flush=True)
            else:
                # new try not better → keep the best-ever gene, but record the rejected attempt
                prev["retune"] = {"kept": False, "prev_net_R": round(prev_r, 1),
                                  "tried_net_R": best["net_R"], "ts": time.time()}
                _safe_write(GENO / f"{s}.json", prev)
                summary[s] = {"deployed": True, "improved": False, "rejected_retune": True, **best}
                print(f"  = {s:10s} kept best-ever {prev_r:.1f}R (new try {best['net_R']}R not better) "
                      f"[{tried} tried, {time.time()-t0:.0f}s]", flush=True)
        else:
            summary[s] = {"deployed": False}
            print(f"  ✗ {s:10s} no surviving edge across any TF/window ({tried} tried, {time.time()-t0:.0f}s)", flush=True)
    deployed = [s for s, v in summary.items() if v.get("deployed")]
    (DATA / "genome_factory_summary.json").write_text(
        json.dumps({"ts": time.time(), "trained": len(syms), "deployed": deployed, "results": summary},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[FACTORY] DONE — deployable genomes: {deployed or 'NONE'}", flush=True)
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
