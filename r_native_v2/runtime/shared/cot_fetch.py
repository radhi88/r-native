"""
cot_fetch.py — CFTC Commitments of Traders (COT) fetcher + Commercials-vs-Retail index.

DATA SOURCE
-----------
CFTC public reporting Socrata API (Legacy Futures-Only report):
    https://publicreporting.cftc.gov/resource/6dca-aqww.json

This is the official CFTC "Legacy Futures-Only" Commitments of Traders dataset
(dataset id 6dca-aqww), published weekly (report date = Tuesday). It is free and
requires no API token for the request volumes used here. If the Socrata endpoint
is unreachable, the same data can be downloaded as annual CSV/zip archives from
    https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
(see fetch_via_csv_todo() at the bottom of this file).

EXACT MARKET / COMMODITY NAMES USED (field: market_and_exchange_names)
----------------------------------------------------------------------
    GOLD       -> "GOLD - COMMODITY EXCHANGE INC."        (CME/COMEX, code 088691)
    EURO FX    -> "EURO FX - CHICAGO MERCANTILE EXCHANGE" (CME,        code 099741)
    BRITISH    -> "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE" (CME,  code 096742)
                  (older rows for the same contract code appear under the legacy
                   name "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE";
                   we match on the contract market code so the history is continuous.)

COMPUTATION
-----------
For every weekly report row (Legacy report, "all" columns):
    commercial_net   = comm_positions_long_all   - comm_positions_short_all
    nonreportable_net= nonrept_positions_long_all - nonrept_positions_short_all   (RETAIL proxy)

COT INDEX (Williams-style): for each net series, normalise the value over a
trailing rolling 52-week min-max window to 0..100:
    index = 100 * (net - min_52w) / (max_52w - min_52w)
(If max==min the index is set to 50 / neutral.)

STATE:
    index > 70  -> "BULLISH"
    index < 30  -> "BEARISH"
    else        -> "NEUTRAL"

OUTPUT  (data/cot_index.json, relative to this module's parent runtime):
    {
      "GOLD":    [ {date, comm_net, comm_index, comm_state,
                    retail_net, retail_index, retail_state}, ... ],
      "EURO FX": [ ... ],
      "BRITISH POUND": [ ... ],
      "_meta":   { source, dataset_id, commodity_names, generated_utc, sample }
    }
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SOCRATA_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
DATASET_ID = "6dca-aqww"

# Contract market codes are stable across legacy name changes, so we filter on
# the CFTC contract market code where it helps (British Pound name changed).
MARKETS = {
    "GOLD": {
        "names": ["GOLD - COMMODITY EXCHANGE INC."],
        "codes": ["088691"],
    },
    "EURO FX": {
        "names": ["EURO FX - CHICAGO MERCANTILE EXCHANGE"],
        "codes": ["099741"],
    },
    "BRITISH POUND": {
        "names": [
            "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
            "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
        ],
        "codes": ["096742"],
    },
}

ROLLING_WINDOW = 52          # weeks for the COT index min-max normalisation
YEARS_OF_OUTPUT = 2          # weeks of final output we keep (~104 rows)
# We fetch extra history so the very first output row already has a full 52w window.
FETCH_WEEKS = YEARS_OF_OUTPUT * 52 + ROLLING_WINDOW + 4   # ~160 weeks

BULL_THRESHOLD = 70
BEAR_THRESHOLD = 30

# data/cot_index.json must live where cot_signal.py reads it: <ROOT>/data,
# where ROOT == C:\Users\Radhi\MT5\r_native_v2 (the parent of runtime/).
# cot_signal.py resolves ROOT = Path(__file__).parent.parent.parent, so the
# writer here must target the same <ROOT>/data dir — NOT runtime/data — or the
# signal module would read a stale/missing file (the historic path mismatch).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))           # .../runtime/shared
_RUNTIME_DIR = os.path.dirname(_THIS_DIR)                         # .../runtime
_ROOT = os.path.dirname(_RUNTIME_DIR)                            # .../r_native_v2
if not os.path.isdir(os.path.join(_ROOT, "runtime")):
    _ROOT = r"C:\Users\Radhi\MT5\r_native_v2"
DATA_DIR = os.path.join(_ROOT, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "cot_index.json")


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #

def _http_get_json(url: str, timeout: int = 60):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "friday-cot-fetch/1.0 (+r_native_v2)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_where(market_cfg: dict) -> str:
    """SoQL WHERE clause matching either the contract code(s) or the name(s)."""
    clauses = []
    for code in market_cfg.get("codes", []):
        clauses.append(f"cftc_contract_market_code = '{code}'")
    for name in market_cfg.get("names", []):
        safe = name.replace("'", "''")
        clauses.append(f"market_and_exchange_names = '{safe}'")
    return "(" + " OR ".join(clauses) + ")"


def fetch_market(label: str, market_cfg: dict, limit: int = FETCH_WEEKS):
    """Fetch the most recent `limit` weekly rows for one market from Socrata."""
    where = _build_where(market_cfg)
    params = {
        "$select": (
            "report_date_as_yyyy_mm_dd,"
            "comm_positions_long_all,comm_positions_short_all,"
            "nonrept_positions_long_all,nonrept_positions_short_all,"
            "market_and_exchange_names,cftc_contract_market_code"
        ),
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(limit),
    }
    url = SOCRATA_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    rows = _http_get_json(url)
    # Oldest -> newest so the rolling window walks forward in time.
    rows.sort(key=lambda r: r.get("report_date_as_yyyy_mm_dd", ""))
    return rows


# --------------------------------------------------------------------------- #
# Compute
# --------------------------------------------------------------------------- #

def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _state(index_val):
    if index_val is None:
        return "NEUTRAL"
    if index_val > BULL_THRESHOLD:
        return "BULLISH"
    if index_val < BEAR_THRESHOLD:
        return "BEARISH"
    return "NEUTRAL"


def _rolling_index(nets, i, window=ROLLING_WINDOW):
    """Williams COT index over a trailing min-max window ending at i (inclusive)."""
    start = max(0, i - window + 1)
    win = nets[start : i + 1]
    lo, hi = min(win), max(win)
    if hi == lo:
        return 50.0
    return round(100.0 * (nets[i] - lo) / (hi - lo), 2)


def compute_series(rows):
    """Transform raw CFTC rows into the per-week index/state records."""
    dates, comm_nets, retail_nets = [], [], []
    for r in rows:
        raw_date = r.get("report_date_as_yyyy_mm_dd", "")
        dates.append(raw_date[:10] if raw_date else "")
        comm_nets.append(
            _to_int(r.get("comm_positions_long_all"))
            - _to_int(r.get("comm_positions_short_all"))
        )
        retail_nets.append(
            _to_int(r.get("nonrept_positions_long_all"))
            - _to_int(r.get("nonrept_positions_short_all"))
        )

    out = []
    for i in range(len(rows)):
        comm_idx = _rolling_index(comm_nets, i)
        retail_idx = _rolling_index(retail_nets, i)
        out.append(
            {
                "date": dates[i],
                "comm_net": comm_nets[i],
                "comm_index": comm_idx,
                "comm_state": _state(comm_idx),
                "retail_net": retail_nets[i],
                "retail_index": retail_idx,
                "retail_state": _state(retail_idx),
            }
        )

    # Keep only the most recent ~2 years of output (the leading rows existed
    # only to warm up the 52-week rolling window).
    keep = YEARS_OF_OUTPUT * 52
    if len(out) > keep:
        out = out[-keep:]
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def build_index(verbose: bool = True) -> dict:
    result = {}
    meta = {
        "source": "CFTC public reporting Socrata API — Legacy Futures-Only COT report",
        "source_url": SOCRATA_URL,
        "dataset_id": DATASET_ID,
        "commodity_names": {k: v["names"] for k, v in MARKETS.items()},
        "rolling_window_weeks": ROLLING_WINDOW,
        "thresholds": {"bullish": ">70", "bearish": "<30", "neutral": "30..70"},
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sample": False,
    }

    for label, cfg in MARKETS.items():
        try:
            rows = fetch_market(label, cfg)
            series = compute_series(rows)
            result[label] = series
            if verbose:
                last = series[-1]["date"] if series else "n/a"
                print(f"[cot_fetch] {label}: {len(series)} weekly rows (latest {last})")
        except Exception as exc:  # network or parse failure for this market
            result[label] = []
            meta.setdefault("errors", {})[label] = repr(exc)
            if verbose:
                print(f"[cot_fetch] {label}: FAILED ({exc})", file=sys.stderr)

    result["_meta"] = meta
    return result


def save(result: dict, path: str = OUTPUT_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    return path


# --------------------------------------------------------------------------- #
# Sample / offline fallback
# --------------------------------------------------------------------------- #

def _sample_index() -> dict:
    """Tiny clearly-marked SAMPLE used only if all network attempts fail."""
    def mk(date, cn, ci, rn, ri):
        return {
            "date": date, "comm_net": cn, "comm_index": ci, "comm_state": _state(ci),
            "retail_net": rn, "retail_index": ri, "retail_state": _state(ri),
        }

    sample = {
        "GOLD": [
            mk("2026-05-12", -180000, 25.0, 42000, 78.0),
            mk("2026-05-19", -165000, 48.0, 38000, 55.0),
            mk("2026-05-26", -150000, 72.0, 35000, 22.0),
        ],
        "EURO FX": [
            mk("2026-05-12", 60000, 80.0, -12000, 18.0),
            mk("2026-05-19", 52000, 60.0, -9000, 40.0),
            mk("2026-05-26", 45000, 35.0, -6000, 66.0),
        ],
        "BRITISH POUND": [
            mk("2026-05-12", -20000, 28.0, 7000, 71.0),
            mk("2026-05-19", -15000, 50.0, 5000, 49.0),
            mk("2026-05-26", -10000, 73.0, 3000, 27.0),
        ],
        "_meta": {
            "sample": True,
            "source": "SAMPLE DATA — NOT REAL CFTC DATA",
            "dataset_id": DATASET_ID,
            "commodity_names": {k: v["names"] for k, v in MARKETS.items()},
            "TODO": (
                "All network attempts to the CFTC Socrata API failed. Download the "
                "annual Legacy Futures-Only CSV from "
                "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
                "HistoricalCompressed/index.htm and feed it through "
                "fetch_via_csv_todo(), or re-run this module when online."
            ),
            "generated_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
    return sample


def fetch_via_csv_todo(csv_path: str):
    """
    TODO (offline path): parse a CFTC annual Legacy Futures-Only CSV.
    The CSV column names differ from the API field names, e.g.:
        'Commercial Positions-Long (All)'   -> comm_positions_long_all
        'Commercial Positions-Short (All)'  -> comm_positions_short_all
        'Nonreportable Positions-Long (All)'  -> nonrept_positions_long_all
        'Nonreportable Positions-Short (All)' -> nonrept_positions_short_all
        'Market and Exchange Names'           -> market_and_exchange_names
        'As of Date in Form YYYY-MM-DD'       -> report_date_as_yyyy_mm_dd
    Map those into the same dict shape fetch_market() returns, then call
    compute_series(). Not implemented here because the live API succeeded.
    """
    raise NotImplementedError(
        "Offline CSV path not implemented — live Socrata API was reachable."
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main():
    result = build_index(verbose=True)
    total = sum(len(v) for k, v in result.items() if k != "_meta")
    if total == 0:
        print(
            "[cot_fetch] ALL network attempts failed — writing SAMPLE data.",
            file=sys.stderr,
        )
        result = _sample_index()
    path = save(result)
    print(f"[cot_fetch] wrote {path}")
    for k in MARKETS:
        n = len(result.get(k, []))
        print(f"[cot_fetch]   {k}: {n} rows")
    return result


if __name__ == "__main__":
    main()
