"""gold_htf_trend.py — Track B step-1: higher-timeframe trend-following gold.

PURPOSE
-------
The ONLY profitable arm found in all prior FRIDAY testing was UNGATED gold
LONGS riding the 2024-2026 bull (PF ~1.03, +804 net after costs, on H1). That
edge is thin because H1 trades cluster near the ~$7 round-trip commission. This
module builds a PROPER trend-follower designed so winners DWARF friction:

  * Trend filter on a HIGHER timeframe (H4 or D1): EMA50 > EMA200 (and/or a
    Donchian breakout) — only trade WITH the dominant trend.
  * Entry on an H1 pullback-then-resume: price pulls back toward EMA20 in the
    uptrend, then resumes (H1 close back above EMA20 / above the prior swing).
  * Stop is STRUCTURE-based: just beyond the most recent swing low (longs) —
    NOT a fixed pip stop — so the stop sits where the trade thesis is wrong.
  * Target is WIDE: a fixed R-multiple (default 3R-5R) OR a Chandelier trailing
    stop (ATR-based) so a runner can capture the multi-hundred-dollar legs that
    make trend following pay. TP measured in dollars-per-lot far above the ~$7
    round-trip friction.
  * Position sizing is ATR-based: risk a fixed $ per trade, lot = risk$ / (SL
    distance in points * point_value). Friction is charged on EVERY trade via
    runtime.shared.cost_model.round_trip_cost (NEVER reported gross).
  * Optional COT gate (runtime.shared.cot_signal.supply_long_ok / _short_ok),
    as-of the last report on or before the bar — strictly causal.

SCIENTIFIC DISCIPLINE (non-negotiable)
--------------------------------------
  * STRICTLY CAUSAL. Every decision on bar i uses ONLY closed data <= bar i.
    The higher-TF trend value applied to an H1 bar is the last HTF bar that
    CLOSED at or before that H1 bar's open time (HTF "as-of", never future).
    Indicators (EMA/ATR/Donchian/swing) at bar i use bars [.. i] only; entries
    fire at the OPEN of bar i+1 (no same-bar look-ahead on the signal close).
  * COT as-of: cot_signal already returns the last report <= dt; we pass the
    bar's timestamp, never a future one.
  * NET after costs. Each closed trade subtracts round_trip_cost(symbol, lot,
    entry_price). We report trades / win_rate / profit_factor / net / max_dd
    on the NET equity curve. A strategy is "real" only if PF>1 AND net>0.

DATA
----
Primary source is MT5 (matches runtime.oos_backtest convention):
    mt5.copy_rates_range(symbol, TF, since, now).
If the MT5 terminal IPC is unavailable, we fall back to a local CSV cache under
data/htf_cache/<SYMBOL>_<TF>.csv with columns: time(ISO or epoch),open,high,
low,close[,volume]. The cache lets the backtest run (on REAL bars previously
persisted) even when the terminal is closed. The loader is source-agnostic and
returns plain numpy arrays, so the strategy core never knows where bars came
from.

PUBLIC API
----------
    load_bars(symbol, timeframe, days=..., source="auto") -> Bars
    backtest(symbol, cfg=Config(), days=..., bars_h1=None, bars_htf=None) -> dict
    Config(...)  — all knobs (see dataclass).

This module is READ-ONLY w.r.t. live state. It never sends orders, never writes
live_genome__*.json, never touches unified_trader. The only files it may write
are CSV caches under data/htf_cache/ (and only via the explicit cache helper).
"""
from __future__ import annotations

import csv
import math
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

# ─────────────────────────── paths / root ──────────────────────────────────
_HERE = Path(__file__).resolve()
# <ROOT>/runtime/gold_htf_trend.py  ->  ROOT == C:\Users\Radhi\MT5\r_native_v2
ROOT = _HERE.parent.parent if (_HERE.parent.parent / "runtime").exists() else Path(
    r"C:\Users\Radhi\MT5\r_native_v2"
)
DATA = ROOT / "data"
CACHE_DIR = DATA / "htf_cache"

# Make `runtime.shared.*` importable whether run as a module or a script.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─────────────────────────── cost model (reuse) ────────────────────────────
try:
    from runtime.shared.cost_model import round_trip_cost as _round_trip_cost
    _COST_OK = True
except Exception:  # pragma: no cover - fallback keeps the module importable
    _COST_OK = False

    def _round_trip_cost(symbol: str, lot: float, price: float) -> float:
        # Conservative XAU-ish fallback: spread+commission+slippage ~ $7/0.10lot.
        # Scales with lot; mild notional term for commission.
        return 70.0 * lot + (lot * 100.0 * price) * 0.000218


# ─────────────────────────── COT gate (reuse, optional) ────────────────────
try:
    from runtime.shared.cot_signal import supply_long_ok as _cot_long_ok
    from runtime.shared.cot_signal import supply_short_ok as _cot_short_ok
    _COT_OK = True
except Exception:  # pragma: no cover
    _COT_OK = False

    def _cot_long_ok(symbol, dt):  # type: ignore
        return True, "cot_signal unavailable -> gate disabled"

    def _cot_short_ok(symbol, dt):  # type: ignore
        return True, "cot_signal unavailable -> gate disabled"


# ─────────────────────────── MetaTrader5 (optional) ────────────────────────
try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:  # pragma: no cover
    mt5 = None


# ════════════════════════════════════════════════════════════════════════════
# Data container
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Bars:
    """Plain OHLC series. times are tz-aware UTC datetimes (len == n)."""

    symbol: str
    timeframe: str
    time: np.ndarray   # object array of datetime (UTC)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    source: str = "unknown"

    def __len__(self) -> int:
        return int(self.close.shape[0])


# Timeframe string -> (minutes, MT5 const name)
_TF_MINUTES = {
    "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}


def _mt5_tf(timeframe: str):
    if mt5 is None:
        return None
    name = {
        "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
        "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1",
    }.get(timeframe)
    return getattr(mt5, name, None) if name else None


# ════════════════════════════════════════════════════════════════════════════
# Data loading: MT5 primary, CSV cache fallback
# ════════════════════════════════════════════════════════════════════════════
def _bars_from_mt5(symbol: str, timeframe: str, days: int) -> Optional[Bars]:
    if mt5 is None:
        return None
    tf = _mt5_tf(timeframe)
    if tf is None:
        return None
    if not mt5.initialize():
        return None
    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        rates = mt5.copy_rates_range(symbol, tf, start, now)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
    if rates is None or len(rates) == 0:
        return None
    t = np.array(
        [datetime.fromtimestamp(int(r["time"]), tz=timezone.utc) for r in rates],
        dtype=object,
    )
    return Bars(
        symbol=symbol, timeframe=timeframe, time=t,
        open=np.array([r["open"] for r in rates], dtype=float),
        high=np.array([r["high"] for r in rates], dtype=float),
        low=np.array([r["low"] for r in rates], dtype=float),
        close=np.array([r["close"] for r in rates], dtype=float),
        source="mt5",
    )


def _cache_path(symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{symbol}_{timeframe}.csv"


def _parse_time(s: str) -> datetime:
    s = s.strip()
    # epoch ms or s
    if s.isdigit():
        v = int(s)
        if v > 10_000_000_000:  # ms
            v //= 1000
        return datetime.fromtimestamp(v, tz=timezone.utc)
    # ISO
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bars_from_cache(symbol: str, timeframe: str, days: Optional[int]) -> Optional[Bars]:
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return None
    times, o, h, l, c = [], [], [], [], []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        # normalise header names
        fields = {k.lower().strip(): k for k in (reader.fieldnames or [])}
        def col(*names):
            for n in names:
                if n in fields:
                    return fields[n]
            return None
        tk = col("time", "t", "date", "datetime")
        ok_, hk, lk, ck = col("open", "o"), col("high", "h"), col("low", "l"), col("close", "c")
        if not all([tk, ok_, hk, lk, ck]):
            return None
        for row in reader:
            try:
                times.append(_parse_time(str(row[tk])))
                o.append(float(row[ok_])); h.append(float(row[hk]))
                l.append(float(row[lk])); c.append(float(row[ck]))
            except (ValueError, KeyError, TypeError):
                continue
    if not times:
        return None
    idx = np.argsort(np.array([t.timestamp() for t in times]))
    t = np.array(times, dtype=object)[idx]
    o = np.array(o)[idx]; h = np.array(h)[idx]; l = np.array(l)[idx]; c = np.array(c)[idx]
    if days is not None and len(t) > 0:
        cutoff = t[-1] - timedelta(days=days)
        mask = np.array([x >= cutoff for x in t])
        t, o, h, l, c = t[mask], o[mask], h[mask], l[mask], c[mask]
    return Bars(symbol=symbol, timeframe=timeframe, time=t,
                open=o, high=h, low=l, close=c, source="cache")


def save_cache(bars: Bars) -> Path:
    """Persist a Bars series to the CSV cache so it can be replayed offline."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(bars.symbol, bars.timeframe)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close"])
        for i in range(len(bars)):
            w.writerow([
                bars.time[i].astimezone(timezone.utc).isoformat(),
                f"{bars.open[i]:.5f}", f"{bars.high[i]:.5f}",
                f"{bars.low[i]:.5f}", f"{bars.close[i]:.5f}",
            ])
    return path


def load_bars(symbol: str, timeframe: str, days: int = 480,
              source: str = "auto") -> Optional[Bars]:
    """Load OHLC. source: 'mt5' | 'cache' | 'auto' (mt5 then cache)."""
    if source in ("auto", "mt5"):
        b = _bars_from_mt5(symbol, timeframe, days)
        if b is not None and len(b) > 0:
            return b
        if source == "mt5":
            return None
    return _bars_from_cache(symbol, timeframe, days)


# ════════════════════════════════════════════════════════════════════════════
# Indicators (all strictly causal: value[i] uses bars[..i] only)
# ════════════════════════════════════════════════════════════════════════════
def ema(values: np.ndarray, period: int) -> np.ndarray:
    n = len(values)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    k = 2.0 / (period + 1.0)
    out[0] = values[0]
    for i in range(1, n):
        out[i] = values[i] * k + out[i - 1] * (1.0 - k)
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    if n == 0:
        return out
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    # Wilder's smoothing
    if n <= period:
        # not enough bars: running mean
        for i in range(n):
            out[i] = np.mean(tr[: i + 1])
        return out
    out[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def donchian_high(high: np.ndarray, period: int) -> np.ndarray:
    """Highest high of the PRIOR `period` bars (exclusive of current bar)."""
    n = len(high)
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(0, i - period)
        if i - lo > 0:
            out[i] = np.max(high[lo:i])
    return out


def donchian_low(low: np.ndarray, period: int) -> np.ndarray:
    n = len(low)
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(0, i - period)
        if i - lo > 0:
            out[i] = np.min(low[lo:i])
    return out


def swing_low(low: np.ndarray, i: int, lookback: int) -> float:
    """Lowest low of the last `lookback` bars up to and including i."""
    lo = max(0, i - lookback + 1)
    return float(np.min(low[lo:i + 1]))


def swing_high(high: np.ndarray, i: int, lookback: int) -> float:
    lo = max(0, i - lookback + 1)
    return float(np.max(high[lo:i + 1]))


# ════════════════════════════════════════════════════════════════════════════
# Strategy configuration
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Config:
    # --- trend filter (higher timeframe) ---
    htf: str = "H4"                 # higher timeframe for the trend filter
    trend_mode: str = "ema"         # "ema" | "donchian" | "both"
    ema_fast: int = 50              # HTF fast EMA
    ema_slow: int = 200             # HTF slow EMA
    donchian_htf: int = 20          # HTF Donchian breakout lookback

    # --- entry (H1 pullback-then-resume) ---
    entry_tf: str = "H1"
    pullback_ema: int = 20          # H1 EMA the price must pull back toward
    pullback_atr_mult: float = 1.0  # "near" EMA = within this * ATR
    require_resume: bool = True     # require H1 close back across EMA20 (resume)
    swing_lookback: int = 10        # bars to define the structural swing

    # --- risk / stop / target ---
    atr_period: int = 14
    sl_swing_buffer_atr: float = 0.5  # SL = swingLow - buffer*ATR (longs)
    sl_min_atr: float = 1.0           # floor on SL distance (in ATR)
    tp_mode: str = "rr"               # "rr" (fixed R-multiple) | "chandelier"
    rr_target: float = 4.0            # TP = entry + rr_target * risk  (longs)
    chandelier_atr_mult: float = 3.0  # trailing stop = highestHigh - mult*ATR
    chandelier_lookback: int = 22

    # --- position sizing (ATR risk) ---
    risk_dollars: float = 10.0        # $ risked per trade
    min_lot: float = 0.01
    max_lot: float = 1.00
    lot_step: float = 0.01

    # --- direction & gates ---
    allow_long: bool = True
    allow_short: bool = False         # bull-trend insight => longs by default
    use_cot_gate: bool = False        # optional COT confirmation (causal)

    # --- execution realism ---
    one_position_at_a_time: bool = True
    max_hold_bars: int = 0            # 0 = no time stop


# ════════════════════════════════════════════════════════════════════════════
# HTF "as-of" alignment (strictly causal: no future HTF info on an H1 bar)
# ════════════════════════════════════════════════════════════════════════════
def _asof_index(htf_time: np.ndarray, ts: datetime) -> int:
    """Index of the last HTF bar whose CLOSE time is <= ts.

    A bar at htf_time[k] for an H-hour timeframe closes at htf_time[k] + Hh.
    We treat the bar as 'known' only once it has closed, so the as-of bar is the
    last one with (open_time + tf_duration) <= ts. Returns -1 if none.
    """
    # binary search on close-times
    lo, hi, res = 0, len(htf_time) - 1, -1
    # close time per HTF bar derived below by caller via _tf_delta
    while lo <= hi:
        mid = (lo + hi) // 2
        if htf_time[mid] <= ts:
            res = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return res


def _tf_delta(timeframe: str) -> timedelta:
    return timedelta(minutes=_TF_MINUTES.get(timeframe, 60))


# ════════════════════════════════════════════════════════════════════════════
# Backtest core
# ════════════════════════════════════════════════════════════════════════════
def _round_lot(lot: float, cfg: Config) -> float:
    lot = max(cfg.min_lot, min(cfg.max_lot, lot))
    steps = round(lot / cfg.lot_step)
    return max(cfg.min_lot, steps * cfg.lot_step)


def backtest(symbol: str, cfg: Optional[Config] = None, days: int = 480,
             bars_h1: Optional[Bars] = None, bars_htf: Optional[Bars] = None) -> dict:
    """Run the HTF trend-follower. Returns a results dict (NET, after costs)."""
    cfg = cfg or Config()

    if bars_h1 is None:
        bars_h1 = load_bars(symbol, cfg.entry_tf, days=days)
    if bars_htf is None:
        bars_htf = load_bars(symbol, cfg.htf, days=days + 90)  # extra warmup

    if bars_h1 is None or len(bars_h1) < 250:
        return {"error": f"insufficient {cfg.entry_tf} bars for {symbol}",
                "trades": 0, "data_source": getattr(bars_h1, "source", None)}
    if bars_htf is None or len(bars_htf) < 60:
        return {"error": f"insufficient {cfg.htf} bars for {symbol}",
                "trades": 0, "data_source": getattr(bars_htf, "source", None)}

    H = bars_h1
    n = len(H)

    # --- H1 indicators (causal) ---
    h1_ema_pb = ema(H.close, cfg.pullback_ema)
    h1_atr = atr(H.high, H.low, H.close, cfg.atr_period)

    # --- HTF indicators (causal) + close-time array for as-of alignment ---
    htf_close_time = np.array(
        [bars_htf.time[k] + _tf_delta(cfg.htf) for k in range(len(bars_htf))],
        dtype=object,
    )
    htf_ema_fast = ema(bars_htf.close, cfg.ema_fast)
    htf_ema_slow = ema(bars_htf.close, cfg.ema_slow)
    htf_don_hi = donchian_high(bars_htf.high, cfg.donchian_htf)
    htf_don_lo = donchian_low(bars_htf.low, cfg.donchian_htf)

    def htf_trend(ts: datetime) -> int:
        """+1 up, -1 down, 0 none — using only HTF bars closed at/before ts."""
        k = _asof_index(htf_close_time, ts)
        if k < 0:
            return 0
        up = down = False
        if cfg.trend_mode in ("ema", "both"):
            ef, es = htf_ema_fast[k], htf_ema_slow[k]
            if np.isnan(ef) or np.isnan(es):
                return 0
            up_e, down_e = ef > es, ef < es
        else:
            up_e = down_e = None
        if cfg.trend_mode in ("donchian", "both"):
            price = bars_htf.close[k]
            dh, dl = htf_don_hi[k], htf_don_lo[k]
            up_d = (not np.isnan(dh)) and price >= dh
            down_d = (not np.isnan(dl)) and price <= dl
        else:
            up_d = down_d = None

        if cfg.trend_mode == "ema":
            up, down = up_e, down_e
        elif cfg.trend_mode == "donchian":
            up, down = up_d, down_d
        else:  # both -> EMA defines regime, breakout confirms momentum
            up = bool(up_e) and (up_d or True)  # EMA regime; donchian as soft
            down = bool(down_e)
            up = bool(up_e); down = bool(down_e)
            if up_d is not None:
                up = up and (up_d or htf_don_hi[k] is not None)
        if up and not down:
            return 1
        if down and not up:
            return -1
        return 0

    # --- trade loop ---
    trades = []
    equity = 0.0
    equity_curve = [0.0]
    peak = 0.0
    max_dd = 0.0

    in_pos = False
    side = 0
    entry_px = entry_i = 0
    sl = tp = 0.0
    lot = 0.0
    chand_extreme = 0.0  # highest-high (long) / lowest-low (short) since entry

    # decide on bar i (closed), act at open of i+1
    for i in range(max(cfg.ema_slow, cfg.pullback_ema, cfg.atr_period) + 2, n - 1):
        a = h1_atr[i]
        if np.isnan(a) or a <= 0:
            continue

        # ---------- manage open position on bar i+1 path ----------
        if in_pos:
            nxt = i + 1
            hi_, lo_, cl_ = H.high[nxt], H.low[nxt], H.close[nxt]
            # update chandelier trail BEFORE checking exits using prior extreme
            exit_px = None
            reason = ""
            if side == 1:
                # check stop then target within the bar (stop-first = conservative)
                if lo_ <= sl:
                    exit_px, reason = sl, "stop"
                elif cfg.tp_mode == "rr" and hi_ >= tp:
                    exit_px, reason = tp, "target"
                else:
                    # update chandelier and trail the stop up
                    chand_extreme = max(chand_extreme, hi_)
                    if cfg.tp_mode == "chandelier":
                        new_sl = chand_extreme - cfg.chandelier_atr_mult * h1_atr[nxt] \
                            if not np.isnan(h1_atr[nxt]) else sl
                        sl = max(sl, new_sl)
            else:  # short
                if hi_ >= sl:
                    exit_px, reason = sl, "stop"
                elif cfg.tp_mode == "rr" and lo_ <= tp:
                    exit_px, reason = tp, "target"
                else:
                    chand_extreme = min(chand_extreme, lo_)
                    if cfg.tp_mode == "chandelier":
                        new_sl = chand_extreme + cfg.chandelier_atr_mult * h1_atr[nxt] \
                            if not np.isnan(h1_atr[nxt]) else sl
                        sl = min(sl, new_sl)

            # time stop
            if exit_px is None and cfg.max_hold_bars and (nxt - entry_i) >= cfg.max_hold_bars:
                exit_px, reason = cl_, "time"

            if exit_px is not None:
                gross = (exit_px - entry_px) * lot * _point_contract(symbol) if side == 1 \
                    else (entry_px - exit_px) * lot * _point_contract(symbol)
                cost = _round_trip_cost(symbol, lot, entry_px)
                net = gross - cost
                equity += net
                trades.append({
                    "entry_time": str(H.time[entry_i]), "exit_time": str(H.time[nxt]),
                    "side": "long" if side == 1 else "short",
                    "entry": round(float(entry_px), 3), "exit": round(float(exit_px), 3),
                    "lot": round(float(lot), 2), "gross": round(float(gross), 2),
                    "cost": round(float(cost), 2), "net": round(float(net), 2),
                    "reason": reason,
                })
                equity_curve.append(equity)
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
                in_pos = False
                side = 0
                continue  # one action per bar

        # ---------- look for an entry decided on bar i ----------
        if in_pos and cfg.one_position_at_a_time:
            continue

        trend = htf_trend(H.time[i])  # as-of: only HTF bars closed <= H1 open[i]
        if trend == 0:
            continue

        pb = h1_ema_pb[i]
        if np.isnan(pb):
            continue

        long_setup = (
            cfg.allow_long and trend == 1
            # pulled back near EMA20 recently
            and (H.low[i] <= pb + cfg.pullback_atr_mult * a)
            # resume: this bar closes back above the pullback EMA
            and (not cfg.require_resume or H.close[i] > pb)
            and H.close[i] > H.open[i]  # bullish resume bar
        )
        short_setup = (
            cfg.allow_short and trend == -1
            and (H.high[i] >= pb - cfg.pullback_atr_mult * a)
            and (not cfg.require_resume or H.close[i] < pb)
            and H.close[i] < H.open[i]
        )

        if not (long_setup or short_setup):
            continue

        # COT confirmation (optional, causal: as-of bar time)
        if cfg.use_cot_gate:
            if long_setup:
                ok, _ = _cot_long_ok(symbol, H.time[i])
                if not ok:
                    continue
            if short_setup:
                ok, _ = _cot_short_ok(symbol, H.time[i])
                if not ok:
                    continue

        # entry at next bar OPEN (no same-bar look-ahead)
        e_i = i + 1
        e_px = H.open[e_i]

        if long_setup:
            struct = swing_low(H.low, i, cfg.swing_lookback)
            raw_sl = struct - cfg.sl_swing_buffer_atr * a
            sl_dist = e_px - raw_sl
            min_dist = cfg.sl_min_atr * a
            if sl_dist < min_dist:
                sl_dist = min_dist
                raw_sl = e_px - sl_dist
            if sl_dist <= 0:
                continue
            side_new = 1
            sl_new = raw_sl
            tp_new = e_px + cfg.rr_target * sl_dist
            chand_extreme = H.high[e_i]
        else:
            struct = swing_high(H.high, i, cfg.swing_lookback)
            raw_sl = struct + cfg.sl_swing_buffer_atr * a
            sl_dist = raw_sl - e_px
            min_dist = cfg.sl_min_atr * a
            if sl_dist < min_dist:
                sl_dist = min_dist
                raw_sl = e_px + sl_dist
            if sl_dist <= 0:
                continue
            side_new = -1
            sl_new = raw_sl
            tp_new = e_px - cfg.rr_target * sl_dist
            chand_extreme = H.low[e_i]

        # ATR position sizing: risk_dollars / (sl_dist * dollar-per-price-unit/lot)
        dpp = _point_contract(symbol)  # $ per 1.0 price unit per 1.0 lot
        risk_per_lot = sl_dist * dpp
        if risk_per_lot <= 0:
            continue
        lot_new = _round_lot(cfg.risk_dollars / risk_per_lot, cfg)

        in_pos = True
        side = side_new
        entry_px = e_px
        entry_i = e_i
        sl = sl_new
        tp = tp_new
        lot = lot_new

    return _summarize(symbol, cfg, bars_h1, bars_htf, trades, equity_curve, max_dd)


def _point_contract(symbol: str) -> float:
    """Dollars per 1.0 price-unit move per 1.0 lot (USD account).

    Derived from cost_model's SymbolCost where available so sizing and friction
    use the SAME contract spec. point_value = point * contract_size is $/point;
    dollars per 1.0 price-unit = point_value / point = contract_size.
    """
    try:
        from runtime.shared.cost_model import _profile  # type: ignore
        return float(_profile(symbol).contract_size)
    except Exception:
        s = symbol.upper()
        if "XAU" in s or "GOLD" in s:
            return 100.0
        if "BTC" in s:
            return 1.0
        return 100000.0


def _summarize(symbol, cfg, bars_h1, bars_htf, trades, equity_curve, max_dd) -> dict:
    n_tr = len(trades)
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] <= 0]
    gross_win = sum(t["net"] for t in wins)
    gross_loss = -sum(t["net"] for t in losses)
    net = sum(t["net"] for t in trades)
    total_cost = sum(t["cost"] for t in trades)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    wr = (len(wins) / n_tr) if n_tr else 0.0
    avg_win = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 0.0

    period = None
    if len(bars_h1):
        period = f"{bars_h1.time[0]} .. {bars_h1.time[-1]}"

    return {
        "symbol": symbol,
        "config": asdict(cfg),
        "data_source_h1": bars_h1.source,
        "data_source_htf": bars_htf.source,
        "h1_bars": len(bars_h1),
        "htf_bars": len(bars_htf),
        "period_utc": period,
        "trades": n_tr,
        "win_rate": round(wr, 4),
        "profit_factor": round(pf, 4) if pf != float("inf") else "inf",
        "net": round(net, 2),
        "total_costs": round(total_cost, 2),
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(-gross_loss, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(max_dd, 2),
        "cost_model": "shared.cost_model" if _COST_OK else "fallback",
        "verdict_real": bool(net > 0 and (pf == float("inf") or pf > 1.0) and n_tr >= 10),
        "sample_trades": trades[:5],
        "last_trades": trades[-3:],
    }


# ════════════════════════════════════════════════════════════════════════════
# Self-test
# ════════════════════════════════════════════════════════════════════════════
def _selftest() -> int:
    sym = "XAUUSDm"
    print("=" * 76)
    print("gold_htf_trend.py self-test —", sym)
    print("=" * 76)
    print(f"ROOT={ROOT}")
    print(f"cost_model loaded : {_COST_OK}   cot_signal loaded : {_COT_OK}")
    print(f"MT5 module        : {'present' if mt5 is not None else 'absent'}")
    print(f"cache dir         : {CACHE_DIR}  exists={CACHE_DIR.exists()}")

    h1 = load_bars(sym, "H1", days=480, source="auto")
    h4 = load_bars(sym, "H4", days=560, source="auto")
    if h1 is None or h4 is None:
        print("\n[FATAL] could not load real H1/H4 bars from MT5 or cache.")
        print("        Open the MT5 terminal (auto-trading enabled) OR populate")
        print(f"        {CACHE_DIR} with {sym}_H1.csv and {sym}_H4.csv.")
        return 2
    print(f"\nH1 bars: {len(h1)} from {h1.source}   ({h1.time[0]} .. {h1.time[-1]})")
    print(f"H4 bars: {len(h4)} from {h4.source}   ({h4.time[0]} .. {h4.time[-1]})")

    # Default config: H4 EMA50>EMA200 trend, H1 pullback-to-EMA20 resume, 4R TP.
    cfg = Config(htf="H4", trend_mode="ema", rr_target=4.0, risk_dollars=10.0,
                 allow_long=True, allow_short=False, use_cot_gate=False)
    res = backtest(sym, cfg=cfg, bars_h1=h1, bars_htf=h4)

    print("\n--- RESULTS (NET, after cost_model friction) ---")
    for k in ("trades", "win_rate", "profit_factor", "net", "total_costs",
              "gross_profit", "gross_loss", "avg_win", "avg_loss",
              "max_drawdown", "verdict_real"):
        print(f"  {k:14s}: {res.get(k)}")
    if res.get("sample_trades"):
        print("\n  sample trades:")
        for t in res["sample_trades"]:
            print("   ", t)

    n = res.get("trades", 0)
    if isinstance(n, int) and n > 0:
        print(f"\n[OK] strategy generated {n} trades on REAL {sym} data "
              f"(h1 source={h1.source}).")
        return 0
    print("\n[WARN] zero trades generated — loosen filters or check data.")
    return 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
