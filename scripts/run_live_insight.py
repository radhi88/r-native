import argparse
import json
import mimetypes
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import joblib
import numpy as np

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.ai_brain import TradingBrain
from mt5_ai.config import (
    FEATURE_COLUMNS,
    LOG_DIR,
    MODEL_PATH,
    MT5_SYMBOL,
    PROJECT_ROOT,
    SCALER_PATH,
    SEQ_LEN,
)
from mt5_ai.market_structure import add_market_structure
from mt5_ai.mt5_gateway import MT5Gateway
from mt5_ai.pivot_engine import PivotEngine


WEB_DIR = PROJECT_ROOT / "web" / "live_insight"
DEFAULT_TIMEFRAMES = ("M1", "M5", "M15", "H1")


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_float(value, default=None):
    try:
        value = float(value)
        if np.isnan(value):
            return default
        return value
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        value = int(value)
        return value
    except Exception:
        return default


def _tail_jsonl(path: Path, limit: int = 80) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _bars_payload(df, enriched, max_bars: int) -> list[dict]:
    start = max(0, len(df) - max_bars)
    rows = []
    for i in range(start, len(df)):
        raw = df.iloc[i]
        enr = enriched.iloc[i]
        rows.append(
            {
                "i": i,
                "time": raw["time"].isoformat(),
                "open": _safe_float(raw["open"]),
                "high": _safe_float(raw["high"]),
                "low": _safe_float(raw["low"]),
                "close": _safe_float(raw["close"]),
                "volume": _safe_float(raw.get("tick_volume", raw.get("volume", 0)), 0),
                "bos_up": _safe_int(enr.get("bos_up")),
                "bos_down": _safe_int(enr.get("bos_down")),
                "choch_up": _safe_int(enr.get("choch_up")),
                "choch_down": _safe_int(enr.get("choch_down")),
                "bullish_fvg": _safe_int(enr.get("bullish_fvg")),
                "bearish_fvg": _safe_int(enr.get("bearish_fvg")),
                "buy_sweep": _safe_int(enr.get("buy_side_liquidity_sweep")),
                "sell_sweep": _safe_int(enr.get("sell_side_liquidity_sweep")),
                "in_bullish_ob": _safe_int(enr.get("in_bullish_ob")),
                "in_bearish_ob": _safe_int(enr.get("in_bearish_ob")),
                "smc_buy": _safe_float(enr.get("smc_buy_score"), 0),
                "smc_sell": _safe_float(enr.get("smc_sell_score"), 0),
                "smc_bias": _safe_float(enr.get("smc_bias"), 0),
            }
        )
    return rows


def _zone_payload(enriched, max_bars: int) -> list[dict]:
    start = max(0, len(enriched) - max_bars)
    latest = enriched.iloc[-1]
    zones = []
    for side, low_col, high_col in (
        ("bullish_ob", "bullish_ob_low", "bullish_ob_high"),
        ("bearish_ob", "bearish_ob_low", "bearish_ob_high"),
    ):
        low = _safe_float(latest.get(low_col))
        high = _safe_float(latest.get(high_col))
        if low is not None and high is not None and high > low:
            zones.append({"type": side, "from": start, "to": len(enriched) - 1, "low": low, "high": high})
    return zones


def _event_payload(enriched, max_bars: int, limit: int = 120) -> list[dict]:
    start = max(0, len(enriched) - max_bars)
    columns = [
        ("bos_up", "BOS+"),
        ("bos_down", "BOS-"),
        ("choch_up", "CHOCH+"),
        ("choch_down", "CHOCH-"),
        ("bullish_fvg", "FVG+"),
        ("bearish_fvg", "FVG-"),
        ("buy_side_liquidity_sweep", "BSL sweep"),
        ("sell_side_liquidity_sweep", "SSL sweep"),
        ("demand_zone", "Demand"),
        ("supply_zone", "Supply"),
    ]
    events = []
    for i in range(start, len(enriched)):
        row = enriched.iloc[i]
        for column, label in columns:
            if _safe_int(row.get(column)) == 1:
                price = _safe_float(row.get("high" if column in {"bos_up", "buy_side_liquidity_sweep"} else "low"))
                if price is None:
                    price = _safe_float(row.get("close"), 0)
                events.append(
                    {
                        "i": i,
                        "time": row["time"].isoformat() if "time" in row else str(i),
                        "type": label,
                        "price": price,
                    }
                )
    return events[-limit:]


def _latest_smc(enriched) -> dict:
    row = enriched.iloc[-1]
    keys = [
        "bos_up",
        "bos_down",
        "choch_up",
        "choch_down",
        "buy_side_liquidity_sweep",
        "sell_side_liquidity_sweep",
        "bullish_fvg",
        "bearish_fvg",
        "ifvg_bull",
        "ifvg_bear",
        "in_bullish_ob",
        "in_bearish_ob",
        "demand_zone",
        "supply_zone",
        "smc_buy_score",
        "smc_sell_score",
        "smc_bias",
        "trend",
        "atr",
        "rsi",
        "adx",
        "spread",
        "bullish_ob_low",
        "bullish_ob_high",
        "bearish_ob_low",
        "bearish_ob_high",
        "prev_swing_high",
        "prev_swing_low",
        "liquidity_high",
        "liquidity_low",
    ]
    return {key: _safe_float(row.get(key), 0) for key in keys}


def _make_sequence(enriched, scaler):
    seq = enriched[FEATURE_COLUMNS].tail(SEQ_LEN).to_numpy(dtype=np.float32)
    if len(seq) < SEQ_LEN:
        raise RuntimeError(f"Need {SEQ_LEN} bars, got {len(seq)}")
    seq = scaler.transform(seq)
    return seq.reshape(1, SEQ_LEN, len(FEATURE_COLUMNS))


class LiveInsightState:
    def __init__(self, symbol: str, profile: str, bars: int):
        import tensorflow as tf

        self.symbol = symbol
        self.profile = profile
        self.bars = int(bars)
        self.gateway = MT5Gateway()
        self.gateway.initialize()
        symbol_info = self.gateway.symbol_snapshot(self.symbol)
        point_size = float(symbol_info.get("point") or 0.01)
        self.pivot = PivotEngine(self.gateway, self.symbol, point_size=point_size)
        self.model = tf.keras.models.load_model(MODEL_PATH, compile=False)
        self.scaler = joblib.load(SCALER_PATH)
        self.brain = TradingBrain(model=self.model, profile_name=profile)

    def close(self):
        self.gateway.shutdown()

    def snapshot(self, chart_bars: int = 240) -> dict:
        chart_bars = max(60, min(int(chart_bars), self.bars))
        df = self.gateway.fetch_rates(self.symbol, "M1", self.bars)
        enriched = add_market_structure(df)
        sequence = _make_sequence(enriched, self.scaler)
        spread = _safe_float(df["spread"].iloc[-1]) if "spread" in df.columns else None
        decision = self.brain.decide(df=enriched, sequence=sequence, spread=spread).to_dict()

        mtf = {}
        for timeframe in DEFAULT_TIMEFRAMES:
            try:
                tf_df = self.gateway.fetch_rates(self.symbol, timeframe, 260)
                tf_enriched = add_market_structure(tf_df)
                tf_latest = _latest_smc(tf_enriched)
                mtf[timeframe] = {
                    "close": _safe_float(tf_enriched["close"].iloc[-1]),
                    "smc_buy": tf_latest["smc_buy_score"],
                    "smc_sell": tf_latest["smc_sell_score"],
                    "bias": tf_latest["smc_bias"],
                    "bos_up": bool(tf_latest["bos_up"]),
                    "bos_down": bool(tf_latest["bos_down"]),
                    "choch_up": bool(tf_latest["choch_up"]),
                    "choch_down": bool(tf_latest["choch_down"]),
                    "trend": tf_latest["trend"],
                }
            except Exception as exc:
                mtf[timeframe] = {"error": str(exc)}

        decision.update(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "symbol": self.symbol,
                "profile": self.profile,
                "close": _safe_float(df["close"].iloc[-1]),
            }
        )
        pivot_result = self.pivot.apply(
            signal=decision.get("action", "HOLD"),
            confidence=float(decision.get("confidence", 0.0)),
            price=float(decision["close"]),
        )
        decision["pivot"] = pivot_result
        decision["confidence"] = pivot_result["confidence"]

        paper_trades = _tail_jsonl(LOG_DIR / "live_paper_trades.jsonl", 120)
        paper_decisions = _tail_jsonl(LOG_DIR / "live_paper_decisions.jsonl", 120)
        auto_trades = _tail_jsonl(LOG_DIR / "auto_trades.jsonl", 120)
        account = self.gateway.account_snapshot()
        positions = self.gateway.get_open_positions()
        total_profit = sum(float(p.get("profit") or 0.0) for p in positions)

        return {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbol": self.symbol,
            "profile": self.profile,
            "account": account,
            "symbol_snapshot": self.gateway.symbol_snapshot(self.symbol),
            "bars": _bars_payload(df, enriched, chart_bars),
            "zones": _zone_payload(enriched, chart_bars),
            "events": _event_payload(enriched, chart_bars),
            "latest_smc": _latest_smc(enriched),
            "decision": decision,
            "mtf": mtf,
            "positions": positions,
            "positions_profit": total_profit,
            "paper_trades": paper_trades,
            "paper_decisions": paper_decisions[-40:],
            "auto_trades": auto_trades,
        }


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict):
    body = json.dumps(payload, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(state: LiveInsightState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                try:
                    query = parse_qs(parsed.query)
                    bars = int(query.get("bars", ["240"])[0])
                    _send_json(self, 200, state.snapshot(chart_bars=bars))
                except Exception as exc:
                    _send_json(self, 500, {"ok": False, "error": str(exc)})
                return

            rel = "index.html" if parsed.path in ("", "/") else parsed.path.lstrip("/")
            path = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in path.parents and path != WEB_DIR.resolve():
                self.send_error(403)
                return
            if not path.exists() or not path.is_file():
                self.send_error(404)
                return
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="FRIDAY live read-only insight dashboard")
    parser.add_argument("--symbol", default=MT5_SYMBOL)
    parser.add_argument("--profile", default="scalping")
    parser.add_argument("--bars", type=int, default=700)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()

    state = LiveInsightState(symbol=args.symbol, profile=args.profile, bars=args.bars)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(f"FRIDAY Live Insight: http://{args.host}:{args.port}")
    print("Read-only dashboard. It does not send MT5 orders.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()


if __name__ == "__main__":
    main()
