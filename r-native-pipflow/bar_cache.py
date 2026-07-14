"""bar_cache.py — Tiny LRU cache for MT5 bar arrays.

Currently scanner.py calls mt5.copy_rates_from_pos directly. Long-term we want
those calls to route through `get(symbol, tf, n)` here so we can evict old
symbols' bar history to keep RAM bounded.

For H.4 this module mainly provides `shrink_to(keep)` so the post-campaign
cleanup hook in app.py has something to call. If/when scanner.py is refactored
to use this cache, the eviction will actually free memory.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Optional

# key = (symbol, tf_name, n_bars) → numpy structured array from MT5
_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_MAX_KEYS = 20


def put(key: tuple, bars: object) -> None:
    """Store bars under a (symbol, tf, n) key. Evicts oldest if cache full."""
    if key in _CACHE:
        _CACHE.move_to_end(key)
    _CACHE[key] = bars
    while len(_CACHE) > _MAX_KEYS:
        _CACHE.popitem(last=False)


def get(key: tuple) -> Optional[object]:
    """Retrieve cached bars, marking key as recently-used. Returns None if miss."""
    if key not in _CACHE:
        return None
    _CACHE.move_to_end(key)
    return _CACHE[key]


def shrink_to(keep: int = 5) -> int:
    """Evict all but the `keep` most-recently-used entries.
    Returns the number of entries evicted. Safe to call when cache is empty."""
    evicted = 0
    while len(_CACHE) > keep:
        _CACHE.popitem(last=False)
        evicted += 1
    return evicted


def clear() -> int:
    """Drop everything. Returns the number of entries cleared."""
    n = len(_CACHE)
    _CACHE.clear()
    return n


def size() -> int:
    return len(_CACHE)


def keys() -> list:
    return list(_CACHE.keys())
