"""prop_firm.py — FTMO/MFF-style compliance gates.

Use case: traders on funded accounts (FTMO, MyForexFunds, FundedNext, etc.)
have strict rules; violating them = account terminated. This module gives
R Native the checks Algory has built-in.

Loaded by trade_gate.py before any GO verdict.

Configurable via data/r_native/prop_firm.json. Example:
{
  "enabled": true,
  "mode": "FTMO",
  "news_filter_mins": 30,
  "no_open_on_news_day": true,
  "daily_dd_limit_pct": 4.0,
  "max_aggregate_risk_pct": 5.0,
  "friday_close_hour_utc": 19,
  "profit_target_pct": 10.0,
  "use_profit_target": false,
  "symbol_lock": true
}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\prop_firm.json")
NEWS_PATH   = Path(r"C:\Users\Radhi\MT5\friday_v3\data\news_calendar.json")

# FTMO defaults — safe out-of-the-box
DEFAULTS = {
    "enabled":                False,    # opt-in
    "mode":                   "FTMO",
    "news_filter_mins":       30,        # block trades ±30min around high-impact news
    "no_open_on_news_day":    True,      # if ANY high-impact news today on symbol's currency
    "daily_dd_limit_pct":     4.0,       # FTMO: 5%, leave 1% safety margin
    "max_aggregate_risk_pct": 5.0,       # sum of open SL risks
    "friday_close_hour_utc":  19,        # close all positions by Friday 19:00 UTC
    "profit_target_pct":      10.0,
    "use_profit_target":      False,     # if hit, stop trading for the month
    "symbol_lock":            True,      # one symbol at a time
    "use_no_open_news_day":   True,
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded); return cfg
    except Exception:
        return DEFAULTS.copy()


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── News filter ────────────────────────────────────────────────────────
def _load_news_events() -> list:
    if not NEWS_PATH.exists(): return []
    try:
        data = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
        return data.get("events") or data if isinstance(data, dict) else data
    except Exception:
        return []


def _symbol_currencies(symbol: str) -> set:
    """Extract currencies relevant to a symbol (e.g. EURUSDm → {EUR, USD})."""
    base = symbol.upper().rstrip("M").rstrip("_")
    cur = set()
    known = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD",
             "XAU", "XAG", "BTC", "ETH", "OIL", "GAS"]
    for k in known:
        if k in base: cur.add(k)
    return cur


def news_blackout(symbol: str, now: datetime | None = None,
                  cfg: dict | None = None) -> dict:
    """Check if we're inside a news blackout window for `symbol`."""
    cfg = cfg or load_config()
    if not cfg.get("enabled"): return {"blocked": False, "reason": "prop_firm disabled"}
    if not cfg.get("news_filter_mins"): return {"blocked": False, "reason": "news_filter off"}

    now = now or datetime.now(timezone.utc)
    events = _load_news_events()
    if not events: return {"blocked": False, "reason": "no calendar data"}
    minutes = int(cfg["news_filter_mins"])
    relevant_curr = _symbol_currencies(symbol)

    for ev in events:
        if (ev.get("impact") or "").lower() not in ("high", "red", "3"): continue
        ev_curr = (ev.get("currency") or ev.get("country") or "").upper()
        if relevant_curr and ev_curr and ev_curr not in relevant_curr: continue
        # Parse event time
        ts = ev.get("ts") or ev.get("time") or ev.get("date")
        try:
            ev_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else \
                    datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except Exception:
            continue
        if ev_dt.tzinfo is None: ev_dt = ev_dt.replace(tzinfo=timezone.utc)
        delta = (ev_dt - now).total_seconds() / 60.0
        if -minutes <= delta <= minutes:
            return {"blocked": True, "reason":
                    f"news blackout: {ev.get('title','?')} {ev_curr} in {delta:+.0f}min"}

    # "No open on news day" — block if ANY high-impact today
    if cfg.get("no_open_on_news_day"):
        for ev in events:
            if (ev.get("impact") or "").lower() not in ("high", "red", "3"): continue
            ev_curr = (ev.get("currency") or ev.get("country") or "").upper()
            if relevant_curr and ev_curr and ev_curr not in relevant_curr: continue
            ts = ev.get("ts") or ev.get("time") or ev.get("date")
            try:
                ev_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else \
                        datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                continue
            if ev_dt.tzinfo is None: ev_dt = ev_dt.replace(tzinfo=timezone.utc)
            if ev_dt.date() == now.date():
                return {"blocked": True, "reason":
                        f"no_open_on_news_day: {ev_curr} news today"}

    return {"blocked": False, "reason": "no news block"}


# ── Daily drawdown ────────────────────────────────────────────────────
def daily_dd_check(start_balance: float, current_equity: float,
                   cfg: dict | None = None) -> dict:
    """Check if daily drawdown limit is breached (FTMO 5%, MFF 4%, etc.)."""
    cfg = cfg or load_config()
    if not cfg.get("enabled"): return {"blocked": False, "reason": "off"}
    limit_pct = float(cfg.get("daily_dd_limit_pct", 4.0))
    if start_balance <= 0: return {"blocked": False, "reason": "no balance"}
    dd_pct = (start_balance - current_equity) / start_balance * 100
    if dd_pct >= limit_pct:
        return {"blocked": True, "reason":
                f"daily DD {dd_pct:.2f}% ≥ limit {limit_pct}%",
                "dd_pct": round(dd_pct, 2)}
    return {"blocked": False, "reason": f"DD {dd_pct:.2f}% < {limit_pct}%",
            "dd_pct": round(dd_pct, 2)}


# ── Friday close ──────────────────────────────────────────────────────
def friday_close_check(now: datetime | None = None,
                       cfg: dict | None = None) -> dict:
    """Block new trades after Friday close hour. Existing positions should be
    closed by the executor."""
    cfg = cfg or load_config()
    if not cfg.get("enabled"): return {"blocked": False}
    now = now or datetime.now(timezone.utc)
    if now.weekday() != 4: return {"blocked": False}   # Friday
    cutoff_hour = int(cfg.get("friday_close_hour_utc", 19))
    if now.hour >= cutoff_hour:
        return {"blocked": True, "reason":
                f"Friday close: now {now:%H:%M} ≥ {cutoff_hour:02d}:00 UTC"}
    return {"blocked": False, "reason":
            f"Friday {now:%H:%M} < {cutoff_hour:02d}:00 UTC"}


# ── Max aggregate risk ────────────────────────────────────────────────
def aggregate_risk_check(open_positions: list, balance: float,
                         cfg: dict | None = None) -> dict:
    """Sum risk-to-SL across open positions; block if > limit %."""
    cfg = cfg or load_config()
    if not cfg.get("enabled"): return {"blocked": False}
    if balance <= 0: return {"blocked": False, "reason": "no balance"}
    limit_pct = float(cfg.get("max_aggregate_risk_pct", 5.0))
    total_risk = 0.0
    for p in open_positions or []:
        entry = float(p.get("price_open", 0) or 0)
        sl    = float(p.get("sl", 0) or 0)
        vol   = float(p.get("volume", 0) or 0)
        if not (entry and sl and vol): continue
        # rough USD risk (multiplier per asset class would refine)
        risk = abs(entry - sl) * vol * 100  # gold contract size proxy
        total_risk += risk
    risk_pct = total_risk / balance * 100
    if risk_pct >= limit_pct:
        return {"blocked": True, "reason":
                f"agg risk {risk_pct:.2f}% ≥ {limit_pct}%"}
    return {"blocked": False, "reason":
            f"agg risk {risk_pct:.2f}% < {limit_pct}%"}


# ── Profit target ─────────────────────────────────────────────────────
def profit_target_check(start_balance: float, current_equity: float,
                        cfg: dict | None = None) -> dict:
    """If profit target enabled and reached, stop trading."""
    cfg = cfg or load_config()
    if not cfg.get("enabled") or not cfg.get("use_profit_target"):
        return {"blocked": False}
    target_pct = float(cfg.get("profit_target_pct", 10.0))
    if start_balance <= 0: return {"blocked": False}
    ret_pct = (current_equity - start_balance) / start_balance * 100
    if ret_pct >= target_pct:
        return {"blocked": True, "reason":
                f"🏆 profit target hit ({ret_pct:.2f}% ≥ {target_pct}%) — stop trading"}
    return {"blocked": False, "reason":
            f"{ret_pct:.2f}% / {target_pct}% target"}


# ── Symbol lock ───────────────────────────────────────────────────────
def symbol_lock_check(symbol: str, open_positions: list,
                      cfg: dict | None = None) -> dict:
    """If symbol_lock enabled, only allow trading the symbol already open."""
    cfg = cfg or load_config()
    if not cfg.get("enabled") or not cfg.get("symbol_lock"):
        return {"blocked": False}
    if not open_positions: return {"blocked": False, "reason": "no open positions"}
    open_syms = {p.get("symbol") for p in open_positions if p.get("symbol")}
    if open_syms and symbol not in open_syms:
        return {"blocked": True, "reason":
                f"symbol_lock: {symbol} not in active set {open_syms}"}
    return {"blocked": False}


# ── Master gate: run all checks ───────────────────────────────────────
def all_checks(symbol: str, account: dict, open_positions: list = None,
               now: datetime | None = None) -> dict:
    """One-shot master check. Returns dict with overall verdict + per-check details."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return {"ok": True, "reason": "prop firm checks disabled", "enabled": False}
    open_positions = open_positions or []
    balance = float(account.get("balance", 0) or 0)
    equity  = float(account.get("equity",  balance) or balance)
    # Reload start_balance from state if available — else use today's first deposit
    # (simplification: use balance - today_pl proxy if no state)
    start_balance = balance   # caller can override

    checks = {
        "news":        news_blackout(symbol, now, cfg),
        "daily_dd":    daily_dd_check(start_balance, equity, cfg),
        "friday":      friday_close_check(now, cfg),
        "agg_risk":    aggregate_risk_check(open_positions, balance, cfg),
        "profit_tgt":  profit_target_check(start_balance, equity, cfg),
        "sym_lock":    symbol_lock_check(symbol, open_positions, cfg),
    }
    blockers = [name for name, r in checks.items() if r.get("blocked")]
    return {
        "ok":       not blockers,
        "blockers": blockers,
        "checks":   checks,
        "enabled":  True,
        "mode":     cfg.get("mode", "FTMO"),
    }
