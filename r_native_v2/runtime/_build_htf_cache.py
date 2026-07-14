"""One-time cache builder: parse Massive MCP-saved gold H1 results -> cache CSVs.

Reads every saved tool-result file, extracts the real C:XAUUSD H1 OHLC rows,
dedupes by timestamp, writes data/htf_cache/XAUUSDm_H1.csv, then resamples to
H4 and writes XAUUSDm_H4.csv. Real data only; no synthetic bars.
"""
from __future__ import annotations
import json, glob, os, csv
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(r"C:\Users\Radhi\.claude\projects\C--Users-Radhi-MT5\6917ff55-c9c4-450f-9e9e-f92c76cc6cc2\tool-results")
ROOT = Path(r"C:\Users\Radhi\MT5\r_native_v2")
CACHE = ROOT / "data" / "htf_cache"
CACHE.mkdir(parents=True, exist_ok=True)


def parse_rows():
    """columns: v,vw,o,c,h,l,t,n  -> dict[epoch_ms] = (o,h,l,c)."""
    bars = {}
    for f in glob.glob(str(RESULTS_DIR / "mcp-Massive_Market_Data-call_api-*.txt")):
        txt = Path(f).read_text(encoding="utf-8")
        try:
            s = json.loads(txt)["result"]
        except Exception:
            s = txt
        for ln in s.splitlines():
            if not ln or not ln[0].isdigit():
                continue
            p = ln.split(",")
            if len(p) < 7:
                continue
            try:
                o = float(p[2]); c = float(p[3]); h = float(p[4]); l = float(p[5]); t = int(p[6])
            except ValueError:
                continue
            # only hourly-grid gold rows (filter out any 4h-spaced contaminants is fine;
            # dedupe by exact epoch keeps both grids consistent — but we only want H1 here)
            bars[t] = (o, h, l, c)
    return bars


def write_h1(bars):
    path = CACHE / "XAUUSDm_H1.csv"
    keys = sorted(bars)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close"])
        for t in keys:
            o, h, l, c = bars[t]
            dt = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
            w.writerow([dt.isoformat(), f"{o:.3f}", f"{h:.3f}", f"{l:.3f}", f"{c:.3f}"])
    return path, keys


def resample_h4(bars):
    """Aggregate H1 -> H4 buckets aligned to 0,4,8,12,16,20 UTC."""
    keys = sorted(bars)
    buckets = {}  # bucket_start_epoch -> [o,h,l,c, first_t, last_t]
    for t in keys:
        dt = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        bh = (dt.hour // 4) * 4
        bstart = dt.replace(hour=bh, minute=0, second=0, microsecond=0)
        bkey = int(bstart.timestamp())
        o, h, l, c = bars[t]
        if bkey not in buckets:
            buckets[bkey] = [o, h, l, c, t, t]
        else:
            b = buckets[bkey]
            b[1] = max(b[1], h)   # high
            b[2] = min(b[2], l)   # low
            b[3] = c              # close = latest
            if t < b[4]:
                b[4] = t; b[0] = o
            if t > b[5]:
                b[5] = t; b[3] = c
    path = CACHE / "XAUUSDm_H4.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close"])
        for bkey in sorted(buckets):
            o, h, l, c, _, _ = buckets[bkey]
            dt = datetime.fromtimestamp(bkey, tz=timezone.utc)
            w.writerow([dt.isoformat(), f"{o:.3f}", f"{h:.3f}", f"{l:.3f}", f"{c:.3f}"])
    return path, len(buckets)


def largest_clean_window(bars, max_gap_days=5):
    """Return bars restricted to the longest run with no gap > max_gap_days
    (weekends ~2d are fine; the 40-100d inter-fetch holes are excluded)."""
    keys = sorted(bars)
    best = (0, 0, 0)  # (count, start, end)
    run_start = keys[0]; prev = keys[0]; cnt = 1
    thresh = max_gap_days * 24 * 3600 * 1000
    for t in keys[1:]:
        if t - prev > thresh:
            if cnt > best[0]:
                best = (cnt, run_start, prev)
            run_start = t; cnt = 1
        else:
            cnt += 1
        prev = t
    if cnt > best[0]:
        best = (cnt, run_start, prev)
    _, a, b = best
    return {t: v for t, v in bars.items() if a <= t <= b}


if __name__ == "__main__":
    bars = parse_rows()
    bars = largest_clean_window(bars)  # restrict to hole-free contiguous block
    p1, keys = write_h1(bars)
    p4, n4 = resample_h4(bars)
    t0 = datetime.fromtimestamp(keys[0] / 1000, tz=timezone.utc)
    t1 = datetime.fromtimestamp(keys[-1] / 1000, tz=timezone.utc)
    print(f"H1 cache: {p1}  ({len(keys)} bars, {t0} .. {t1})")
    print(f"H4 cache: {p4}  ({n4} bars)")
    # report largest contiguous H1 run (gap > 6h breaks continuity)
    runs = []
    run_start = keys[0]; prev = keys[0]
    for t in keys[1:]:
        if t - prev > 6 * 3600 * 1000:
            runs.append((run_start, prev)); run_start = t
        prev = t
    runs.append((run_start, prev))
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    a, b = runs[0]
    da = datetime.fromtimestamp(a / 1000, tz=timezone.utc)
    db = datetime.fromtimestamp(b / 1000, tz=timezone.utc)
    nbars = sum(1 for t in keys if a <= t <= b)
    print(f"largest contiguous run: {da} .. {db}  ({nbars} H1 bars, {len(runs)} runs total)")
