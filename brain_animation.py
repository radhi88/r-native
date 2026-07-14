"""brain_animation.py — FRIDAY ARENA: the live trading system as an interactive financial GAME.

Genomes = characters (avatar, LVL, HP, XP, class = their session specialty). Agents = workers.
A decision arena (canvas) shows inputs → per-currency decisions → win/loss sinks. A full RISK
COMMAND CENTER implements the ICA/ISO-31000 cycle from the user's course slides (establish
context → identify → analyze → prioritize → treat + monitoring & communication rails) with the
LIVE risk register from risk_manager.py. Tabs: الساحة · المخاطر · الاستخبارات · التطوّر · الخريطة.

Read-only · stdlib only · windowless · no sounds.  Open:  http://127.0.0.1:8870
"""
from __future__ import annotations
import json, time, glob, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

V2 = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
PORT = 8870


def _load(p, d=None):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return d


SWARM_STATE = Path(r"C:\Users\Radhi\MT5\plutobrain_swarm\swarm_state")


def _swarm():
    st = _load(SWARM_STATE / "agent_status.json", {}) or {}
    alloc = _load(SWARM_STATE / "agent_allocation_map.json", {}) or {}
    alerts = (_load(SWARM_STATE / "alerts.json", {}) or {}).get("alerts", []) or []
    log = (_load(SWARM_STATE / "orchestrator_log.json", {}) or {}).get("cycles", []) or []
    agents = st.get("agents", []) or []
    last = log[-1] if log else {}
    clusters = {}
    for a in agents:
        clusters.setdefault(a.get("cluster", "?"), []).append(a)
    fresh = bool(agents) and (time.time() - st.get("generated", 0)) < 300
    return {"online": fresh, "cycle": st.get("cycle", 0), "agents": agents,
            "n_agents": len(agents), "active_pool": len(alloc.get("active_pool", []) or []),
            "escalate": alloc.get("escalate", []) or [], "alerts": alerts[-6:],
            "findings": last.get("findings", 0), "uptime": round(last.get("uptime_s", 0) / 60, 1),
            "clusters": {k: len(v) for k, v in clusters.items()}}


def _session_now():
    try:
        if str(V2.parent) not in sys.path:
            sys.path.insert(0, str(V2.parent))
        from indicators import session as S
        return S.classify().name
    except Exception:
        return "?"


def _data():
    sess = _session_now()
    # stables (session specialists) — include stable-only symbols as characters too
    stables = {}
    for sf in glob.glob(str(V2 / "genomes" / "*" / "stable.json")):
        st = _load(sf, {}) or {}
        sym = st.get("symbol") or Path(sf).parent.name
        specs = st.get("specialists", []) or []
        if specs:                                   # empty stable = no validated session edge → not a hero
            stables[sym] = specs
    top_syms = {Path(f).stem for f in glob.glob(str(V2 / "genomes/*.json"))}
    syms = sorted(top_syms | set(stables))
    pnl, openpos, curves = {}, {}, {}
    acct_curve, start_bal = [], 0
    try:
        import MetaTrader5 as mt5; mt5.initialize()
        dl = sorted([d for d in (mt5.history_deals_get(int(time.time() - 24 * 3600), int(time.time())) or [])
                     if d.entry == 1 and d.magic == 20260608], key=lambda d: d.time)
        for d in dl:
            t = pnl.setdefault(d.symbol, [0, 0.0]); t[0] += 1; t[1] += d.profit + d.commission + d.swap
            cur = curves.setdefault(d.symbol, [0.0])
            cur.append(round(cur[-1] + d.profit + d.commission + d.swap, 2))
        for p in (mt5.positions_get() or []):
            if p.magic == 20260608:
                o = openpos.setdefault(p.symbol, [0, 0.0]); o[0] += 1; o[1] += p.profit
        acct = mt5.account_info(); equity = round(acct.equity, 2) if acct else 0
        alld = sorted([d for d in (mt5.history_deals_get(int(time.time() - 12 * 3600), int(time.time())) or [])
                       if d.entry == 1], key=lambda d: d.time)
        run = 0.0
        for d in alld:
            run += d.profit + d.commission + d.swap; acct_curve.append(round(run, 2))
        start_bal = round((acct.balance if acct else 0) - run, 2)
        mt5.shutdown()
    except Exception:
        equity = 0; acct_curve = []; start_bal = 0
    insights = []
    try:
        import urllib.request
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:5055/api/r/agents/insights?n=10", timeout=3).read())
        il = d.get("insights", d) if isinstance(d, dict) else d
        insights = [{"agent": x.get("agent"), "msg": str(x.get("message", ""))[:90]} for x in (il or [])][:8]
    except Exception:
        pass
    _nsig = (_load(RN / "agents" / "news_signals.json", {}) or {}).get("symbols", {})
    _xsig = (_load(V2 / "intermarket_signals.json", {}) or {}).get("signals", {})
    _drv = (_load(RN / "market_directive.json", {}) or {}).get("symbols", {})
    _dlt = _load(RN / "delta_state.json", {}) or {}
    cards = []
    for s in syms:
        g = _load(V2 / f"genomes/{s}.json", {}) or {}
        cfg = g.get("config", {}); oos = g.get("oos", {})
        specs = stables.get(s, [])
        sessions = [x.get("session") for x in specs]
        if not cfg and specs:                       # stable-only character: use its session gene
            best = next((x for x in specs if x.get("session") == sess), None) or \
                   max(specs, key=lambda x: x.get("pf", 0))
            cfg = {"tf": best.get("tf"), "stop_atr": best.get("stop_atr"),
                   "target_atr": best.get("target_atr"), "conf_gate": best.get("conf_gate")}
            oos = {k: best.get(k) for k in ("pf", "net_R", "trades", "folds_pos", "win_rate")}
        w = (_load(V2 / f"indicator_weights_{s}.json", {}) or {}).get("weights", {})
        acc = (_load(V2 / f"indicator_accuracy_{s}.json", {}) or {}).get("accuracy", {})
        sec = _load(V2 / f"secure_config_{s}.json", {}) or {}
        vol = _load(V2 / f"vol_regime_{s}.json", {}) or {}
        n, net = pnl.get(s, [0, 0.0])
        on, ofl = openpos.get(s, [0, 0.0])
        inds = []
        for k, wt in sorted(w.items(), key=lambda x: -x[1]):
            hr = (acc.get(k, {}) or {}).get("hit_rate", 0.5)
            inds.append({"name": k, "w": round(wt, 2), "hit": round(hr * 100, 1)})
        fix = []
        if net < -1:
            if n >= 4 and net < -8:
                fix.append("🛑 بُنّح — ينزف حيّاً")
            if float(sec.get("be_atr", 1) or 1) <= 0.1:
                fix.append("🛡 تأمين أسرع")
            fix.append("🧠 أوزان أُعيد قياسها")
        why = sorted([i for i in inds if i["hit"] >= 52], key=lambda i: -i["hit"])[:4]
        active = (sess in sessions) if sessions else True
        cards.append({"sym": s, "tf": cfg.get("tf", "?"), "oos_pf": oos.get("pf", 0) or 0,
                      "oos_r": oos.get("net_R", 0), "live_n": n, "live_net": round(net, 2),
                      "open_n": on, "open_fl": round(ofl, 2),
                      "vol": vol.get("state", "?"), "rev": round(sec.get("reversal_rate", 0) * 100),
                      "be": sec.get("be_atr", "?"), "inds": inds[:8], "fix": fix,
                      "stop": cfg.get("stop_atr"), "target": cfg.get("target_atr"), "gate": cfg.get("conf_gate"),
                      "win": round(float(oos.get("win_rate", 0) or 0) * 100, 1),
                      "folds": oos.get("folds_pos"), "trades": oos.get("trades"), "why": why,
                      "news_dir": (_nsig.get(s) or {}).get("news_dir", 0),
                      "xa_dir": (_xsig.get(s) or {}).get("dir", 0),
                      "action": (_drv.get(s) or {}).get("action", ""),
                      "delta_bias": (_dlt.get(s) or {}).get("bias"),
                      "sessions": sessions, "active": active,
                      "trained": g.get("trained"), "retune": g.get("retune"),
                      "curve": (curves.get(s, [0.0]))[-30:]})
    cards.sort(key=lambda c: (-int(c["active"]), -c["live_net"]))
    cand = _load(V2 / "market_candidates.json", {}) or {}
    gate = _load(V2 / "market_gate.json", {}) or {}
    proof = _load(V2 / "paper_proof.json", {}) or {}
    elig = len(gate.get("eligible", []) or [])
    nspec = sum(len(v) for v in stables.values()) + len(top_syms)
    proven = [s for s, x in (proof.get("symbols", {}) or {}).items() if x.get("status") == "PROVEN"]
    roadmap = [
        {"n": "اكتشاف الأسواق", "v": f"{cand.get('scanned', '—')} سوق", "st": "done"},
        {"n": "بوّابة OOS + سبريد حقيقي", "v": f"{elig} مؤهّل", "st": "done"},
        {"n": "مصنع الجينات", "v": f"{nspec} جين/متخصّص", "st": "done"},
        {"n": "توجيه الجلسات", "v": "حيّ", "st": "done"},
        {"n": "إدارة المخاطر ICA", "v": "حيّ", "st": "done"},
        {"n": "إثبات أمامي", "v": f"{len(proven)} PROVEN", "st": "active"},
        {"n": "ربحية حيّة مستدامة", "v": "قيد الإثبات", "st": "active"},
        {"n": "فلوس حقيقية", "v": "بانتظار إثبات + إذنك", "st": "wait"},
    ]
    im = _load(V2 / "intermarket_signals.json", {}) or {}
    xpairs = (im.get("pairs", []) or [])[:10]
    xsig = im.get("signals", {}) or {}
    xsignals = [{"sym": s, "dir": v.get("dir"), "conf": v.get("conf"), "why": v.get("why", "")}
                for s, v in sorted(xsig.items(), key=lambda kv: -float(kv[1].get("conf", 0)))][:8]
    ns = _load(RN / "agents" / "news_signals.json", {}) or {}
    nsyms = ns.get("symbols", {}) or {}
    news = [{"sym": s, "dir": v.get("news_dir"), "tier": v.get("tier"), "conv": v.get("conviction"),
             "veto": v.get("veto"), "reason": v.get("reason", "")}
            for s, v in sorted(nsyms.items(), key=lambda kv: -abs(float(kv[1].get("conviction", 0))))
            if v.get("news_dir") or v.get("veto")][:8]
    evo = _load(V2 / "genome_evo_history.json", {}) or {}
    ega = evo.get("ga", {}) or {}
    evolist = [{"sym": s, "pf": v.get("cur_pf"), "win": v.get("win"), "folds": v.get("folds"),
                "pct": v.get("pct")} for s, v in sorted((evo.get("symbols", {}) or {}).items(),
                key=lambda kv: -(float(kv[1].get("cur_pf") or 0)))]
    truth = _load(RN / "pnl_scoreboard.json", {}) or {}
    wd = _load(RN / "watchdog_status.json", {}) or {}
    truth = dict(truth); truth["guard"] = {"alive": wd.get("n_alive"), "total": wd.get("n_total"),
                                           "restarts": sum((wd.get("restarts") or {}).values())}
    risk = _load(RN / "risk_register.json", {}) or {}
    risk = dict(risk); risk["modes"] = (_load(RN / "mode_weights.json", {}) or {}).get("modes", {})
    # 🏆 بطولة التوائم — live duel lineage for the breeding tree
    tst = _load(RN / "tournament_state.json", {}) or {}
    tlin = []
    try:
        for ln in (RN / "tournament_lineage.jsonl").read_text(encoding="utf-8").strip().splitlines()[-60:]:
            tlin.append(json.loads(ln))
    except Exception:
        pass
    tournament = {"contestants": list((tst.get("contestants") or {}).values())[-40:],
                  "duels": list((tst.get("duels") or {}).values()),
                  "lineage": tlin, "confirmed": _load(RN / "tournament_confirmed.json", {}) or {}}
    sst = _load(RN / "straddle_state.json", {}) or {}
    sj = (_load(RN / "straddle_journal.json", {}) or {}).get("episodes", [])
    straddle = {"eval": sst.get("last_eval", ""), "cfg": (sst.get("cfg") or {}),
                "episodes": sj[-8:], "net": round(sum(e.get("net", 0) for e in sj), 2),
                "help": bool(_load(RN / "straddle_help_request.json"))}
    return {"ts": time.time(), "equity": equity, "start_bal": start_bal, "acct_curve": acct_curve[-60:],
            "straddle": straddle, "tournament": tournament,
            "session": sess, "roadmap": roadmap, "cards": cards, "insights": insights,
            "xpairs": xpairs, "xsignals": xsignals, "news": news, "news_n": ns.get("n_items", 0),
            "news_clusters": ns.get("clusters", {}), "evo_ga": ega, "evo_syms": evolist,
            "truth": truth, "swarm": _swarm(), "risk": risk}


HTML = """<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8>
<title>FRIDAY ARENA — ساحة الجينات</title><style>
*{box-sizing:border-box;margin:0;font-family:'Segoe UI',Tahoma,sans-serif}
body{background:radial-gradient(1400px 700px at 50% -10%,#131b34,#06080f 62%);color:#e6edf3;padding:10px 14px;min-height:100vh}
.hud{display:flex;gap:10px;align-items:center;justify-content:center;flex-wrap:wrap;background:linear-gradient(180deg,#0e1730ee,#0a1020cc);
 border:1px solid #27355a;border-radius:16px;padding:10px 16px;margin-bottom:10px;box-shadow:0 0 50px #1a2a5530 inset}
.logo{font-size:19px;font-weight:900;color:#e8c46a;text-shadow:0 0 22px #e8c46a66;letter-spacing:1px}
.orb{display:flex;flex-direction:column;align-items:center;min-width:74px}
.orb .v{font-size:19px;font-weight:900}.orb .l{font-size:9px;color:#7d8590}
.pos{color:#3fe07a}.neg{color:#ff6b62}.neu{color:#9fb0c3}
.sessbadge{background:#101b38;border:1px solid #2c3c66;border-radius:10px;padding:5px 12px;font-size:12px;color:#9fc1ff;font-weight:800}
.sessbadge b{color:#e8c46a}
.gauge{position:relative;width:62px;height:62px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:900}
.gauge::before{content:'';position:absolute;inset:5px;border-radius:50%;background:#0a1020}
.gauge span{position:relative;z-index:1}
.glow-pulse{animation:gp 1.6s infinite}
@keyframes gp{0%,100%{filter:brightness(1)}50%{filter:brightness(1.45)}}
.tabs{display:flex;gap:6px;justify-content:center;flex-wrap:wrap;margin-bottom:10px}
.tab{background:#0e1628;border:1px solid #243250;color:#9fb0c3;border-radius:11px;padding:8px 18px;font-size:13px;font-weight:800;cursor:pointer;transition:.2s}
.tab:hover{border-color:#e8c46a88;color:#e8c46a}
.tab.on{background:linear-gradient(180deg,#1c2a4d,#131d38);border-color:#e8c46a;color:#e8c46a;box-shadow:0 0 18px #e8c46a33}
.page{display:none}.page.on{display:block;animation:fadein .25s}
@keyframes fadein{from{opacity:0;transform:translateY(6px)}to{opacity:1}}
.lanes{display:flex;gap:6px;justify-content:center;margin-bottom:8px;flex-wrap:wrap}
.lane{background:#0d1526;border:1px solid #1f2c48;border-radius:9px;padding:4px 14px;font-size:11px;color:#6c7a92;font-weight:700}
.lane.on{background:linear-gradient(180deg,#2b2410,#171303);border-color:#e8c46a;color:#e8c46a;box-shadow:0 0 16px #e8c46a44;animation:gp 2s infinite}
.stage{background:#0b1222cc;border:1px solid #1f2a44;border-radius:16px;padding:8px;margin-bottom:12px;box-shadow:0 0 40px #0b1e3a55 inset}
#net{width:100%;height:430px;display:block;cursor:pointer}
.fttl{text-align:center;color:#8fa3bd;font-size:11px;margin-top:3px}
.heroes{display:grid;grid-template-columns:repeat(auto-fill,minmax(235px,1fr));gap:10px;margin-bottom:12px}
.hero{position:relative;background:linear-gradient(165deg,#121c33,#0b1222);border:1.5px solid #233252;border-radius:14px;padding:10px 12px;cursor:pointer;transition:.25s;overflow:hidden}
.hero:hover{transform:translateY(-3px);border-color:#e8c46a99;box-shadow:0 8px 26px #00000066}
.hero.win{border-color:#2ea04399}.hero.loss{border-color:#f8514999}.hero.sleep{opacity:.62}
.hero.sel{border-color:#e8c46a;box-shadow:0 0 24px #e8c46a44}
.hav{font-size:30px;float:right;margin-left:8px;filter:drop-shadow(0 0 8px #e8c46a55)}
.hname{font-size:15px;font-weight:900;color:#ffd97a}.hlvl{font-size:9px;background:#2b2410;color:#e8c46a;border:1px solid #e8c46a66;border-radius:5px;padding:1px 6px;margin-right:5px}
.hclass{font-size:9.5px;color:#8fa3bd;margin:2px 0 6px}
.hbar{display:flex;align-items:center;gap:5px;font-size:9px;color:#7d8590;margin:3px 0}
.hbar .lab{width:18px}
.htrack{flex:1;height:8px;background:#0a0f1c;border-radius:5px;overflow:hidden;border:1px solid #1c2740}
.hfill{height:100%;border-radius:5px;transition:width .8s cubic-bezier(.2,.8,.2,1)}
.hstat{display:flex;justify-content:space-between;align-items:center;margin-top:6px;font-size:10px}
.hbadge{border-radius:6px;padding:2px 8px;font-weight:800;font-size:9.5px}
.b-fight{background:#11301d;color:#3fe07a;border:1px solid #2ea04366}
.b-sleep{background:#1a1f2e;color:#8a93a8;border:1px solid #2c354d}
.b-bench{background:#33141a;color:#ff8c85;border:1px solid #f8514966}
.hpnl{font-size:15px;font-weight:900}
.panel{background:#0d1526;border:1px solid #233252;border-radius:14px;padding:12px 14px;margin-bottom:12px}
.panel h3{font-size:13px;color:#9fc1ff;margin-bottom:8px;text-align:center}
.cyc{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-bottom:10px}
.cstep{background:linear-gradient(180deg,#3d1140,#220a26);border:1px solid #a83cb066;border-radius:9px;padding:7px 13px;font-size:11px;color:#f5c8fa;font-weight:800;position:relative}
.cstep::after{content:'⟵';position:absolute;left:-13px;top:8px;color:#5a3a60;font-size:10px}
.cstep:last-child::after{content:''}
.rails{display:flex;gap:8px;justify-content:center;margin-bottom:10px;font-size:10px}
.rail{background:#171030;border:1px solid #5a48a066;border-radius:8px;padding:4px 14px;color:#b8a8f0}
.rtable{width:100%;border-collapse:collapse;font-size:11px}
.rtable th{color:#6c7a92;font-size:10px;text-align:right;padding:4px 6px;border-bottom:1px solid #1f2c48}
.rtable td{padding:6px;border-bottom:1px solid #141d33;color:#bac6da}
.lv{border-radius:6px;padding:2px 9px;font-weight:900;font-size:10px}
.lv.CRITICAL{background:#4a1016;color:#ff7a72;border:1px solid #ff4d4d66;animation:gp 1.2s infinite}
.lv.HIGH{background:#3d2a0c;color:#ffb24d;border:1px solid #ff9d2e55}
.lv.MED{background:#33300e;color:#e8d44d;border:1px solid #d4c42e44}
.lv.LOW{background:#0e2e18;color:#52d97a;border:1px solid #2ea04355}
.matrix{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;max-width:330px;margin:10px auto}
.mcell{aspect-ratio:1.6;border-radius:5px;display:grid;place-items:center;font-size:9px;font-weight:900;color:#0a0f1c}
.treat{font-size:10px;color:#7fd0a0}
.road{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-bottom:12px}
.rstage{background:#0d1526;border:1px solid #1f2c48;border-radius:9px;padding:6px 11px;font-size:11px;text-align:center;min-width:92px}
.rstage .rn{color:#cdd9e5;font-weight:800;display:block}.rstage .rv{color:#6c7a92;font-size:9.5px}
.rstage.done{border-color:#2ea04388}.rstage.done .rn{color:#3fe07a}
.rstage.active{border-color:#e8c46a;box-shadow:0 0 14px #e8c46a33}.rstage.active .rn{color:#e8c46a}
.rstage.wait{opacity:.5}
#acctc{width:100%;height:110px;display:block}
.acctlbl{display:flex;justify-content:space-between;font-size:11px;color:#8fa3bd;margin-top:2px}
.detail{background:#0e1730;border:1.5px solid #e8c46a88;border-radius:14px;padding:12px 14px;margin-bottom:12px;display:none;font-size:11px;box-shadow:0 0 30px #e8c46a22}
.detail .dh{font-size:13px;margin-bottom:7px;border-bottom:1px solid #243250;padding-bottom:6px}
.detail .dh b{color:#ffd97a;font-size:17px}
.detail .drow{margin:4px 0;color:#bac6da;line-height:1.7}.detail .drow>b{color:#8fa3bd}
.chip{background:#1c2740;border-radius:5px;padding:2px 8px;margin:0 3px;color:#9fd0b5;font-size:10px;display:inline-block}
.dclose{float:left;cursor:pointer;color:#6c7a92;font-size:15px}
.bar{display:flex;align-items:center;gap:6px;margin:2px 0;font-size:10px}
.bn{width:70px;color:#8fa3bd;text-align:left}
.btrack{flex:1;background:#0a0f1c;border-radius:4px;height:10px;overflow:hidden}
.bfill{height:100%;border-radius:4px;transition:width .7s}
.nrow{display:flex;gap:6px;flex-wrap:wrap;justify-content:center}
.nchip{background:#0d1526;border:1px solid #1f2c48;border-radius:8px;padding:5px 10px;font-size:11px}
.nchip.t1{border-color:#cba6f7aa;box-shadow:0 0 10px #cba6f733}
.nbuy{color:#3fe07a}.nsell{color:#ff6b62}.nveto{color:#ffb24d;font-weight:900}
.xpair{display:inline-block;background:#0d1526;border:1px solid #1f2c48;border-radius:8px;padding:4px 10px;font-size:11px;margin:3px}
.evocell{background:#0d1526;border:1px solid #1f2c48;border-radius:8px;padding:6px 9px;font-size:11px;display:inline-block;margin:3px;min-width:130px}
.swcol{background:#0d1526;border:1px solid #1f2c48;border-radius:10px;padding:7px;display:inline-block;vertical-align:top;margin:4px;min-width:185px}
.ag{font-size:10px;color:#9fb0c3;padding:3px 6px;margin:2px 0;border-radius:5px;background:#121a2e;border-right:3px solid #2ea043;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px}
.ag b{color:#cdd6f4}.ag.error{border-right-color:#f85149}.ag.esc{border-right-color:#cba6f7;opacity:.75}.ag.idle,.ag.running{border-right-color:#6c7086}
.ins div{color:#8fa3bd;margin:3px 0;font-size:11px}.ins b{color:#cba6f7}
.foot{text-align:center;color:#3d4a63;font-size:10px;margin-top:14px}
</style></head><body>

<div class=hud>
  <span class=logo>⚔️ FRIDAY ARENA</span>
  <div class=orb><div class="v neu" id=h_eq>—</div><div class=l>الحقوق</div></div>
  <div class=orb><div class=v id=h_day>—</div><div class=l>اليوم</div></div>
  <div class=orb><div class=v id=h_w>—</div><div class=l>7 أيام</div></div>
  <div class=orb><div class=v id=h_fl>—</div><div class=l>عائم</div></div>
  <div class=sessbadge id=h_sess>الجلسة: —</div>
  <div class=gauge id=h_gauge><span id=h_gtxt>—</span></div>
  <div class=orb><div class="v neu" id=h_guard>—</div><div class=l>🛡 المحرّكات</div></div>
</div>

<div class=tabs>
  <div class="tab on" data-p=arena>⚔️ الساحة</div>
  <div class=tab data-p=risk>🛡️ المخاطر</div>
  <div class=tab data-p=intel>📰 الاستخبارات</div>
  <div class=tab data-p=evo>🧬 التطوّر</div>
  <div class=tab data-p=map>🗺️ الخريطة</div>
</div>

<div class="page on" id=p_arena>
  <div class=lanes id=lanes></div>
  <div class=stage><canvas id=net></canvas><div class=fttl id=fttl>—</div></div>
  <div class=detail id=detail></div>
  <div class=heroes id=heroes></div>
</div>

<div class=page id=p_risk>
  <div class=panel><h3>دورة إدارة المخاطر — ICA (حيّة، كل 60 ثانية)</h3>
    <div class=cyc id=cyc></div>
    <div class=rails><div class=rail>↕ التواصل والاستشارة: اللوحة + سجل الوكلاء</div><div class=rail>↕ المراقبة والمراجعة: watchdog + truth + retune</div></div>
    <div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap;justify-content:center">
      <div style="text-align:center"><div class=gauge id=r_gauge style="width:110px;height:110px"><span id=r_gtxt style="font-size:16px">—</span></div>
        <div style="font-size:10px;color:#6c7a92;margin-top:4px">مستوى الخطر الكلي</div>
        <div id=r_lot style="font-size:11px;color:#9fd0b5;margin-top:3px"></div></div>
      <div class=matrix id=matrix></div>
    </div>
  </div>
  <div class=panel><h3>سجل المخاطر الحيّ (تحديد ← تحليل ← أولويات ← معالجة)</h3>
    <table class=rtable><thead><tr><th>الخطر</th><th>المستوى</th><th>احتمال×أثر</th><th>الحالة الآن</th><th>المعالجة الفعّالة</th></tr></thead>
    <tbody id=rtb></tbody></table>
  </div>
</div>

<div class=page id=p_intel>
  <div class=panel><h3>🪤 صيّاد القفزات (Straddle الأخبار · OCO + تبديل + تقييم ذاتي)</h3><div style="text-align:center" id=strad></div></div>
  <div class=panel><h3>📰 الأخبار (متعدد المصادر · 🧠 كلود أعلى وزن ×5)</h3><div class=nrow id=nw></div><div style="text-align:center;font-size:10px;color:#6c7a92;margin-top:6px" id=ncl></div></div>
  <div class=panel><h3>🔗 الدماغ بين الأسواق</h3><div style="text-align:center" id=xa></div></div>
  <div class=panel><h3>🤖 قرارات الوكلاء</h3><div class=ins id=ins></div></div>
</div>

<div class=page id=p_evo>
  <div class=panel><h3>🏆 بطولة التوائم — شجرة التكاثر الحيّة (مبارزات حقيقية، بلا باكتيست)</h3>
    <canvas id=tournc style="width:100%;height:320px;display:block"></canvas>
    <div style="text-align:center;font-size:9.5px;color:#5d6b85;margin-top:4px">▲ شراء · ▼ بيع · ذهبي=حيّ · أحمر باهت=قُتل · أخضر=قيم مؤكَّدة 🏆 · النابض=يتبارز الآن · الخط=النسب (قيم الميت تُورَّث معكوسة)</div>
    <div id=tournfeed style="font-size:10px;color:#8fa3bd;margin-top:6px;max-height:120px;overflow:auto"></div></div>
  <div class=panel><h3>🧬 تطوّر الجينات (وين كان → وين صار)</h3><div style="text-align:center" id=evh></div><div style="text-align:center" id=evo></div></div>
</div>

<div class=page id=p_map>
  <div class=road id=road></div>
  <div class=panel><h3>رحلة الحساب (قبل/بعد القرارات)</h3><canvas id=acctc></canvas><div class=acctlbl id=acctlbl>—</div></div>
  <div class=panel><h3>🐝 سرب PlutoBrain</h3><div style="text-align:center" id=swarm></div></div>
</div>

<div class=foot>FRIDAY ARENA · DEMO · القرار النهائي للوحة الحقيقة لا للحماس</div>

<script>
let DATA=null, SEL=null, pulses=[], NODEPOS=[];
const cv=document.getElementById('net'), ctx=cv.getContext('2d'); const NETH=430;
function resize(){cv.width=cv.clientWidth*devicePixelRatio;cv.height=NETH*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
window.addEventListener('resize',resize);resize();
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
 document.querySelectorAll('.page').forEach(x=>x.classList.remove('on'));t.classList.add('on');document.getElementById('p_'+t.dataset.p).classList.add('on');});
const COL=h=>h>=55?'#3fe07a':h>=52?'#e8d44d':h>=50?'#6c7086':'#ff6b62';
function avatar(sym){const s=sym.replace(/m$/,'');if(s.includes('XAU'))return'🥇';if(s==='USDJPY')return'💴';if(s==='JP225')return'🗾';if(s.includes('BTC'))return'₿';
 return({GOOGL:'🔎',IBM:'🖥️',NVDA:'🎮',TSLA:'🚗',ORCL:'🗄️',LLY:'💊'})[s]||'📈';}
function lerp(a,b,t){return a+(b-a)*t;}
function pfCol(pf){return pf>=2?'#2ee06a':pf>=1.5?'#9bd16a':pf>=1.3?'#e2c044':pf>=1?'#d98c3a':'#ff6b62';}
function sgn(v){return (v>=0?'+':'')+'$'+(v||0).toFixed(2);}
function hpOf(c){return Math.max(0,Math.min(100,Math.round(100+(c.live_net*100/8))));}
function lvlOf(c){return (c.folds||1)+(c.retune&&c.retune.kept&&c.retune.prev_net_R!=null?1:0);}

function draw(){
 const W=cv.clientWidth,H=NETH;ctx.clearRect(0,0,W,H);
 if(!DATA||!DATA.cards||!DATA.cards.length){requestAnimationFrame(draw);return;}
 const list=DATA.cards.slice().sort((a,b)=>(b.oos_pf||0)-(a.oos_pf||0));
 const t=Date.now()/600;
 const feeds=[{n:'المؤشرات',c:'#89b4fa'},{n:'📰 أخبار',c:'#f0883e'},{n:'🔗 ترابط',c:'#cba6f7'},{n:'🛡 مخاطر',c:'#ff6b62'}];
 const fx=W*0.94;const feedPos=feeds.map((f,i)=>({...f,x:fx,y:70+i*((H-140)/(feeds.length-1))}));
 const winY=H*0.28,lossY=H*0.72,sinkX=W*0.06;
 let nWin=0,nLoss=0;list.forEach(c=>{if(c.live_net>0)nWin++;else if(c.live_net<0)nLoss++;});
 const N=list.length,cols=Math.ceil(Math.sqrt(N*1.7)),rows=Math.ceil(N/cols);
 const x0=W*0.22,x1=W*0.80,y0=48,y1=H-34,maxPF=Math.max(...list.map(c=>c.oos_pf||0),1);
 NODEPOS=[];
 const pos=list.map((c,i)=>{const r=Math.floor(i/cols),col=i%cols;
  const x=x1-(cols<=1?0.5:col/(cols-1))*(x1-x0);
  const y=y0+(rows<=1?0.5:r/(rows-1))*(y1-y0);
  const rad=12+13*((c.oos_pf||1)/maxPF);
  NODEPOS.push({sym:c.sym,x,y,r:rad});return{c,x,y,rad};});
 feedPos.forEach(f=>{ctx.strokeStyle=f.c;ctx.globalAlpha=0.08;ctx.lineWidth=1.2;
  ctx.beginPath();ctx.moveTo(f.x-8,f.y);ctx.bezierCurveTo(W*0.85,f.y,W*0.83,(y0+y1)/2,(x0+x1)/2,(y0+y1)/2);ctx.stroke();ctx.globalAlpha=1;});
 pos.forEach(p=>{const win=p.c.live_net>0,loss=p.c.live_net<0;if(!win&&!loss)return;
  const sy=win?winY:lossY,sc=win?'#2ea043':'#f85149';
  ctx.strokeStyle=sc;ctx.globalAlpha=0.12;ctx.beginPath();ctx.moveTo(p.x,p.y);
  ctx.bezierCurveTo(W*0.16,p.y,W*0.11,sy,sinkX,sy);ctx.stroke();ctx.globalAlpha=1;});
 ctx.textAlign='center';ctx.fillStyle='#5d6b85';ctx.font='11px Segoe UI';
 ctx.fillText('المدخلات',fx,26);ctx.fillText('أبطال الجينات — الأكبر = الأقوى',(x0+x1)/2,24);ctx.fillText('النتيجة',sinkX,26);
 feedPos.forEach(f=>{ctx.fillStyle=f.c;ctx.shadowColor=f.c;ctx.shadowBlur=12;ctx.beginPath();ctx.arc(f.x,f.y,7,0,7);ctx.fill();ctx.shadowBlur=0;
  ctx.fillStyle='#cdd9e5';ctx.font='10px Segoe UI';ctx.textAlign='left';ctx.fillText(f.n,f.x+11,f.y+4);});
 pos.forEach(p=>{const c=p.c,col=pfCol(c.oos_pf||0),seld=SEL===c.sym,asleep=!c.active;
  const pl=seld?3*Math.sin(t*1.6):0;
  ctx.globalAlpha=asleep?0.35:1;
  ctx.fillStyle='#0d1526';ctx.strokeStyle=col;ctx.lineWidth=2;ctx.shadowColor=col;ctx.shadowBlur=seld?22:9;
  ctx.beginPath();ctx.arc(p.x,p.y,p.rad+pl,0,7);ctx.fill();ctx.stroke();ctx.shadowBlur=0;
  const hp=hpOf(c);const hc=hp>60?'#3fe07a':hp>30?'#e8d44d':'#ff6b62';
  ctx.strokeStyle=hc;ctx.lineWidth=3;
  ctx.beginPath();ctx.arc(p.x,p.y,p.rad+4,-Math.PI/2,-Math.PI/2+(hp/100)*2*Math.PI);ctx.stroke();
  ctx.font=(p.rad*1.0)+'px Segoe UI';ctx.textAlign='center';ctx.fillText(avatar(c.sym),p.x,p.y+p.rad*0.35);
  ctx.fillStyle=asleep?'#5d6b85':'#cdd9e5';ctx.font='bold 9.5px Segoe UI';
  ctx.fillText(c.sym.replace(/m$/,'').slice(0,6)+(asleep?' 💤':''),p.x,p.y+p.rad+15);
  ctx.globalAlpha=1;});
 [['✅ ناجحون',winY,'#2ea043',nWin],['❌ خاسرون',lossY,'#f85149',nLoss]].forEach(a=>{
  const rr=22+3*Math.sin(t);ctx.fillStyle=a[2];ctx.shadowColor=a[2];ctx.shadowBlur=22;
  ctx.beginPath();ctx.arc(sinkX,a[1],rr,0,7);ctx.fill();ctx.shadowBlur=0;
  ctx.fillStyle='#fff';ctx.font='bold 14px Segoe UI';ctx.fillText(a[3],sinkX,a[1]+5);
  ctx.fillStyle=a[2];ctx.font='11px Segoe UI';ctx.fillText(a[0],sinkX,a[1]+rr+14);});
 const act=pos.filter(p=>p.c.active);
 if(act.length&&Math.random()<0.6){const p=act[Math.floor(Math.random()*act.length)],f=feedPos[Math.floor(Math.random()*feedPos.length)];
  pulses.push({x0:f.x,y0:f.y,x1:p.x,y1:p.y,t:0,c:f.c});}
 pos.forEach(p=>{const win=p.c.live_net>0,loss=p.c.live_net<0;if((win||loss)&&p.c.active&&Math.random()<0.03)
  pulses.push({x0:p.x,y0:p.y,x1:sinkX,y1:win?winY:lossY,t:0,c:win?'#2ea043':'#f85149'});});
 pulses=pulses.filter(p=>p.t<1);
 pulses.forEach(p=>{p.t+=0.03;const u=p.t,mx=(p.x0+p.x1)/2,my=(p.y0+p.y1)/2;
  const x=lerp(lerp(p.x0,mx,u),lerp(mx,p.x1,u),u),y=lerp(lerp(p.y0,my,u),lerp(my,p.y1,u),u);
  ctx.fillStyle=p.c;ctx.shadowColor=p.c;ctx.shadowBlur=8;ctx.beginPath();ctx.arc(x,y,2.6,0,7);ctx.fill();ctx.shadowBlur=0;});
 const nA=list.filter(c=>c.active).length;
 document.getElementById('fttl').textContent='اضغط بطلاً لورقة شخصيته · '+nA+' يقاتلون الآن · '+(N-nA)+' 💤 خارج جلستهم · ✅ '+nWin+' / ❌ '+nLoss;
 requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
cv.addEventListener('click',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 let best=null,bd=1e9;NODEPOS.forEach(nd=>{const d=Math.hypot(mx-nd.x,my-nd.y);if(d<nd.r+8&&d<bd){bd=d;best=nd;}});
 if(best){SEL=best.sym;renderDetail();}});

function ageTxt(ts){if(!ts)return'—';const m=Math.max(0,(Date.now()/1000-ts)/60);return m<60?Math.round(m)+'د':(m/60).toFixed(1)+'س';}
function retuneTxt(c){const r=c.retune;const age='آخر تدريب قبل '+ageTxt(c.trained);
 if(!r)return age+' · يُعاد ضبطه كل 3 ساعات';
 if(r.kept&&r.prev_net_R!=null)return age+' · <span style=color:#3fe07a>↑ تطوّر '+r.prev_net_R+'→'+r.new_net_R+'R (جين أذكى)</span>';
 if(r.kept)return age+' · جين جديد '+r.new_net_R+'R';
 return age+' · <span style=color:#8fa3bd>جرّب '+r.tried_net_R+'R — أبقى الأفضل '+r.prev_net_R+'R</span>';}
function renderDetail(){const el=document.getElementById('detail');if(!DATA)return;
 const c=(DATA.cards||[]).find(x=>x.sym===SEL);if(!c){el.style.display='none';return;}
 el.style.display='block';
 const st=c.live_net>0?'<span style=color:#3fe07a>✅ رابح حيّاً</span>':c.live_net<0?'<span style=color:#ff6b62>❌ خاسر حيّاً</span>':'⏳ ما قاتل بعد';
 const why=(c.why||[]).map(i=>'<span class=chip>'+i.name+' '+i.hit+'%</span>').join('')||'<span class=chip>يقيس…</span>';
 const bars=(c.inds||[]).slice(0,6).map(i=>'<div class=bar><span class=bn>'+i.name+'</span><span class=btrack><span class=bfill style="width:'+Math.min(100,i.w*40)+'%;background:'+COL(i.hit)+'"></span></span><span style="color:#6c7a92;font-size:9px;width:34px;text-align:left">'+i.hit+'%</span></div>').join('');
 const dd=v=>v>0?'<span style=color:#3fe07a>▲</span>':v<0?'<span style=color:#ff6b62>▼</span>':'—';
 const sess=(c.sessions&&c.sessions.length)?c.sessions.join(' · '):'كل الجلسات';
 el.innerHTML='<div class=dh><span class=dclose onclick="SEL=null;document.getElementById(\\'detail\\').style.display=\\'none\\'">✕</span>'
 +'<span style=font-size:22px>'+avatar(c.sym)+'</span> <b>'+c.sym.replace(/m$/,'')+'</b> <span class=hlvl>LVL '+lvlOf(c)+'</span> · '+st+' · حيّ '+sgn(c.live_net)+(c.open_n?' · ⚔️ '+c.open_n+' معركة مفتوحة':'')+'</div>'
 +'<div class=drow><b>🎖 التخصص (الجلسات):</b> '+sess+' · '+(c.active?'<span style=color:#3fe07a>في جلسته الآن ⚔️</span>':'<span style=color:#8a93a8>💤 ينتظر جلسته</span>')+' · أمر المحلّل: '+(c.action||'—')+'</div>'
 +'<div class=drow><b>🧬 الاستراتيجية:</b> '+c.tf+' · وقف '+c.stop+'×ATR · هدف '+c.target+'×ATR · بوّابة '+c.gate+' · تأمين '+c.be+'</div>'
 +'<div class=drow><b>📊 الجودة (OOS سبريد حقيقي):</b> PF '+c.oos_pf+' · فوز '+c.win+'% · '+c.folds+'/4 نوافذ · '+c.trades+' معركة · '+c.oos_r+'R</div>'
 +'<div class=drow><b>🔧 التطوّر:</b> '+retuneTxt(c)+'</div>'
 +'<div class=drow><b>✨ أسلحته الأدق:</b> '+why+'</div>'
 +'<div class=drow><b>📡 إشارات:</b> 📰'+dd(c.news_dir)+' · 🔗'+dd(c.xa_dir)+(c.delta_bias!=null?' · Δ دلتا <b style="color:'+(c.delta_bias>10?'#3fe07a':c.delta_bias<-10?'#ff6b62':'#8a93a8')+'">'+(c.delta_bias>0?'+':'')+c.delta_bias+'</b> <span style="color:#5d6b85;font-size:9px">(سياق ~50%)</span>':'')+'</div>'
 +'<div class=drow><b>🧠 المخ:</b></div>'+bars;}

function renderHeroes(d){const g=document.getElementById('heroes');g.innerHTML='';
 (d.cards||[]).forEach(c=>{const hp=hpOf(c),xp=Math.min(100,Math.max(3,(c.oos_r||0)/4));
  const badge=c.live_n>=4&&c.live_net<-8?'<span class="hbadge b-bench">🛑 مُبنّح</span>':c.active?'<span class="hbadge b-fight">⚔️ يقاتل</span>':'<span class="hbadge b-sleep">💤 ينتظر جلسته</span>';
  const cls=(c.sessions&&c.sessions.length)?('متخصّص: '+c.sessions.map(s=>({'ASIAN':'آسيا','LONDON':'لندن','NY_OVERLAP':'نيويورك','NY_LATE':'نيويورك المتأخرة'})[s]||s).join(' + ')):'مقاتل كل الجلسات';
  const div=document.createElement('div');
  div.className='hero '+(c.live_net>1?'win ':c.live_net<-1?'loss ':'')+(c.active?'':'sleep ')+(SEL===c.sym?'sel':'');
  div.onclick=()=>{SEL=c.sym;renderDetail();window.scrollTo({top:0,behavior:'smooth'});};
  div.innerHTML='<div class=hav>'+avatar(c.sym)+'</div>'
  +'<div class=hname>'+c.sym.replace(/m$/,'')+' <span class=hlvl>LVL '+lvlOf(c)+'</span></div>'
  +'<div class=hclass>'+cls+' · '+c.tf+'</div>'
  +'<div class=hbar><span class=lab>HP</span><span class=htrack><span class=hfill style="width:'+hp+'%;background:'+(hp>60?'#3fe07a':hp>30?'#e8d44d':'#ff6b62')+'"></span></span><span>'+hp+'</span></div>'
  +'<div class=hbar><span class=lab>XP</span><span class=htrack><span class=hfill style="width:'+xp+'%;background:#7aa2ff"></span></span><span>'+(c.oos_r||0)+'R</span></div>'
  +'<div class=hstat>'+badge+'<span class="hpnl '+(c.live_net>0?'pos':c.live_net<0?'neg':'neu')+'">'+sgn(c.live_net)+'</span></div>';
  g.appendChild(div);});}

function renderLanes(d){const L=['ASIAN','LONDON','NY_OVERLAP','NY_LATE'];const NM={'ASIAN':'🌏 آسيا','LONDON':'🇬🇧 لندن','NY_OVERLAP':'🗽 نيويورك','NY_LATE':'🌆 نيويورك المتأخرة'};
 document.getElementById('lanes').innerHTML=L.map(s=>'<div class="lane'+(d.session===s?' on':'')+'">'+NM[s]+(d.session===s?' — نشطة':'')+'</div>').join('');}

function gaugeCol(p){return p>=60?'#ff4d4d':p>=35?'#ffb24d':'#3fe07a';}
function renderHud(d){const t=d.truth||{};const cls=v=>v>=0?'pos':'neg';
 document.getElementById('h_eq').textContent='$'+(d.equity||0).toFixed(0);
 const el=(id,v)=>{const e=document.getElementById(id);e.textContent=sgn(v||0);e.className='v '+cls(v||0);};
 el('h_day',t.today_net);el('h_w',t.d7_net);el('h_fl',t.floating);
 document.getElementById('h_sess').innerHTML='الجلسة: <b>'+(d.session||'—')+'</b>';
 const r=d.risk||{};const p=r.risk_pct||0;const gc=gaugeCol(p);
 const gg=document.getElementById('h_gauge');gg.style.background='conic-gradient('+gc+' '+(p*3.6)+'deg,#16203a 0)';
 if((r.overall||'')==='CRITICAL')gg.classList.add('glow-pulse');else gg.classList.remove('glow-pulse');
 document.getElementById('h_gtxt').innerHTML=p+'%<br><span style="font-size:8px;color:'+gc+'">'+(r.overall||'')+'</span>';
 const g=t.guard||{};document.getElementById('h_guard').textContent=(g.alive||'—')+'/'+(g.total||'—')+(g.restarts?' ⟳'+g.restarts:'');}

function renderRisk(d){const r=d.risk||{};
 document.getElementById('cyc').innerHTML=(r.cycle||[]).map(s=>'<div class=cstep>'+s+'</div>').join('');
 const p=r.risk_pct||0,gc=gaugeCol(p);
 const gg=document.getElementById('r_gauge');gg.style.background='conic-gradient('+gc+' '+(p*3.6)+'deg,#16203a 0)';
 document.getElementById('r_gtxt').innerHTML=p+'%<br><span style="font-size:10px;color:'+gc+'">'+(r.overall||'—')+'</span>';
 document.getElementById('r_lot').textContent=r.lot_mult&&r.lot_mult<1?('⚙️ معالجة فعّالة: اللوت مُقلّص ×'+r.lot_mult):'الأحجام طبيعية';
 const M=r.modes||{};const NM2={macro:'ماكرو',xasset:'ترابط',dive:'غوص',wick_rev:'ذيل',gap_pend:'فجوات',srlim:'مستويات'};
 const mch=Object.keys(NM2).map(m=>{const v=M[m]||{};const dis=v.disabled;
  return '<span class=xpair style="border-color:'+(dis?'#ff4d4d66':(v.mult||1)>1?'#3fe07a66':'#1f2c48')+'">'+(dis?'🛑 ':'')+NM2[m]+' <b style="color:'+((v.net||0)>=0?'#3fe07a':'#ff6b62')+'">'+((v.net||0)>=0?'+':'')+'$'+(v.net||0)+'</b> ('+(v.n||0)+')'+(dis?' معطّل':'')+'</span>';}).join('');
 let mEl=document.getElementById('modestrip');
 if(!mEl){mEl=document.createElement('div');mEl.id='modestrip';mEl.style.cssText='text-align:center;margin-top:8px;font-size:10px';document.getElementById('r_lot').parentNode.appendChild(mEl);}
 mEl.innerHTML='<div style="color:#6c7a92;margin-bottom:3px">أوضاع الدخول — تُحاسَب من ربحها الحيّ (التطوّر يعطّل الخاسر):</div>'+mch;
 const rows=(r.risks||[]).map(x=>'<tr><td><b>'+x.id+'</b> '+x.name+'</td><td><span class="lv '+x.level+'">'+x.level+'</span></td>'
  +'<td>'+x.prob+'×'+x.impact+'='+x.score+'</td><td>'+x.why+'</td><td class=treat>'+x.treatment+'</td></tr>').join('');
 document.getElementById('rtb').innerHTML=rows||'<tr><td colspan=5>ينتظر risk_manager…</td></tr>';
 // 5x5 matrix: impact rows (top=5) x prob cols (right=1 RTL)
 let cells='';
 for(let imp=5;imp>=1;imp--){for(let pr=1;pr<=5;pr++){
  const sc=imp*pr;const bg=sc>=16?'#c0392b':sc>=9?'#d98c3a':sc>=4?'#d4c42e':'#2ea043';
  const here=(r.risks||[]).filter(x=>x.prob===pr&&x.impact===imp).map(x=>x.id).join(' ');
  cells+='<div class=mcell style="background:'+bg+(here?'':'55')+'">'+(here||'')+'</div>';}}
 document.getElementById('matrix').innerHTML=cells;}

function renderStraddle(d){const s=d.straddle||{};const el=document.getElementById('strad');
 const eps=(s.episodes||[]).slice().reverse().map(e=>'<span class=xpair>'+(e.sym||'').replace(/m$/,'')
  +' <b style="color:'+((e.net||0)>0?'#3fe07a':(e.net||0)<0?'#ff6b62':'#8a93a8')+'">'+sgn(e.net||0)+'</b>'
  +(e.whipsaw?' 🔄':'')+(e.filled_side?'':' ⌛')+'</span>').join('');
 el.innerHTML='<div style="font-size:13px;margin-bottom:6px">إجمالي الصيد: <b style="color:'+((s.net||0)>=0?'#3fe07a':'#ff6b62')+'">'+sgn(s.net||0)+'</b>'
  +(s.help?' · <span class="lv CRITICAL">🆘 طلب مساعدة!</span>':'')
  +'</div><div style="font-size:10px;color:#8fa3bd;margin-bottom:6px">🧪 '+(s.eval||'يجمع البيانات…')+'</div>'
  +(eps||'<span style=color:#6c7a92>لا محاولات بعد — يترصّد الخبر القادم</span>')
  +'<div style="font-size:9px;color:#5d6b85;margin-top:6px">مسافة '+((s.cfg||{}).dist_atr||'—')+'×ATR · وقف '+((s.cfg||{}).sl_atr||'—')+' · هدف '+((s.cfg||{}).tp_atr||'—')+' · 🔄=تبديل بعد مصيدة · ⌛=ما انفّذ</div>';}
function renderIntel(d){
 const N=d.news||[];document.getElementById('nw').innerHTML=N.length?N.map(n=>{const t1=n.tier===1;
  return '<div class="nchip'+(t1?' t1':'')+'" title="'+(n.reason||'').replace(/"/g,'')+'">'+(t1?'🧠 ':n.tier===2?'🏛 ':'📡 ')+n.sym.replace(/m$/,'')
  +' <span class='+(n.dir>0?'nbuy':'nsell')+'>'+(n.dir>0?'▲شراء':n.dir<0?'▼بيع':'—')+'</span>'+(n.veto?' <span class=nveto>⛔</span>':'')+'</div>';}).join('')
  :'<span style=color:#6c7a92>لا إشارات قوية الآن · '+(d.news_n||0)+' عنوان حيّ</span>';
 const C=d.news_clusters||{};document.getElementById('ncl').textContent='ميل طويل المدى: ذهب '+(C.gold_bias||0).toFixed(2)+' · دولار '+(C.USD_bias||0).toFixed(2)+' · كريبتو '+(C.crypto_bias||0).toFixed(2);
 document.getElementById('xa').innerHTML=(d.xpairs||[]).map(p=>'<span class=xpair>'+p.a.replace(/m$/,'')+(p.r>=0?' ↔ ':' ⇄ ')+p.b.replace(/m$/,'')+' <b style="color:'+(p.r>=0?'#3fe07a':'#ff6b62')+'">'+(p.r>=0?'+':'')+p.r+'</b></span>').join('')||'يقيس…';
 document.getElementById('ins').innerHTML=(d.insights||[]).map(x=>'<div><b>'+x.agent+'</b> · '+x.msg+'</div>').join('')||'<div>—</div>';}

const tcv=document.getElementById('tournc');const tctx=tcv.getContext('2d');
function drawTourn(){
 const d=DATA;const W=tcv.width=tcv.clientWidth,H=tcv.height=320;
 tctx.clearRect(0,0,W,H);
 if(!d||!d.tournament){requestAnimationFrame(drawTourn);return;}
 const T=d.tournament,cs=T.contestants||[],duels=T.duels||[],conf=T.confirmed||{};
 if(!cs.length){tctx.fillStyle='#5d6b85';tctx.font='12px Segoe UI';tctx.textAlign='center';
  tctx.fillText('تنتظر أول مبارزة — تبدأ تلقائياً في الجلسة النشطة',W/2,H/2);requestAnimationFrame(drawTourn);return;}
 const syms=[...new Set(cs.map(c=>c.sym))];const t=Date.now()/500;
 const rowH=Math.min(90,(H-40)/Math.max(1,syms.length));
 const fighting=new Set();duels.forEach(du=>{fighting.add(du.long);fighting.add(du.short);});
 const NP={};
 cs.forEach(c=>{const row=syms.indexOf(c.sym);
  const sibs=cs.filter(x=>x.sym===c.sym);const idx=sibs.indexOf(c);
  const x=W*0.88-(Math.min(c.stage,4)-1)*W*0.26-(idx%2)*26;
  const y=34+row*rowH+(idx%3)*16;NP[c.id]={x,y,c};});
 // lineage edges (parent -> child = inheritance flip)
 tctx.lineWidth=1;
 cs.forEach(c=>{if(c.parent&&NP[c.parent]&&NP[c.id]){const a=NP[c.parent],b=NP[c.id];
  tctx.strokeStyle='#d9923a';tctx.globalAlpha=0.35;tctx.beginPath();
  tctx.moveTo(a.x,a.y);tctx.bezierCurveTo((a.x+b.x)/2,a.y,(a.x+b.x)/2,b.y,b.x,b.y);tctx.stroke();tctx.globalAlpha=1;}});
 // stage columns labels
 tctx.font='10px Segoe UI';tctx.fillStyle='#5d6b85';tctx.textAlign='center';
 ['التصفيات','نصف النهائي','قيم مؤكَّدة 🏆'].forEach((s,i)=>tctx.fillText(s,W*0.88-i*W*0.26,14));
 cs.forEach(c=>{const p=NP[c.id];if(!p)return;
  const crowned=conf[c.sym]&&conf[c.sym].id===c.id;
  const col=crowned?'#3fe07a':!c.alive?'#7a3030':'#e8c46a';
  const pulse=fighting.has(c.id)?2.5*Math.sin(t)+2.5:0;
  tctx.globalAlpha=c.alive?1:0.4;
  tctx.fillStyle='#0d1526';tctx.strokeStyle=col;tctx.lineWidth=2;
  tctx.shadowColor=col;tctx.shadowBlur=crowned?18:fighting.has(c.id)?14:6;
  tctx.beginPath();tctx.arc(p.x,p.y,11+pulse,0,7);tctx.fill();tctx.stroke();tctx.shadowBlur=0;
  tctx.fillStyle=c.dir>0?'#3fe07a':'#ff6b62';tctx.font='bold 11px Segoe UI';
  tctx.fillText(c.dir>0?'▲':'▼',p.x,p.y+4);
  tctx.fillStyle='#8fa3bd';tctx.font='8.5px Segoe UI';
  tctx.fillText(c.sym.replace(/m$/,'')+(c.wins?' ★'+c.wins:''),p.x,p.y+22);
  tctx.globalAlpha=1;});
 requestAnimationFrame(drawTourn);}
requestAnimationFrame(drawTourn);
function renderTournFeed(d){const T=d.tournament||{};const lin=(T.lineage||[]).slice().reverse().slice(0,12);
 document.getElementById('tournfeed').innerHTML=lin.map(e=>{
  const ic={'ولادة':'🐣','مبارزة':'⚔️','فوز':'🏅','موت':'💀','تتويج':'🏆','تعادل':'🤝'}[e.ev]||'·';
  return '<div>'+ic+' <b>'+e.ev+'</b> '+(e.sym||'').replace(/m$/,'')+(e.dir?' '+e.dir:'')+(e.net!=null?' $'+e.net:'')+(e.title?' → '+e.title:'')+'</div>';}).join('')||'—';}
function renderEvo(d){const ga=d.evo_ga||{};
 document.getElementById('evh').innerHTML=(ga.fit_first!=null)?('<span style="font-size:19px;font-weight:900;color:#3fe07a">'+ga.fit_first+' → '+ga.fit_cur+'</span> <span style="font-size:11px;color:#6c7a92">لياقة المحرّك '+(ga.fit_pct>0?'+':'')+(ga.fit_pct||0)+'% · جيل '+(ga.generation||'?')+' · وُلد '+(ga.born_total||0)+' · قُتل '+(ga.killed_total||0)+'</span>'):'';
 document.getElementById('evo').innerHTML=(d.evo_syms||[]).map(s=>{const pf=s.pf||0;
  return '<div class=evocell><b style=color:#ffd97a>'+s.sym.replace(/m$/,'')+'</b> <span style="font-weight:900;color:'+pfCol(pf)+'">PF '+pf+'</span><br><span style="font-size:9px;color:#6c7a92">فوز '+(s.win||0)+'% · '+('★'.repeat(s.folds||1))+' · <span style="color:'+((s.pct||0)>=0?'#3fe07a':'#ff6b62')+'">'+((s.pct||0)>0?'▲+':'')+(s.pct||0)+'%</span></span></div>';}).join('');}

function renderMap(d){
 document.getElementById('road').innerHTML=(d.roadmap||[]).map(r=>'<div class="rstage '+r.st+'"><span class=rn>'+r.n+'</span><span class=rv>'+r.v+'</span></div>').join('');
 const c=document.getElementById('acctc'),x=c.getContext('2d'),W=c.width=c.clientWidth,H=c.height=110;
 x.clearRect(0,0,W,H);const cur=d.acct_curve||[];if(cur.length>=2){
  const base=d.start_bal||0,eq=cur.map(v=>base+v),mn=Math.min(...eq,base),mx=Math.max(...eq,base),rg=(mx-mn)||1;
  const sy=H-6-(base-mn)/rg*(H-12);x.strokeStyle='#2c3a5c';x.setLineDash([4,4]);x.beginPath();x.moveTo(0,sy);x.lineTo(W,sy);x.stroke();x.setLineDash([]);
  const up=eq[eq.length-1]>=base,col=up?'#3fe07a':'#ff6b62';
  x.beginPath();eq.forEach((v,i)=>{const px=i/(eq.length-1)*W,py=H-6-(v-mn)/rg*(H-12);i?x.lineTo(px,py):x.moveTo(px,py);});
  x.lineTo(W,H);x.lineTo(0,H);x.closePath();const gr=x.createLinearGradient(0,0,0,H);gr.addColorStop(0,col+'44');gr.addColorStop(1,col+'00');x.fillStyle=gr;x.fill();
  x.beginPath();eq.forEach((v,i)=>{const px=i/(eq.length-1)*W,py=H-6-(v-mn)/rg*(H-12);i?x.lineTo(px,py):x.moveTo(px,py);});x.strokeStyle=col;x.lineWidth=2;x.stroke();
  document.getElementById('acctlbl').innerHTML='<span>البداية: <b>$'+base.toFixed(2)+'</b></span><span style="color:'+col+'">الآن: <b>$'+(base+cur[cur.length-1]).toFixed(2)+'</b></span>';}
 const s=d.swarm;document.getElementById('swarm').innerHTML=(s&&s.online)?('<div style="font-size:11px;color:#e8c46a;margin-bottom:6px">'+s.n_agents+' وكيل · دورة '+s.cycle+' · '+s.findings+' نتيجة</div>'
  +['ALPHA','BETA','GAMMA','ORCH'].filter(c2=>s.agents.some(a=>a.cluster===c2)).map(c2=>{const ags=s.agents.filter(a=>a.cluster===c2);
   return '<div class=swcol><div style="font-size:11px;font-weight:800;margin-bottom:4px;color:#9fc1ff">'+c2+' · '+ags.length+'</div>'+ags.slice(0,8).map(a=>'<div class="ag '+(a.worker==='ESCALATE'?'esc':(a.status||'idle'))+'"><b>'+a.id+'</b> '+a.role+'</div>').join('')+'</div>';}).join('')):'<span style=color:#6c7a92>السرب غير متصل</span>';}

async function tick(){let d;try{d=await(await fetch('/data')).json();}catch(e){return;}DATA=d;
 renderHud(d);renderLanes(d);renderHeroes(d);renderRisk(d);renderStraddle(d);renderTournFeed(d);renderIntel(d);renderEvo(d);renderMap(d);renderDetail();}
tick();setInterval(tick,3000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/data"):
            body = json.dumps(_data(), ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            body = HTML.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    print(f"FRIDAY ARENA on http://127.0.0.1:{PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
