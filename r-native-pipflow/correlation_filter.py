"""correlation_filter.py — J.23 — Cross-asset correlation risk capping.

If BTC and gold are 0.9 correlated today, trading both = double risk on the same
bet. This module:
1. Computes rolling correlation matrix across watched symbols
2. Detects "clusters" (groups of highly-correlated assets)
3. Caps max simultaneous positions per cluster
4. Optional: blocks new entries that would breach the cap

Usage:
  matrix = correlation_matrix(["BTCUSDm", "ETHUSDm", "XAUUSDm"], hours=24)
  clusters = detect_clusters(matrix, threshold=0.7)
  if would_breach_cap("BTCUSDm", open_positions, clusters): skip()
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


def correlation_matrix(symbols: list[str], hours: int = 24,
                       tf: str = "H1") -> dict:
    """Pearson correlation of close-to-close returns across symbols.

    Returns: { "symbol_a": {"symbol_b": 0.85, ...}, ... }
    """
    try:
        import MetaTrader5 as mt5
        import numpy as np
    except ImportError:
        return {}

    if not mt5.initialize(): return {}

    tf_map = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
              "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
              "H4": mt5.TIMEFRAME_H4}
    tf_const = tf_map.get(tf, mt5.TIMEFRAME_H1)
    bars_per_hour = {"M5": 12, "M15": 4, "M30": 2, "H1": 1, "H4": 0.25}.get(tf, 1)
    n = max(20, int(hours * bars_per_hour))

    # Pull returns for each symbol
    returns = {}
    for sym in symbols:
        bars = mt5.copy_rates_from_pos(sym, tf_const, 0, n)
        if bars is None or len(bars) < 5: continue
        closes = np.array([b["close"] for b in bars], dtype=float)
        if len(closes) < 2: continue
        rets = np.diff(closes) / closes[:-1]
        returns[sym] = rets

    # Align lengths (truncate to min)
    if not returns: return {}
    min_len = min(len(r) for r in returns.values())
    if min_len < 5: return {}
    for s in list(returns):
        returns[s] = returns[s][-min_len:]

    # Pairwise correlation
    matrix = {}
    syms = list(returns.keys())
    for i, a in enumerate(syms):
        matrix[a] = {}
        for j, b in enumerate(syms):
            if i == j: matrix[a][b] = 1.0; continue
            try:
                ra, rb = returns[a], returns[b]
                if ra.std() == 0 or rb.std() == 0:
                    matrix[a][b] = 0.0
                else:
                    matrix[a][b] = float(np.corrcoef(ra, rb)[0, 1])
                matrix[a][b] = round(matrix[a][b], 3)
            except Exception:
                matrix[a][b] = 0.0
    return matrix


def detect_clusters(matrix: dict, threshold: float = 0.7) -> list[set]:
    """Greedy cluster detection: symbols with correlation > threshold."""
    if not matrix: return []
    syms = list(matrix.keys())
    visited = set()
    clusters = []

    for s in syms:
        if s in visited: continue
        cluster = {s}
        # BFS to find connected component
        frontier = [s]
        while frontier:
            cur = frontier.pop()
            for other in syms:
                if other == cur or other in cluster: continue
                if abs(matrix.get(cur, {}).get(other, 0)) >= threshold:
                    cluster.add(other)
                    frontier.append(other)
        if len(cluster) > 1:
            clusters.append(cluster)
        visited |= cluster
    return clusters


def would_breach_cap(new_symbol: str, open_positions: list[dict],
                     clusters: list[set], max_per_cluster: int = 1) -> dict:
    """Check if adding a position on `new_symbol` would push any cluster over cap."""
    open_syms = {p.get("symbol") for p in open_positions or [] if p.get("symbol")}
    for cluster in clusters:
        if new_symbol not in cluster: continue
        in_cluster_open = open_syms & cluster
        if len(in_cluster_open) >= max_per_cluster:
            return {"breach": True, "cluster": sorted(cluster),
                    "already_open": sorted(in_cluster_open),
                    "reason":
                    f"would exceed cluster cap {max_per_cluster}: "
                    f"{cluster} (open: {in_cluster_open})"}
    return {"breach": False}


def correlation_report(symbols: list[str], hours: int = 24) -> dict:
    """One-shot report ready for UI display."""
    matrix = correlation_matrix(symbols, hours)
    clusters = detect_clusters(matrix)
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "hours":       hours,
        "matrix":      matrix,
        "clusters":    [sorted(c) for c in clusters],
        "n_symbols":   len(matrix),
        "n_clusters":  len(clusters),
    }
