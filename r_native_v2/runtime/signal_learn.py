"""signal_learn.py — SHADOW learning: does the % actually predict? self-tune.

Answers the user's question: "لو 30% كانت فرصة أكبر من 85% كان دخلنا؟ وهل يضبط
نفسه؟" — we can only know by MEASURING. This shadow-tracks EVERY signal (every
confidence, even ones we didn't trade) and checks the outcome by price movement
after a horizon. Then it computes hit-rate PER CONFIDENCE BUCKET, so we discover
the TRUTH: maybe 30% wins more than 85% (mis-calibration). The executor reads the
recommended threshold from here and SELF-TUNES.

Outputs:
  data/signal_predictions.jsonl  — every logged prediction + its evaluated outcome
  data/signal_buckets.md         — hit-rate by confidence bucket (the learning)
  data/signal_tuning.json        — {recommended_min_conf, per_bucket} the executor reads
"""
from __future__ import annotations
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_V2 = Path(__file__).resolve().parent.parent
if str(_V2) not in sys.path:
    sys.path.insert(0, str(_V2))

COMMON = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")
DATA = _V2 / "data"
PRED = DATA / "signal_predictions.jsonl"
BUCKETS_MD = DATA / "signal_buckets.md"
TUNING = DATA / "signal_tuning.json"

SYMBOLS = ["XAUUSDm", "BTCUSDm", "EURUSDm", "GBPUSDm", "XAGUSDm"]
HORIZON_S = 600             # judge a prediction 10 min after it was made (faster feedback)
MIN_MOVE_FRAC = 0.20        # price must move >= this * ATR(at-call) to count as a hit/miss
LOG_EVERY_S = 60            # log a fresh prediction per symbol every 1 min (more data, fast)
POLL = 20


def _now():
    return time.time()


def _bucket(c):
    if c >= 90: return "90-100"
    if c >= 80: return "80-90"
    if c >= 70: return "70-80"
    if c >= 60: return "60-70"
    if c >= 50: return "50-60"
    if c >= 40: return "40-50"
    if c >= 30: return "30-40"
    return "<30"


def _read_signal(symbol):
    f = COMMON / f"signal_{symbol}.json"
    try:
        if not f.exists() or time.time() - f.stat().st_mtime > 90:
            return None
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if d.get("symbol") == symbol else None
    except Exception:
        return None


def _atr(mt5, symbol, n=14):
    r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, n + 2)
    if r is None or len(r) < n + 1:
        return None
    import numpy as np
    h = np.array([x["high"] for x in r]); l = np.array([x["low"] for x in r])
    c = np.array([x["close"] for x in r]); pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return float(np.mean(tr[-n:]))


def _load_preds():
    rows = []
    if PRED.exists():
        for ln in PRED.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try: rows.append(json.loads(ln))
                except Exception: pass
    return rows


def _save_preds(rows):
    PRED.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def cycle(mt5):
    rows = _load_preds()
    last_log = {}
    for r in rows:
        if r.get("outcome") is None:
            last_log[r["symbol"]] = max(last_log.get(r["symbol"], 0), r["ts"])

    # 1) log fresh predictions (every symbol, EVERY confidence — even low/WAIT)
    for symbol in SYMBOLS:
        sig = _read_signal(symbol)
        if not sig:
            continue
        if _now() - last_log.get(symbol, 0) < LOG_EVERY_S:
            continue
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            continue
        atr = _atr(mt5, symbol) or 0.0
        action = sig.get("action", "WAIT")
        conf = float(sig.get("confidence") or 0)
        # for WAIT we still log the directional LEAN (score sign) so we can test
        # whether low-confidence leans are actually predictive
        score = float(sig.get("score") or 0)
        lean = "BUY" if score > 0 else "SELL" if score < 0 else "FLAT"
        rows.append({
            "ts": int(_now()), "iso": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol, "action": action, "lean": lean,
            "confidence": conf, "bucket": _bucket(conf), "score": score,
            "components": sig.get("components", {}),   # raw pillars for the optimizer
            "price": float(tick.bid), "atr": round(atr, 5), "outcome": None,
        })

    # 2) evaluate matured predictions
    now = _now()
    for r in rows:
        if r.get("outcome") is not None:
            continue
        if now - r["ts"] < HORIZON_S:
            continue
        tick = mt5.symbol_info_tick(r["symbol"])
        if not tick:
            continue
        cur = float(tick.bid)
        move = cur - r["price"]
        thr = max(r.get("atr", 0) * MIN_MOVE_FRAC, 1e-9)
        d = r["lean"]                      # judge the directional lean
        if d == "FLAT":
            r["outcome"] = "flat"
        elif abs(move) < thr:
            r["outcome"] = "neutral"       # didn't move enough either way
        else:
            went_up = move > 0
            correct = (d == "BUY" and went_up) or (d == "SELL" and not went_up)
            r["outcome"] = "hit" if correct else "miss"
        r["move"] = round(move, 5)
    if len(rows) > 5000:
        rows = rows[-5000:]
    _save_preds(rows)

    # 3) aggregate hit-rate by bucket (only decided hit/miss)
    by_bucket = defaultdict(lambda: [0, 0])   # bucket -> [decided, hits]
    for r in rows:
        if r.get("outcome") in ("hit", "miss"):
            b = r["bucket"]
            by_bucket[b][0] += 1
            by_bucket[b][1] += 1 if r["outcome"] == "hit" else 0

    # 4) recommend a threshold: lowest bucket with enough samples AND hit-rate >= 55%
    order = ["<30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100"]
    per_bucket = {}
    for b in order:
        if b in by_bucket:
            n, h = by_bucket[b]
            per_bucket[b] = {"n": n, "hit_rate": round(100 * h / n, 1) if n else 0.0}
    # find lowest bucket (by confidence floor) with n>=8 and hit_rate>=55
    floor = {"<30": 0, "30-40": 30, "40-50": 40, "50-60": 50, "60-70": 60,
             "70-80": 70, "80-90": 80, "90-100": 90}
    rec = 50.0          # until enough data, trade decent setups (>=50); learning raises/lowers
    best = None
    for b in order:
        pb = per_bucket.get(b)
        if pb and pb["n"] >= 8 and pb["hit_rate"] >= 55.0:
            best = b; break
    if best is not None:
        rec = float(floor[best])
    total_decided = sum(v[0] for v in by_bucket.values())
    total_hits = sum(v[1] for v in by_bucket.values())
    overall_hit = round(100 * total_hits / total_decided, 1) if total_decided else 0.0
    # learning is "mature" only after enough decided samples AND a real edge
    # (edge can be FOLLOW the signal OR FADE = trade the opposite if it's inverse-predictive)
    edge = max(overall_hit, 100 - overall_hit)   # best achievable by follow OR fade
    mature = bool(total_decided >= 50 and edge >= 58.0)
    # FOLLOW vs FADE: if the signal is consistently WRONG (<45%), trade the OPPOSITE
    mode = "FOLLOW"
    if total_decided >= 15:
        if overall_hit <= 45.0:
            mode = "FADE"          # signal is inverse-predictive -> flip BUY<->SELL
        elif overall_hit >= 55.0:
            mode = "FOLLOW"
        else:
            mode = "FOLLOW"        # 45-55%: no edge either way
    # per-bucket follow/fade hit-rate (so we SEE that e.g. 30% bucket -> 70% if faded)
    for b, pb in per_bucket.items():
        pb["fade_hit_rate"] = round(100 - pb["hit_rate"], 1)
    TUNING.write_text(json.dumps({
        "recommended_min_conf": rec,
        "mode": mode,
        "total_decided": total_decided,
        "overall_hit_rate": overall_hit,
        "fade_hit_rate": round(100 - overall_hit, 1),
        "edge_best": edge,
        "mature": mature,
        "rationale": (f"lowest bucket with n>=8 & hit>=55% is {best} ({per_bucket.get(best)})"
                      if best else "no bucket cleared 55% with n>=8 yet — default 50"),
        "per_bucket": per_bucket,
        "ts": int(now),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) human report
    L = ["# هل النسبة تصدق؟ — دقّة كل شريحة ثقة (تعلّم ظلّي)\n",
         f"_تحديث {datetime.now(timezone.utc).isoformat()} · أفق الحكم {HORIZON_S//60} دقيقة_\n",
         "كل إشارة (حتى اللي ما دخلناها) تُسجّل، ونتحقق بعد فترة هل السعر صدق الاتجاه.\n",
         "| شريحة الثقة | عيّنات | صدق% (متابعة) | معكوس% (عكس) |", "|---|---|---|---|"]
    for b in order:
        if b in per_bucket:
            pb = per_bucket[b]
            L.append(f"| {b}% | {pb['n']} | {pb['hit_rate']}% | {pb.get('fade_hit_rate', 0)}% |")
    decided = sum(v[0] for v in by_bucket.values())
    L.append(f"\n**الوضع المُتعلَّم: {mode}**  (صدق متابعة {overall_hit}% · عكس {round(100-overall_hit,1)}%)")
    L.append(f"> FOLLOW = نتبع الإشارة · **FADE = نعكسها** (نبيع لما تقول اشترِ) لأنها تخسر باستمرار")
    L.append(f"\n**العتبة الموصى بها للتداول: ≥ {rec:.0f}%**")
    L.append(f"\n_(محكوم {decided} إشارة. القاعدة: أدنى شريحة عيّناتها ≥8 ودقّتها ≥55%.)_")
    L.append("\n> هذا يجاوب: هل 30% فعلاً أفضل من 85%؟ — لو شريحة 30-40% طلعت دقّتها أعلى،")
    L.append("> النظام **يخفّض العتبة لها تلقائياً** ويتداولها. لو لا، يبقى على الثقة العالية.")
    BUCKETS_MD.write_text("\n".join(L), encoding="utf-8")
    return {"decided": decided, "rec": rec, "buckets": per_bucket}


def main(argv=None):
    import MetaTrader5 as mt5
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args(argv)
    if not mt5.initialize():
        print("MT5 init failed"); return 1
    try:
        while True:
            try:
                r = cycle(mt5)
                print(f"[learn] decided={r['decided']} rec_min_conf={r['rec']:.0f} buckets={r['buckets']}", flush=True)
            except Exception as e:
                print(f"[learn] error: {e}", flush=True)
            if not (args.loop and not args.once):
                break
            time.sleep(POLL)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
