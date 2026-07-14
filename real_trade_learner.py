# -*- coding: utf-8 -*-
"""real_trade_learner.py — تعلّم من صفقات الديمو المنفّذة فعلاً (صافي التكلفة).

(قراءة-فقط من friday.db، windowless تحت الوصيّ — لا order_send.)

الفرق الجوهري عن العقل العميق: هذا يتعلّم من **النتائج الحقيقية للصفقات المنفّذة**
(pnl + commission + swap = صافي السبريد والانزلاق) لا من تنبّؤ ظلّي إجمالي. فالثقة هنا
ثقة حقيقية: «هذا الشرط ربح فعلاً صافيةً على الديمو، معنوياً، بعد Bonferroni».

يربط جدول features (خصائص الدخول لكل ticket) بجدول trades (الصافي المحقّق)، ويحكم على:
  rsi-regime · atr-regime · الجلسة · الرمز · الاتجاه · تركيبات (rsi×جلسة، رمز×اتجاه).
يكتب:
  data/r_native/real_learning.json — التقرير الكامل (كل شرط: n/صافي/t/فوز/حُكم).
  data/r_native/real_rules.json    — قواعد قابلة للتنفيذ (veto/favor) يستهلكها جسر القناعة.

صدق علمي: t حقيقي بالانحراف، Bonferroni على عدد الشروط، n≥30 للحُكم. لا overfitting.
"""
from __future__ import annotations
import json, math, sqlite3, time
from pathlib import Path

try:
    import MetaTrader5 as mt5
    _HAVE_MT5 = True
except Exception:
    _HAVE_MT5 = False

ROOT = Path(r"C:\Users\Radhi\MT5")
DB = ROOT / "data" / "friday.db"
RN = ROOT / "data" / "r_native"
OUT = RN / "real_learning.json"
RULES = RN / "real_rules.json"
DOSSIER = RN / "deep_dossier.json"
FPRINTS = RN / "trade_fingerprints.json"   # بصمة كل صفقة مفتوحة (خصائص العقل الغنيّة) للتعلّم الأمامي
LOG = RN / "real_trade_learner.log"
PROT = {0, 2447, 20250418, 20250421, 20250422, 20250618}

POLL_S = 300.0          # أعِد التحليل كل 5 دقائق (مع تراكم صفقات جديدة)
MIN_N = 30              # أدنى عيّنة للحُكم
ALPHA = 0.05            # دلالة (بعد Bonferroni)
OUR_MAGICS = (20260605, 20260608, 20260611, 20260612, 20260613, 20260614,
              20260616, 20260617, 20260618, 20260626)


def _log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")
    except Exception:
        pass


def _rsi_b(v):
    if v is None:
        return None
    return "ob" if v > 70 else "os" if v < 30 else "neutral"


def _atr_b(p):
    if p is None:
        return None
    return "hi" if p >= 0.66 else "lo" if p <= 0.33 else "mid"


def _sess(ts):
    h = time.gmtime(ts).tm_hour
    return "asia" if h < 7 else "london" if h < 12 else "ny" if h < 21 else "off"


def _bstat(rs):
    n = len(rs)
    if n < 2:
        return {"n": n, "net": 0.0, "t": 0.0, "win": 0, "total": round(sum(rs), 2)}
    m = sum(rs) / n
    var = sum((x - m) ** 2 for x in rs) / n
    sd = math.sqrt(var)
    t = m / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "net": round(m, 3), "t": round(t, 2),
            "win": round(100 * sum(1 for x in rs if x > 0) / n), "total": round(sum(rs), 2)}


def _p_two(t):
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t) / math.sqrt(2.0))))


def _load_trades():
    """يربط خصائص الدخول بالصافي المحقّق لصفقاتنا المُغلقة."""
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except Exception:
        c = sqlite3.connect(str(DB))
    # FIX (2026-06-30): the recorder logs f.ticket = the entry POSITION ticket,
    # but trades.ticket = the closing DEAL ticket (different id in MT5 hedging).
    # Joining only on t.ticket froze the set at 3527 (old single-deal rows where
    # ticket==position_id). Join on (ticket OR position_id) so EVERY newly closed
    # trade is ingested each cycle and the forward set grows. No double-count:
    # verified no feature ticket matches >1 closed trade.
    q = ("select f.symbol, f.side, f.rsi, f.atr_pctile, f.ts, "
         "(t.pnl + t.commission + t.swap) net, t.magic "
         "from features f join trades t "
         "on (f.ticket = t.ticket or f.ticket = t.position_id) "
         "where t.exit is not null")
    rows = []
    for sym, side, rsi, ap, ts, net, magic in c.execute(q).fetchall():
        if net is None:
            continue
        if isinstance(side, (int, float)):
            sd = "BUY" if int(side) == 0 else "SELL"
        else:
            sd = str(side or "").upper()
            if sd in ("0", "BUY"): sd = "BUY"
            elif sd in ("1", "SELL"): sd = "SELL"
        rows.append({"sym": sym, "side": sd, "rsi_b": _rsi_b(rsi),
                     "atr_b": _atr_b(ap), "sess": _sess(ts or time.time()), "net": float(net)})
    c.close()
    return rows


def analyze(rows):
    if not rows:
        return None
    buckets = {}

    def add(key, net):
        buckets.setdefault(key, []).append(net)

    for r in rows:
        if r["rsi_b"]:
            add(f"rsi={r['rsi_b']}", r["net"])
            add(f"{r['sess']}|rsi={r['rsi_b']}", r["net"])
        if r["atr_b"]:
            add(f"atr={r['atr_b']}", r["net"])
        add(f"sess={r['sess']}", r["net"])
        add(f"sym={r['sym']}", r["net"])
        if r["side"]:
            add(f"symdir={r['sym']}:{r['side']}", r["net"])
    stats = {k: _bstat(v) for k, v in buckets.items() if len(v) >= MIN_N}
    n_tests = max(len(stats), 1)
    pos, neg = {}, {}
    for k, s in stats.items():
        if abs(s["t"]) <= 2:
            continue
        bonf = _p_two(s["t"]) * n_tests < ALPHA
        s = {**s, "bonf": bonf}
        (pos if s["net"] > 0 else neg)[k] = s
    overall = _bstat([r["net"] for r in rows])
    return {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "n": len(rows), "n_tests": n_tests,
            "overall": overall, "conditions": dict(sorted(stats.items(), key=lambda kv: kv[1]["net"])),
            "favors": dict(sorted(pos.items(), key=lambda kv: -kv[1]["t"])),
            "vetoes": dict(sorted(neg.items(), key=lambda kv: kv[1]["t"]))}


def _capture_fingerprints():
    """يلتقط بصمة (خصائص العقل الـ14 الغنيّة) لكل صفقة مفتوحة جديدة — للتعلّم الأمامي المستمرّ."""
    if not _HAVE_MT5:
        return
    try:
        if not (mt5.initialize() or mt5.initialize()):
            return
    except Exception:
        return
    try:
        fp = json.load(open(FPRINTS, encoding="utf-8-sig"))
    except Exception:
        fp = {}
    try:
        doss = json.load(open(DOSSIER, encoding="utf-8-sig")).get("symbols", {})
    except Exception:
        doss = {}
    changed = False
    try:
        for p in (mt5.positions_get() or []):
            if p.magic in PROT:
                continue
            tk = str(p.ticket)
            if tk in fp:
                continue
            feat = (doss.get(p.symbol) or {}).get("features")
            if not feat:
                continue
            fp[tk] = {"sym": p.symbol, "side": "BUY" if p.type == 0 else "SELL",
                      "ts": p.time, "feat": feat}
            changed = True
    except Exception:
        pass
    if len(fp) > 5000:
        for k in sorted(fp, key=lambda k: fp[k].get("ts", 0))[:len(fp) - 5000]:
            fp.pop(k, None)
        changed = True
    if changed:
        try:
            json.dump(fp, open(FPRINTS, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass


def _load_fingerprint_trades():
    """يربط بصمات الخصائص الغنيّة بصافي الصفقات المُغلقة (friday.db)."""
    try:
        fp = json.load(open(FPRINTS, encoding="utf-8-sig"))
    except Exception:
        return []
    if not fp:
        return []
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except Exception:
        c = sqlite3.connect(str(DB))
    # FIX (2026-06-30): fingerprints are keyed by the open POSITION ticket, but
    # trades.ticket is the closing DEAL ticket. Index net by BOTH ticket and
    # position_id so a fingerprint resolves to its closed-trade net regardless.
    nets = {}
    for tk, pid, pnl, comm, swap in c.execute(
            "select ticket, position_id, pnl, commission, swap "
            "from trades where exit is not null"):
        net = float((pnl or 0) + (comm or 0) + (swap or 0))
        nets[str(tk)] = net
        if pid is not None:
            nets[str(pid)] = net
    c.close()
    return [{"sym": d["sym"], "side": d["side"], "feat": d.get("feat") or {}, "net": nets[tk]}
            for tk, d in fp.items() if tk in nets]


def analyze_rich(rows):
    """تعلّم على خصائص العقل الـ14 الغنيّة (صافي صفقات منفّذة) — التعلّم الأمامي."""
    if not rows:
        return {"n": 0, "favors": {}, "vetoes": {}}
    buckets = {}
    for r in rows:
        for k, v in (r["feat"] or {}).items():
            buckets.setdefault(f"{k}={v}", []).append(r["net"])
        buckets.setdefault(f"symdir={r['sym']}:{r['side']}", []).append(r["net"])
    stats = {k: _bstat(v) for k, v in buckets.items() if len(v) >= MIN_N}
    n_tests = max(len(stats), 1)
    pos, neg = {}, {}
    for k, s in stats.items():
        if abs(s["t"]) <= 2:
            continue
        bonf = _p_two(s["t"]) * n_tests < ALPHA
        (pos if s["net"] > 0 else neg)[k] = {**s, "bonf": bonf}
    return {"n": len(rows), "favors": pos, "vetoes": neg}


def _rules(rep, rich=None):
    """يحوّل أقوى الشروط (تاريخية + أمامية غنيّة) إلى قواعد تنفيذ يقرأها جسر القناعة."""
    rules = {"updated": rep["updated"], "vetoes": [], "favors": []}

    def emit(dst, src):
        for k, s in src.items():
            dst.append({"key": k, "net": s["net"], "t": s["t"], "n": s["n"], "bonf": s.get("bonf", False)})
    emit(rules["vetoes"], rep["vetoes"]); emit(rules["favors"], rep["favors"])
    if rich:
        emit(rules["vetoes"], rich.get("vetoes", {})); emit(rules["favors"], rich.get("favors", {}))
    return rules


def main():
    RN.mkdir(parents=True, exist_ok=True)
    _log("real_trade_learner start")
    while True:
        try:
            _capture_fingerprints()                       # التعلّم الأمامي: بصمة كل صفقة مفتوحة
            rows = _load_trades()
            rep = analyze(rows)
            rich = analyze_rich(_load_fingerprint_trades())
            if rep:
                rep["forward"] = {"n": rich["n"], "favors": len(rich["favors"]), "vetoes": len(rich["vetoes"])}
                json.dump(rep, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                json.dump(_rules(rep, rich), open(RULES, "w", encoding="utf-8"), ensure_ascii=False)
                _log(f"n={rep['n']} fwd={rich['n']} overall_net={rep['overall']['net']} "
                     f"favors={len(rep['favors'])} vetoes={len(rep['vetoes'])}")
        except Exception as e:
            _log(f"err: {type(e).__name__}: {e}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        r = analyze(_load_trades())
        print(json.dumps({"n": r["n"], "overall": r["overall"],
                          "vetoes": list(r["vetoes"].items())[:6],
                          "favors": list(r["favors"].items())[:6]}, ensure_ascii=False, indent=1))
    else:
        main()
