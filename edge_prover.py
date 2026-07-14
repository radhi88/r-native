"""edge_prover.py — مُثبِت ورقي مستقبلي (FORWARD PAPER PROVER) للحوافّ الثلاث الناجية.
=====================================================================================

ملف جديد، PAPER فقط — صفر أوامر حيّة. لا order_send، لا فتح/تعديل/إغلاق أي صفقة.
لا يُعدِّل أي ملف .py قائم. البناء إضافي بالكامل.

الهدف
-----
الحوافّ الثلاث التي نجت من مسح الكون (data/lab_cache/UNIVERSE_SCAN_REPORT.md):
  1) XAUUSDm  H1  BREAKOUT_long  (OOS PF 2.21, expR +0.499, n=515) — الأقوى، لكن أحدث
     كتلة ~شهرين خاسرة (PF 0.45) → النظام الحالي ضدّها.
  2) XAUEURm  H1  BREAKOUT_long  (OOS PF 1.91, expR +0.439, n=56) — آخر 56 صفقة خسرت
     (PF 0.22) → علم أصفر، الحافّة نائمة/منعكسة في أحدث نافذة.
  3) USOILm   M15 BREAKOUT_LONG  (OOS PF 1.44, expR +0.227, n=590) — حقيقية لكن معتدلة،
     تتجاوز Bonferroni بأقل من ضعفين → الأهشّ.

التحذير الحاسم من المسح: الثلاثة رابحة بعيدة-المدى لكن خاسرة في أحدث نافذة. لذلك يحتوي
هذا المُثبِت **بوّابة نظام-سوقي سببية (regime gate)** تمنع الدخول حين يكون الاتجاه الأطول
ضدّ الحافّة — فلا ندخل اختراقاً صعودياً والسوق في هبوط هيكلي.

كيف يُمنع الـlookahead (نفس ميكانيكا full_scan_lab.py، حرفياً)
-------------------------------------------------------------
* كل المؤشّرات عند الشمعة i تُحسب من بيانات index ≤ i فقط (سببي).
* الاختراق يستخدم نافذة 20-شمعة **سابقة** تستثني i نفسها (rolling_max/ min على [i-20:i]).
* الدخول عند **افتتاح الشمعة i+1** (لا عند إغلاق i) — لا نتداول على شمعة لم تكتمل.
* بوّابة الregime تُحسب أيضاً عند i من بيانات ≤ i فقط (ميل EMA50 + محاذاة EMA8>EMA21).
* حلّ الصفقة داخل الشمعة محافِظ: إن لمست الشمعة SL وTP معاً، نفترض SL أولاً.
* السبريد/التكلفة (وحدات سعر) تُطرح من P&L الخام قبل التحويل إلى R.

وضعا التشغيل
-----------
  python edge_prover.py backtest     # إعادة-تشغيل تاريخي على .npz المخبّأ (إثبات الميكانيكا
                                      # + قياس أثر بوّابة الregime: قبل/بعد). لا MT5، لا أوامر.
  python edge_prover.py forward       # حلقة ورقية مستقبلية: عند كل شمعة H1/M15 جديدة، تقرأ
                                      # شموع MT5 (قراءة فقط)، تطبّق نفس القواعد، وتسجّل كل
                                      # صفقة ورقية إلى data/proven_edges.db. صفر أوامر حيّة.
  python edge_prover.py status        # ملخّص الحافّة الحيّة من قاعدة البيانات + حالة الترقية.

قاعدة البيانات (مستقلّة، لا تمسّ trading.db الحيّة)
-------------------------------------------------
DB: data/proven_edges.db
  • proven_edges        — صف لكل حافّة (تعريفها + إحصاؤها المتراكم + حالة الترقية)
  • proven_edge_trades  — صف لكل صفقة ورقية (دخول/خروج/R/سبب/regime عند الإطلاق)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# المسارات
# ──────────────────────────────────────────────────────────────────────────────
ROOT = Path(r"C:\Users\Radhi\MT5")
LAB = ROOT / "data" / "lab_cache"
DB_PATH = ROOT / "data" / "proven_edges.db"

# ──────────────────────────────────────────────────────────────────────────────
# ميكانيكا المسح الأصلية (مطابِقة لـ full_scan_lab.py — لا تُغيَّر)
# ──────────────────────────────────────────────────────────────────────────────
EMA_FAST, EMA_SLOW = 8, 21
ATR_LEN = 14
BREAK_LOOKBACK = 20         # نافذة الاختراق (سابقة، تستثني i)
TP_R = 2.0                  # خروج 2R
MAX_HOLD = 200              # أقصى شموع انتظار للـSL/TP قبل المغادرة بسعر الإغلاق

# ──────────────────────────────────────────────────────────────────────────────
# بوّابة الregime السببية (إضافية فوق المسح — هذه هي الحماية ضدّ "النظام ضدّ الحافّة")
# ──────────────────────────────────────────────────────────────────────────────
# الفكرة: لا تدخل اختراقاً صعودياً إلا إذا كان الهيكل الأطول صاعداً أو محايداً.
# تُحاكي مفهوم regime في chart_read (محاذاة EMA + ميل EMA الأطول) لكن بحساب سببي مكتفٍ
# ذاتياً من نفس بيانات الشموع المخبّأة، كي يكون قابلاً للإعادة بلا اتصال MT5 وبلا lookahead.
REGIME_EMA_LONG = 50        # EMA الأطول الذي نقيس ميله
REGIME_SLOPE_LOOKBACK = 10  # ميل EMA50 على آخر 10 شموع (يجب أن لا يكون هابطاً للدخول long)
REGIME_SLOPE_MIN = 0.0      # ميل EMA50 ≥ 0 (لا هبوط) شرطٌ للدخول الصعودي

# ──────────────────────────────────────────────────────────────────────────────
# تعريف الحوافّ الثلاث (PAPER candidates) — كلٌّ long/صعودي فقط (هذا ما نجا)
# COST = تكلفة ذهاب-وإياب بوحدات السعر (تُطرح من P&L الخام). مصادرها:
#   • USOILm  0.004  : نفس قيمة المسح (4pt، نفط واقعي).
#   • XAUUSDm 0.30   : ~30c ذهاب-وإياب على الذهب (المسح أثبت بقاءها 15–50c؛ SL بالـATR
#                       يقزّم السبريد فالتكلفة ليست حاملة-للحِمل، لكننا نطرحها بصدق).
#   • XAUEURm 0.30   : مماثلة للذهب (نفس مقياس السعر تقريباً).
# هذه قيم محافظة؛ الحلقة المستقبلية تطرح السبريد الحيّ الحقيقي بدلاً منها عند توفّره.
# ──────────────────────────────────────────────────────────────────────────────
EDGES = [
    {
        "edge_id": "XAUUSDm_H1_BREAKOUT_long",
        "symbol": "XAUUSDm", "tf": "H1", "direction": 1,
        "setup": "BREAKOUT_long",
        "cost_price": 0.30,
        "scan_oos_pf": 2.21, "scan_oos_expR": 0.499, "scan_n": 515,
        "caveat": "أقوى الثلاث لكن أحدث ~شهرين خاسرة (PF 0.45) — راقب التحلّل.",
    },
    {
        "edge_id": "XAUEURm_H1_BREAKOUT_long",
        "symbol": "XAUEURm", "tf": "H1", "direction": 1,
        "setup": "BREAKOUT_long",
        "cost_price": 0.30,
        "scan_oos_pf": 1.91, "scan_oos_expR": 0.439, "scan_n": 56,
        "caveat": "علم أصفر: آخر 56 صفقة خسرت (PF 0.22) — الحافّة نائمة في أحدث نافذة.",
    },
    {
        "edge_id": "USOILm_M15_BREAKOUT_long",
        "symbol": "USOILm", "tf": "M15", "direction": 1,
        "setup": "BREAKOUT_long",
        "cost_price": 0.004,
        "scan_oos_pf": 1.44, "scan_oos_expR": 0.227, "scan_n": 590,
        "caveat": "حقيقية لكن الأهشّ — تتجاوز Bonferroni بأقل من ضعفين؛ أطول مهلة وأصغر لوت.",
    },
]
EDGE_BY_ID = {e["edge_id"]: e for e in EDGES}

# ──────────────────────────────────────────────────────────────────────────────
# معايير الترقية الصريحة (قبل أي اقتراح توصيل حيّ) — pre-committed، لا تُليَّن لاحقاً
# ──────────────────────────────────────────────────────────────────────────────
PROMOTION = {
    "min_paper_trades": 30,        # حدّ أدنى لعدد الصفقات الورقية المستقبلية (غير متداخلة)
    "min_pf": 1.20,                # عامل ربح ورقي ≥ 1.20
    "min_expR": 0.05,              # توقّع R موجب وذو معنى ≥ +0.05R
    "require_ci_excludes_0": True, # 95% bootstrap CI على R يجب أن يستبعد الصفر
    "require_user_approval": True, # موافقة المستخدم الصريحة إلزامية
    "min_lot_on_promote": 0.01,    # يبدأ الحيّ بأدنى لوت فقط
    "max_concurrent_per_edge": 1,  # بوّابة مركز-واحد لكل حافّة (يمنع التداخل/التكرار-الزائف)
    "respect_daily_loss_cap": True,
    "anti_revenge": True,
}

# ──────────────────────────────────────────────────────────────────────────────
# مؤشّرات سببية (متّجهة، بلا lookahead) — مطابِقة لـ full_scan_lab.py
# ──────────────────────────────────────────────────────────────────────────────
def ema(x: np.ndarray, length: int) -> np.ndarray:
    a = 2.0 / (length + 1.0)
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, length: int) -> np.ndarray:
    n = len(c)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.empty(n, dtype=np.float64)
    out[0] = tr[0]
    a = 1.0 / length
    for i in range(1, n):
        out[i] = a * tr[i] + (1 - a) * out[i - 1]   # Wilder
    return out


def rolling_max(x: np.ndarray, w: int) -> np.ndarray:
    """rolling_max[i] = max(x[i-w .. i-1]) — نافذة سابقة تستثني i. NaN حتى تصبح صالحة."""
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(w, n):
        out[i] = np.max(x[i - w:i])
    return out


def rolling_min(x: np.ndarray, w: int) -> np.ndarray:
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(w, n):
        out[i] = np.min(x[i - w:i])
    return out


# ──────────────────────────────────────────────────────────────────────────────
# بوّابة الregime السببية
# ──────────────────────────────────────────────────────────────────────────────
def regime_state_at(i: int, c_ema_fast: np.ndarray, c_ema_slow: np.ndarray,
                    c_ema_long: np.ndarray) -> dict:
    """يُرجع حالة الregime السببية عند الشمعة i (تستخدم index ≤ i فقط).

    التصنيف:
      • slope = (EMA50[i] - EMA50[i-LOOKBACK]) / |EMA50[i-LOOKBACK]| — ميل نسبي.
      • aligned_up = EMA8[i] > EMA21[i] (محاذاة قصيرة-المدى صاعدة).
      • regime: 'UP'    إذا (slope>0 و aligned_up)
                'DOWN'  إذا (slope<0 و not aligned_up)
                'NEUTRAL' خلاف ذلك.
    """
    lb = REGIME_SLOPE_LOOKBACK
    if i - lb < 0 or not np.isfinite(c_ema_long[i]) or not np.isfinite(c_ema_long[i - lb]):
        return {"regime": "NEUTRAL", "slope": 0.0, "aligned_up": False, "ok_long": False}
    base = c_ema_long[i - lb]
    slope = (c_ema_long[i] - base) / (abs(base) + 1e-12)
    aligned_up = bool(c_ema_fast[i] > c_ema_slow[i])
    if slope > 0 and aligned_up:
        regime = "UP"
    elif slope < 0 and not aligned_up:
        regime = "DOWN"
    else:
        regime = "NEUTRAL"
    # بوّابة الدخول الصعودي: امنع الدخول حين الهيكل الأطول هابط.
    #   نسمح UP أو NEUTRAL؛ نمنع DOWN ونمنع الميل الهابط الحادّ.
    ok_long = (regime != "DOWN") and (slope >= REGIME_SLOPE_MIN)
    return {"regime": regime, "slope": float(slope), "aligned_up": aligned_up, "ok_long": bool(ok_long)}


# ──────────────────────────────────────────────────────────────────────────────
# توليد إشارات الاختراق الصعودي + حلّها (سببياً)
# ──────────────────────────────────────────────────────────────────────────────
def resolve_trade(h, l, c, entry_idx, direction, entry, sl, tp):
    """يُرجع (exit_price, exit_idx). محافِظ: SL وTP في نفس الشمعة → SL أولاً."""
    n = len(c)
    end = min(n, entry_idx + MAX_HOLD)
    for j in range(entry_idx, end):
        hi, lo = h[j], l[j]
        if direction == 1:
            hit_sl = lo <= sl
            hit_tp = hi >= tp
            if hit_sl:
                return sl, j
            if hit_tp:
                return tp, j
        else:
            hit_sl = hi >= sl
            hit_tp = lo <= tp
            if hit_sl:
                return sl, j
            if hit_tp:
                return tp, j
    return c[end - 1], end - 1


def compute_indicators(o, h, l, c):
    return {
        "ema_fast": ema(c, EMA_FAST),
        "ema_slow": ema(c, EMA_SLOW),
        "ema_long": ema(c, REGIME_EMA_LONG),
        "atr": atr(h, l, c, ATR_LEN),
        "hh": rolling_max(h, BREAK_LOOKBACK),
        "ll": rolling_min(l, BREAK_LOOKBACK),
    }


def breakout_long_signals(o, h, l, c, ind, apply_regime_gate: bool):
    """يُولّد صفقات الاختراق الصعودي مع/بدون بوّابة regime.

    إشارة الاختراق الصعودي عند i: close[i] > rolling_max(high,20)[i] (الحدّ الأعلى السابق).
      SL = rolling_min(low,20)[i] (الجانب الآخر من المدى).  TP = 2R.  الدخول عند open[i+1].

    يُرجع قائمة dicts، كلٌّ صفقة محلولة مع R وحقول التشخيص.
    """
    ema_f, ema_s, ema_lng = ind["ema_fast"], ind["ema_slow"], ind["ema_long"]
    hh, ll = ind["hh"], ind["ll"]
    n = len(c)
    start = max(EMA_SLOW, ATR_LEN, BREAK_LOOKBACK, REGIME_EMA_LONG) + 1
    trades = []
    busy_until = -1  # بوّابة مركز-واحد: لا دخول جديد قبل خروج السابق (يمنع التداخل/التكرار-الزائف)
    for i in range(start, n - 1):
        if i <= busy_until:
            continue
        if not (np.isfinite(hh[i]) and np.isfinite(ll[i])):
            continue
        ci = c[i]
        if not (ci > hh[i]):
            continue  # لا اختراق صعودي

        reg = regime_state_at(i, ema_f, ema_s, ema_lng)
        gated_out = apply_regime_gate and (not reg["ok_long"])
        if gated_out:
            continue  # بوّابة الregime منعت الدخول ضدّ الاتجاه

        entry_idx = i + 1
        entry = float(o[entry_idx])
        sl = float(ll[i])
        dist = entry - sl
        if dist <= 0:
            continue
        tp = entry + TP_R * dist
        exit_price, exit_idx = resolve_trade(h, l, c, entry_idx, 1, entry, sl, tp)
        # نطرح التكلفة لاحقاً عند حساب R (تحتاج cost لكل حافّة)
        trades.append({
            "signal_idx": int(i), "entry_idx": int(entry_idx), "exit_idx": int(exit_idx),
            "entry": entry, "sl": sl, "tp": tp, "dist": float(dist),
            "exit_price": float(exit_price),
            "regime": reg["regime"], "regime_slope": round(reg["slope"], 6),
            "regime_ok_long": reg["ok_long"],
        })
        busy_until = exit_idx  # مركز-واحد
    return trades


def trades_to_R(trades, cost_price):
    rs = []
    for t in trades:
        raw = t["exit_price"] - t["entry"]      # long
        net = raw - cost_price
        r = net / t["dist"]
        t["R"] = float(r)
        rs.append(r)
    return np.asarray(rs, dtype=np.float64)


# ──────────────────────────────────────────────────────────────────────────────
# إحصاء
# ──────────────────────────────────────────────────────────────────────────────
def profit_factor(rs: np.ndarray) -> float:
    rs = np.asarray(rs, dtype=np.float64)
    gains = rs[rs > 0].sum()
    losses = -rs[rs < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def bootstrap_ci(rs: np.ndarray, n_boot: int = 2000, seed: int = 12345):
    rs = np.asarray(rs, dtype=np.float64)
    if len(rs) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n = len(rs)
    means = np.empty(n_boot)
    for b in range(n_boot):
        means[b] = rs[rng.integers(0, n, n)].mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(rs: np.ndarray) -> dict:
    n = len(rs)
    if n == 0:
        return {"n": 0, "pf": None, "expR": None, "wr": None,
                "ci_lo": None, "ci_hi": None, "ci_excludes_0": False}
    pf = profit_factor(rs)
    lo, hi = bootstrap_ci(rs)
    ci_excl = bool(np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0))
    return {
        "n": int(n),
        "pf": (round(pf, 4) if np.isfinite(pf) else None),
        "expR": round(float(rs.mean()), 5),
        "wr": round(float((rs > 0).mean()), 4),
        "ci_lo": round(lo, 5) if np.isfinite(lo) else None,
        "ci_hi": round(hi, 5) if np.isfinite(hi) else None,
        "ci_excludes_0": ci_excl,
    }


# ──────────────────────────────────────────────────────────────────────────────
# قاعدة البيانات (مستقلّة) — proven_edges + proven_edge_trades
# ──────────────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS proven_edges (
    edge_id        TEXT PRIMARY KEY,
    symbol         TEXT NOT NULL,
    tf             TEXT NOT NULL,
    direction      INTEGER NOT NULL,
    setup          TEXT NOT NULL,
    cost_price     REAL NOT NULL,
    scan_oos_pf    REAL,
    scan_oos_expR  REAL,
    scan_n         INTEGER,
    caveat         TEXT,
    paper_trades   INTEGER DEFAULT 0,
    paper_pf       REAL,
    paper_expR     REAL,
    paper_ci_lo    REAL,
    paper_ci_hi    REAL,
    status         TEXT DEFAULT 'PAPER',   -- PAPER | PROVEN | SHELVED
    updated_ts     TEXT
);
CREATE TABLE IF NOT EXISTS proven_edge_trades (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id        TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    tf             TEXT NOT NULL,
    mode           TEXT NOT NULL,          -- backtest | forward
    signal_iso     TEXT,
    entry_iso      TEXT,
    exit_iso       TEXT,
    entry          REAL,
    sl             REAL,
    tp             REAL,
    exit_price     REAL,
    r_multiple     REAL,
    cost_price     REAL,
    regime         TEXT,
    regime_slope   REAL,
    regime_ok_long INTEGER,
    reason         TEXT,
    recorded_ts    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pet_edge ON proven_edge_trades(edge_id);
CREATE INDEX IF NOT EXISTS idx_pet_mode ON proven_edge_trades(mode);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def db_register_edges(conn: sqlite3.Connection) -> None:
    for e in EDGES:
        conn.execute(
            """INSERT INTO proven_edges
               (edge_id, symbol, tf, direction, setup, cost_price,
                scan_oos_pf, scan_oos_expR, scan_n, caveat, status, updated_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?, COALESCE(
                   (SELECT status FROM proven_edges WHERE edge_id=?), 'PAPER'), ?)
               ON CONFLICT(edge_id) DO UPDATE SET
                   symbol=excluded.symbol, tf=excluded.tf, direction=excluded.direction,
                   setup=excluded.setup, cost_price=excluded.cost_price,
                   scan_oos_pf=excluded.scan_oos_pf, scan_oos_expR=excluded.scan_oos_expR,
                   scan_n=excluded.scan_n, caveat=excluded.caveat, updated_ts=excluded.updated_ts
            """,
            (e["edge_id"], e["symbol"], e["tf"], e["direction"], e["setup"], e["cost_price"],
             e["scan_oos_pf"], e["scan_oos_expR"], e["scan_n"], e["caveat"],
             e["edge_id"], _now_iso()),
        )
    conn.commit()


def db_record_trade(conn: sqlite3.Connection, edge: dict, t: dict, mode: str,
                    times: np.ndarray | None, reason: str = "") -> None:
    def iso(idx):
        if times is None or idx is None or idx >= len(times):
            return None
        return datetime.fromtimestamp(int(times[idx]), timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO proven_edge_trades
           (edge_id, symbol, tf, mode, signal_iso, entry_iso, exit_iso,
            entry, sl, tp, exit_price, r_multiple, cost_price,
            regime, regime_slope, regime_ok_long, reason, recorded_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (edge["edge_id"], edge["symbol"], edge["tf"], mode,
         iso(t.get("signal_idx")), iso(t.get("entry_idx")), iso(t.get("exit_idx")),
         t["entry"], t["sl"], t["tp"], t["exit_price"], t.get("R"), edge["cost_price"],
         t.get("regime"), t.get("regime_slope"), int(bool(t.get("regime_ok_long"))),
         reason, _now_iso()),
    )


def db_update_edge_stats(conn: sqlite3.Connection, edge_id: str) -> dict:
    rows = conn.execute(
        "SELECT r_multiple FROM proven_edge_trades WHERE edge_id=? AND mode='forward' AND r_multiple IS NOT NULL",
        (edge_id,),
    ).fetchall()
    rs = np.asarray([r["r_multiple"] for r in rows], dtype=np.float64)
    s = summarize(rs)
    status_row = conn.execute("SELECT status FROM proven_edges WHERE edge_id=?", (edge_id,)).fetchone()
    status = status_row["status"] if status_row else "PAPER"
    conn.execute(
        """UPDATE proven_edges SET paper_trades=?, paper_pf=?, paper_expR=?,
           paper_ci_lo=?, paper_ci_hi=?, updated_ts=? WHERE edge_id=?""",
        (s["n"], s["pf"], s["expR"], s["ci_lo"], s["ci_hi"], _now_iso(), edge_id),
    )
    conn.commit()
    s["status"] = status
    return s


def promotion_check(stats: dict) -> tuple[bool, list[str]]:
    """يقيّم معايير الترقية الصريحة. يُرجع (مؤهّل-فنياً, أسباب-عدم-التأهّل).
    ملاحظة: التأهّل الفنّي ≠ ترقية — تبقى موافقة المستخدم وأدنى-لوت إلزاميين دائماً."""
    reasons = []
    if (stats.get("n") or 0) < PROMOTION["min_paper_trades"]:
        reasons.append(f"trades {stats.get('n')} < {PROMOTION['min_paper_trades']}")
    pf = stats.get("pf")
    if pf is None or pf < PROMOTION["min_pf"]:
        reasons.append(f"PF {pf} < {PROMOTION['min_pf']}")
    expR = stats.get("expR")
    if expR is None or expR < PROMOTION["min_expR"]:
        reasons.append(f"expR {expR} < {PROMOTION['min_expR']}")
    if PROMOTION["require_ci_excludes_0"] and not stats.get("ci_excludes_0"):
        reasons.append("95% bootstrap CI لا يستبعد 0")
    return (len(reasons) == 0), reasons


# ──────────────────────────────────────────────────────────────────────────────
# الوضع 1: backtest — إثبات الميكانيكا + قياس أثر بوّابة الregime (قبل/بعد)
# ──────────────────────────────────────────────────────────────────────────────
def load_npz(symbol: str, tf: str):
    d = np.load(LAB / f"{symbol}_{tf}.npz")
    return (d["t"].astype(np.int64), d["o"].astype(np.float64), d["h"].astype(np.float64),
            d["l"].astype(np.float64), d["c"].astype(np.float64))


def run_backtest(record: bool = False) -> dict:
    """يعيد تشغيل كل حافّة على .npz: بلا-بوّابة مقابل مع-بوّابة-regime، ويطبع المقارنة.

    الغرض إثبات أن (1) الميكانيكا تستنسخ منطق المسح، و(2) بوّابة الregime تُحسّن
    أحدث-النافذة (تطرد الدخولات-ضدّ-الاتجاه التي كان النظام الحالي ضدّها)."""
    print("=" * 96)
    print("EDGE_PROVER — BACKTEST (no MT5, no orders). regime-gate ON vs OFF, recent-window focus.")
    print("=" * 96)
    out = {}
    conn = db_connect() if record else None
    if conn:
        db_register_edges(conn)
    for e in EDGES:
        t, o, h, l, c = load_npz(e["symbol"], e["tf"])
        ind = compute_indicators(o, h, l, c)
        n = len(c)
        split_idx = int(n * 0.67)   # نفس انقسام المسح: نقيس الكلّ + OOS + أحدث-20%

        def stats_for(apply_gate):
            trades = breakout_long_signals(o, h, l, c, ind, apply_regime_gate=apply_gate)
            rs_all = trades_to_R(trades, e["cost_price"])
            oos = [tr for tr in trades if tr["entry_idx"] >= split_idx]
            recent_cut = int(n * 0.80)
            recent = [tr for tr in trades if tr["entry_idx"] >= recent_cut]
            return {
                "trades": trades,
                "all": summarize(rs_all),
                "oos": summarize(np.asarray([tr["R"] for tr in oos])),
                "recent20": summarize(np.asarray([tr["R"] for tr in recent])),
            }

        no_gate = stats_for(False)
        gated = stats_for(True)
        out[e["edge_id"]] = {"no_gate": {k: no_gate[k] for k in ("all", "oos", "recent20")},
                             "gated": {k: gated[k] for k in ("all", "oos", "recent20")}}

        print(f"\n■ {e['edge_id']}  (scan OOS PF={e['scan_oos_pf']}, n={e['scan_n']})")
        print(f"   caveat: {e['caveat']}")
        for label, blk in (("ALL ", "all"), ("OOS ", "oos"), ("REC20", "recent20")):
            ng, g = no_gate[blk], gated[blk]
            print(f"   {label}  no-gate: n={ng['n']:>4} PF={_f(ng['pf'])} expR={_f(ng['expR'])} wr={_f(ng['wr'])}"
                  f"   |  gated: n={g['n']:>4} PF={_f(g['pf'])} expR={_f(g['expR'])} wr={_f(g['wr'])}")

        if conn:
            # نسجّل صفقات النسخة المُبوَّبة فقط (هي القواعد الحيّة المقترحة) كـ mode='backtest'
            for tr in gated["trades"]:
                db_record_trade(conn, e, tr, mode="backtest", times=t,
                                reason="backtest_regime_gated")
            conn.commit()
    if conn:
        conn.close()
        print(f"\n[DB] backtest trades recorded -> {DB_PATH}")
    print("\nملاحظة: backtest للإثبات فقط؛ الترقية تتطلّب صفقات mode='forward' مستقبلية + موافقة.")
    return out


def _f(v):
    if v is None:
        return "  n/a"
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return "  inf"
    return f"{v:6.3f}" if isinstance(v, float) else f"{v}"


# ──────────────────────────────────────────────────────────────────────────────
# الوضع 2: forward — حلقة ورقية مستقبلية (قراءة MT5 فقط، صفر أوامر)
# ──────────────────────────────────────────────────────────────────────────────
_TF_MAP = {"M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1"}
N_BARS_PULL = 400   # شموع كافية لـEMA50 + نافذة الاختراق + هامش
POLL_S = 60


def _mt5_tf(mt5, tf: str):
    return getattr(mt5, _TF_MAP[tf])


def forward_loop():
    """حلقة ورقية: عند كل شمعة جديدة مكتملة لكل حافّة، طبّق القواعد (سببياً) وسجّل أي صفقة
    ورقية فُتحت/أُغلقت إلى proven_edges.db. لا order_send إطلاقاً. اتصال MT5 واحد، خفيف."""
    try:
        import MetaTrader5 as mt5  # noqa: PLC0415  (استيراد كسول كي يستورد الملف بلا MT5)
    except Exception as ex:
        print(f"[FWD] MetaTrader5 غير متاح: {ex}")
        return
    print("[FWD] edge_prover forward paper loop — PAPER ONLY, zero live orders.", flush=True)
    conn = db_connect()
    db_register_edges(conn)
    open_paper: dict[str, dict] = {}   # edge_id -> صفقة ورقية مفتوحة (بوّابة مركز-واحد)
    last_bar: dict[str, int] = {}      # edge_id -> آخر طابع زمني شمعة عولج

    while True:
        try:
            if not (mt5.initialize() or mt5.initialize()):
                time.sleep(POLL_S); continue
            for e in EDGES:
                eid = e["edge_id"]
                rates = mt5.copy_rates_from_pos(e["symbol"], _mt5_tf(mt5, e["tf"]), 0, N_BARS_PULL)
                if rates is None or len(rates) < REGIME_EMA_LONG + BREAK_LOOKBACK + 5:
                    continue
                t = np.array([r["time"] for r in rates], dtype=np.int64)
                o = np.array([r["open"] for r in rates], dtype=np.float64)
                h = np.array([r["high"] for r in rates], dtype=np.float64)
                l = np.array([r["low"] for r in rates], dtype=np.float64)
                c = np.array([r["close"] for r in rates], dtype=np.float64)
                # الشمعة الأخيرة (index -1) قد تكون قيد التكوين → نعتمد المكتملة (index -2)
                i = len(c) - 2
                if i < REGIME_EMA_LONG + BREAK_LOOKBACK + 1:
                    continue
                if last_bar.get(eid) == int(t[i]):
                    continue  # عولجت هذه الشمعة
                ind = compute_indicators(o, h, l, c)

                # ── إدارة صفقة ورقية مفتوحة: هل لمست SL/TP على الشمعة المكتملة؟ ──
                pos = open_paper.get(eid)
                if pos is not None:
                    hit = None
                    if l[i] <= pos["sl"]:
                        hit = ("SL", pos["sl"])
                    elif h[i] >= pos["tp"]:
                        hit = ("TP", pos["tp"])
                    if hit:
                        exit_price = hit[1]
                        raw = exit_price - pos["entry"]
                        r = (raw - e["cost_price"]) / pos["dist"]
                        rec = {"signal_idx": pos["signal_idx_t"], "entry_idx": pos["entry_idx_t"],
                               "exit_idx": i, "entry": pos["entry"], "sl": pos["sl"], "tp": pos["tp"],
                               "dist": pos["dist"], "exit_price": float(exit_price), "R": float(r),
                               "regime": pos["regime"], "regime_slope": pos["regime_slope"],
                               "regime_ok_long": pos["regime_ok_long"]}
                        db_record_trade(conn, e, rec, mode="forward", times=t,
                                        reason=f"paper_exit_{hit[0]}")
                        conn.commit()
                        s = db_update_edge_stats(conn, eid)
                        elig, why = promotion_check(s)
                        print(f"[FWD] {eid} paper {hit[0]} R={r:+.3f} | n={s['n']} PF={s['pf']} "
                              f"expR={s['expR']} elig={elig} {('' if elig else why)}", flush=True)
                        open_paper.pop(eid, None)

                # ── دخول جديد (مركز-واحد): فقط إن لا صفقة مفتوحة على هذه الحافّة ──
                if eid not in open_paper:
                    hh, ll = ind["hh"], ind["ll"]
                    if np.isfinite(hh[i]) and np.isfinite(ll[i]) and c[i] > hh[i]:
                        reg = regime_state_at(i, ind["ema_fast"], ind["ema_slow"], ind["ema_long"])
                        if reg["ok_long"]:
                            entry = float(o[-1])   # الدخول عند افتتاح الشمعة الحالية (i+1) = آخر شمعة
                            sl = float(ll[i]); dist = entry - sl
                            if dist > 0:
                                open_paper[eid] = {
                                    "entry": entry, "sl": sl, "tp": entry + TP_R * dist, "dist": dist,
                                    "regime": reg["regime"], "regime_slope": round(reg["slope"], 6),
                                    "regime_ok_long": reg["ok_long"],
                                    "signal_idx_t": i, "entry_idx_t": len(c) - 1,
                                }
                                print(f"[FWD] {eid} PAPER ENTRY @ {entry} sl={sl} tp={entry+TP_R*dist:.3f} "
                                      f"regime={reg['regime']}", flush=True)
                        else:
                            print(f"[FWD] {eid} breakout BLOCKED by regime gate "
                                  f"(regime={reg['regime']} slope={reg['slope']:+.4f})", flush=True)
                last_bar[eid] = int(t[i])
            mt5.shutdown()
        except Exception as ex:
            print(f"[FWD] err {ex}", flush=True)
        time.sleep(POLL_S)


# ──────────────────────────────────────────────────────────────────────────────
# الوضع 3: status — ملخّص الحافّة الحيّة + حالة الترقية
# ──────────────────────────────────────────────────────────────────────────────
def show_status() -> dict:
    conn = db_connect()
    db_register_edges(conn)
    print("=" * 96)
    print("EDGE_PROVER — STATUS  (forward paper edge + promotion gate)")
    print("=" * 96)
    print(f"معايير الترقية الصريحة: trades≥{PROMOTION['min_paper_trades']}, "
          f"PF≥{PROMOTION['min_pf']}, expR≥{PROMOTION['min_expR']}, CI يستبعد 0, "
          f"+موافقة مستخدم, +أدنى لوت {PROMOTION['min_lot_on_promote']}, مركز-واحد/حافّة.")
    result = {}
    for e in EDGES:
        s = db_update_edge_stats(conn, e["edge_id"])
        elig, why = promotion_check(s)
        result[e["edge_id"]] = {"stats": s, "tech_eligible": elig, "blockers": why}
        print(f"\n■ {e['edge_id']}  status={s.get('status')}")
        print(f"   forward paper: n={s['n']} PF={s['pf']} expR={s['expR']} "
              f"CI=[{s['ci_lo']},{s['ci_hi']}] excl0={s['ci_excludes_0']}")
        if elig:
            print("   ✔ مؤهّل فنّياً — لا تزال موافقة المستخدم + أدنى لوت إلزاميين قبل أي توصيل حيّ.")
        else:
            print(f"   ✗ غير مؤهّل بعد: {'; '.join(why)}")
    conn.close()
    return result


# ──────────────────────────────────────────────────────────────────────────────
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "backtest":
        run_backtest(record="--record" in sys.argv)
    elif mode == "forward":
        forward_loop()
    elif mode == "status":
        show_status()
    else:
        print(__doc__)
        print(f"أوضاع: backtest [--record] | forward | status")


if __name__ == "__main__":
    main()
