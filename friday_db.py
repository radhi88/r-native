"""friday_db.py — العمود الفقري للبيانات في FRIDAY: مخزن SQLite محلّي، صفر اعتماديات
(sqlite3 مدمج في بايثون)، آمن للكتابة المتزامنة من عدّة محرّكات (WAL).

لماذا؟ حالة النظام مبعثرة عبر عشرات ملفات JSON تُكتب كاملةً في كل نبضة (سباق كتابة،
لا تاريخ، لا فهرسة، لا استعلام). هذا الملف يوحّد كل شيء في قاعدة واحدة قابلة للاستعلام:
  trades         — كل صفقة (دخول/خروج، magic، صافي، عمولة، سواب، المصدر)
  features       — لقطة سمات سببية لكل دخول، مرتبطة بصفقة
  signals        — قرارات army_warroom / chart_read (rمز، فريم، اتجاه، التقاء، نظام)
  scoreboard     — حافّة لكل فصيل/رمز (n, wins, expectancy_R)
  proven_edges   — حوافّ مُثبتة OOS (PF، النافذة، الحالة paper/live)
  engine_health  — نبضة كل محرّك مع ts صريح (لا نقرأ حالة بايتة بعد اليوم)

قواعد التصميم:
  * إضافي فقط: لا يعدّل أي ملف .py قائم ولا يرسل أي أمر تداول. قراءة + إدراج فقط.
  * idempotent: migrate() آمنة للتشغيل المتكرر (INSERT OR REPLACE على مفاتيح طبيعية).
  * WAL mode + busy_timeout → عدّة محرّكات تكتب بأمان دون قفل.
  * فهارس على (symbol, ts) و (magic, ts) لاستعلامات تحليلية سريعة.

تشغيل:
  python friday_db.py --init                 # ينشئ السكيمة فقط
  python friday_db.py --migrate              # يستورد مصادر JSON + history_deals 30 يوماً
  python friday_db.py --init --migrate        # الاثنان معاً
  python friday_db.py --stats                # يطبع COUNT لكل جدول

واجهة بايثون للمحرّكات الحيّة (مثال):
  from friday_db import FridayDB
  db = FridayDB()                            # WAL، آمن للتزامن
  db.record_signal(symbol="XAUUSDm", tf="M5", dir=1, confluence=0.62, regime="trend",
                   votes=14, weights=0.71, source="chart_read")
  db.heartbeat("spike_rider", pid=12345, status="alive")
  rows = db.pnl_by_source(hours=24)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent
RN = ROOT / "data" / "r_native"
DB_PATH = ROOT / "data" / "friday.db"

# JSON مصادر الترحيل (المسارات الفعلية كما تحقّقنا منها)
SRC_WATCHDOG = RN / "watchdog_status.json"
SRC_AUTOPILOT = RN / "autopilot_status.json"
SRC_EDGE_GUARD = RN / "edge_guard.json"
SRC_ARMY = RN / "army_scoreboard.json"          # سكوربورد army_warroom
SRC_PNL = RN / "pnl_scoreboard.json"            # صافٍ لكل مصدر/magic (مصدر مكمّل)
SRC_MANUAL_FEATURES = RN / "manual_trade_features.jsonl"  # سمات سببية مُعنونة


# ---------------------------------------------------------------------------- schema
SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

-- كل صفقة (مغلقة أو لقطة): مفتاح طبيعي (position_id, magic) لمنع التكرار عبر إعادة التشغيل
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id   INTEGER,            -- MT5 position_id (يربط دخول+خروج)
    ticket        INTEGER,            -- تذكرة الدخول
    magic         INTEGER NOT NULL DEFAULT 0,
    symbol        TEXT    NOT NULL,
    ts            REAL    NOT NULL,   -- زمن الدخول (unix)
    iso           TEXT,
    side          INTEGER,            -- 1 شراء / -1 بيع
    lots          REAL,
    entry         REAL,
    exit          REAL,
    pnl           REAL    DEFAULT 0,  -- profit فقط (بدون عمولة/سواب)
    commission    REAL    DEFAULT 0,
    swap          REAL    DEFAULT 0,
    net           REAL    DEFAULT 0,  -- pnl + commission + swap
    win           INTEGER,            -- 1/0 إن عُرف
    hold_min      REAL,               -- مدة الحفظ بالدقائق
    source        TEXT,               -- 'manual' / 'bot' / 'user_ea' / اسم البوت
    closed        INTEGER DEFAULT 1,  -- 1 مُغلقة، 0 مفتوحة-لقطة
    UNIQUE(position_id, magic)
);
CREATE INDEX IF NOT EXISTS ix_trades_symbol_ts ON trades(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_trades_magic_ts  ON trades(magic, ts);
CREATE INDEX IF NOT EXISTS ix_trades_source     ON trades(source);

-- لقطة سمات سببية لكل دخول (≤ وقت الدخول)؛ JSON خام محفوظ + أعمدة مفهرسة شائعة
CREATE TABLE IF NOT EXISTS features (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket      INTEGER,             -- يربط بـ trades.ticket
    trade_id    INTEGER,             -- FK اختياري إلى trades.id إن وُجد
    symbol      TEXT NOT NULL,
    ts          REAL NOT NULL,       -- زمن لقطة الدخول (unix)
    iso         TEXT,
    side        INTEGER,
    lot         REAL,
    -- أعمدة مستخرَجة من السمات للاستعلام السريع
    price       REAL,
    spread      REAL,
    atr         REAL,
    atr_pctile  REAL,
    rsi         REAL,
    stoch       REAL,
    trend       INTEGER,
    htf_trend   INTEGER,
    dist_ema_atr REAL,
    hour        INTEGER,
    dow         INTEGER,
    session     TEXT,
    -- التسمية (النتيجة)
    net         REAL,
    win         INTEGER,
    hold_min    REAL,
    src         TEXT,                -- backfill / live
    features_json TEXT,              -- اللقطة الكاملة (شموع .. إلخ)
    UNIQUE(ticket)
);
CREATE INDEX IF NOT EXISTS ix_features_symbol_ts ON features(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_features_session    ON features(session);

-- قرارات army_warroom / chart_read (تيار قرارات، append فقط)
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    tf          TEXT,
    ts          REAL NOT NULL,
    iso         TEXT,
    dir         INTEGER,             -- 1 / 0 / -1
    confluence  REAL,
    regime      TEXT,
    votes       INTEGER,
    weights     REAL,
    entry       REAL,
    sl          REAL,
    tgt         REAL,
    risk        REAL,
    source      TEXT,                -- 'chart_read' / 'army_warroom' / ...
    extra_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_signals_symbol_ts ON signals(symbol, ts);
CREATE INDEX IF NOT EXISTS ix_signals_source     ON signals(source);

-- إحصاء حافّة لكل فصيل(squad)/رمز: مفتاح طبيعي (squad, symbol) محدّث upsert
CREATE TABLE IF NOT EXISTS scoreboard (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    squad         TEXT NOT NULL,     -- اسم الفصيل/المحرّك/البوت
    symbol        TEXT NOT NULL,
    n             INTEGER DEFAULT 0,
    wins          INTEGER DEFAULT 0,
    sum_r         REAL    DEFAULT 0, -- مجموع R
    expectancy_r  REAL,              -- sum_r / n
    ts            REAL,              -- آخر تحديث
    iso           TEXT,
    UNIQUE(squad, symbol)
);
CREATE INDEX IF NOT EXISTS ix_scoreboard_symbol ON scoreboard(symbol);

-- حوافّ مُثبتة OOS مع PF/النافذة/الحالة
CREATE TABLE IF NOT EXISTS proven_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,       -- وصف الحافّة
    symbol      TEXT,
    tf          TEXT,
    pf          REAL,                -- profit factor
    window      TEXT,                -- نافذة الاختبار (تواريخ/كتل)
    n           INTEGER,
    status      TEXT,                -- 'paper' / 'live' / 'retired'
    ts          REAL,
    iso         TEXT,
    meta_json   TEXT,
    UNIQUE(name, symbol, tf)
);
CREATE INDEX IF NOT EXISTS ix_proven_status ON proven_edges(status);

-- نبضة كل محرّك مع ts صريح (لا حالة بايتة)
CREATE TABLE IF NOT EXISTS engine_health (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    engine      TEXT NOT NULL,       -- اسم العملية
    ts          REAL NOT NULL,       -- آخر نبضة (unix)
    iso         TEXT,
    status      TEXT,                -- 'alive' / 'dead' / 'stale'
    pid         INTEGER,
    restarts    INTEGER DEFAULT 0,
    age_s       REAL,                -- عمر النبضة عند التسجيل
    meta_json   TEXT,
    UNIQUE(engine)
);
CREATE INDEX IF NOT EXISTS ix_engine_ts ON engine_health(ts);
"""


# ---------------------------------------------------------------------------- core
def connect(db_path: Path | str = DB_PATH, *, timeout: float = 30.0) -> sqlite3.Connection:
    """اتصال WAL آمن للتزامن. busy_timeout كبير ليصبر على كتّاب آخرين."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=timeout, isolation_level=None)  # autocommit
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=30000;")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _now() -> tuple[float, str]:
    t = time.time()
    return t, datetime.fromtimestamp(t, timezone.utc).isoformat()


class FridayDB:
    """واجهة نظيفة للمحرّكات الحيّة. كل instance يفتح اتصالاً WAL مستقلاً (آمن للتزامن)."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.con = connect(db_path)
        init_schema(self.con)

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass

    def __enter__(self) -> "FridayDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -------------------------------------------------------------- trades
    def insert_trade(self, *, position_id: Optional[int], magic: int, symbol: str, ts: float,
                     side: Optional[int] = None, lots: Optional[float] = None,
                     entry: Optional[float] = None, exit: Optional[float] = None,
                     pnl: float = 0.0, commission: float = 0.0, swap: float = 0.0,
                     net: Optional[float] = None, win: Optional[int] = None,
                     hold_min: Optional[float] = None, source: Optional[str] = None,
                     ticket: Optional[int] = None, iso: Optional[str] = None,
                     closed: int = 1) -> None:
        if net is None:
            net = pnl + commission + swap
        if iso is None:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        self.con.execute(
            """INSERT INTO trades
               (position_id, ticket, magic, symbol, ts, iso, side, lots, entry, exit,
                pnl, commission, swap, net, win, hold_min, source, closed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(position_id, magic) DO UPDATE SET
                 exit=excluded.exit, pnl=excluded.pnl, commission=excluded.commission,
                 swap=excluded.swap, net=excluded.net, win=excluded.win,
                 hold_min=excluded.hold_min, closed=excluded.closed""",
            (position_id, ticket, magic, symbol, ts, iso, side, lots, entry, exit,
             pnl, commission, swap, net, win, hold_min, source, closed),
        )

    # -------------------------------------------------------------- features
    def insert_feature(self, *, ticket: int, symbol: str, ts: float, features: dict,
                       side: Optional[int] = None, lot: Optional[float] = None,
                       net: Optional[float] = None, win: Optional[int] = None,
                       hold_min: Optional[float] = None, src: Optional[str] = None,
                       iso: Optional[str] = None, trade_id: Optional[int] = None) -> None:
        f = features or {}
        if iso is None:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        self.con.execute(
            """INSERT INTO features
               (ticket, trade_id, symbol, ts, iso, side, lot, price, spread, atr, atr_pctile,
                rsi, stoch, trend, htf_trend, dist_ema_atr, hour, dow, session,
                net, win, hold_min, src, features_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ticket) DO UPDATE SET
                 net=excluded.net, win=excluded.win, hold_min=excluded.hold_min,
                 src=excluded.src, features_json=excluded.features_json""",
            (ticket, trade_id, symbol, ts, iso, side, lot,
             f.get("price"), f.get("spread"), f.get("atr"), f.get("atr_pctile"),
             f.get("rsi"), f.get("stoch"), f.get("trend"), f.get("htf_trend"),
             f.get("dist_ema_atr"), f.get("hour"), f.get("dow"), f.get("session"),
             net, win, hold_min, src, json.dumps(f, ensure_ascii=False)),
        )

    # -------------------------------------------------------------- signals
    def record_signal(self, *, symbol: str, tf: Optional[str] = None, dir: Optional[int] = None,
                      confluence: Optional[float] = None, regime: Optional[str] = None,
                      votes: Optional[int] = None, weights: Optional[float] = None,
                      entry: Optional[float] = None, sl: Optional[float] = None,
                      tgt: Optional[float] = None, risk: Optional[float] = None,
                      source: str = "chart_read", ts: Optional[float] = None,
                      extra: Optional[dict] = None) -> None:
        if ts is None:
            ts, iso = _now()
        else:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        self.con.execute(
            """INSERT INTO signals
               (symbol, tf, ts, iso, dir, confluence, regime, votes, weights,
                entry, sl, tgt, risk, source, extra_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol, tf, ts, iso, dir, confluence, regime, votes, weights,
             entry, sl, tgt, risk, source,
             json.dumps(extra, ensure_ascii=False) if extra else None),
        )

    # -------------------------------------------------------------- scoreboard
    def upsert_scoreboard(self, *, squad: str, symbol: str, n: int, wins: int,
                          sum_r: float, ts: Optional[float] = None) -> None:
        if ts is None:
            ts, iso = _now()
        else:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        exp = (sum_r / n) if n else None
        self.con.execute(
            """INSERT INTO scoreboard (squad, symbol, n, wins, sum_r, expectancy_r, ts, iso)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(squad, symbol) DO UPDATE SET
                 n=excluded.n, wins=excluded.wins, sum_r=excluded.sum_r,
                 expectancy_r=excluded.expectancy_r, ts=excluded.ts, iso=excluded.iso""",
            (squad, symbol, n, wins, sum_r, exp, ts, iso),
        )

    # -------------------------------------------------------------- proven_edges
    def upsert_proven_edge(self, *, name: str, symbol: Optional[str] = None,
                           tf: Optional[str] = None, pf: Optional[float] = None,
                           window: Optional[str] = None, n: Optional[int] = None,
                           status: str = "paper", ts: Optional[float] = None,
                           meta: Optional[dict] = None) -> None:
        if ts is None:
            ts, iso = _now()
        else:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        self.con.execute(
            """INSERT INTO proven_edges (name, symbol, tf, pf, window, n, status, ts, iso, meta_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name, symbol, tf) DO UPDATE SET
                 pf=excluded.pf, window=excluded.window, n=excluded.n,
                 status=excluded.status, ts=excluded.ts, iso=excluded.iso,
                 meta_json=excluded.meta_json""",
            (name, symbol, tf, pf, window, n, status, ts, iso,
             json.dumps(meta, ensure_ascii=False) if meta else None),
        )

    # -------------------------------------------------------------- engine_health
    def heartbeat(self, engine: str, *, status: str = "alive", pid: Optional[int] = None,
                  restarts: int = 0, age_s: Optional[float] = None,
                  ts: Optional[float] = None, meta: Optional[dict] = None) -> None:
        """نبضة محرّك. تُكتب دائماً مع ts صريح → stale_engines() يكشف البايت."""
        if ts is None:
            ts, iso = _now()
        else:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        self.con.execute(
            """INSERT INTO engine_health (engine, ts, iso, status, pid, restarts, age_s, meta_json)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(engine) DO UPDATE SET
                 ts=excluded.ts, iso=excluded.iso, status=excluded.status,
                 pid=excluded.pid, restarts=excluded.restarts, age_s=excluded.age_s,
                 meta_json=excluded.meta_json""",
            (engine, ts, iso, status, pid, restarts, age_s,
             json.dumps(meta, ensure_ascii=False) if meta else None),
        )

    # ============================================================== ANALYTICS
    def pnl_by_source(self, hours: float = 24.0) -> list[dict]:
        cutoff = time.time() - hours * 3600
        cur = self.con.execute(
            """SELECT source, COUNT(*) AS n,
                      SUM(CASE WHEN net>0 THEN 1 ELSE 0 END) AS wins,
                      ROUND(SUM(net),2) AS net
               FROM trades WHERE ts >= ? AND closed=1
               GROUP BY source ORDER BY net ASC""",
            (cutoff,),
        )
        return [dict(r) for r in cur.fetchall()]

    def pnl_by_magic(self, hours: float = 24.0) -> list[dict]:
        cutoff = time.time() - hours * 3600
        cur = self.con.execute(
            """SELECT magic, COUNT(*) AS n,
                      SUM(CASE WHEN net>0 THEN 1 ELSE 0 END) AS wins,
                      ROUND(SUM(net),2) AS net
               FROM trades WHERE ts >= ? AND closed=1
               GROUP BY magic ORDER BY net ASC""",
            (cutoff,),
        )
        return [dict(r) for r in cur.fetchall()]

    def edge_by_squad(self) -> list[dict]:
        cur = self.con.execute(
            """SELECT squad, symbol, n, wins, ROUND(sum_r,3) AS sum_r,
                      ROUND(expectancy_r,3) AS expectancy_r
               FROM scoreboard ORDER BY expectancy_r DESC""")
        return [dict(r) for r in cur.fetchall()]

    def stale_engines(self, max_age: float = 120.0) -> list[dict]:
        """المحرّكات التي تجاوزت نبضتها max_age ثانية (أو حالتها != alive)."""
        now = time.time()
        cur = self.con.execute("SELECT engine, ts, iso, status, pid, restarts FROM engine_health")
        out = []
        for r in cur.fetchall():
            age = now - (r["ts"] or 0)
            if age > max_age or (r["status"] and r["status"] != "alive"):
                d = dict(r)
                d["age_s"] = round(age, 1)
                out.append(d)
        return sorted(out, key=lambda x: -x["age_s"])

    def feature_outcomes(self, *, symbol: Optional[str] = None, session: Optional[str] = None,
                         limit: int = 1000) -> list[dict]:
        q = ("SELECT ticket, symbol, ts, session, side, net, win, hold_min, "
             "rsi, atr_pctile, trend, htf_trend FROM features WHERE 1=1")
        args: list[Any] = []
        if symbol:
            q += " AND symbol=?"; args.append(symbol)
        if session:
            q += " AND session=?"; args.append(session)
        q += " ORDER BY ts DESC LIMIT ?"; args.append(limit)
        cur = self.con.execute(q, args)
        return [dict(r) for r in cur.fetchall()]

    def counts(self) -> dict[str, int]:
        tables = ["trades", "features", "signals", "scoreboard", "proven_edges", "engine_health"]
        out = {}
        for t in tables:
            out[t] = self.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out


# ---------------------------------------------------------------------------- migration
def _load_json(p: Path) -> Optional[dict | list]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"  [skip] {p.name}: {e}")
        return None


# مغناطيسات بوتاتنا الصريحة (نتحكّم بها) — كل ما عداها ليس "بوتنا"
OUR_MAGICS = {3627, 99779, 99782, 99791, 99792,
              20260605, 20260608, 20260611, 20260612, 20260613,
              20260614, 20260616, 20260617, 20260618}
# إكسبيرتات المستخدم (ملكه، لا نلمسها): QuantumShark 20250421/22 + LOCK30X 2447 (جهازه الثاني)
USER_EA_MAGICS = {2447, 20250421, 20250422}


def _classify_source(magic: int) -> str:
    if magic == 0:
        return "manual"
    if magic in OUR_MAGICS or 20260000 <= magic < 20270000:
        return "bot"
    if magic in USER_EA_MAGICS or 20250000 <= magic < 20260000:
        return "user_ea"
    return "external"          # طرف ثالث/مجهول (مثل 12345) — ليس بوتنا ولا يدويك المعروف


def migrate(db_path: Path | str = DB_PATH, *, deal_days: int = 30) -> dict[str, int]:
    """يستورد المصادر مرّة واحدة (idempotent). يرجع خريطة (مصدر → عدد الصفوف المُدرجة)."""
    db = FridayDB(db_path)
    rep: dict[str, int] = {}

    # 1) engine_health <- watchdog_status.json
    wd = _load_json(SRC_WATCHDOG)
    n = 0
    if isinstance(wd, dict):
        alive = wd.get("alive", {}) or {}
        restarts = wd.get("restarts", {}) or {}
        ts = wd.get("ts", time.time())
        for eng, _flag in alive.items():
            db.heartbeat(eng, status="alive", restarts=int(restarts.get(eng, 0) or 0),
                         ts=ts, age_s=0.0, meta={"src": "watchdog_status"})
            n += 1
    rep["watchdog_status.json -> engine_health"] = n

    # 2) autopilot_status.json -> engine_health (نبضة autopilot نفسه) + proven_edge للحالة
    ap = _load_json(SRC_AUTOPILOT)
    n = 0
    if isinstance(ap, dict):
        eng = ap.get("engines", {}) or {}
        db.heartbeat("friday_autopilot", status="alive",
                     ts=ap.get("ts", time.time()), age_s=eng.get("age_s"),
                     meta={"equity": ap.get("equity"), "balance": ap.get("balance"),
                           "discipline_score": ap.get("discipline_score"),
                           "safety_flag": ap.get("safety_flag", "OK"),
                           "realized_7d": ap.get("realized_7d"),
                           "src": "autopilot_status"})
        n = 1
    rep["autopilot_status.json -> engine_health"] = n

    # 3) edge_guard.json -> engine_health (نبضة edge_guard + الانتهاكات)
    eg = _load_json(SRC_EDGE_GUARD)
    n = 0
    if isinstance(eg, dict):
        db.heartbeat("edge_guard", status="alive", ts=eg.get("ts", time.time()), age_s=0.0,
                     meta={"discipline_score": eg.get("discipline_score"),
                           "active_violations": eg.get("active_violations"),
                           "n_manual": eg.get("n_manual"),
                           "edge_reminder": eg.get("edge_reminder"),
                           "src": "edge_guard"})
        n = 1
    rep["edge_guard.json -> engine_health"] = n

    # 4) army_scoreboard.json -> scoreboard (stats) + signals (pending قرارات)
    army = _load_json(SRC_ARMY)
    n_sb = n_sig = 0
    if isinstance(army, dict):
        stats = army.get("stats", {}) or {}
        for sym, s in stats.items():
            db.upsert_scoreboard(squad="army_warroom", symbol=sym,
                                 n=int(s.get("n", 0)), wins=int(s.get("wins", 0)),
                                 sum_r=float(s.get("sumR", 0.0)))
            n_sb += 1
        for p in (army.get("pending", []) or []):
            db.record_signal(symbol=p.get("sym", "?"), tf="army", dir=p.get("dir"),
                             entry=p.get("entry"), sl=p.get("sl"), tgt=p.get("tgt"),
                             risk=p.get("risk"), source="army_warroom",
                             ts=p.get("t"), extra={"pending": True})
            n_sig += 1
    rep["army_scoreboard.json -> scoreboard"] = n_sb
    rep["army_scoreboard.json -> signals"] = n_sig

    # 5) manual_trade_features.jsonl -> features (+ trades من اللقطات المُعنونة)
    n_feat = n_tr = 0
    if SRC_MANUAL_FEATURES.exists():
        for ln in SRC_MANUAL_FEATURES.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            tk = rec.get("ticket")
            if tk is None:
                continue
            db.insert_feature(ticket=tk, symbol=rec.get("symbol", "?"),
                              ts=rec.get("time", 0), features=rec.get("features", {}),
                              side=rec.get("dir"), lot=rec.get("lot"),
                              net=rec.get("net"), win=rec.get("win"),
                              hold_min=rec.get("hold_min"), src=rec.get("src"),
                              iso=rec.get("iso"))
            n_feat += 1
            # كل سجلّ سمات مُعنون = صفقة يدوية مغلقة → trades
            if rec.get("net") is not None:
                db.insert_trade(position_id=tk, ticket=tk, magic=0,
                                symbol=rec.get("symbol", "?"), ts=rec.get("time", 0),
                                side=rec.get("dir"), lots=rec.get("lot"),
                                entry=rec.get("features", {}).get("price"),
                                net=rec.get("net"), win=rec.get("win"),
                                hold_min=rec.get("hold_min"), source="manual",
                                iso=rec.get("iso"), closed=1)
                n_tr += 1
    rep["manual_trade_features.jsonl -> features"] = n_feat
    rep["manual_trade_features.jsonl -> trades"] = n_tr

    # 6) history_deals آخر deal_days يوماً -> trades (قراءة فقط من MT5، اتصال واحد)
    n_deals = _migrate_history_deals(db, deal_days)
    rep[f"MT5 history_deals (last {deal_days}d) -> trades"] = n_deals

    db.con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    db.close()
    return rep


def _migrate_history_deals(db: FridayDB, days: int) -> int:
    """يبني صفقات (دخول+خروج مجمّعة بـ position_id) من MT5 history_deals. اتصال واحد، قراءة فقط."""
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        print(f"  [deals] MetaTrader5 غير متاح: {e}")
        return 0
    if not (mt5.initialize() or mt5.initialize()):
        print("  [deals] mt5.initialize فشل — تخطّي history_deals")
        return 0
    try:
        now = time.time()
        deals = mt5.history_deals_get(int(now - days * 86400), int(now)) or []
        pos: dict[int, dict] = {}
        for d in deals:
            if d.position_id == 0:
                continue
            p = pos.setdefault(d.position_id, {
                "in": None, "out": None, "magic": d.magic, "symbol": d.symbol,
                "pnl": 0.0, "commission": 0.0, "swap": 0.0})
            p["magic"] = d.magic or p["magic"]
            p["symbol"] = d.symbol or p["symbol"]
            if d.entry == 0:        # دخول
                p["in"] = d
            elif d.entry == 1:      # خروج
                p["out"] = d
            p["pnl"] += d.profit
            p["commission"] += d.commission
            p["swap"] += d.swap
        n = 0
        for pid, p in pos.items():
            din = p["in"]
            dout = p["out"]
            if din is None:
                continue  # دخول خارج النافذة؛ نتخطّى لتجنّب لقطة منقوصة
            net = p["pnl"] + p["commission"] + p["swap"]
            closed = 1 if dout is not None else 0
            hold = ((dout.time - din.time) / 60.0) if (dout and din) else None
            db.insert_trade(
                position_id=pid, ticket=din.ticket, magic=p["magic"], symbol=p["symbol"],
                ts=din.time, side=(1 if din.type == 0 else -1), lots=din.volume,
                entry=din.price, exit=(dout.price if dout else None),
                pnl=round(p["pnl"], 2), commission=round(p["commission"], 2),
                swap=round(p["swap"], 2), net=round(net, 2),
                win=(int(net > 0) if closed else None),
                hold_min=(round(hold, 1) if hold is not None else None),
                source=_classify_source(p["magic"]), closed=closed,
            )
            n += 1
        return n
    finally:
        mt5.shutdown()


# ---------------------------------------------------------------------------- live recorder
# Go-forward ingestion: keep `trades` fresh from MT5 history for OUR bot magics ONLY.
# Why this exists: friday_db.migrate() was a one-shot 30-day backfill (run once on build day,
# 2026-06-18) and was never wired to run again — so `trades` froze while the bots kept trading,
# and real_account_gate.py was grading on an 11-day-old snapshot. This recorder, guarded 24/7,
# keeps the closed-trade store current.
#   * Manual (magic 0) has its OWN pipeline (manual_trade_features.jsonl) → never ingested here.
#   * External / user EAs are off-limits → never ingested here.
# This matches real_account_gate._load_trades' consumer filter (closed=1 AND source='bot',
# excluding EXTERNAL_EA_MAGICS and magic 0).
PROTECTED_MAGICS = {0, 2447, 20250418, 20250421, 20250422, 20250618}


def _is_our_bot(magic: int) -> bool:
    """True ONLY for our automated magics — skips manual (0) + external/user EAs."""
    if magic in PROTECTED_MAGICS:
        return False
    return _classify_source(magic) == "bot"


def record_recent_deals(db: "FridayDB", mt5, *, days: float = 7.0) -> tuple[int, float]:
    """Upsert closed (and open-snapshot) bot trades from MT5 history into `trades`.

    Read-only on MT5 (history_deals_get only). Groups deals by position_id (entry+exit), nets
    cost (net = pnl + commission + swap) and writes source='bot' rows for OUR magics only.
    Idempotent via insert_trade's ON CONFLICT(position_id, magic) upsert — an open snapshot flips
    to closed on a later pass. Returns (rows_written, newest_entry_ts).

    `mt5` is an already-initialized module handle: the loop owns ONE persistent connection
    (no per-call initialize/shutdown — per the IPC-flood lesson)."""
    now = time.time()
    deals = mt5.history_deals_get(int(now - days * 86400), int(now)) or []
    pos: dict[int, dict] = {}
    for d in deals:
        if d.position_id == 0 or not _is_our_bot(d.magic):
            continue
        p = pos.setdefault(d.position_id, {
            "in": None, "out": None, "magic": d.magic, "symbol": d.symbol,
            "pnl": 0.0, "commission": 0.0, "swap": 0.0})
        p["magic"] = d.magic or p["magic"]
        p["symbol"] = d.symbol or p["symbol"]
        if d.entry == 0:        # دخول
            p["in"] = d
        elif d.entry == 1:      # خروج
            p["out"] = d
        p["pnl"] += d.profit
        p["commission"] += d.commission
        p["swap"] += d.swap
    n = 0
    max_ts = 0.0
    for pid, p in pos.items():
        din, dout = p["in"], p["out"]
        if din is None:
            continue            # دخول خارج النافذة → نتخطّى لقطة منقوصة (مرآة migrate)
        net = p["pnl"] + p["commission"] + p["swap"]
        closed = 1 if dout is not None else 0
        hold = ((dout.time - din.time) / 60.0) if dout else None
        db.insert_trade(
            position_id=pid, ticket=din.ticket, magic=p["magic"], symbol=p["symbol"],
            ts=din.time, side=(1 if din.type == 0 else -1), lots=din.volume,
            entry=din.price, exit=(dout.price if dout else None),
            pnl=round(p["pnl"], 2), commission=round(p["commission"], 2),
            swap=round(p["swap"], 2), net=round(net, 2),
            win=(int(net > 0) if closed else None),
            hold_min=(round(hold, 1) if hold is not None else None),
            source=_classify_source(p["magic"]), closed=closed,
        )
        n += 1
        max_ts = max(max_ts, float(din.time))
    try:
        db.con.execute("PRAGMA wal_checkpoint(PASSIVE);")
    except Exception:
        pass
    return n, max_ts


def record_loop(db_path: Path | str = DB_PATH, *, days: float = 7.0,
                interval: float = 120.0, once: bool = False) -> int:
    """24/7 recorder: keep `trades` fresh from MT5 for OUR bot magics. Windowless under watchdog.
    ONE persistent MT5 connection (bare initialize → follows the running terminal's account = demo)."""
    try:
        import MetaTrader5 as mt5
    except Exception as e:
        print(f"[REC] MetaTrader5 unavailable: {e}", flush=True)
        return 1
    if not (mt5.initialize() or mt5.initialize()):
        print("[REC] mt5.initialize failed — terminal not reachable", flush=True)
        return 1
    db = FridayDB(db_path)
    print(f"[REC] trade recorder up — bot-only, {days:g}d window, every {interval:g}s "
          f"-> {Path(db_path)}", flush=True)
    try:
        while True:
            try:
                n, mx = record_recent_deals(db, mt5, days=days)
                mxs = datetime.fromtimestamp(mx, timezone.utc).isoformat() if mx else "—"
                print(f"[REC] upserted {n} bot trades · newest_entry={mxs}", flush=True)
            except Exception as e:
                print(f"[REC] err {type(e).__name__}: {e}", flush=True)
            if once:
                break
            time.sleep(interval)
    finally:
        try:
            db.close()
        finally:
            mt5.shutdown()
    return 0


# ---------------------------------------------------------------------------- cli
def _print_stats(db_path: Path | str = DB_PATH) -> None:
    db = FridayDB(db_path)
    c = db.counts()
    print(f"\nDB: {Path(db_path)}")
    print("table COUNTs:")
    for t, n in c.items():
        print(f"  {t:14s} {n}")
    db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="friday_db — SQLite backbone")
    ap.add_argument("--init", action="store_true", help="إنشاء السكيمة")
    ap.add_argument("--migrate", action="store_true", help="ترحيل مصادر JSON + history_deals")
    ap.add_argument("--stats", action="store_true", help="طباعة COUNT لكل جدول")
    ap.add_argument("--record-loop", action="store_true",
                    help="مُسجّل حيّ 24/7: يُبقي trades محدّثة من MT5 (بوتاتنا فقط)")
    ap.add_argument("--record-once", action="store_true", help="تمريرة تسجيل واحدة (للتحقّق)")
    ap.add_argument("--days", type=int, default=30, help="عدد أيام history_deals (للترحيل)")
    ap.add_argument("--window-days", type=float, default=7.0, help="نافذة المُسجّل الحيّ (أيام)")
    ap.add_argument("--interval", type=float, default=120.0, help="فترة حلقة المُسجّل (ثوانٍ)")
    ap.add_argument("--db", default=str(DB_PATH), help="مسار قاعدة البيانات")
    args = ap.parse_args()

    # المُسجّل الحيّ (حلقة أو تمريرة واحدة) — يُشغَّل تحت الوصيّ windowless.
    if args.record_loop or args.record_once:
        raise SystemExit(record_loop(args.db, days=args.window_days,
                                     interval=args.interval, once=args.record_once))

    if not (args.init or args.migrate or args.stats):
        ap.print_help()
        return

    if args.init:
        db = FridayDB(args.db)
        print(f"[init] schema created at {args.db}")
        db.close()

    if args.migrate:
        print(f"[migrate] importing sources -> {args.db}")
        rep = migrate(args.db, deal_days=args.days)
        print("[migrate] rows inserted by source:")
        for k, v in rep.items():
            print(f"  {v:6d}  {k}")

    if args.stats or args.migrate:
        _print_stats(args.db)


if __name__ == "__main__":
    main()
