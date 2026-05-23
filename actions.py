"""actions.py - All R Native action handlers (wires up buttons to real work).

Every button in app.py UI delegates to one of these functions.
Keeps app.py focused on layout while logic lives here.
"""
from __future__ import annotations
import json
import subprocess
import sys
import os
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

PROJECT_ROOT = Path(r"C:\Users\Radhi\MT5")
DATA_DIR     = PROJECT_ROOT / "data" / "r_native"
CONFIG_DIR   = DATA_DIR / "symbol_configs"
INTEL_DIR    = DATA_DIR / "symbol_intel"
LEARN_DIR    = DATA_DIR / "symbol_learning"
CAMPAIGN_DIR = DATA_DIR / "campaigns"

R_MAGIC = 20260605
BRAIN_URL = "http://127.0.0.1:5055"


# ─── MT5 helpers ───
def _ensure_mt5() -> bool:
    if mt5.account_info() is None:
        try: mt5.shutdown()
        except Exception: pass
        return mt5.initialize()
    return True


def get_account_snapshot() -> dict:
    if not _ensure_mt5(): return {"ok": False, "error": "mt5 init"}
    info = mt5.account_info()
    if not info: return {"ok": False}
    positions = []
    open_pl = 0.0
    for p in (mt5.positions_get() or []):
        if p.magic == R_MAGIC:
            age = (datetime.now().timestamp() - p.time) / 60
            positions.append({
                "ticket": p.ticket, "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume, "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl, "tp": p.tp, "profit": round(p.profit, 2),
                "age_min": round(age, 1), "comment": p.comment,
            })
            open_pl += p.profit
    # Today P/L
    deals = mt5.history_deals_get(datetime.now() - timedelta(hours=24), datetime.now()) or []
    r_closed = [d for d in deals if d.magic == R_MAGIC and d.entry == 1]
    today_pl = sum(d.profit + d.swap + d.commission for d in r_closed)
    return {
        "ok": True,
        "balance": info.balance, "equity": info.equity,
        "free_margin": info.margin_free, "leverage": info.leverage,
        "currency": info.currency, "trade_allowed": info.trade_allowed,
        "positions": positions, "positions_count": len(positions),
        "open_pl": round(open_pl, 2),
        "today_pl": round(today_pl, 2),
        "today_trades": len(r_closed),
        "today_wins": sum(1 for d in r_closed if d.profit > 0),
    }


def get_trade_gate(symbol: str = "BTCUSDm") -> dict:
    """Pull trade_gate verdict from brain_server (with bypass)."""
    try:
        url = (f"{BRAIN_URL}/api/r/trade_gate"
               f"?bypass_session=1&bypass_weekend=1&bypass_friday=1&symbol={symbol}")
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"verdict": "OFFLINE", "error": str(e)}


def get_price_levels(symbol: str = "BTCUSDm") -> dict:
    try:
        with urllib.request.urlopen(f"{BRAIN_URL}/api/r/levels?symbol={symbol}", timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_multi_tf(symbol: str = "BTCUSDm") -> dict:
    try:
        with urllib.request.urlopen(f"{BRAIN_URL}/api/multi_tf?symbol={symbol}", timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_algory_intel() -> dict:
    try:
        with urllib.request.urlopen(f"{BRAIN_URL}/api/algory", timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Trading actions ───
def close_position(ticket: int) -> dict:
    if not _ensure_mt5(): return {"ok": False, "error": "mt5"}
    pos = mt5.positions_get(ticket=int(ticket))
    if not pos: return {"ok": False, "error": "position not found"}
    p = pos[0]
    tick = mt5.symbol_info_tick(p.symbol)
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol,
        "volume": p.volume,
        "type": mt5.ORDER_TYPE_BUY if p.type == 1 else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if p.type == 1 else tick.bid,
        "deviation": 30, "magic": p.magic,
        "comment": "R_MANUAL_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        return {"ok": True, "ticket": p.ticket, "close_price": res.price}
    return {"ok": False, "error": f"retcode={res.retcode if res else 'None'}"}


def close_all_r_positions() -> dict:
    if not _ensure_mt5(): return {"ok": False}
    closed = []; failed = []
    for p in (mt5.positions_get() or []):
        if p.magic == R_MAGIC:
            r = close_position(p.ticket)
            (closed if r["ok"] else failed).append(p.ticket)
    return {"ok": True, "closed": closed, "failed": failed}


def deploy_genome_to_live(symbol: str, genome_id: str, tf: str) -> dict:
    """Mark this genome as the active deployment for R Executor to use."""
    cfg_path = CONFIG_DIR / f"{symbol}.json"
    if not cfg_path.exists():
        return {"ok": False, "error": "symbol config missing"}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # Find the genome in ga_strategies
    target = None
    for s in cfg.get("ga_strategies", []):
        if s.get("id") == genome_id:
            target = s; break
    if not target:
        return {"ok": False, "error": f"genome {genome_id} not in vault"}
    cfg["deployed_genome"]    = target
    cfg["deployed_at"]        = datetime.now(timezone.utc).isoformat()
    cfg["tradeable"]          = True
    cfg["best_archetype"]     = "GA_EVOLVED"
    cfg["best_tf"]            = tf
    cfg["best_pf"]            = target.get("profit_factor", 0)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok":            True,
        "symbol":        symbol,
        "genome_id":     genome_id,
        "tf":            tf,
        "profit_factor": target.get("profit_factor", 0),
        "deployed_at":   cfg["deployed_at"],
        "cfg_path":      str(cfg_path),
    }