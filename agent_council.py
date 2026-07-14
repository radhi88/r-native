# -*- coding: utf-8 -*-
"""agent_council.py — 🏛️ محرّك إجماع مجلس الـ100 وكيلاً (طلب المستخدم 2026-07-05 «100 وكيل حقيقيّ،
كلٌّ يحسب زاويته، والإجماع يصهرها»). يكتشف تلقائياً كلّ AGENTS في agents/agent_*.py (importlib + glob)،
يبني ctx لكلّ رمز (فريمات m1/m5/m15/h1 كمصفوفات numpy عبر mt5.copy_rates + حقول SMC من النبض)،
يُشغّل كلّ الوكلاء، ويصهر أصواتهم في إجماعٍ لكلّ عملة.

المخرج data/r_native/agent_council.json = {sym: {verdict, dir, agreement_pct, n_voted, votes_buy,
  votes_sell, top_reasons:[..], gene:"بصمة الوكلاء المتّفقين"}} لكلّ 17 عملة.

🧬 التعلّم الذاتيّ: يراقب مراكز المنفّذ (ماجيك 20260704). حين يفتح مركزٌ جديد يحفظ (تذكرة⇒جين) لحظة
الدخول في agent_council_genes.jsonl. حين يُغلَق (من history) يربط ربحه بجينه ⇒ يزيد/يُنقص عدّاد
الفوز/الخسارة وwinrate لذلك الجين في gene_registry.json. الجينات الرابحة ترفع وزن وكلائها تدريجياً.

⚖️ صدق صارم: 100 صوت = تنسيقٌ وتنويع زوايا، لا ضمان حافّة (درس التجميع المُثبَت). كلّ شيء ديمو،
مقيس، ويُحاسَب. المجلس عينٌ سادسة في المخ الواحد — سياقٌ وبوّابة، لا آلة ربح."""
import os, sys, json, time, glob, hashlib, importlib.util
from datetime import datetime, timedelta

import numpy as np

_BASE = os.path.dirname(os.path.abspath(__file__))
_RN = os.path.join(_BASE, "data", "r_native")
_AGENTS_DIR = os.path.join(_BASE, "agents")

# stdout/stderr → ملفّ (نمط unified_brain.py — windowless daemon)
try:
    _lf = open(os.path.join(_RN, "agent_council.out.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _lf; sys.stderr = _lf
except Exception:
    pass

import MetaTrader5 as mt5

try:
    import engine_lock
    engine_lock.claim("agent_council")
except SystemExit:
    raise
except Exception:
    pass

EXEC_MAGIC = 20260704                                   # منفّذ المخ (brain_trader.py)
PULSE_F = os.path.join(_RN, "market_pulse.json")
OUT_F = os.path.join(_RN, "agent_council.json")
GENES_F = os.path.join(_RN, "agent_council_genes.jsonl")      # سجلّ (تذكرة⇒جين) لحظة الدخول
REGISTRY_F = os.path.join(_RN, "gene_registry.json")          # عدّاد فوز/خسارة لكلّ جين
KILL1 = os.path.join(_RN, "kill_switch.txt")
KILL2 = os.path.join(_BASE, "kill_switch.txt")

_N_BARS = 200                                           # آخر ~200 شمعة لكلّ فريم
_TFS = {"m1": None, "m5": None, "m15": None, "h1": None}  # تُملأ بثوابت mt5 في main


# ═══════════════════════════ اكتشاف الوكلاء ═══════════════════════════════

def _discover_agents():
    """يستورد كلّ agents/agent_*.py ويجمع AGENTS = [(name, category, func, weight)]."""
    registry = []
    for path in sorted(glob.glob(os.path.join(_AGENTS_DIR, "agent_*.py"))):
        modname = "agents." + os.path.splitext(os.path.basename(path))[0]
        try:
            spec = importlib.util.spec_from_file_location(modname, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            agents = getattr(mod, "AGENTS", None)
            if not agents:
                continue
            for item in agents:
                try:
                    name, cat, func, weight = item
                    if callable(func):
                        registry.append((str(name), str(cat), func, float(weight)))
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ فشل استيراد {path}: {type(e).__name__}: {e}", flush=True)
    return registry


# ═══════════════════════════ بناء ctx ════════════════════════════════════

def _rates(sym, tf):
    """مصفوفات o/h/l/c/v لآخر ~200 شمعة أو None."""
    try:
        r = mt5.copy_rates_from_pos(sym, tf, 0, _N_BARS)
        if r is None or len(r) == 0:
            return None
        return {"o": np.asarray(r["open"], dtype=float),
                "h": np.asarray(r["high"], dtype=float),
                "l": np.asarray(r["low"], dtype=float),
                "c": np.asarray(r["close"], dtype=float),
                "v": np.asarray(r["tick_volume"], dtype=float)}
    except Exception:
        return None


def _atr_m5(m5):
    try:
        if not m5:
            return 0.0
        h, l, c = m5["h"], m5["l"], m5["c"]
        if h.size < 15:
            return 0.0
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr[-14:]))
    except Exception:
        return 0.0


def _spread(sym):
    try:
        t = mt5.symbol_info_tick(sym)
        if t:
            return float(t.ask - t.bid)
    except Exception:
        pass
    return 0.0


def _build_ctx(sym, psym, peers):
    """ctx جاهز: sym + m1/m5/m15/h1 (numpy) + price + atr_m5 + spread + smc + peers."""
    m1 = _rates(sym, _TFS["m1"]); m5 = _rates(sym, _TFS["m5"])
    m15 = _rates(sym, _TFS["m15"]); h1 = _rates(sym, _TFS["h1"])
    smc = (psym or {}).get("smc") or {}
    # نُثري smc بحقول النبض الأخرى المفيدة للوكلاء (structure/momentum/volume/volatility)
    smc = dict(smc)
    for extra in ("structure", "momentum", "volume", "volatility", "pattern_m1", "pattern_m5"):
        if extra in (psym or {}):
            smc.setdefault(extra, psym[extra])
    price = float((psym or {}).get("price") or (m5["c"][-1] if m5 else 0.0))
    ctx = {"sym": sym, "m1": m1, "m5": m5, "m15": m15, "h1": h1,
           "price": price, "atr_m5": _atr_m5(m5), "spread": _spread(sym),
           "smc": smc,
           # حقول النبض الخام لمن يقرؤها الوكلاء مباشرةً
           "momentum": (psym or {}).get("momentum") or {},
           "structure": (psym or {}).get("structure") or {},
           "volume": (psym or {}).get("volume") or {},
           "volatility": (psym or {}).get("volatility") or {},
           "pattern_m1": (psym or {}).get("pattern_m1") or {},
           "pattern_m5": (psym or {}).get("pattern_m5") or {},
           "peers": peers, "pulse_symbols": peers}
    return ctx


# ═══════════════════════════ الإجماع ═════════════════════════════════════

def _gene(agree_names):
    """بصمة مستقرّة (hash مرتّب لأسماء الوكلاء المتّفقين مع الاتجاه) — تمثّل «التركيبة»."""
    if not agree_names:
        return "none"
    key = "|".join(sorted(agree_names))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _consensus(sym, ctx, registry, weight_boost):
    """يُشغّل كلّ الوكلاء، يصهر أصواتهم في إجماعٍ موزون."""
    buy_w = 0.0; sell_w = 0.0; n_voted = 0
    votes_buy = 0; votes_sell = 0
    reasons = []                                        # (conf, name, reason, vote)
    per_dir = {1: [], -1: []}                           # اتجاه ⇒ أسماء الوكلاء
    for name, cat, func, base_w in registry:
        try:
            vote, conf, reason = func(ctx)
            vote = int(vote); conf = float(conf)
        except Exception:
            continue
        if vote not in (-1, 0, 1) or not (0.0 <= conf <= 1.0):
            continue
        w = base_w * float(weight_boost.get(name, 1.0))
        if vote == 1:
            buy_w += w * conf; votes_buy += 1; n_voted += 1
            per_dir[1].append(name); reasons.append((conf, name, reason, 1))
        elif vote == -1:
            sell_w += w * conf; votes_sell += 1; n_voted += 1
            per_dir[-1].append(name); reasons.append((conf, name, reason, -1))
        # vote == 0 ⇒ تحفّظ (لا يُحتسَب اتجاهاً؛ صدق التجميع)
    total_w = buy_w + sell_w
    if total_w <= 1e-9 or n_voted == 0:
        direction = 0; agreement_pct = 0.0
    else:
        direction = 1 if buy_w > sell_w else (-1 if sell_w > buy_w else 0)
        win_w = max(buy_w, sell_w)
        agreement_pct = round(100.0 * win_w / total_w, 1)
    agree_names = per_dir.get(direction, []) if direction != 0 else []
    top_reasons = [f"{r}" for (_, _, r, v) in
                   sorted([x for x in reasons if x[3] == direction], key=lambda z: -z[0])[:3]]
    gene = _gene(agree_names)
    verdict = ("🟢 شراء" if direction == 1 else ("🔴 بيع" if direction == -1 else "⚪ حياد"))
    if direction != 0 and agreement_pct >= 65 and len(agree_names) >= 5:
        verdict += " قويّ"
    return {"verdict": verdict, "dir": direction, "agreement_pct": agreement_pct,
            "n_voted": n_voted, "votes_buy": votes_buy, "votes_sell": votes_sell,
            "top_reasons": top_reasons, "gene": gene, "agree_names": agree_names}


# ═══════════════════════════ التعلّم الذاتيّ (جينات) ══════════════════════

def _load_registry():
    try:
        return json.load(open(REGISTRY_F, encoding="utf-8"))
    except Exception:
        return {"genes": {}, "agents": {}, "linked_tickets": []}


def _save_registry(reg):
    try:
        t = REGISTRY_F + ".tmp"
        json.dump(reg, open(t, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(t, REGISTRY_F)
    except Exception as e:
        print(f"registry save err: {type(e).__name__}: {e}", flush=True)


def _record_entry_genes(council, reg):
    """يحفظ (تذكرة⇒جين) لأيّ مركز جديد لماجيك المنفّذ لحظة فتحه (يربط جينه بالسعر/الوقت)."""
    try:
        poss = [p for p in (mt5.positions_get() or []) if p.magic == EXEC_MAGIC]
    except Exception:
        return
    seen = set(reg.get("ticket_gene", {}).keys())
    tg = reg.setdefault("ticket_gene", {})
    for p in poss:
        tk = str(p.ticket)
        if tk in seen:
            continue
        c = council.get(p.symbol) or {}
        gene = c.get("gene", "none")
        agree = c.get("agree_names", [])
        tg[tk] = {"gene": gene, "agree_names": agree, "symbol": p.symbol,
                  "dir": (1 if p.type == 0 else -1), "ts": time.time()}
        try:
            with open(GENES_F, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ticket": tk, "gene": gene, "agree_names": agree,
                                    "symbol": p.symbol, "dir": (1 if p.type == 0 else -1),
                                    "ts": time.time(),
                                    "iso": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass


def _learn_from_closes(reg):
    """يقرأ إغلاقات المنفّذ من history؛ يربط ربح كلّ تذكرة بجينها ⇒ يحدّث winrate الجين + أوزان وكلائه."""
    tg = reg.get("ticket_gene", {})
    if not tg:
        return
    linked = set(reg.get("linked_tickets", []))
    open_tickets = set()
    try:
        open_tickets = {str(p.ticket) for p in (mt5.positions_get() or []) if p.magic == EXEC_MAGIC}
    except Exception:
        pass
    # profit لكلّ تذكرة مُغلقة عبر deals الخروج (entry==1) خلال آخر 7 أيّام
    prof_by_ticket = {}
    try:
        since = datetime.now() - timedelta(days=7)
        for d in (mt5.history_deals_get(since, datetime.now() + timedelta(hours=12)) or []):
            if d.magic != EXEC_MAGIC:
                continue
            tk = str(getattr(d, "position_id", 0) or 0)
            if tk == "0":
                continue
            prof_by_ticket.setdefault(tk, 0.0)
            prof_by_ticket[tk] += float(d.profit) + float(d.commission) + float(d.swap)
    except Exception:
        pass
    genes = reg.setdefault("genes", {})
    agents_reg = reg.setdefault("agents", {})
    changed = False
    for tk, info in list(tg.items()):
        if tk in linked or tk in open_tickets:
            continue                                    # لم يُغلَق بعد أو حُسِب سابقاً
        if tk not in prof_by_ticket:
            continue                                    # لا سجلّ إغلاق بعد
        profit = prof_by_ticket[tk]
        gene = info.get("gene", "none"); names = info.get("agree_names", []) or []
        g = genes.setdefault(gene, {"wins": 0, "losses": 0, "pnl": 0.0, "agree_names": names})
        won = profit > 0
        if won:
            g["wins"] += 1
        else:
            g["losses"] += 1
        g["pnl"] = round(float(g.get("pnl", 0.0)) + profit, 2)
        tot = g["wins"] + g["losses"]
        g["winrate"] = round(g["wins"] / tot, 3) if tot else 0.0
        g["agree_names"] = names or g.get("agree_names", [])
        # 🧬 تعلّم أوزان الوكلاء: كلّ وكيل في جينٍ رابح يُكافأ، وفي خاسر يُعاقَب — تدريجياً ومقيّداً
        for nm in names:
            a = agents_reg.setdefault(nm, {"wins": 0, "losses": 0})
            if won:
                a["wins"] += 1
            else:
                a["losses"] += 1
        linked.add(tk)
        changed = True
        print(f"🧬 تعلّم: تذكرة {tk} جين {gene[:8]} ربح ${profit:+.2f} "
              f"({'فوز' if won else 'خسارة'}) winrate={g['winrate']}", flush=True)
    if changed:
        reg["linked_tickets"] = list(linked)[-2000:]    # سقف الذاكرة
        # نظافة: احذف tickets مربوطة قديمة من ticket_gene (بقيت لكن حُسبت)
        for tk in list(tg.keys()):
            if tk in linked and tk not in open_tickets:
                tg.pop(tk, None)
    return changed


def _weight_boost(reg):
    """وزن كلّ وكيل = 1 + معامل تعلّمٍ مقيّد من سجلّ فوزه/خسارته (0.5..1.5، تدريجيّ)."""
    boost = {}
    for nm, a in (reg.get("agents") or {}).items():
        w = int(a.get("wins", 0)); l = int(a.get("losses", 0))
        tot = w + l
        if tot < 5:                                     # لا حكم قبل 5 عيّنات — تدرّج
            continue
        wr = w / tot
        # خرِّطة winrate 0..1 ⇒ boost 0.6..1.4 حول 0.5، مع تخفيفٍ بحجم العيّنة
        conf = min(1.0, tot / 40.0)                     # ثقة تتشبّع عند 40 صفقة
        boost[nm] = round(1.0 + conf * (wr - 0.5) * 0.8, 3)
    return boost


# ═══════════════════════════ الحلقة ══════════════════════════════════════

def _kill():
    return os.path.exists(KILL1) or os.path.exists(KILL2)


def main():
    print(f"🏛️ مجلس الوكلاء بدأ {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    registry = _discover_agents()
    cats = {}
    for _, cat, _, _ in registry:
        cats[cat] = cats.get(cat, 0) + 1
    print(f"🧮 اكتُشِف {len(registry)} وكيلاً عبر {len(cats)} فئة: "
          + ", ".join(f"{k}={v}" for k, v in sorted(cats.items())), flush=True)
    if not registry:
        print("⛔ لا وكلاء — خروج", flush=True); return

    ok = False
    for i in range(6):
        if mt5.initialize():
            ok = True; break
        print(f"⏳ mt5.initialize فشل ({i + 1}/6) — انتظار 10ث", flush=True); time.sleep(10)
    if not ok:
        print("⛔ تعذّرت تهيئة MT5 — خروج", flush=True); return
    _TFS["m1"] = mt5.TIMEFRAME_M1; _TFS["m5"] = mt5.TIMEFRAME_M5
    _TFS["m15"] = mt5.TIMEFRAME_M15; _TFS["h1"] = mt5.TIMEFRAME_H1

    reg = _load_registry()
    last_learn = 0.0
    while True:
        if _kill():
            time.sleep(5); continue
        t0 = time.time()
        try:
            pulse = json.load(open(PULSE_F, encoding="utf-8"))
        except Exception:
            time.sleep(2); continue
        psyms = pulse.get("symbols") or {}
        # peers = لمحة سريعة لكلّ رمز (لوكلاء الارتباط cross-symbol)
        peers = {}
        for s, pd in psyms.items():
            mom = (pd or {}).get("momentum") or {}
            peers[s] = {"price": (pd or {}).get("price"), "score": (pd or {}).get("score"),
                        "trend_m5": mom.get("trend_m5"), "trend_m1": mom.get("trend_m1"),
                        "spark": (pd or {}).get("spark")}

        weight_boost = _weight_boost(reg)
        council = {}
        for sym, pd in psyms.items():
            try:
                ctx = _build_ctx(sym, pd, peers)
                council[sym] = _consensus(sym, ctx, registry, weight_boost)
            except Exception as e:
                council[sym] = {"verdict": "⚪ حياد", "dir": 0, "agreement_pct": 0.0,
                                "n_voted": 0, "votes_buy": 0, "votes_sell": 0,
                                "top_reasons": [f"خطأ: {type(e).__name__}"], "gene": "none",
                                "agree_names": []}

        # 🧬 تعلّم ذاتيّ: سجّل جينات الدخول الجديدة، وتعلّم من الإغلاقات (كلّ ~30ث)
        try:
            _record_entry_genes(council, reg)
            if time.time() - last_learn > 30:
                if _learn_from_closes(reg):
                    _save_registry(reg)
                else:
                    _save_registry(reg)                 # نحفظ ticket_gene الجديدة أيضاً
                last_learn = time.time()
        except Exception as e:
            print(f"learn err: {type(e).__name__}: {e}", flush=True)

        # المخرج الذرّي (بلا agree_names الطويلة داخل الملفّ العامّ — نُبقيها مختصرة)
        out = {}
        for s, c in council.items():
            o = {k: v for k, v in c.items() if k != "agree_names"}
            o["n_agree"] = len(c.get("agree_names", []))
            out[s] = o
        payload = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "n_agents": len(registry), "n_categories": len(cats),
                   "boosted": len(weight_boost),
                   "symbols": out,
                   "honesty": "100 صوت = تنسيق زوايا لا حافّة. ديمو، مقيس، محاسَب. عينٌ في المخ."}
        try:
            t = OUT_F + ".tmp"
            json.dump(payload, open(t, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(t, OUT_F)
        except Exception as e:
            print(f"write err: {type(e).__name__}: {e}", flush=True)

        dt = time.time() - t0
        time.sleep(max(0.5, 2.0 - dt))                  # دورة ~2ث


if __name__ == "__main__":
    main()
