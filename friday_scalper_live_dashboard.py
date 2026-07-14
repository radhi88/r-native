from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5
import pandas as pd
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn


ROOT = Path(r"C:\Users\Radhi\MT5")
LOG_DIR = ROOT / "realtime_scalper_logs"
GENES_FILE = ROOT / "friday_strategy_genes.json"
FEATURE_STATE_FILE = ROOT / "friday_feature_council_state.json"
ORDERFLOW_STATE_FILE = ROOT / "friday_orderflow_state.json"
ORDERFLOW_EVENTS_FILE = ROOT / "friday_orderflow_events.json"

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

app = FastAPI(title="FRIDAY Scalper TradingView Dashboard", version="0.2")
_STATE_CACHE: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
_STATE_LOCK = threading.Lock()
_STATE_CACHE_TTL_SECONDS = 3.0
_LAST_STATE_PAYLOAD: dict[str, Any] | None = None


def ensure_mt5() -> bool:
    try:
        if mt5.terminal_info() is not None:
            return True
    except Exception:
        pass

    return bool(mt5.initialize())


def latest_log_file() -> Path | None:
    if not LOG_DIR.exists():
        return None

    files = list(LOG_DIR.glob("realtime_demo_executor_*.jsonl"))
    files += list(LOG_DIR.glob("realtime_scalper_*.jsonl"))

    if not files:
        return None

    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def read_jsonl_tail(path: Path, limit: int = 1000) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    rows: list[dict[str, Any]] = []

    for line in lines[-limit:]:
        line = line.strip()

        if not line:
            continue

        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    return rows


def load_latest_events(symbol: str, limit: int = 1000) -> dict[str, Any]:
    path = latest_log_file()

    if not path:
        return {
            "log_path": None,
            "events": [],
            "latest_decision": None,
            "executions": [],
            "errors": [],
        }

    rows = read_jsonl_tail(path, limit=limit)

    latest_decision = None
    executions = []
    errors = []
    filtered = []

    for row in rows:
        row_type = row.get("type")
        decision = row.get("decision") or {}
        row_symbol = str(decision.get("symbol") or row.get("symbol") or "")

        if row_type == "error":
            if not symbol or row_symbol == symbol:
                errors.append(row)
            continue

        if symbol and row_symbol != symbol:
            continue

        filtered.append(row)

        if row_type in {"decision", "demo_execution"} and decision:
            latest_decision = decision

        if row_type == "demo_execution":
            executions.append(row)

    return {
        "log_path": str(path),
        "events": filtered[-250:],
        "latest_decision": latest_decision,
        "executions": executions[-80:],
        "errors": errors[-80:],
    }


def rates_df(symbol: str, timeframe: str = "M1", bars: int = 250) -> pd.DataFrame:
    if timeframe not in TIMEFRAMES:
        timeframe = "M1"

    if not ensure_mt5():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Could not select symbol: {symbol}")

    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, bars)

    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No rates for {symbol} {timeframe}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).ewm(span=period, adjust=False).mean()


def candle_payload(symbol: str, timeframe: str = "M1", bars: int = 250) -> dict[str, Any]:
    df = rates_df(symbol, timeframe, bars)

    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)

    swing_high = None
    swing_low = None

    if len(df) >= 40:
        swing_high = float(df["high"].iloc[-32:-2].max())
        swing_low = float(df["low"].iloc[-32:-2].min())

    candles = []
    ema20 = []
    ema50 = []

    for row in df.itertuples():
        t = int(row.time.timestamp())

        candles.append(
            {
                "time": t,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
        )

        if pd.notna(row.ema20):
            ema20.append({"time": t, "value": float(row.ema20)})

        if pd.notna(row.ema50):
            ema50.append({"time": t, "value": float(row.ema50)})

    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)

    spread_points = None
    bid = None
    ask = None

    if tick is not None and info is not None:
        point = float(info.point or 0.0) or 0.01
        bid = float(tick.bid)
        ask = float(tick.ask)
        spread_points = abs(ask - bid) / point

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles,
        "ema20": ema20,
        "ema50": ema50,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "spread_points": round(float(spread_points), 1) if spread_points is not None else None,
        "bid": bid,
        "ask": ask,
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }



def load_feature_state() -> dict[str, Any]:
    if not FEATURE_STATE_FILE.exists():
        return {}

    try:
        return json.loads(FEATURE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_genes() -> dict[str, Any]:
    if not GENES_FILE.exists():
        return {}

    try:
        return json.loads(GENES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_orderflow_state(symbol: str, timeframe: str) -> dict[str, Any]:
    """Read orderflow state for a specific symbol/timeframe from the orderflow engine output."""
    try:
        if ORDERFLOW_STATE_FILE.exists():
            data = json.loads(ORDERFLOW_STATE_FILE.read_text(encoding="utf-8"))
            return (data.get("symbols", {}).get(symbol, {}).get(timeframe, {}))
    except Exception:
        pass
    return {}


def load_orderflow_events(symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    """Read latest order flow events for a symbol."""
    try:
        if ORDERFLOW_EVENTS_FILE.exists():
            events = json.loads(ORDERFLOW_EVENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(events, list):
                filtered = [e for e in events if e.get("symbol") == symbol]
                return filtered[-limit:]
    except Exception:
        pass
    return []


def account_payload() -> dict[str, Any]:
    if not ensure_mt5():
        return {"connected": False, "error": str(mt5.last_error())}

    account = mt5.account_info()

    if account is None:
        return {"connected": False, "error": "No account info"}

    server = str(getattr(account, "server", "") or "")

    return {
        "connected": True,
        "login": getattr(account, "login", None),
        "server": server,
        "balance": float(getattr(account, "balance", 0.0) or 0.0),
        "equity": float(getattr(account, "equity", 0.0) or 0.0),
        "margin": float(getattr(account, "margin", 0.0) or 0.0),
        "free_margin": float(getattr(account, "margin_free", 0.0) or 0.0),
        "currency": getattr(account, "currency", None),
        "trade_mode": getattr(account, "trade_mode", None),
        "demo_detected": any(k in server.lower() for k in ["demo", "trial", "practice", "contest"]),
    }


def positions_payload(symbol: str | None = None) -> list[dict[str, Any]]:
    if not ensure_mt5():
        return []

    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()

    if not positions:
        return []

    rows = []

    for pos in positions:
        rows.append(
            {
                "ticket": int(pos.ticket),
                "symbol": str(pos.symbol),
                "type": "BUY" if int(pos.type) == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": float(pos.volume),
                "price_open": float(pos.price_open),
                "price_current": float(pos.price_current),
                "sl": float(pos.sl or 0.0),
                "tp": float(pos.tp or 0.0),
                "profit": float(pos.profit),
                "magic": int(pos.magic or 0),
                "comment": str(pos.comment or ""),
                "time": int(pos.time),
            }
        )

    return rows


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "friday_scalper_live_dashboard",
        "port": 8822,
        "time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/state")
def api_state(
    symbol: str = Query("XAUUSDm"),
    timeframe: str = Query("M1"),
    bars: int = Query(120),
):
    global _LAST_STATE_PAYLOAD
    bars = max(5, min(int(bars or 120), 120))
    cache_key = (str(symbol or "XAUUSDm"), str(timeframe or "M1"), bars)
    now_ts = time.time()

    cached = _STATE_CACHE.get(cache_key)
    if cached and now_ts - cached[0] <= _STATE_CACHE_TTL_SECONDS:
        payload = dict(cached[1])
        payload["cached"] = True
        return JSONResponse(payload)

    if not _STATE_LOCK.acquire(blocking=False):
        fallback = cached[1] if cached else _LAST_STATE_PAYLOAD
        if fallback:
            payload = dict(fallback)
            payload["cached"] = True
            payload["stale"] = True
            return JSONResponse(payload)
        return JSONResponse({"ok": False, "error": "state_builder_busy"}, status_code=503)

    try:
        cached = _STATE_CACHE.get(cache_key)
        if cached and time.time() - cached[0] <= _STATE_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["cached"] = True
            return JSONResponse(payload)

        candles = candle_payload(symbol, timeframe, bars)
        events = load_latest_events(symbol=symbol, limit=1200)
        genes = load_genes()
        feature_state = load_feature_state()
        account = account_payload()
        positions = positions_payload(symbol)
        orderflow = load_orderflow_state(symbol, timeframe)
        orderflow_events = load_orderflow_events(symbol, limit=30)

        payload = {
            "ok": True,
            "cached": False,
            "candles": candles,
            "events": events,
            "genes": genes,
            "feature_state": feature_state,
            "account": account,
            "positions": positions,
            "orderflow": orderflow,
            "orderflow_events": orderflow_events,
        }
        _STATE_CACHE[cache_key] = (time.time(), payload)
        _LAST_STATE_PAYLOAD = payload
        return JSONResponse(payload)

    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "account": account_payload(),
            },
            status_code=500,
        )
    finally:
        _STATE_LOCK.release()


HTML = r'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>FRIDAY TradingView Scalper</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #0b1020;
      color: #e5e7eb;
      font-family: Arial, sans-serif;
      overflow: hidden;
    }
    .topbar {
      height: 56px;
      background: #111827;
      border-bottom: 1px solid #263244;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 14px;
    }
    .brand {
      font-size: 20px;
      font-weight: 900;
      color: #fff;
      margin-right: auto;
    }
    input, select, button {
      background: #0f172a;
      color: #e5e7eb;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 8px 10px;
      outline: none;
    }
    button { cursor: pointer; }
    .layout {
      display: grid;
      grid-template-columns: 1fr 410px;
      height: calc(100vh - 56px);
    }
    #chart {
      width: 100%;
      height: 100%;
    }
    .side {
      border-left: 1px solid #263244;
      background: #0f172a;
      padding: 12px;
      overflow-y: auto;
    }
    .card {
      background: #111827;
      border: 1px solid #263244;
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 12px;
    }
    .card h3 {
      margin: 0 0 10px;
      font-size: 15px;
    }
    .big {
      font-size: 32px;
      font-weight: 900;
      letter-spacing: 1px;
    }
    .buy { color: #22c55e; }
    .sell { color: #ef4444; }
    .hold { color: #eab308; }
    .muted { color: #94a3b8; font-size: 12px; }
    .row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin: 6px 0;
      font-size: 13px;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      background: #020617;
      border: 1px solid #263244;
      border-radius: 8px;
      padding: 8px;
      max-height: 220px;
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    td, th {
      border-bottom: 1px solid #263244;
      padding: 6px 4px;
      text-align: left;
    }
    .badge {
      display: inline-block;
      padding: 3px 7px;
      border-radius: 999px;
      background: #020617;
      border: 1px solid #334155;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">FRIDAY TradingView Scalper</div>
    <label>Symbol</label>
    <input id="symbol" value="XAUUSDm" style="width:120px" />
    <label>TF</label>
    <select id="timeframe">
      <option>M1</option>
      <option>M5</option>
      <option>M15</option>
      <option>H1</option>
      <option>H4</option>
      <option>D1</option>
    </select>
    <label>Bars</label>
    <input id="bars" type="number" value="120" style="width:80px" />
    <button onclick="refreshNow(true)">Refresh</button>
    <button onclick="fitChart()">Fit</button>
    <span id="status" class="muted">loading...</span>
  </div>

  <div class="layout">
    <div id="chart"></div>

    <div class="side">
      <div class="card">
        <h3>Decision</h3>
        <div id="action" class="big hold">WAIT</div>
        <div class="row"><span>Confidence</span><b id="confidence">-</b></div>
        <div class="row"><span>Buy Score</span><b id="buyScore">-</b></div>
        <div class="row"><span>Sell Score</span><b id="sellScore">-</b></div>
        <div class="row"><span>Spread</span><b id="spread">-</b></div>
        <div class="row"><span>Dynamic TP</span><b id="tp">-</b></div>
        <div class="row"><span>Log</span><span id="logPath" class="muted">-</span></div>
        <pre id="reason">-</pre>
      </div>

      <div class="card">
        <h3>Account</h3>
        <div class="row"><span>Server</span><b id="server">-</b></div>
        <div class="row"><span>Demo</span><b id="demo">-</b></div>
        <div class="row"><span>Balance</span><b id="balance">-</b></div>
        <div class="row"><span>Equity</span><b id="equity">-</b></div>
      </div>

      <div class="card">
        <h3>Open Positions</h3>
        <div id="positions">-</div>
      </div>

      <div class="card">
        <h3>Executions</h3>
        <div id="executions">-</div>
      </div>

      <div class="card">
        <h3>Feature Council A/B/C</h3>
        <div id="featureCouncil">-</div>
      </div>

      <div class="card">
        <h3>VWAP Panel</h3>
        <div id="vwapPanel">-</div>
      </div>

      <div class="card">
        <h3>Volume Profile / POC</h3>
        <div id="vpPanel">-</div>
      </div>

      <div class="card">
        <h3>Delta / CVD</h3>
        <div id="deltaPanel">-</div>
      </div>

      <div class="card">
        <h3>Order Flow Events</h3>
        <div id="ofEvents">-</div>
      </div>

      <div class="card">
        <h3>Absorption / Exhaustion</h3>
        <div id="absPanel">-</div>
      </div>

      <div class="card">
        <h3>Strategy Genes</h3>
        <div id="genes">-</div>
      </div>
    </div>
  </div>

<script>
let chart;
let candleSeries;
let ema20Series;
let ema50Series;
let forecastSeries;
let lastDecisionLine = null;
let lastTpLine = null;
let swingHighLine = null;
let swingLowLine = null;
let positionLines = [];
// Order Flow chart lines
let vwapLine = null;
let vwapUpperLine = null;
let vwapLowerLine = null;
let anchoredVwapLine = null;
let pocLine = null;
let vahLine = null;
let valLine = null;
let ofExtraLines = [];

function num(x, d=2) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "-";
  return Number(x).toFixed(d);
}

function initChart() {
  const el = document.getElementById("chart");
  chart = LightweightCharts.createChart(el, {
    layout: {
      background: { type: "solid", color: "#020617" },
      textColor: "#cbd5e1",
      fontFamily: "Arial",
    },
    grid: {
      vertLines: { color: "#111827" },
      horzLines: { color: "#111827" },
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: "#334155",
      autoScale: true,
    },
    timeScale: {
      borderColor: "#334155",
      timeVisible: true,
      secondsVisible: true,
    },
    watermark: {
      visible: true,
      fontSize: 24,
      horzAlign: "left",
      vertAlign: "top",
      color: "rgba(148, 163, 184, 0.18)",
      text: "FRIDAY",
    },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#22c55e",
    downColor: "#ef4444",
    borderUpColor: "#22c55e",
    borderDownColor: "#ef4444",
    wickUpColor: "#22c55e",
    wickDownColor: "#ef4444",
  });

  ema20Series = chart.addLineSeries({
    color: "#60a5fa",
    lineWidth: 2,
    title: "EMA20",
  });

  ema50Series = chart.addLineSeries({
    color: "#f97316",
    lineWidth: 2,
    title: "EMA50",
  });

  forecastSeries = chart.addLineSeries({
    color: "#a78bfa",
    lineWidth: 2,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    title: "Forecast",
  });

  window.addEventListener("resize", () => {
    chart.applyOptions({
      width: el.clientWidth,
      height: el.clientHeight,
    });
  });
}

function removeLines() {
  [lastDecisionLine, lastTpLine, swingHighLine, swingLowLine,
   vwapLine, vwapUpperLine, vwapLowerLine, anchoredVwapLine,
   pocLine, vahLine, valLine].forEach(l => {
    if (l) { try { candleSeries.removePriceLine(l); } catch(e) {} }
  });
  positionLines.forEach(l => { try { candleSeries.removePriceLine(l); } catch(e) {} });
  ofExtraLines.forEach(l => { try { candleSeries.removePriceLine(l); } catch(e) {} });

  lastDecisionLine = null;
  lastTpLine = null;
  swingHighLine = null;
  swingLowLine = null;
  vwapLine = null;
  vwapUpperLine = null;
  vwapLowerLine = null;
  anchoredVwapLine = null;
  pocLine = null;
  vahLine = null;
  valLine = null;
  positionLines = [];
  ofExtraLines = [];
}

function line(price, color, title, style=LightweightCharts.LineStyle.Solid) {
  return candleSeries.createPriceLine({
    price,
    color,
    lineWidth: 2,
    lineStyle: style,
    axisLabelVisible: true,
    title,
  });
}

function updateChart(state) {
  const c = state.candles;
  const decision = state.events.latest_decision || {};
  const positions = state.positions || [];

  candleSeries.setData(c.candles || []);
  ema20Series.setData(c.ema20 || []);
  ema50Series.setData(c.ema50 || []);

  const featureState = state.feature_state || {};
  const featureDecision = (featureState.decisions || [])[0] || {};
  const forecastCandles = ((featureDecision.forecast || {}).forecast_candles || []);

  if (forecastCandles.length && c.candles && c.candles.length) {
    const lastTime = c.candles[c.candles.length - 1].time;
    const tfSeconds = {
      "M1": 60,
      "M5": 300,
      "M15": 900,
      "H1": 3600,
      "H4": 14400,
      "D1": 86400,
    }[c.timeframe] || 60;

    forecastSeries.setData(forecastCandles.map(fc => ({
      time: lastTime + fc.step * tfSeconds,
      value: fc.close,
    })));
  } else {
    forecastSeries.setData([]);
  }

  removeLines();

  if (c.swing_high) {
    swingHighLine = line(c.swing_high, "#38bdf8", "Swing High", LightweightCharts.LineStyle.Dashed);
  }

  if (c.swing_low) {
    swingLowLine = line(c.swing_low, "#38bdf8", "Swing Low", LightweightCharts.LineStyle.Dashed);
  }

  if (decision && decision.close) {
    const color = decision.action === "BUY" ? "#22c55e" : decision.action === "SELL" ? "#ef4444" : "#eab308";
    lastDecisionLine = line(decision.close, color, `${decision.action} ${num(decision.close, 2)}`);
  }

  if (decision && decision.tp_level) {
    lastTpLine = line(decision.tp_level, "#a78bfa", `Dynamic TP ${num(decision.tp_level, 2)}`, LightweightCharts.LineStyle.Dashed);
  }

  positions.forEach(p => {
    const color = p.type === "BUY" ? "#22c55e" : "#ef4444";
    positionLines.push(line(p.price_open, color, `OPEN ${p.type} #${p.ticket}`, LightweightCharts.LineStyle.Solid));

    if (p.tp && p.tp > 0) {
      positionLines.push(line(p.tp, "#a78bfa", `TP #${p.ticket}`, LightweightCharts.LineStyle.Dashed));
    }

    if (p.sl && p.sl > 0) {
      positionLines.push(line(p.sl, "#eab308", `SL #${p.ticket}`, LightweightCharts.LineStyle.Dotted));
    }
  });

  // --- VWAP lines from feature council state ---
  const vwapSummary = featureDecision.vwap_summary || {};

  if (vwapSummary.session_vwap) {
    vwapLine = line(vwapSummary.session_vwap, "#06b6d4", `sVWAP ${num(vwapSummary.session_vwap, 2)}`, LightweightCharts.LineStyle.Solid);
  }
  if (vwapSummary.anchored_vwap && vwapSummary.anchored_vwap !== vwapSummary.session_vwap) {
    anchoredVwapLine = line(vwapSummary.anchored_vwap, "#0891b2", `aVWAP ${num(vwapSummary.anchored_vwap, 2)}`, LightweightCharts.LineStyle.Dashed);
  }
  if (vwapSummary.vwap_band_upper) {
    vwapUpperLine = line(vwapSummary.vwap_band_upper, "#164e63", `VWAP+ ${num(vwapSummary.vwap_band_upper, 2)}`, LightweightCharts.LineStyle.Dotted);
  }
  if (vwapSummary.vwap_band_lower) {
    vwapLowerLine = line(vwapSummary.vwap_band_lower, "#164e63", `VWAP- ${num(vwapSummary.vwap_band_lower, 2)}`, LightweightCharts.LineStyle.Dotted);
  }

  // --- Volume Profile lines (POC/VAH/VAL) from orderflow state ---
  const of = state.orderflow || {};
  const vp = of.volume_profile || {};

  if (vp.poc) {
    pocLine = line(vp.poc, "#f59e0b", `POC ${num(vp.poc, 2)}`, LightweightCharts.LineStyle.Solid);
  }
  if (vp.vah) {
    vahLine = line(vp.vah, "#fb923c", `VAH ${num(vp.vah, 2)}`, LightweightCharts.LineStyle.Dashed);
  }
  if (vp.val) {
    valLine = line(vp.val, "#fb923c", `VAL ${num(vp.val, 2)}`, LightweightCharts.LineStyle.Dashed);
  }

  const markers = [];

  (state.events.executions || []).forEach(e => {
    const d = e.decision || {};
    if (!d.time || !d.close || !d.action) return;

    const ts = Math.floor(new Date(d.time).getTime() / 1000);

    markers.push({
      time: ts,
      position: d.action === "BUY" ? "belowBar" : "aboveBar",
      color: d.action === "BUY" ? "#22c55e" : "#ef4444",
      shape: d.action === "BUY" ? "arrowUp" : "arrowDown",
      text: `DEMO ${d.action}`,
    });
  });

  // --- Order Flow event markers (deduped by time+event_type+side) ---
  const seenOfKeys = new Set();
  (state.orderflow_events || []).forEach(e => {
    if (!e.created_at || !e.price) return;
    const ts = Math.floor(new Date(e.created_at).getTime() / 1000);
    const dedupeKey = `${ts}_${e.event_type}_${e.side}`;
    if (seenOfKeys.has(dedupeKey)) return;
    seenOfKeys.add(dedupeKey);
    const isBuy = e.side === "BUY";
    markers.push({
      time: ts,
      position: isBuy ? "belowBar" : "aboveBar",
      color: isBuy ? "#22d3ee" : "#f87171",
      shape: "circle",
      text: (e.event_type || "OF").replace(/_/g, " "),
    });
  });

  candleSeries.setMarkers(markers.sort((a, b) => a.time - b.time));

  chart.timeScale().scrollToRealTime();
}

function updateSide(state) {
  const decision = state.events.latest_decision || {};
  const account = state.account || {};
  const positions = state.positions || [];
  const executions = state.events.executions || [];
  const genes = state.genes || {};

  const action = decision.action || "WAIT";
  const actionEl = document.getElementById("action");

  actionEl.textContent = action;
  actionEl.className = "big " + (action === "BUY" ? "buy" : action === "SELL" ? "sell" : "hold");

  document.getElementById("confidence").textContent = num(decision.confidence, 4);
  document.getElementById("buyScore").textContent = num(decision.buy_score, 3);
  document.getElementById("sellScore").textContent = num(decision.sell_score, 3);
  document.getElementById("spread").textContent = num(decision.spread_points ?? state.candles.spread_points, 1);
  document.getElementById("tp").textContent = decision.tp_level ? `${num(decision.tp_level, 2)} (${num(decision.tp_points, 1)} pts)` : "-";
  document.getElementById("reason").textContent = decision.reason || "-";
  document.getElementById("logPath").textContent = state.events.log_path || "-";

  document.getElementById("server").textContent = account.server || "-";
  document.getElementById("demo").textContent = account.demo_detected ? "YES" : "NO";
  document.getElementById("balance").textContent = num(account.balance, 2);
  document.getElementById("equity").textContent = num(account.equity, 2);

  if (!positions.length) {
    document.getElementById("positions").innerHTML = '<span class="muted">No open positions</span>';
  } else {
    document.getElementById("positions").innerHTML = `
      <table>
        <tr><th>Type</th><th>Vol</th><th>Open</th><th>Profit</th></tr>
        ${positions.map(p => `
          <tr>
            <td class="${p.type === "BUY" ? "buy" : "sell"}">${p.type}</td>
            <td>${p.volume}</td>
            <td>${num(p.price_open, 2)}</td>
            <td>${num(p.profit, 2)}</td>
          </tr>
        `).join("")}
      </table>
    `;
  }

  if (!executions.length) {
    document.getElementById("executions").innerHTML = '<span class="muted">No executions in latest log for selected symbol</span>';
  } else {
    document.getElementById("executions").innerHTML = executions.slice(-10).reverse().map(e => {
      const d = e.decision || {};
      const r = e.execution_result || {};
      return `
        <div class="row">
          <span class="${d.action === "BUY" ? "buy" : "sell"}">${d.action || "-"}</span>
          <span>${d.symbol || "-"}</span>
          <span class="badge">${r.sent ? "SENT" : "FAILED"}</span>
        </div>
      `;
    }).join("");
  }


  const featureState = state.feature_state || {};
  const featureDecision = (featureState.decisions || [])[0] || {};
  const ga = featureDecision.group_a || {};
  const gb = featureDecision.group_b || {};
  const gc = featureDecision.group_c || {};

  if (featureDecision.symbol) {
    document.getElementById("featureCouncil").innerHTML = `
      <div class="row"><span>Action</span><b class="${featureDecision.action === "BUY" ? "buy" : featureDecision.action === "SELL" ? "sell" : "hold"}">${featureDecision.action || "-"}</b></div>
      <div class="row"><span>Exec</span><b>${featureDecision.execution_mode || "-"}</b></div>
      <div class="row"><span>Conf</span><b>${num(featureDecision.confidence, 4)}</b></div>
      <div class="row"><span>A Trend</span><b>${ga.buy_percent || "-"}% ${ga.vote || ""}</b></div>
      <div class="row"><span>B Flow</span><b>${gb.buy_percent || "-"}% ${gb.vote || ""}</b></div>
      <div class="row"><span>C Structure</span><b>${gc.buy_percent || "-"}% ${gc.vote || ""}</b></div>
      <div class="muted" style="margin-top:8px;word-break:break-word">${featureDecision.feature_signature || ""}</div>
    `;
  } else {
    document.getElementById("featureCouncil").innerHTML = '<span class="muted">No feature council state yet</span>';
  }

  // --- VWAP Panel ---
  const vwapSummary = featureDecision.vwap_summary || {};
  if (vwapSummary.session_vwap) {
    const vsig = vwapSummary.vwap_signal || "-";
    const sigColor = vsig === "VWAP_RECLAIM" ? "buy" : vsig === "VWAP_REJECTION" ? "sell" : vsig === "ABOVE_VWAP" ? "buy" : "sell";
    document.getElementById("vwapPanel").innerHTML = `
      <div class="row"><span>Signal</span><b class="${sigColor}">${vsig}</b></div>
      <div class="row"><span>Session VWAP</span><b>${num(vwapSummary.session_vwap, 2)}</b></div>
      <div class="row"><span>Anchored VWAP</span><b>${num(vwapSummary.anchored_vwap, 2)}</b></div>
      <div class="row"><span>Band Upper</span><b>${num(vwapSummary.vwap_band_upper, 2)}</b></div>
      <div class="row"><span>Band Lower</span><b>${num(vwapSummary.vwap_band_lower, 2)}</b></div>
      <div class="row"><span>Deviation (ATR)</span><b>${num(vwapSummary.vwap_deviation, 3)}</b></div>
    `;
  } else {
    document.getElementById("vwapPanel").innerHTML = '<span class="muted">No VWAP data yet — run feature engine</span>';
  }

  // --- Volume Profile Panel ---
  const ofData = state.orderflow || {};
  const vpData = ofData.volume_profile || {};
  if (vpData.poc) {
    const locColor = vpData.price_location_vs_value_area === "ABOVE_VALUE" ? "buy" :
                     vpData.price_location_vs_value_area === "BELOW_VALUE" ? "sell" : "hold";
    document.getElementById("vpPanel").innerHTML = `
      <div class="row"><span>Location</span><b class="${locColor}">${vpData.price_location_vs_value_area || "-"}</b></div>
      <div class="row"><span>POC</span><b>${num(vpData.poc, 2)}</b></div>
      <div class="row"><span>VAH</span><b>${num(vpData.vah, 2)}</b></div>
      <div class="row"><span>VAL</span><b>${num(vpData.val, 2)}</b></div>
      <div class="row"><span>Dist to POC (pts)</span><b>${vpData.distance_to_poc_points ?? "-"}</b></div>
      <div class="muted" style="font-size:11px;margin-top:4px">${vpData.note || ""}</div>
    `;
  } else {
    document.getElementById("vpPanel").innerHTML = '<span class="muted">No volume profile — run orderflow engine</span>';
  }

  // --- Delta / CVD Panel ---
  const deltaData = ofData.delta_features || {};
  if (deltaData.bar_delta_proxy !== undefined) {
    const divColor = deltaData.delta_divergence === "BULLISH_DIVERGENCE" ? "buy" :
                     deltaData.delta_divergence === "BEARISH_DIVERGENCE" ? "sell" : "";
    document.getElementById("deltaPanel").innerHTML = `
      <div class="row"><span>Bar Delta</span><b>${num(deltaData.bar_delta_proxy, 1)}</b></div>
      <div class="row"><span>Cum Delta</span><b>${num(deltaData.cumulative_delta_proxy, 1)}</b></div>
      <div class="row"><span>Session Delta</span><b>${num(deltaData.session_delta_proxy, 1)}</b></div>
      <div class="row"><span>Divergence</span><b class="${divColor}">${deltaData.delta_divergence || "-"}</b></div>
      <div class="row"><span>Vol Spike</span><b>${num(deltaData.volume_spike_score, 2)}x</b></div>
      <div class="row"><span>Body Efficiency</span><b>${num(deltaData.body_efficiency, 3)}</b></div>
      <div class="row"><span>Wick Absorption</span><b>${num(deltaData.wick_absorption_score, 3)}</b></div>
      <div class="muted" style="font-size:11px;margin-top:4px">${deltaData.note || ""}</div>
    `;
  } else {
    document.getElementById("deltaPanel").innerHTML = '<span class="muted">No delta data — run orderflow engine</span>';
  }

  // --- Order Flow Events Panel ---
  const ofEvents = state.orderflow_events || [];
  if (ofEvents.length) {
    document.getElementById("ofEvents").innerHTML = ofEvents.slice(-8).reverse().map(e => {
      const isBuy = e.side === "BUY";
      return `
        <div style="font-size:12px;margin-bottom:7px;border-left:3px solid ${isBuy ? "#22c55e" : "#ef4444"};padding-left:7px">
          <b class="${isBuy ? "buy" : "sell"}">${e.event_type || "-"}</b>
          <span class="muted"> ${e.timeframe || ""}</span><br/>
          <span class="muted">${e.reason || ""}</span><br/>
          <span class="muted">conf=${num(e.confidence, 2)} @ ${num(e.price, 2)}</span>
        </div>
      `;
    }).join("");
  } else {
    document.getElementById("ofEvents").innerHTML = '<span class="muted">No order flow events detected</span>';
  }

  // --- Absorption / Exhaustion Panel ---
  const absData = ofData.absorption_exhaustion || {};
  if (Object.keys(absData).length) {
    const flags = [
      ["absorption_buy", "Absorption BUY", "buy"],
      ["absorption_sell", "Absorption SELL", "sell"],
      ["exhaustion_buy", "Exhaustion BUY (→ SELL?)", "sell"],
      ["exhaustion_sell", "Exhaustion SELL (→ BUY?)", "buy"],
      ["aggressive_buy_burst", "Aggressive BUY Burst", "buy"],
      ["aggressive_sell_burst", "Aggressive SELL Burst", "sell"],
      ["unfinished_auction_high_proxy", "Unfinished High", "hold"],
      ["unfinished_auction_low_proxy", "Unfinished Low", "hold"],
    ];
    document.getElementById("absPanel").innerHTML = flags.map(([key, label, cls]) => {
      const active = absData[key];
      return `<div class="row"><span>${label}</span><b class="${active ? cls : "muted"}">${active ? "YES" : "no"}</b></div>`;
    }).join("") + `<div class="muted" style="font-size:11px;margin-top:4px">${absData.note || ""}</div>`;
  } else {
    document.getElementById("absPanel").innerHTML = '<span class="muted">No absorption data — run orderflow engine</span>';
  }

  const geneList = Object.values(genes.genes || {});
  geneList.sort((a, b) => (b.score || 0) - (a.score || 0));

  if (!geneList.length) {
    document.getElementById("genes").innerHTML = '<span class="muted">No strategy genes yet</span>';
  } else {
    document.getElementById("genes").innerHTML = geneList.slice(0, 8).map(g => `
      <div style="font-size:12px;margin-bottom:9px">
        <b>score=${num(g.score, 2)}</b>
        boost=${num(g.confidence_boost, 3)}
        seen=${g.seen || 0}
        W/L/N=${g.wins || 0}/${g.losses || 0}/${g.neutral || 0}
        <div class="muted">${String(g.gene_id || "").slice(0, 150)}</div>
      </div>
    `).join("");
  }
}

let refreshInFlight = false;

async function refreshNow(forceFit=false) {
  if (refreshInFlight && !forceFit) {
    return;
  }
  refreshInFlight = true;
  const symbol = document.getElementById("symbol").value || "XAUUSDm";
  const timeframe = document.getElementById("timeframe").value || "M1";
  const bars = document.getElementById("bars").value || "120";

  try {
    const res = await fetch(`/api/state?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&bars=${bars}`);
    const state = await res.json();

    if (!state.ok) {
      document.getElementById("status").textContent = "ERROR: " + state.error;
      return;
    }

    updateChart(state);
    updateSide(state);

    if (forceFit) {
      fitChart();
    }

    document.getElementById("status").textContent = "updated " + new Date().toLocaleTimeString();

  } catch (err) {
    document.getElementById("status").textContent = "ERROR: " + err;
  } finally {
    refreshInFlight = false;
  }
}

function fitChart() {
  chart.timeScale().fitContent();
}

initChart();
refreshNow(true);
setInterval(() => refreshNow(false), 3000);
</script>
</body>
</html>
'''


def main() -> None:
    uvicorn.run(
        "friday_scalper_live_dashboard:app",
        host="127.0.0.1",
        port=8822,
        reload=False,
    )


if __name__ == "__main__":
    main()
