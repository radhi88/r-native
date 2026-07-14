"""
live_fractal_projection_monitor.py
-----------------------------------
Standalone fractal projection monitor — runs every 5 seconds.

Loop: active_genomes.json → MT5 bars → analyse_structure → generate_projection
Output: fractal_live_state.json  {symbol|tf: {structure, projection}}
Console: FRAC-PROJECTION status block
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\Radhi\MT5")
SRC  = ROOT / "src"
DATA = Path(r"C:\Users\Radhi\AppData\Local\FRIDAY")

for p in (str(SRC), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mt5_ai.fractal_structure_engine import analyse_structure
from mt5_ai.market_projection_engine  import generate_projection

ACTIVE_GENOMES_FILE  = DATA / "active_genomes.json"
FRACTAL_STATE_FILE   = DATA / "fractal_live_state.json"
INTERVAL_SECS        = 5

_TF_MAP = None   # lazy import after MT5 init


def _get_tf_map():
    global _TF_MAP
    if _TF_MAP is None:
        import MetaTrader5 as mt5
        _TF_MAP = {
            "M1":  mt5.TIMEFRAME_M1,  "M5":  mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
            "H1":  mt5.TIMEFRAME_H1,  "H4":  mt5.TIMEFRAME_H4,
            "D1":  mt5.TIMEFRAME_D1,
        }
    return _TF_MAP


def _fetch_bars(symbol: str, timeframe: str, n: int = 250):
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        tf_map = _get_tf_map()
        mt5.initialize()
        rates = mt5.copy_rates_from_pos(symbol, tf_map[timeframe], 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})[
            ["open", "high", "low", "close", "volume"]
        ].copy()
        return df
    except Exception:
        return None


def _load_active_genomes() -> dict:
    if not ACTIVE_GENOMES_FILE.exists():
        return {}
    try:
        return json.loads(ACTIVE_GENOMES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        text = json.dumps(state, ensure_ascii=False, indent=2)
        tmp  = FRACTAL_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        import os, time as _t
        for attempt in range(5):
            try:
                os.replace(str(tmp), str(FRACTAL_STATE_FILE))
                return
            except OSError:
                if attempt == 4:
                    FRACTAL_STATE_FILE.write_text(text, encoding="utf-8")
                    try: tmp.unlink(missing_ok=True)
                    except Exception: pass
                    return
                _t.sleep(0.05 * (attempt + 1))
    except Exception:
        pass


_RESET = "\033[0m"
_G     = "\033[92m"
_R     = "\033[91m"
_Y     = "\033[93m"
_C     = "\033[96m"
_M     = "\033[95m"
_DG    = "\033[90m"


def _dir_color(direction: str) -> str:
    return _G if direction == "UP" else _R if direction == "DOWN" else _DG


def _run_cycle() -> None:
    genomes = _load_active_genomes()
    if not genomes:
        print(f"{_DG}[FRAC] no active genomes{_RESET}")
        return

    state: dict = {}
    rows: list[str] = []

    for key, gdict in sorted(genomes.items()):
        sym, tf = key.split("|", 1)
        df = _fetch_bars(sym, tf)
        if df is None or len(df) < 30:
            continue

        try:
            fs   = analyse_structure(df)
            ema  = df["close"].ewm(span=21, adjust=False).mean()
            wr   = float(gdict.get("win_rate", 0.5))
            proj = generate_projection(df, fs, symbol=sym, tf=tf,
                                       ema_series=ema, genome_win_rate=wr)
        except Exception as exc:
            rows.append(f"  {_DG}{key:<20} ERROR: {exc}{_RESET}")
            continue

        state[key] = {
            "structure":  fs.to_dict(),
            "projection": proj,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        dc   = _dir_color(proj["direction"])
        bias = fs.structure_bias
        bc   = _G if bias == "bullish" else _R if bias == "bearish" else _DG
        tags = []
        if fs.bos_recent:   tags.append(f"{_G}BOS{_RESET}")
        if fs.choch_recent: tags.append(f"{_M}CHoCH{_RESET}")
        if fs.sweep_recent: tags.append(f"{_Y}SW{_RESET}")
        tag_str = " ".join(tags) if tags else ""
        rows.append(
            f"  {_C}{sym:<10}{_RESET}{tf:<5}"
            f" bias={bc}{bias:<8}{_RESET}"
            f" {fs.trend_quality:<11}"
            f" {dc}{proj['direction']:<9}{_RESET}"
            f" conf={proj['confidence']:.2f}"
            f" tgt={proj['target']:<10.5f}"
            f" {tag_str}"
        )

    _save_state(state)

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"\n{_M}━━ FRAC-PROJECTION {ts} ({'%d pairs' % len(state)}) ━━{_RESET}")
    for r in rows:
        print(r)


def main() -> None:
    print(f"{_M}[FRIDAY] Fractal Projection Monitor — starting (interval {INTERVAL_SECS}s){_RESET}")
    DATA.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            _run_cycle()
        except Exception as exc:
            print(f"{_R}[FRAC] cycle error: {exc}{_RESET}")
        time.sleep(INTERVAL_SECS)


if __name__ == "__main__":
    main()
