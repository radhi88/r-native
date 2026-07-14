# -*- coding: utf-8 -*-
"""FRIDAY Desktop — Backend API (FastAPI).

طبقة خلفية نظيفة موحّدة فوق محرّكات FRIDAY (بايثون): تقرأ ما تكتبه المحرّكات (العقل العميق،
الأرضية، السبورة، صحّة المحرّكات) + حساب MT5 (الصفقات الحيّة، التاريخ، منحنى الحقوق)،
وتعرضها عبر REST + WebSocket لحظياً، مع تحكّم تشغيل/إيقاف. تستهلكها واجهة الويب
وغلاف النافذة الأصلية (pywebview). قابلة للتوسّع: أضِف endpoint = ميزة جديدة + لوحة.

تشغيل: python -m uvicorn friday_desktop.backend.server:app --host 127.0.0.1 --port 8770
"""
from __future__ import annotations
import asyncio, json, math, os, subprocess, threading, time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import psutil
import MetaTrader5 as mt5

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PYW = str(MT5DIR / ".venv" / "Scripts" / "pythonw.exe")
KILL = MT5DIR / "kill_switch.txt"
FLAGS = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
# لا نلمس: يدوي(0) + EA خارجية للمستخدم
PROT = {0, 2447, 20250418, 20250421, 20250422, 20250618}
# 🌍 الأسطول النشط بعد خطة الحسم 2026-07-04 (الاسم المعروض ← بصمة سطر الأوامر).
# صُحّح: كانت القائمة قديمةً بأسماء محرّكاتٍ متقاعدة ⇒ العدّاد يقرأ 0 ويظهر «خامل» زوراً.
ENGINE_HINTS = {
    "watchdog_guard": "watchdog_guard",           # 🐕 الوصيّ
    "unified_brain": "unified_brain",             # 🧠 المخ الواحد
    "radhi_mimic": "radhi_mimic",                 # 🪞 منفّذ الذهب (استراتيجية راضي)
    "brain_trader": "brain_trader",               # 🌍 منفّذ المخ متعدّد العملات
    "self_evolver": "self_evolver",               # 🧬 التطوّر الذاتيّ
    "brain_watch": "brain_watch",                 # 👁️ حارس المخ
    "market_pulse": "market_pulse",               # 🫀 نبض السوق (17 عملة)
    "quant_desk": "quant_desk",                   # 🧮 مكتب الحسابات
    "gold_level_sentinel": "gold_level_sentinel", # 🔔 حارس المستويات
    "news_straddle": "news_straddle",             # 🎯 قوسا الأخبار
    "news_alarm": "news_alarm",                   # ⏰ إنذار الأخبار
    "order_janitor": "order_janitor",             # 🧹 بوّاب الأوامر
    "ollama_council": "ollama_council",           # 🏛️ مجلس العقول
    "council_executor": "council_executor",       # ⚖️ منفّذ المجلس
    "llm_chart_analyst": "llm_chart_analyst",     # 🤖 محلّل Fable
    "profit_harvester": "profit_harvester",       # 🌾 حاصد الأرباح
    "portfolio_maestro": "portfolio_maestro",     # 🎛️ مايسترو المحفظة
    "self_tuner": "self_tuner",                   # 🔧 المُهذِّب
    "manual_manager": "manual_manager",           # 🖐️ مدير اليدويّ
    "manual_lot_alert": "manual_lot_alert",       # ⚠️ إنذار اللوت
    "master_floor": "master_floor",               # 🛡️ الأرضية
    "peak_watch": "peak_watch",                   # 📈 حارس القمّة
    "real_lock": "real_lock",                     # 🔒 قفل الحقيقيّ
    "risk_manager": "risk_manager",               # ⚖️ إدارة المخاطر
    "coordinator": "coordinator",                 # 🔗 المنسّق
    "system_graph": "system_graph",               # 🕸️ خريطة المنظومة
}

app = FastAPI(title="FRIDAY Desktop API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_ready = False
_lock = threading.Lock()          # MT5 ليس thread-safe — نحرس كل النداءات
_eqhist: deque = deque(maxlen=240)  # منحنى الحقوق (آخر ~240 لقطة)
_last_eq_ts = 0.0


def _mt5():
    global _ready
    if not _ready:
        _ready = bool(mt5.initialize())
    return _ready


def _j(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8-sig"))
    except Exception:
        return {} if default is None else default


def _our_procs():
    me = os.getpid(); out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            if (p.info["name"] or "").lower() not in ("pythonw.exe", "python.exe"):
                continue
            cl = " ".join(p.info["cmdline"] or [])
            if "server:app" in cl or "server.py" in cl:
                continue
            if "MT5" in cl and any(h in cl for h in ENGINE_HINTS.values()):
                out.append((p, cl))
        except Exception:
            continue
    return out


def _engines_state():
    """قائمة محرّكاتنا + هل كل واحد شغّال الآن."""
    running = {}
    for _p, cl in _our_procs():
        for name, hint in ENGINE_HINTS.items():
            if hint in cl:
                running[name] = running.get(name, 0) + 1
    return [{"name": n, "running": running.get(n, 0) > 0, "procs": running.get(n, 0)}
            for n in ENGINE_HINTS]


def status():
    global _last_eq_ts
    acc = {}
    with _lock:
        if _mt5():
            ai = mt5.account_info()
            if ai:
                acc = {"equity": round(ai.equity, 2), "balance": round(ai.balance, 2),
                       "margin_free": round(ai.margin_free, 2),
                       "margin_level": round(ai.margin_level or 0, 0),
                       "server": ai.server, "login": ai.login,
                       "currency": ai.currency}
            poss = [p for p in (mt5.positions_get() or []) if p.magic not in PROT]
            acc["positions"] = len(poss)
            acc["floating"] = round(sum(p.profit for p in poss), 2)
    fl = _j(RN / "master_floor_state.json", {})
    eq = acc.get("equity")
    now = time.time()
    if eq is not None and now - _last_eq_ts > 4.0:
        _eqhist.append([round(now, 1), eq]); _last_eq_ts = now
    floor_dist = None
    if eq is not None and fl.get("floor") is not None:
        floor_dist = round(eq - fl["floor"], 2)
    return {"account": acc, "floor": fl, "floor_dist": floor_dist,
            "kill_switch": KILL.exists(), "engines": len(_our_procs()), "ts": now}


def positions():
    out = []
    with _lock:
        if not _mt5():
            return {"positions": [], "n": 0, "floating": 0}
        for p in (mt5.positions_get() or []):
            if p.magic in PROT:
                continue
            out.append({"symbol": p.symbol, "type": "BUY" if p.type == 0 else "SELL",
                        "volume": p.volume, "price_open": p.price_open,
                        "price_current": p.price_current, "profit": round(p.profit, 2),
                        "magic": p.magic, "sl": p.sl, "tp": p.tp,
                        "minutes": round((time.time() - p.time) / 60.0)})
    out.sort(key=lambda x: x["profit"])
    return {"positions": out, "n": len(out), "floating": round(sum(x["profit"] for x in out), 2)}


def history(days=7):
    with _lock:
        if not _mt5():
            return {"deals": [], "net": 0, "n": 0, "wins": 0}
        frm = time.time() - days * 86400
        deals = mt5.history_deals_get(frm, time.time()) or []
    rows = []
    for d in deals:
        if d.magic in PROT or d.entry != 1:  # entry==1 = OUT (إغلاق محقّق)
            continue
        rows.append({"symbol": d.symbol, "profit": round(d.profit + d.commission + d.swap, 2),
                     "magic": d.magic, "ts": d.time})
    net = round(sum(r["profit"] for r in rows), 2)
    wins = sum(1 for r in rows if r["profit"] > 0)
    rows.sort(key=lambda x: x["ts"], reverse=True)
    return {"deals": rows[:60], "net": net, "n": len(rows), "wins": wins,
            "win_rate": round(100 * wins / len(rows), 1) if rows else 0}


def scoreboard():
    sb = _j(RN / "army_scoreboard.json", {}).get("stats", {})
    n = sum(v.get("n", 0) for v in sb.values()); sr = sum(v.get("sumR", 0.0) for v in sb.values())
    e = sr / n if n else 0
    return {"n": n, "expR": round(e, 4), "t": round(e * math.sqrt(n), 2) if n else 0,
            "cells": len(sb)}


def projection(start=1000.0):
    """تقدير صادق لمسار رأس مال — مبني على الحافّة المقيسة فعلياً (لا تفاؤل ملفّق).

    expR المقيسة ≈ صفر بعد السبريد ⇒ المسار المتوقّع ثبات ثم نزيف بطيء بالتكلفة.
    نعرض المتوقّع + نطاق ثقة (±) ليرى المستخدم الحقيقة لا وعداً."""
    sb = scoreboard()
    expR = sb["expR"]                     # توقّع لكل صفقة بوحدات R
    n_obs = max(sb["n"], 1)
    # تقدير تشتّت R لكل صفقة (افتراض محافظ إن غابت البيانات): ~1R
    sigma_R = 1.0
    risk_pct = 0.005                       # ~0.5% مخاطرة/صفقة (سياسة الأرضية)
    trades_per_day = 40                    # وتيرة غرفة الحرب التقريبية
    horizon_days = 30
    N = trades_per_day * horizon_days
    path, lo, hi = [], [], []
    eq = mu_lo = mu_hi = start
    for i in range(0, N + 1, trades_per_day):  # نقطة/يوم
        t = i
        drift = start * risk_pct * expR * t
        band = start * risk_pct * sigma_R * math.sqrt(max(t, 0))
        path.append(round(start + drift, 2))
        lo.append(round(start + drift - 1.96 * band, 2))
        hi.append(round(start + drift + 1.96 * band, 2))
    exp_end = path[-1]
    t_edge = expR * math.sqrt(max(sb["n"], 1))      # معنوية الحافّة المقيسة
    significant = abs(t_edge) > 2.0
    band_end = round(start * risk_pct * sigma_R * 1.96 * math.sqrt(N), 2)
    if significant:
        honest = ("حافّة معنوية مقيسة (t=%.2f). لكن لا توصيل لرصيد حقيقي قبل الصمود "
                  "عبر أنظمة سوق متعدّدة + إثبات أمامي." % t_edge)
    else:
        honest = ("التوقّع %.3fR لكن t=%.2f ≪ 2 ⇒ لا يُميَّز عن الصفر إحصائياً. "
                  "الـ$%.0f المتوقّعة ضمن الضجيج؛ النطاق المحتمل بعد 30 يوماً ≈ "
                  "$%.0f إلى $%.0f. صافي السبريد يميل للنزيف ببطء. "
                  "النمو الحقيقي يحتاج حافّة موجبة معنوية لم تُثبت بعد." %
                  (expR, t_edge, exp_end, max(exp_end - band_end, 0), exp_end + band_end))
    return {"start": start, "exp_end": exp_end, "expR": expR, "t": round(t_edge, 2),
            "significant": significant, "n_obs": sb["n"], "band_end": band_end,
            "days": horizon_days, "path": path, "lo": lo, "hi": hi, "honest": honest}


# ---------- REST ----------
@app.get("/api/status")
def api_status():
    return status()


def _deep_light():
    """نسخة خفيفة من ملفّ العقل العميق للبثّ اللحظي: ملخّص التعلّم + النداءات + شبكة الرموز
    (دون per_tf/levels الثقيلة — تُجلَب عند النقر على رمز عبر /api/deep_symbol)."""
    d = _j(RN / "deep_dossier.json", {})
    syms = {}
    for s, v in (d.get("symbols") or {}).items():
        pt = v.get("per_tf") or {}
        cv = v.get("conviction") or {}
        syms[s] = {"bias": v.get("bias"), "align": v.get("align"), "score": v.get("score"),
                   "call": v.get("call"), "high_conf": v.get("high_conf"), "net_tf": v.get("net_tf"),
                   "session": v.get("session"), "with_htf": v.get("with_htf"), "rsi_h1": v.get("rsi_h1"),
                   "price": v.get("price"), "conv_mult": cv.get("mult"), "conv_tier": cv.get("tier"),
                   "tf_dirs": {tf: (r or {}).get("dir") for tf, r in pt.items()}}
    return {"updated": d.get("updated"), "n_symbols": d.get("n_symbols"),
            "high_conf_now": d.get("high_conf_now", {}), "learning": d.get("learning", {}),
            "gold_live": d.get("gold_live", {}), "green_lights": d.get("green_lights", []),
            "red_flags": d.get("red_flags", []), "symbols": syms}


@app.get("/api/deep")
def api_deep():
    return _deep_light()


@app.get("/api/deep_full")
def api_deep_full():
    return _j(RN / "deep_dossier.json", {})


@app.get("/api/deep_symbol")
def api_deep_symbol(sym: str):
    d = _j(RN / "deep_dossier.json", {})
    return (d.get("symbols") or {}).get(sym, {})


@app.get("/api/positions")
def api_positions():
    return positions()


@app.get("/api/engines")
def api_engines():
    return {"engines": _engines_state(), "total_running": len(_our_procs())}


@app.get("/api/history")
def api_history():
    return history()


@app.get("/api/scoreboard")
def api_scoreboard():
    return scoreboard()


@app.get("/api/equity")
def api_equity():
    return {"hist": list(_eqhist)}


@app.get("/api/projection")
def api_projection(start: float = 1000.0):
    return projection(start)


@app.post("/api/start")
def api_start():
    try:
        if KILL.exists():
            KILL.unlink()
    except Exception:
        pass
    subprocess.Popen([PYW, "watchdog_guard.py"], cwd=str(MT5DIR), creationflags=FLAGS)
    return {"ok": True, "action": "start"}


@app.post("/api/stop")
def api_stop():
    try:
        KILL.write_text("desktop stop " + time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    except Exception:
        pass
    for p, cl in _our_procs():
        try:
            if "watchdog" in cl:
                p.kill()
        except Exception:
            pass
    time.sleep(0.5)
    for p, _cl in _our_procs():
        try:
            p.kill()
        except Exception:
            pass
    return {"ok": True, "action": "stop"}


# ---------- WebSocket لحظي (جزء من الثانية) ----------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    tick = 0
    try:
        while True:
            payload = {"status": status(), "deep": _deep_light(),
                       "positions": positions(), "scoreboard": scoreboard()}
            if tick % 6 == 0:  # كل ~3ث: محرّكات + حقوق (أثقل)
                payload["engines"] = {"engines": _engines_state()}
                payload["equity"] = {"hist": list(_eqhist)}
            await websocket.send_json(payload)
            await asyncio.sleep(0.5)
            tick += 1
    except Exception:
        pass


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
