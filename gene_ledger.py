"""gene_ledger.py — محلّل مهارات الجينات: يقفل سجل الصفقات ويُجيب بدقّة على سؤال المستخدم
"كل جين متى يدخل بيع ومتى يدخل شراء، وأيّهم شاطر بأي اتجاه؟".

  1. SETTLE: يطابق قيود trade_ledger.jsonl (المكتوبة لحظة الدخول بكامل السياق) مع صفقات
     الإغلاق الحقيقية → كل قيد يكتمل بنتيجته.
  2. SKILLS: يجمع لكل (رمز × جلسة × اتجاه): عدد/صافي/فوز% → gene_skills.json — خريطة
     المهارة الاتجاهية لكل جين، تتحدّث دائماً.
  3. BOOTSTRAP: قبل تراكم السجل الجديد، يمهّد المهارات من تاريخ 7 أيام الحقيقي
     (اتجاه الدخول معروف من نوع صفقة الدخول، والجلسة من وقتها) — عيّنات أكثر = تعلّم أسرع.

evolution_director يقرأ الخريطة ويبني الهجائن (شاطر الشراء + شاطر البيع). Windowless.
Run:  pythonw gene_ledger.py
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
LEDGER = RN / "trade_ledger.jsonl"
SKILLS = RN / "gene_skills.json"
MAGICS = {20260608, 20260613}
POLL_S = 120
if str(MT5DIR / "r_native_v2") not in sys.path:
    sys.path.insert(0, str(MT5DIR / "r_native_v2"))


def _sess_of(ts):
    try:
        from indicators import session as S
        return S.classify(datetime.fromtimestamp(int(ts), tz=timezone.utc)).name
    except Exception:
        return "?"


def _read_ledger():
    out = []
    try:
        for ln in LEDGER.read_text(encoding="utf-8").strip().splitlines():
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _write_ledger(rows):
    tmp = LEDGER.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows[-3000:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, LEDGER)


def settle(mt5, rows):
    """طابق القيود المفتوحة مع الإغلاقات الحقيقية."""
    open_rows = [r for r in rows if not r.get("done")]
    if not open_rows:
        return 0
    t0 = min(float(r["ts"]) for r in open_rows) - 60
    deals = [d for d in (mt5.history_deals_get(int(t0), int(time.time())) or [])
             if d.magic in MAGICS and d.entry == 1]
    by_pos = {}
    for d in deals:
        by_pos.setdefault(d.position_id, 0.0)
        by_pos[d.position_id] += d.profit + d.commission + d.swap
    still_open = {p.ticket for p in (mt5.positions_get() or []) if p.magic in MAGICS}
    n = 0
    for r in open_rows:
        tk = int(r.get("ticket", 0) or 0)
        if tk in still_open:
            continue
        if tk in by_pos:
            r["net"] = round(by_pos[tk], 2)
            r["done"] = True; n += 1
        elif time.time() - float(r["ts"]) > 48 * 3600:
            r["done"] = True; r["net"] = r.get("net", 0.0)   # يتيم قديم — أقفله صفراً
    return n


def bootstrap_skills(mt5, days=7):
    """مهّد المهارات من التاريخ الحقيقي (اتجاه + جلسة لكل صفقة مغلقة)."""
    now = int(time.time())
    deals = [d for d in (mt5.history_deals_get(now - days * 86400, now) or []) if d.magic in MAGICS]
    ent = {d.position_id: d for d in deals if d.entry == 0}
    sk = {}
    for d in deals:
        if d.entry != 1 or d.position_id not in ent:
            continue
        e = ent[d.position_id]
        direction = "long" if e.type == 0 else "short"   # نوع صفقة الدخول يحدّد الاتجاه بدقّة
        sess = _sess_of(e.time)
        cell = sk.setdefault(d.symbol, {}).setdefault(sess, {}).setdefault(
            direction, {"n": 0, "net": 0.0, "wins": 0})
        pnl = d.profit + d.commission + d.swap
        cell["n"] += 1; cell["net"] = round(cell["net"] + pnl, 2)
        cell["wins"] += 1 if pnl > 0 else 0
    return sk


def merge_ledger_skills(sk, rows):
    """أضِف قيود السجل المكتملة (الأدقّ — تحمل القيم والوضع) فوق التمهيد."""
    for r in rows:
        if not r.get("done") or "net" not in r:
            continue
        direction = "long" if int(r.get("dir", 0)) > 0 else "short"
        cell = sk.setdefault(r["sym"], {}).setdefault(r.get("session", "?"), {}).setdefault(
            direction, {"n": 0, "net": 0.0, "wins": 0})
        # ledger rows are also in deal history (bootstrap) — only enrich values metadata
        vals = cell.setdefault("values_seen", {})
        key = json.dumps(r.get("values", {}), sort_keys=True)
        v = vals.setdefault(key, {"n": 0, "net": 0.0})
        v["n"] += 1; v["net"] = round(v["net"] + float(r["net"]), 2)
    return sk


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize() and not mt5.initialize():
        print("mt5 init failed"); return 1
    print("[LEDGER] محلّل مهارات الجينات حيّ — من يشتري ومن يبيع وأين يربح", flush=True)
    while True:
        try:
            rows = _read_ledger()
            n = settle(mt5, rows)
            if n:
                _write_ledger(rows)
            sk = bootstrap_skills(mt5)
            sk = merge_ledger_skills(sk, rows)
            out = {"_ts": time.time(), "_iso": datetime.now(timezone.utc).isoformat(),
                   "skills": sk}
            tmp = SKILLS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, SKILLS)
            hot = []
            for s, ses in sk.items():
                for se, dirs in ses.items():
                    for di, c in dirs.items():
                        if isinstance(c, dict) and c.get("n", 0) >= 5:
                            hot.append((s, se, di, c["net"], c["n"]))
            hot.sort(key=lambda x: -abs(x[3]))
            tag = " · ".join(f"{s.replace('m','')}/{se} {('شراء' if di=='long' else 'بيع')}: ${net:+.0f}/{n}"
                             for s, se, di, net, n in hot[:4])
            print(f"[LEDGER] أقفل {n} قيداً · مهارات بارزة: {tag or 'تتجمع'}", flush=True)
        except Exception as e:
            print(f"[LEDGER] err {e}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
