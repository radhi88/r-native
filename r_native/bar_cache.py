"""bar_cache.py — H.4: symbol-capped LRU cache for MT5 bar arrays.

The heaviest RAM consumers in the worker are the raw bar arrays returned by
mt5.copy_rates_from_pos (a 4000-bar structured array is ~0.5 MB; a full-market
scan touches 30+ symbols x 4 timeframes). This cache bounds that to the
MAX_SYMBOLS most-recently-used *symbols*; evicting a symbol drops ALL of its
cached timeframes at once.

Call sites routed through here (H.4):
  - scanner.scan_symbol_tf_archetype   full-market scan — the same (sym, tf)
    array is otherwise re-fetched once per archetype (~7x per cell)
  - genetic_engine._eval_genome_worker GA campaign — the same (sym, tf, n)
    array is otherwise re-fetched for EVERY genome eval in a pool worker

Pure Python, no MT5 import — unit-testable offline. Each consumer runs in its
own process (GA pool workers) or a single scan thread, and the CPython GIL
makes the OrderedDict ops safe for the Qt-thread shrink_to() cleanup call.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable, Optional

# H.4 DOD: LRU-evict down to 5 symbols
MAX_SYMBOLS       = 5
# Live bars go stale — a hit older than this is treated as a miss (refetched).
DEFAULT_MAX_AGE_S = 90.0

# symbol -> OrderedDict[(tf_key, n_bars)] -> (fetched_at_ts, bars)
# Outer dict ordered LRU-first; inner dict likewise per timeframe request.
_CACHE: "OrderedDict[str, OrderedDict]" = OrderedDict()


def put(symbol: str, tf_key, n_bars: int, bars: object) -> None:
    """Store a bar array; marks `symbol` most-recently-used and evicts the
    least-recently-used symbols beyond MAX_SYMBOLS."""
    sym = _CACHE.get(symbol)
    if sym is None:
        sym = _CACHE[symbol] = OrderedDict()
    _CACHE.move_to_end(symbol)
    sym[(tf_key, n_bars)] = (time.time(), bars)
    sym.move_to_end((tf_key, n_bars))
    while len(_CACHE) > MAX_SYMBOLS:
        _CACHE.popitem(last=False)


def get(symbol: str, tf_key, n_bars: int,
        max_age_s: Optional[float] = DEFAULT_MAX_AGE_S):
    """Cached bars or None. A hit refreshes the symbol's MRU position.
    Entries older than max_age_s are dropped and reported as a miss
    (pass max_age_s=None to disable expiry)."""
    sym = _CACHE.get(symbol)
    if sym is None:
        return None
    entry = sym.get((tf_key, n_bars))
    if entry is None:
        return None
    ts, bars = entry
    if max_age_s is not None and (time.time() - ts) > max_age_s:
        sym.pop((tf_key, n_bars), None)     # stale — force refetch
        return None
    _CACHE.move_to_end(symbol)
    sym.move_to_end((tf_key, n_bars))
    return bars


def fetch(symbol: str, tf_key, n_bars: int, fetcher: Callable[[], object],
          max_age_s: Optional[float] = DEFAULT_MAX_AGE_S):
    """get() or call fetcher() and cache the result.
    Failed fetches (None / empty) are returned but NOT cached, so the next
    call retries instead of pinning a bad result for max_age_s."""
    bars = get(symbol, tf_key, n_bars, max_age_s)
    if bars is not None:
        return bars
    bars = fetcher()
    try:
        if bars is not None and len(bars) > 0:
            put(symbol, tf_key, n_bars, bars)
    except TypeError:       # un-sized object — cache it as-is
        if bars is not None:
            put(symbol, tf_key, n_bars, bars)
    return bars


def shrink_to(keep: int = MAX_SYMBOLS) -> int:
    """Evict all but the `keep` most-recently-used SYMBOLS (H.4 post-campaign
    cleanup hook in app.py calls shrink_to(keep=5)). Returns symbols evicted."""
    evicted = 0
    while len(_CACHE) > keep:
        _CACHE.popitem(last=False)
        evicted += 1
    return evicted


def clear() -> int:
    """Drop everything. Returns the number of symbols cleared."""
    n = len(_CACHE)
    _CACHE.clear()
    return n


def size() -> int:
    """Number of cached SYMBOLS (the LRU unit)."""
    return len(_CACHE)


def symbols() -> list:
    """Cached symbols, least-recently-used first (MRU last)."""
    return list(_CACHE.keys())


def keys() -> list:
    """Flat (symbol, tf_key, n_bars) view — backward-compat with H.1 skeleton."""
    return [(s, tf, n) for s, d in _CACHE.items() for (tf, n) in d.keys()]
