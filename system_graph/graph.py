# -*- coding: utf-8 -*-
"""graph.py — يبني طوبولوجيا منظومة FRIDAY الحيّة كرسمٍ قوّة-موجّه، **باكتشافٍ آليّ** من الكود:
كل محرّك في الوصيّ = عقدة؛ ويُكتشَف تلقائياً ما يتّصل به: MT5 (تنفيذ/قراءة سوق) + ملفّات البيانات
التي يقرؤها/يكتبها فعلاً (من سطور الكود). فلا تبقى عقدة معزولة دون سبب حقيقيّ. يُضاف فوقها تدفّقٌ
**منسّق ملوّن** للمسارات المعروفة (معلومات/تنفيذ/حوكمة) + حالة حيّة (حيّ/طازج/خنق/إقالة) + كشف الفجوات.

قراءة-فقط. يُستهلَك من server.py (/graph.json) و monitor.py."""
from __future__ import annotations
import json, re, time
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
RN = ROOT / "data" / "r_native"
V2 = ROOT / "r_native_v2"
STALE_S = 2 * 3600.0

# تدفّقات منسّقة ملوّنة للمسارات المعروفة (تُلوَّن فوق الاكتشاف الآليّ): محرّك → (نوع, [حوكمة-مجيكات])
TYPED = {
  "gold_scalper": ("executor", 20260628), "multi_trader": ("executor", 20260608),
  "army_warroom": ("executor", 20260618), "gene_tournament": ("executor", 20260612),
  "news_gene": ("executor", 20260614), "orb_trader": ("executor", 20260616),
  "gold_straddle_3627": ("executor", 3627), "spike_rider": ("executor", None),
  "unified_trader": ("executor", None),
  "intermarket": ("feeder", None), "macro_feed": ("feeder", None), "market_internals": ("feeder", None),
  "delta_feed": ("feeder", None), "news_engine": ("feeder", None), "llm_analyst": ("feeder", None),
  "ml_indicator": ("feeder", None), "forecast_lab": ("feeder", None), "vol_forecast": ("feeder", None),
  "accuracy_updater": ("feeder", None), "market_discovery": ("feeder", None), "macro_feed": ("feeder", None),
  "tick_ws": ("feeder", None), "market_data_collector": ("feeder", None),
  "deep_brain": ("brain", None), "real_trade_learner": ("learner", None), "regret_learner": ("learner", None),
  "self_tuner": ("learner", None), "truth_tracker": ("learner", None), "real_account_gate": ("learner", None),
  "gene_ledger": ("learner", None), "evolution_director": ("learner", None), "genome_evo_logger": ("learner", None),
  "secure_learner": ("learner", None), "genome_academy": ("learner", None), "scalp_evolver": ("learner", None),
  "graph_brain": ("brain", None), "plutobrain_swarm": ("brain", None),
  "friday_db": ("recorder", None), "bot_feature_recorder": ("recorder", None),
  "manual_feature_recorder": ("recorder", None), "tape_recorder": ("recorder", None),
  "portfolio_maestro": ("governor", None), "master_floor": ("governor", None), "risk_manager": ("governor", None),
  "profit_harvester": ("governor", None), "manual_manager": ("governor", None), "manual_guard": ("governor", None),
  "edge_guard": ("governor", None), "manual_mimic": ("learner", None),
  # ── وكلاء 2026-07 الجدد ──
  "youtube_analyst_agent": ("executor", 20260631), "gold_level_sentinel": ("executor", 20260701),
  "pipflow_core": ("executor", 20260629), "momentum_harvester": ("executor", 20260630),
  "gold_scalper": ("executor", 20260628),
  "market_pulse": ("feeder", None), "news_alarm": ("feeder", None),
  "quant_desk": ("brain", None), "llm_chart_analyst": ("llm", None),
  "ollama_council": ("llm", None), "council_executor": ("governor", None),
  "order_janitor": ("governor", None), "chart_server": ("ui", None),
}
# 🏛️ عقد LLM الثابتة (ليست عمليّات): موديلات Ollama بأدوارها + Fable — تُحقن كعقدٍ ساكنة
LLM_NODES = [
    ("fable-5 (Claude)", "llm"), ("qwen2.5:7b 🧠محلّل", "llm"), ("llama3.2:3b 🗡️ناقد", "llm"),
    ("qwen2.5:7b ⚖️حكم", "llm"), ("llava 👁️عيون", "llm"), ("qwen-coder 🔧مهندس", "llm"),
    ("qwen2.5:3b ⚡عدّاء", "llm"), ("qwen2.5:1.5b 🏷️مصنّف", "llm"),
]
LLM_EDGES = [
    ("llm_chart_analyst", "fable-5 (Claude)"), ("chart_server", "fable-5 (Claude)"),
    ("ollama_council", "qwen2.5:7b 🧠محلّل"), ("ollama_council", "llama3.2:3b 🗡️ناقد"),
    ("ollama_council", "qwen2.5:7b ⚖️حكم"), ("ollama_council", "llava 👁️عيون"),
    ("ollama_council", "qwen-coder 🔧مهندس"), ("ollama_council", "qwen2.5:3b ⚡عدّاء"),
    ("ollama_council", "qwen2.5:1.5b 🏷️مصنّف"),
    ("ollama_council", "council_executor"),       # اقتراحات ← (موافقة Claude) ← تنفيذ
]
# 🧠 عقد العقل العميق التي تقرؤها القمرة (chart_server) فعلاً لكنّ المسح الآليّ لا يلتقطها
# (تُقرأ عبر _os.path.join لا سلاسل حرفيّة، أو تُحقن ملفّاتها JSON بعد التهذيب) — تُضاف كعقدٍ ساكنة:
COCKPIT_NODES = [
    ("quant_desk", "brain"), ("ollama_council", "llm"), ("llm_chart_analyst", "llm"),
    ("market_pulse", "feeder"), ("news_alarm", "feeder"),
    ("deep_dossier", "brain"), ("graph_brain", "brain"),
]
# 🔌 أسلاك القمرة → مصادرها العميقة (ما يستهلكه get_pro_data حقّاً): تُحقن بعد التشذيب كي لا تُحذف
COCKPIT_EDGES = [
    ("chart_server", "quant_desk"),        # desk = _read_desk() ← quant_desk.json
    ("chart_server", "ollama_council"),    # council = _read_council() ← ai_council.json
    ("chart_server", "llm_chart_analyst"), # تحليل الشارت بالـ LLM (fable/Claude)
    ("chart_server", "market_pulse"),      # feeds.pulse ← market_pulse_feed.jsonl
    ("chart_server", "news_alarm"),        # feeds.news + news_events ← news_alarm
    ("chart_server", "deep_dossier"),      # القمرة تقرأ deep_dossier.json
    ("chart_server", "graph_brain"),       # القمرة تقرأ graph_brain.json
]
GOV_BY = {"portfolio_maestro": [20260628, 20260608, 20260618, 20260612, 20260614, 20260616, 3627],
          "profit_harvester": [20260618, 20260616],
          "master_floor": ["ALL"]}
# وصلات صريحة للمراقبين/المُشغّلين (يصلون عبر متغيّرات/مسارات لا يلتقطها المسح الآليّ):
EXTRA = [("system_graph/server", "engine_governance.json", "data"),   # يعرض حوكمة المايسترو
         ("system_graph/monitor", "engine_governance.json", "data"),  # يراقب الحوكمة/الفجوات
         ("run_bridge", "MT5", "mt5"),                                 # يُشغّل جسر الجوال (تداول عبر MT5)
         ("graph_brain", "MT5", "mt5"),                                # دماغ على المنظومة
         ("footprint_brain_bridge", "MT5", "mt5")]                     # بصمة القدم (تيكات السوق → الدماغ)

_FILE_RE = re.compile(r'["\']([\w\-]+\.(?:json|jsonl|db))["\']')
_WRITE_HINT = re.compile(r'json\.dump|\.write_text|\.write\(|os\.replace|open\([^)]*["\']w')


def _short(name):
    return name.replace(".py", "").replace("runtime.", "").replace("r_native.", "").replace("plutobrain_swarm.", "")


def _engines():
    """يقرأ قائمة محرّكات الوصيّ + مسار سكربت كلّ واحد (من ENGINES في watchdog_guard.py)."""
    out = {}
    try:
        src = (ROOT / "watchdog_guard.py").read_text(encoding="utf-8")
        # أسطر مثل:  "name": (["script.py", ...], CWD),   أو (["-m","pkg.mod"], CWD)
        for m in re.finditer(r'^\s*"([^"]+)":\s*\(\[([^\]]*)\]', src, re.M):
            key = m.group(1)
            args = re.findall(r'"([^"]+)"', m.group(2))
            if key.startswith("#"):
                continue
            script = None
            if "-m" in args:                       # وضع وحدة: الوحدة أوّل وسيطة مُنقّطة بعد -m (نتخطّى uvicorn، لا 127.0.0.1)
                i = args.index("-m")
                for a in args[i + 1:]:
                    if "." in a and not a.startswith("-"):
                        script = a; break
            else:
                for a in args:
                    if a.endswith(".py"):
                        script = a; break
            out[key] = script
    except Exception:
        pass
    return out


def _resolve(script):
    """مسار ملفّ السكربت على القرص (من اسم/وحدة)."""
    if not script:
        return None
    script = script.split(":")[0]   # 🩹 جرّد لاحقة :app (مثل friday_desktop.backend.server:app)
    if script.endswith(".py"):
        for base in (ROOT, V2, V2 / "runtime", ROOT / "plutobrain_swarm"):
            p = base / script
            if p.exists():
                return p
    else:  # module path a.b.c
        rel = script.replace(".", "/") + ".py"
        for base in (V2, ROOT):
            p = base / rel
            if p.exists():
                return p
    return None   # غير موجود في المسارات المعروفة ⇒ تبقى عقدة محروسة عبر الوصيّ (لا globs بطيئة)


# 🔗 الوحدات المشتركة (المؤشّرات/الأدوات/الحرّاس) — نكشف استيرادها كي تظهر متّصلةً بمحرّكاتها (لا معزولة)
SHARED_MODS = ["lot_guard", "trend_flip", "level_map", "engine_gov", "engine_lock", "portfolio_guard",
               "deep_conviction", "candle_anatomy", "market_structure", "delta_flow", "novel_indicators",
               "chart_read", "order_blocks", "sentiment_composite"]


def _scan(path):
    """يكتشف من كود المحرّك: MT5؟ ينفّذ صفقات؟ أيّ ملفّات يلمس؟ وأيّ وحدات مشتركة يستورد (للوصل الدقيق)."""
    try:
        s = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"mt5": False, "exec": False, "files": [], "imports": []}
    mt5 = "MetaTrader5" in s or "import mt5" in s
    execu = "order_send" in s and "TRADE_ACTION_DEAL" in s
    files = sorted(set(m.group(1) for m in _FILE_RE.finditer(s)))
    writes = bool(_WRITE_HINT.search(s))
    imports = [m for m in SHARED_MODS if re.search(r"(^|\n)\s*(import\s+%s\b|from\s+%s\s+import)" % (m, m), s)]
    return {"mt5": mt5, "exec": execu, "files": files[:8], "writes": writes, "imports": imports}


def _alive_map():
    try:
        d = json.load(open(RN / "watchdog_status.json", encoding="utf-8-sig"))
        return {k: (v > 0) for k, v in (d.get("alive", {}) or {}).items()}
    except Exception:
        return {}


def _is_alive(key, alive):
    for k, v in alive.items():
        if key == k or key in k or k in key:
            return v
    return None


def _file_age(fname):
    for base in (RN, RN / "agents", V2 / "data", ROOT / "data", ROOT):
        p = base / fname
        try:
            if p.exists():
                return time.time() - p.stat().st_mtime
        except Exception:
            pass
    return None


# ── نبضٌ حيّ لكل عقدة (heartbeat): أحدث ملفّ حالة/سجلّ/إخراج يحمل اسمها ⇒ عمر آخر نبض ──
# أنواع العقد العمليّة التي تحتاج نبضاً (لا الملفّيّة/الوسيط):
_ALIVE_TYPES = {"engine", "executor", "brain", "llm", "feeder", "learner",
                "governor", "ui", "recorder", "module"}
_PULSE_DIRS = (RN, RN / "agents", V2 / "data", V2 / "runtime", ROOT / "data", ROOT)
# لواحق ملفّات النبض المعروفة (status/state/feed/report/log/out) — أيّها أحدث = آخر نبضة
_PULSE_SUFFIXES = ("_status.json", "_state.json", "_feed.jsonl", "_report.json",
                   "_status.jsonl", ".out.log", ".log", "_config.json", ".json")
_HB_CACHE = {"ts": 0.0, "idx": None}


def _pulse_index():
    """فهرس {اسم-مجرّد → أحدث mtime لأيّ ملفّ نبضٍ يحمله} — مبنيّ مرّةً كل 10ث (مسح المجلّدات)."""
    now = time.time()
    if _HB_CACHE["idx"] is not None and now - _HB_CACHE["ts"] < 10:
        return _HB_CACHE["idx"]
    idx = {}
    for base in _PULSE_DIRS:
        try:
            for p in base.iterdir():
                if not p.is_file():
                    continue
                fn = p.name
                stem = None
                for suf in _PULSE_SUFFIXES:
                    if fn.endswith(suf):
                        stem = fn[: -len(suf)]
                        break
                if not stem:
                    continue
                try:
                    mt = p.stat().st_mtime
                except Exception:
                    continue
                # طبّع: أزل بادئات المسار المنقّط (runtime./r_native.) واللواحق الرقميّة
                key = stem.lower()
                if key not in idx or mt > idx[key]:
                    idx[key] = mt
        except Exception:
            pass
    _HB_CACHE["ts"] = now; _HB_CACHE["idx"] = idx
    return idx


# مرادفات أسماء العقد → جذر ملفّ النبض (حين يختلف اسم العقدة عن اسم ملفّها)
_HB_ALIAS = {
    "gold_level_sentinel": "gold_sentinel", "youtube_analyst_agent": "youtube_analyst",
    "gold_straddle_3627": "straddle3627", "pipflow_core": "pipflow",
    "news_gene": "news_gene", "manual_mimic": "manual_mimic", "radhi_mimic": "radhi_mimic",
}


def _heartbeat_age(node_id):
    """عمر آخر نبضٍ (ثوانٍ) لعقدةٍ عمليّة عبر أحدث ملفّ حالة/سجلّ يحمل اسمها، أو None."""
    idx = _pulse_index()
    now = time.time()
    cand = node_id.lower()
    keys = [cand, _HB_ALIAS.get(cand, "")]
    best = None
    for k in keys:
        if not k:
            continue
        # مطابقة مباشرة أو احتواء (اسم العقدة داخل جذر الملفّ أو العكس، لتغطية اللواحق)
        for stem, mt in idx.items():
            if stem == k or (len(k) >= 5 and (k in stem or stem in k)):
                if best is None or mt > best:
                    best = mt
    return (now - best) if best is not None else None


def _pulse(age_s, alive):
    """يصنّف النبض: live<90 / warm 90-300 / stale 300-1800 / dark >1800 أو لا عملية."""
    if alive is False:
        return "dark"
    if age_s is None:
        return "dark"
    if age_s < 90:
        return "live"
    if age_s < 300:
        return "warm"
    if age_s < 1800:
        return "stale"
    return "dark"


_BUILD_CACHE = {"ts": 0.0, "r": None}


def build():
    now0 = time.time()                                  # طوبولوجيا مُخبّأة 12ث (مسح الكود ثقيل) — الحالة تتحدّث ضمنها
    if _BUILD_CACHE["r"] is not None and now0 - _BUILD_CACHE["ts"] < 12:
        return _BUILD_CACHE["r"]
    engines = _engines()
    alive = _alive_map()
    eg = {}
    try:
        eg = json.load(open(RN / "engine_governance.json", encoding="utf-8"))
    except Exception:
        pass
    mults = eg.get("mults", {}); paused = set(int(x) for x in eg.get("paused", [])); raw = eg.get("raw", {})

    nodes, edges = [], []
    nset = set()
    def add(nid, ntype, **meta):
        if nid in nset: return
        nset.add(nid); nodes.append({"id": nid, "type": ntype, **meta})

    add("MT5", "broker", label="MT5 / الوسيط", alive=True)

    for key, script in engines.items():
        name = _short(key)
        path = _resolve(script)
        sc = _scan(path) if path else {"mt5": False, "exec": False, "files": []}
        typ, magic = TYPED.get(name, ("engine", None))
        if sc.get("exec"):
            typ = "executor" if typ in ("engine",) else typ
        live = _is_alive(key, alive)
        _al = (live if live is not None else True)
        _age = _heartbeat_age(name) or _heartbeat_age(key)
        node = {"alive": _al, "age_s": (round(_age, 0) if _age is not None else None),
                "pulse": _pulse(_age, _al), "magic": magic}
        if magic is not None:
            node["throttle"] = mults.get(str(magic))
            node["fired"] = magic in paused
            node["tier"] = (raw.get(str(magic)) or {}).get("tier")
            node["net"] = (raw.get(str(magic)) or {}).get("net")
        add(name, typ, **node)
        # وصلة MT5 العامّة (الموصِّل الأساسيّ: كل محرّك يستعمل السوق متّصل بالمحور)
        if sc.get("mt5"):
            edges.append({"source": name, "target": "MT5", "kind": "exec" if sc.get("exec") else "mt5"})
        # وصلات الملفّات المُكتشَفة (تربط المحرّك ببقيّة المنظومة عبر الملفّات المشتركة)
        for f in sc.get("files", []):
            if f in ("config.json",):  # ضوضاء
                continue
            age = _file_age(f)
            stale = (age is not None and age > STALE_S and f != "friday.db")
            _fal = (age is not None and age < 180)   # ملفّ حيّ = عمره < 180ث
            add(f, "data", label=f, age=(round(age, 0) if age is not None else None),
                stale=stale, alive=_fal,
                age_s=(round(age, 0) if age is not None else None),
                pulse=_pulse(age, None if age is not None else False))
            # اتجاه تقريبيّ: ملفّات الحالة/الإخراج = كتابة، غيرها = قراءة
            wr = sc.get("writes") and any(t in f for t in ("status", "state", "report", "scoreboard", "rules",
                                          "governance", "dna", "profile", "config", "history", "register", "proof",
                                          "candidates", "weights", "accuracy", "dossier", "directive", "signals", "ledger"))
            edges.append({"source": (name if wr else f), "target": (f if wr else name), "kind": "data"})
        # 🔗 وصلات الوحدات المشتركة (المؤشّرات/الأدوات): المحرّك → الوحدة التي يستوردها (وصلٌ دقيق حقيقيّ)
        for mod in sc.get("imports", []):
            add(mod, "module", label=mod, alive=True)
            edges.append({"source": name, "target": mod, "kind": "uses"})

    # تدفّقات الحوكمة الملوّنة (المايسترو/الأرضية/الحاصد → المنفّذون)
    name_by_magic = {v[1]: k for k, v in TYPED.items() if v[1]}
    for gov, magics in GOV_BY.items():
        if gov not in nset:
            continue
        for mg in magics:
            if mg == "ALL":
                for n in nodes:
                    if n["type"] == "executor":
                        edges.append({"source": gov, "target": n["id"], "kind": "control"})
            elif mg in name_by_magic:
                edges.append({"source": gov, "target": name_by_magic[mg], "kind": "control"})

    # 🧹 تهذيب: أسقِط ملفّات الحالة الخاصّة (درجة 1 — لا تُظهر تغذيةً بين محرّكات) كي تبرز الملفّات المشتركة
    #   (delta/intermarket/deep_dossier/governance...) التي يغذّي عبرها محرّكٌ محرّكاً. الرسم يصير نظيفاً ومعبّراً.
    _d = {}
    for e in edges:
        _d[e["source"]] = _d.get(e["source"], 0) + 1
        _d[e["target"]] = _d.get(e["target"], 0) + 1
    drop = set(n["id"] for n in nodes if n["type"] == "data" and _d.get(n["id"], 0) < 2)
    nodes = [n for n in nodes if n["id"] not in drop]
    edges = [e for e in edges if e["source"] not in drop and e["target"] not in drop]
    nset = set(n["id"] for n in nodes)

    # وصلات المراقبين/المُشغّلين الصريحة (بعد التهذيب — تربطهم بما يقرؤونه فعلاً، بالترتيب الصحيح)
    for src, tgt, kind in EXTRA:
        if src in nset:
            if tgt not in nset:
                add(tgt, "data", label=tgt)
            edges.append({"source": src, "target": tgt, "kind": kind})

    # 🏛️ حقن عقد LLM/Ollama الثابتة + خيوط المجلس (موديلات ليست عمليّات — تُعرض كطبقة عقولٍ)
    for lid, ltype in LLM_NODES:
        if lid not in nset:
            add(lid, ltype, label=lid)
            nset.add(lid)
    for src, tgt in LLM_EDGES:
        if src in nset and tgt in nset:
            edges.append({"source": src, "target": tgt, "kind": "llm"})

    # 🧠 حقن عقد القمرة العميقة + أسلاكها (بعد التهذيب — مصادر get_pro_data الحقيقيّة لا يلتقطها المسح الآليّ)
    for cid, ctype in COCKPIT_NODES:
        if cid not in nset:
            add(cid, ctype, label=cid, alive=True)
            nset.add(cid)
    for src, tgt in COCKPIT_EDGES:
        if src in nset and tgt in nset:
            edges.append({"source": src, "target": tgt, "kind": "reads"})

    # 🕸️ الموصِّل العامّ: الوصيّ يحرس كل محرّك ⇒ صِل أيّ عقدة لم يلتقطها الاكتشاف بالوصيّ (لا انفصال حقيقيّ)
    deg0 = {}
    for e in edges:
        deg0[e["source"]] = deg0.get(e["source"], 0) + 1
        deg0[e["target"]] = deg0.get(e["target"], 0) + 1
    iso = [n["id"] for n in nodes if deg0.get(n["id"], 0) == 0 and n["id"] != "watchdog_guard"]
    if iso:
        add("watchdog_guard", "governor", label="watchdog_guard", alive=True)
        for nid in iso:
            edges.append({"source": "watchdog_guard", "target": nid, "kind": "control"})

    # 💓 نبضٌ موحّد لكل عقدةٍ عمليّة لم تُختَم بعد (الوحدات/القمرة/العقول/الوصيّ المحقونة post-prune):
    #    alive/age_s/pulse من أحدث ملفّ حالة/سجلّ يحمل اسمها. عقد LLM الساكنة (موديلات، لا عمليّات)
    #    تبقى نبضها من ملفّ مستهلكها إن وُجد وإلّا dark — دون كسر بنيتها.
    for n in nodes:
        if n["type"] not in _ALIVE_TYPES:
            continue
        if "pulse" in n:                     # خُتِمت في حلقة المحرّكات
            continue
        hb = _heartbeat_age(n["id"])
        al = n.get("alive")
        n["age_s"] = (round(hb, 0) if hb is not None else None)
        n["pulse"] = _pulse(hb, al if al is not None else (None if hb is not None else False))
        if "alive" not in n:
            n["alive"] = (hb is not None and hb < 180)

    # كشف الفجوات (بعد الوصل العامّ — المتبقّي = فجوة حقيقيّة)
    deg = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    disconnected = [n["id"] for n in nodes if deg.get(n["id"], 0) == 0]
    dead = [n["id"] for n in nodes if n.get("alive") is False]
    stale = [n["id"] for n in nodes if n.get("stale")]
    gaps = {"disconnected": disconnected, "dead_engines": dead, "stale_files": stale,
            "n_nodes": len(nodes), "n_edges": len(edges)}
    out = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nodes": nodes, "edges": edges, "gaps": gaps}
    _BUILD_CACHE["ts"] = time.time(); _BUILD_CACHE["r"] = out
    return out


def _find_file(name):
    for base in (RN, RN / "agents", V2 / "data", ROOT / "data", ROOT):
        p = base / name
        try:
            if p.exists():
                return p
        except Exception:
            pass
    return None


def _read_file(name, limit=1800):
    """يقرأ ملفّ بياناتٍ (مقصوصاً) + عمره — لإثبات أنّ العقدة تنتج فعلاً."""
    p = _find_file(name)
    if not p:
        return {"exists": False}
    try:
        age = time.time() - p.stat().st_mtime
        if name.endswith(".db"):
            return {"exists": True, "age_min": round(age / 60, 1), "note": "SQLite DB (ثنائيّ)"}
        txt = p.read_text(encoding="utf-8", errors="replace")
        return {"exists": True, "age_min": round(age / 60, 1), "size": p.stat().st_size,
                "fresh": age < STALE_S, "content": txt[:limit], "truncated": len(txt) > limit}
    except Exception as e:
        return {"exists": True, "error": str(e)}


def _read_log(name):
    short = name.split("/")[-1].split(".")[-1] if "." in name else name
    for cand in (RN / f"{name}.log", RN / f"{short}.log", RN / f"{name.split('/')[-1]}.log"):
        try:
            if cand.exists():
                return cand.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        except Exception:
            pass
    return None


def node_detail(node_id):
    """بيانات عقدةٍ حيّة (للمفتّش): حالتها + مخرجاتها (الملفّات التي تكتبها) + ذيل سجلّها + ما تقرؤه."""
    g = build()
    node = next((n for n in g["nodes"] if n["id"] == node_id), None)
    if not node:
        return {"error": "node not found", "id": node_id}
    det = {"id": node_id, "type": node["type"]}
    for k in ("alive", "magic", "throttle", "fired", "tier", "net", "age", "stale", "label"):
        if node.get(k) is not None:
            det[k] = node[k]
    if node["type"] == "data":
        det["file"] = _read_file(node_id)
    elif node["type"] == "broker":
        det["connected_engines"] = sorted(set(e["source"] for e in g["edges"] if e["target"] == node_id))
        det["floor"] = _read_file("master_floor_state.json")
        det["pnl"] = _read_file("pnl_scoreboard.json")
    else:  # engine
        data_ids = set(n["id"] for n in g["nodes"] if n["type"] == "data")
        outs = [e["target"] for e in g["edges"] if e["source"] == node_id and e["target"] in data_ids]
        reads = [e["source"] for e in g["edges"] if e["target"] == node_id and e["source"] in data_ids]
        det["outputs"] = {f: _read_file(f) for f in sorted(set(outs))[:3]}     # ما تُغذّيه (تكتبه)
        det["reads"] = sorted(set(reads))                                       # ما تتغذّى منه (تقرؤه)
        det["log"] = _read_log(node_id)                                         # ترمينال: ذيل السجلّ
        det["trades_to"] = "MT5" if any(e["target"] == "MT5" for e in g["edges"] if e["source"] == node_id) else None
    return det


if __name__ == "__main__":
    import sys
    g = build()
    print(json.dumps(g["gaps"], ensure_ascii=False, indent=1))
    if "--full" in sys.argv:
        print(json.dumps(g, ensure_ascii=False))
