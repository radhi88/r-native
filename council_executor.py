# -*- coding: utf-8 -*-
"""council_executor.py — ⚖️ منفّذ قرارات المجلس: ينفّذ فقط الاقتراحات التي وافق عليها Claude.

السلسلة: 🏛️ المجلس يقترح (council_proposals.jsonl) ← 🤖 Claude يُقرّر (council_decisions.jsonl)
        ← ⚖️ هذا المنفّذ يُطبّق الموافَق عليه فقط، من قائمة أفعالٍ بيضاء ضيّقة:
  - restart_engine: قتل محرّكٍ من قائمتنا (الواتشدوغ يُحييه نظيفاً).
  - cancel_orders: إلغاء معلّقات مجيكٍ من مجيكاتنا فقط (لا يدويّ/خارجيّ أبداً).
  - set_config: تعديل مفاتيح محدّدة بنطاقاتٍ مُتحقَّقة (قائمة بيضاء صارمة).
  - request_analysis: لمس أعلام تحليل (Fable/المجلس).
  - spawn_agent: لا يُنفَّذ آلياً أبداً — يبقى لـClaude يبنيه بنفسه.
لا كود عشوائيّ، لا فتح صفقات، لا حذف ملفّات. كل تنفيذٍ يُسجَّل في council_exec_log.jsonl."""
import os, sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
try:
    _lf = open(os.path.join(_RN, "council_executor.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import json, time
try:
    import engine_lock
    engine_lock.claim("council_executor")
except SystemExit:
    raise
except Exception:
    pass

PROPS_F = os.path.join(_RN, "council_proposals.jsonl")
DECS_F = os.path.join(_RN, "council_decisions.jsonl")
LOG_F = os.path.join(_RN, "council_exec_log.jsonl")

# ── القوائم البيضاء (صارمة) ──
ENGINES_OK = {"youtube_analyst_agent.py", "market_pulse.py", "gold_level_sentinel.py", "quant_desk.py",
              "llm_chart_analyst.py", "news_alarm.py", "news_gene.py", "order_janitor.py",
              "ollama_council.py", "multi_trader.py", "chart_server", "gene_tournament.py",
              "scalp_evolver.py", "profit_harvester.py", "portfolio_maestro.py", "self_tuner.py"}
MAGICS_OK = {20260631, 20260701, 20260608, 20260618, 20260614, 20260605, 20260600, 3627}
CONFIG_OK = {  # (ملف، مفتاح) ⇒ (نوع، أدنى، أقصى)
    ("youtube_analyst_config.json", "max_risk_pct"): (float, 1.0, 10.0),
    ("youtube_analyst_config.json", "dedup_cooldown_s"): (int, 60, 1200),
    ("youtube_analyst_config.json", "max_positions"): (int, 1, 3),
    ("gold_sentinel_config.json", "execute"): (bool, None, None),
    ("gold_sentinel_config.json", "min_exec_score"): (int, 2, 6),
    ("data/r_native/order_janitor_config.json", "default_ttl_min"): (int, 30, 240),
    ("data/r_native/ollama_council_config.json", "interval_min"): (int, 5, 120),
}
FLAGS_OK = {"fable": os.path.join(_RN, "llm_analyst_request.flag"),
            "council": os.path.join(_RN, "ai_council_request.flag")}


def _log(row):
    row["ts"] = time.time(); row["iso"] = time.strftime("%H:%M:%S")
    try:
        with open(LOG_F, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(json.dumps(row, ensure_ascii=False)[:300])


def _jsonl(path):
    out = []
    try:
        for ln in open(path, encoding="utf-8"):
            try: out.append(json.loads(ln))
            except Exception: continue
    except Exception:
        pass
    return out


def _exec_restart(target):
    import psutil
    if target not in ENGINES_OK:
        return False, "محرّك خارج القائمة البيضاء"
    n = 0
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (p.info.get("name") or "").lower() == "pythonw.exe" and target in " ".join(p.info.get("cmdline") or []):
                p.kill(); n += 1
        except Exception:
            continue
    return True, f"قتل {n} — الواتشدوغ يُحييه"


def _exec_cancel(target):
    try:
        magic = int(target)
    except Exception:
        return False, "مجيك غير رقميّ"
    if magic not in MAGICS_OK:
        return False, "مجيك خارج القائمة البيضاء (يدويّ/خارجيّ محميّ)"
    import MetaTrader5 as mt5
    if not mt5.initialize():
        return False, "MT5 غير متاح"
    try:
        ords = [o for o in (mt5.orders_get() or []) if o.magic == magic]
        ok = 0
        for o in ords:
            r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
            if r and r.retcode == mt5.TRADE_RETCODE_DONE: ok += 1
        return True, f"ألغى {ok}/{len(ords)}"
    finally:
        mt5.shutdown()


def _exec_config(target, details):
    key = (str(target), str((details or {}).get("key", "")))
    # target قد يكون الملف والمفتاح معاً "file::key"
    if "::" in str(target):
        f, k = str(target).split("::", 1); key = (f, k)
    spec = CONFIG_OK.get(key)
    if not spec:
        return False, f"({key[0]},{key[1]}) خارج القائمة البيضاء"
    typ, lo, hi = spec
    val = (details or {}).get("value")
    try:
        val = typ(val) if typ is not bool else (str(val).lower() in ("true", "1", "yes"))
    except Exception:
        return False, "قيمة غير صالحة"
    if lo is not None and not (lo <= val <= hi):
        return False, f"خارج النطاق [{lo},{hi}]"
    path = os.path.join(_BASE, key[0])
    cfg = json.load(open(path, encoding="utf-8"))
    old = cfg.get(key[1]); cfg[key[1]] = val
    tmp = path + ".tmp"
    json.dump(cfg, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return True, f"{key[1]}: {old} → {val}"


def cycle():
    props = {p["id"]: p for p in _jsonl(PROPS_F) if p.get("id")}
    decs = {d.get("id"): d for d in _jsonl(DECS_F)}
    done = {r.get("id") for r in _jsonl(LOG_F)}
    for pid, p in props.items():
        d = decs.get(pid)
        if not d or pid in done:
            continue
        if str(d.get("decision", "")).lower() not in ("approve", "approved", "موافق", "نعم"):
            if pid not in done:
                _log({"id": pid, "kind": p.get("kind"), "result": "مرفوض", "why": d.get("why", "")})
            continue
        kind = p.get("kind"); target = p.get("target"); details = p.get("details") or {}
        if kind == "restart_engine":
            ok, msg = _exec_restart(str(target))
        elif kind == "cancel_orders":
            ok, msg = _exec_cancel(target)
        elif kind == "set_config":
            ok, msg = _exec_config(target, details)
        elif kind == "request_analysis":
            fl = FLAGS_OK.get(str(target), FLAGS_OK["council"])
            open(fl, "w").write(str(time.time())); ok, msg = True, "عَلَمٌ مُس"
        elif kind == "spawn_agent":
            ok, msg = False, "spawn_agent لا يُنفَّذ آلياً — Claude يبنيه بنفسه"
        else:
            ok, msg = False, "نوع غير معروف"
        _log({"id": pid, "kind": kind, "target": target, "result": "نُفّذ ✓" if ok else "فشل", "msg": msg})


def main():
    print(f"⚖️ منفّذ المجلس بدأ {time.strftime('%Y-%m-%d %H:%M:%S')} — أفعال بيضاء فقط، بموافقة Claude")
    while True:
        try:
            cycle()
        except Exception as e:
            print(f"cycle err: {type(e).__name__}: {e}")
        time.sleep(20)


if __name__ == "__main__":
    main()
