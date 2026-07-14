"""shared/cot_signal.py — Commitments of Traders (COT) signal / gate module.

Consumes ``data/cot_index.json`` (produced by ``cot_fetch.py``) and turns the
weekly COT positioning into a directional gate for supply/demand-zone trades.

Schema expected (the producer's contract)::

    {
      "GOLD": [
        {"date": "2026-05-27", "comm_state": "BEARISH", "retail_state": "BULLISH",
         "comm_index": 12.4, "retail_index": 88.1},
        ...
      ],
      "EURO FX": [ ... ],
      "BRITISH POUND": [ ... ]
    }

  - ``state`` ∈ {BULLISH, BEARISH, NEUTRAL}
  - ``comm_*``  = commercials (the "smart money" / hedgers)
  - ``retail_*``= small speculators / retail (the "dumb money")

The PDF "Golden Rule" for trading supply/demand zones:

  * SHORT a SUPPLY zone only when commercials are BEARISH and retail is BULLISH
    (smart money selling into retail buying → fade the crowd, sell the rally).
  * LONG a DEMAND zone only when commercials are BULLISH and retail is BEARISH
    (mirror image).

Design notes
------------
* Stdlib + json only — no third-party deps, importable from anywhere.
* Graceful by construction: every public function returns ``None`` / ``False``
  (never raises) when data is missing, stale-shaped, or the symbol is unmapped.
  The gate helpers return ``(bool, reason)`` so callers can log *why* a trade
  was vetoed.
* Reads are cached in-memory with an mtime check so a freshly-written
  ``cot_index.json`` is picked up without a process restart.

Run the self-test::

    C:\\Users\\Radhi\\MT5\\.venv\\Scripts\\python.exe ^
        C:\\Users\\Radhi\\MT5\\r_native_v2\\runtime\\shared\\cot_signal.py
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Optional, Tuple

# ─────────────────────────────────────────────────────────────────
# PATHS — mirror the resolution used in tokens.py / agent_governance.py
# <ROOT>/runtime/shared/cot_signal.py  →  ROOT == C:\Users\Radhi\MT5\r_native_v2
# ─────────────────────────────────────────────────────────────────
_detected = Path(__file__).resolve().parent.parent.parent
ROOT = _detected if (_detected / "runtime").exists() else Path(r"C:\Users\Radhi\MT5\r_native_v2")
DATA = ROOT / "data"
COT_INDEX_FILE = DATA / "cot_index.json"

# ─────────────────────────────────────────────────────────────────
# SYMBOL → COT MARKET MAP
# Keys are our broker symbols; values are the COT market names as keyed in
# cot_index.json. Extend here as new instruments get COT coverage.
# ─────────────────────────────────────────────────────────────────
SYMBOL_TO_MARKET = {
    "XAUUSDm": "GOLD",
    "EURUSDm": "EURO FX",
    "GBPUSDm": "BRITISH POUND",
}

_BULLISH = "BULLISH"
_BEARISH = "BEARISH"
_NEUTRAL = "NEUTRAL"
_VALID_STATES = (_BULLISH, _BEARISH, _NEUTRAL)

# In-memory cache: (parsed_dict, source_mtime). Invalidated when the file's
# mtime changes so a re-fetched index is picked up without a restart.
_CACHE: dict = {"data": None, "mtime": None}


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────
def _coerce_date(dt) -> Optional[_dt.date]:
    """Normalise dt/datetime/ISO-string to a ``date``. None on failure."""
    if dt is None:
        return None
    if isinstance(dt, _dt.datetime):
        return dt.date()
    if isinstance(dt, _dt.date):
        return dt
    if isinstance(dt, str):
        s = dt.strip()
        if not s:
            return None
        # Accept "YYYY-MM-DD" and full ISO timestamps.
        try:
            return _dt.date.fromisoformat(s[:10])
        except ValueError:
            try:
                return _dt.datetime.fromisoformat(s).date()
            except ValueError:
                return None
    return None


def _load_index() -> Optional[dict]:
    """Load + cache cot_index.json. Returns dict, or None if unavailable/bad."""
    try:
        mtime = COT_INDEX_FILE.stat().st_mtime
    except OSError:
        # File missing or unreadable.
        _CACHE["data"] = None
        _CACHE["mtime"] = None
        return None

    if _CACHE["data"] is not None and _CACHE["mtime"] == mtime:
        return _CACHE["data"]

    try:
        raw = COT_INDEX_FILE.read_text(encoding="utf-8-sig")
        parsed = json.loads(raw)
    except (OSError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    _CACHE["data"] = parsed
    _CACHE["mtime"] = mtime
    return parsed


def _normalise_state(value) -> str:
    """Map any raw state value to one of the valid uppercase states."""
    if isinstance(value, str):
        v = value.strip().upper()
        if v in _VALID_STATES:
            return v
    return _NEUTRAL


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────
def cot_state(symbol: str, dt) -> Optional[dict]:
    """Return the most-recent COT week on or before ``dt`` for ``symbol``.

    Returns a dict::

        {"comm_state": str, "retail_state": str,
         "comm_index": float|None, "retail_index": float|None,
         "date": "YYYY-MM-DD", "market": str}

    or ``None`` when:
      * the symbol is not mapped to a COT market,
      * the index file is missing / malformed,
      * the market has no rows, or
      * no row falls on or before ``dt``.
    """
    market = SYMBOL_TO_MARKET.get(symbol)
    if market is None:
        return None

    target = _coerce_date(dt)
    if target is None:
        return None

    index = _load_index()
    if index is None:
        return None

    rows = index.get(market)
    if not isinstance(rows, list) or not rows:
        return None

    # Find the most recent row with date <= target.
    best_row = None
    best_date: Optional[_dt.date] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        rdate = _coerce_date(row.get("date"))
        if rdate is None or rdate > target:
            continue
        if best_date is None or rdate > best_date:
            best_date = rdate
            best_row = row

    if best_row is None or best_date is None:
        return None

    def _num(key):
        val = best_row.get(key)
        if isinstance(val, (int, float)):
            return float(val)
        return None

    return {
        "comm_state": _normalise_state(best_row.get("comm_state")),
        "retail_state": _normalise_state(best_row.get("retail_state")),
        "comm_index": _num("comm_index"),
        "retail_index": _num("retail_index"),
        "date": best_date.isoformat(),
        "market": market,
    }


def supply_short_ok(symbol: str, dt) -> Tuple[bool, str]:
    """Golden Rule gate for SHORTING a supply zone.

    True iff commercials are BEARISH and retail is BULLISH.

    Returns ``(ok, reason)``. ``ok`` is always a plain bool; ``reason`` is a
    short human-readable explanation suitable for the decision log.
    """
    st = cot_state(symbol, dt)
    if st is None:
        return False, f"no COT data for {symbol} on/before {dt}"

    comm = st["comm_state"]
    retail = st["retail_state"]
    if comm == _BEARISH and retail == _BULLISH:
        return True, (
            f"COT[{st['market']} {st['date']}] comm={comm} retail={retail} "
            f"→ smart money selling into retail buying (short OK)"
        )
    return False, (
        f"COT[{st['market']} {st['date']}] comm={comm} retail={retail} "
        f"→ need comm=BEARISH & retail=BULLISH for supply short"
    )


def supply_long_ok(symbol: str, dt) -> Tuple[bool, str]:
    """Mirror Golden Rule gate for LONGING a demand zone.

    True iff commercials are BULLISH and retail is BEARISH.

    Returns ``(ok, reason)``.
    """
    st = cot_state(symbol, dt)
    if st is None:
        return False, f"no COT data for {symbol} on/before {dt}"

    comm = st["comm_state"]
    retail = st["retail_state"]
    if comm == _BULLISH and retail == _BEARISH:
        return True, (
            f"COT[{st['market']} {st['date']}] comm={comm} retail={retail} "
            f"→ smart money buying into retail selling (long OK)"
        )
    return False, (
        f"COT[{st['market']} {st['date']}] comm={comm} retail={retail} "
        f"→ need comm=BULLISH & retail=BEARISH for demand long"
    )


# ─────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────
def _selftest() -> None:
    print("=" * 68)
    print("cot_signal.py self-test")
    print("=" * 68)
    print(f"ROOT           : {ROOT}")
    print(f"COT index file : {COT_INDEX_FILE}")
    print(f"file exists    : {COT_INDEX_FILE.exists()}")
    print(f"symbol map     : {SYMBOL_TO_MARKET}")

    index = _load_index()
    if index is None:
        print("\n[WARN] cot_index.json missing or unreadable — exercising the")
        print("       graceful-degradation paths with synthetic data instead.\n")
        _selftest_synthetic()
        return

    sym = "XAUUSDm"
    print(f"\nLive data found. Probing {sym} on a few recent dates:\n")
    today = _dt.date.today()
    probe_dates = [today - _dt.timedelta(days=off) for off in (0, 7, 14, 30, 90)]
    for d in probe_dates:
        _report(sym, d)

    print("\n[also testing other mapped symbols on today]")
    for sym in ("EURUSDm", "GBPUSDm", "UNMAPPEDm"):
        _report(sym, today)


def _report(symbol: str, d) -> None:
    st = cot_state(symbol, d)
    short_ok, short_why = supply_short_ok(symbol, d)
    long_ok, long_why = supply_long_ok(symbol, d)
    print(f"  {symbol} @ {d}")
    print(f"     state        : {st}")
    print(f"     supply_short : {short_ok:<5}  ({short_why})")
    print(f"     supply_long  : {long_ok:<5}  ({long_why})")


def _selftest_synthetic() -> None:
    """Inject a synthetic index into the cache to prove the logic end-to-end
    without needing cot_fetch.py to have run yet."""
    global _CACHE
    synthetic = {
        "GOLD": [
            {"date": "2026-05-13", "comm_state": "NEUTRAL", "retail_state": "NEUTRAL",
             "comm_index": 50.0, "retail_index": 50.0},
            {"date": "2026-05-20", "comm_state": "BEARISH", "retail_state": "BULLISH",
             "comm_index": 11.2, "retail_index": 89.4},   # short-supply trigger
            {"date": "2026-05-27", "comm_state": "BULLISH", "retail_state": "BEARISH",
             "comm_index": 92.0, "retail_index": 8.5},     # long-demand trigger
        ],
        "EURO FX": [
            {"date": "2026-05-27", "comm_state": "NEUTRAL", "retail_state": "NEUTRAL",
             "comm_index": 47.0, "retail_index": 53.0},
        ],
    }
    # Force the cache to hold our synthetic data (mtime sentinel that won't
    # match any real file stat, but data is non-None so it's returned as-is).
    _CACHE = {"data": synthetic, "mtime": "__synthetic__"}

    def _coerce_state_cache():  # noqa: D401 - tiny shim
        return synthetic

    # Temporarily monkeypatch _load_index so the public API uses synthetic data.
    global _load_index
    _orig_load = _load_index
    _load_index = _coerce_state_cache  # type: ignore[assignment]
    try:
        print("Synthetic GOLD timeline: 05-13 NEUTRAL | 05-20 short-trigger | 05-27 long-trigger\n")
        sym = "XAUUSDm"
        for d in ("2026-05-12", "2026-05-19", "2026-05-22", "2026-05-29"):
            _report(sym, d)
        print("\n[mapped market with only NEUTRAL data]")
        _report("EURUSDm", "2026-05-29")
        print("\n[unmapped symbol → None / False]")
        _report("UNMAPPEDm", "2026-05-29")
        print("\n[mapped symbol, date before any data → None / False]")
        _report("XAUUSDm", "2026-01-01")
    finally:
        _load_index = _orig_load  # type: ignore[assignment]


if __name__ == "__main__":
    _selftest()
