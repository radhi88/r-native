"""telegram_bot.py — J.3 — Mobile alerts + remote commands via Telegram.

Setup:
  1. Create a bot via @BotFather → get token
  2. Send /start to your bot, then visit https://api.telegram.org/bot<TOKEN>/getUpdates
     to find your chat_id
  3. Save to data/r_native/telegram.json:
     { "enabled": true, "bot_token": "...", "chat_id": 123456789,
       "events": {"trade_open":true, "trade_close":true, "freeze":true,
                  "daily_cap":true, "deploy":true, "daily_summary":true} }

Commands available from your phone:
  /stats          → today's P/L + trades
  /today          → recent trades list
  /executor       → R Executor status
  /pause          → set kill_switch.txt (graceful)
  /kill           → emergency stop ALL trading
  /deployed       → which genome is active on each symbol

Uses only stdlib `urllib` — no extra deps (python-telegram-bot would be cleaner
but this works without `pip install`).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\telegram.json")
KILL_SWITCH = Path(r"C:\Users\Radhi\MT5\kill_switch.txt")
STATE_FILE  = Path(r"C:\Users\Radhi\MT5\friday_v3\data\r_executor_state.json")
SYMBOL_CFG  = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")

DEFAULTS = {
    "enabled":   False,
    "bot_token": "",
    "chat_id":   0,
    "events": {
        "trade_open":    True,
        "trade_close":   True,
        "freeze":        True,
        "daily_cap":     True,
        "deploy":        True,
        "daily_summary": True,
    },
    "command_polling_seconds": 30,
}

_last_update_id = 0
_polling_thread: threading.Thread | None = None
_stop = threading.Event()


def load() -> dict:
    if not CONFIG_PATH.exists(): return DEFAULTS.copy()
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = DEFAULTS.copy(); cfg.update(loaded)
        cfg["events"] = {**DEFAULTS["events"], **(loaded.get("events") or {})}
        return cfg
    except Exception:
        return DEFAULTS.copy()


def save(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── Send ──────────────────────────────────────────────────────────────
def _api(method: str, **kwargs) -> dict | None:
    cfg = load()
    if not cfg.get("enabled") or not cfg.get("bot_token"):
        return None
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/{method}"
    data = urllib.parse.urlencode(kwargs).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=data, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[telegram] {method} err: {e}")
        return None


def send(text: str, event: str = None, parse_mode: str = "HTML") -> bool:
    """Send a message to the configured chat. Respects per-event toggles."""
    cfg = load()
    if not cfg.get("enabled"): return False
    if event and not cfg.get("events", {}).get(event, True): return False
    chat_id = cfg.get("chat_id")
    if not chat_id: return False
    r = _api("sendMessage", chat_id=chat_id, text=text[:4000],
             parse_mode=parse_mode)
    return bool(r and r.get("ok"))


# ── Pre-canned alerts ─────────────────────────────────────────────────
def alert_trade_open(side: str, symbol: str, price: float,
                     sl: float, tp: float, magic: int = 20260605):
    send(f"🚀 <b>{side} {symbol}</b> @ {price:.3f}\n"
         f"   SL: {sl:.3f}   TP: {tp:.3f}\n"
         f"   magic: {magic}",
         event="trade_open")


def alert_trade_close(symbol: str, pl: float, reason: str = ""):
    emoji = "💰" if pl > 0 else "🛑" if pl < 0 else "⏹"
    send(f"{emoji} <b>{symbol} closed</b>\n"
         f"   P/L: <b>${pl:+.2f}</b>  ({reason})",
         event="trade_close")


def alert_freeze(reason: str):
    send(f"❄️ <b>R Executor frozen</b>\n   {reason}", event="freeze")


def alert_daily_cap(amount: float):
    send(f"🚨 <b>Daily loss cap hit</b>: ${amount:.2f}\n   Trading paused 24h",
         event="daily_cap")


def alert_deploy(genome_id: str, symbol: str, pf: float):
    send(f"📦 <b>Deployed {genome_id}</b> on {symbol}\n   PF {pf}",
         event="deploy")


def alert_daily_summary(today_pl: float, n_trades: int,
                        wins: int, deployed: dict):
    wr = wins / n_trades * 100 if n_trades else 0
    msg = (f"📊 <b>Daily summary</b> ({datetime.now(timezone.utc):%Y-%m-%d UTC})\n"
           f"   P/L:    <b>${today_pl:+.2f}</b>\n"
           f"   Trades: {n_trades}  ({wins} wins, {wr:.0f}% WR)\n")
    if deployed:
        msg += "   Active genomes:\n"
        for sym, gid in deployed.items():
            msg += f"      {sym}: {gid}\n"
    send(msg, event="daily_summary")


# ── Command listener (polls getUpdates) ───────────────────────────────
def _handle_command(cmd: str, chat_id: int) -> str:
    """Return reply text for a command. None = no reply."""
    cmd = (cmd or "").strip().lower()

    if cmd in ("/start", "/help"):
        return ("👋 <b>R Native bot</b>\n\n"
                "/stats     — today's P/L\n"
                "/today     — recent trades\n"
                "/executor  — R Executor status\n"
                "/deployed  — active genomes\n"
                "/pause     — set kill_switch (graceful stop)\n"
                "/kill      — emergency kill ALL trading\n"
                "/resume    — remove kill_switch")

    if cmd == "/stats":
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return (f"📊 Today P/L: <b>${s.get('today_pl',0):+.2f}</b>\n"
                    f"   Trades:  {s.get('today_trades',0)}\n"
                    f"   Wins:    {s.get('today_wins',0)}\n"
                    f"   Total:   ${s.get('total_pl',0):+.2f}")
        except Exception as e:
            return f"⚠️ stats unavailable: {e}"

    if cmd == "/today":
        try:
            import MetaTrader5 as mt5
            from datetime import timedelta
            if not mt5.initialize(): return "MT5 init failed"
            deals = mt5.history_deals_get(datetime.now() - timedelta(hours=24),
                                          datetime.now()) or []
            r = [d for d in deals if int(d.magic) == 20260605 and d.entry == 1]
            if not r: return "🟢 No R trades closed in last 24h"
            msg = "📋 <b>Last 5 R trades</b>:\n"
            for d in sorted(r, key=lambda x: -x.time)[:5]:
                ts = datetime.fromtimestamp(d.time).strftime("%H:%M")
                pl = d.profit + d.swap + d.commission
                emoji = "💰" if pl > 0 else "🛑"
                msg += f"   {emoji} {ts} {d.symbol} ${pl:+.2f}\n"
            return msg
        except Exception as e:
            return f"⚠️ {e}"

    if cmd == "/executor":
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            armed = "🟢 ARMED" if s.get("armed") else "🔴 OFFLINE"
            return (f"{armed}\n"
                    f"Mode: {s.get('mode','?')}\n"
                    f"Last: {s.get('last_action','—')[:100]}")
        except Exception:
            return "⚠️ R Executor not running"

    if cmd == "/deployed":
        msg = "📦 <b>Deployed genomes</b>:\n"
        for f in (SYMBOL_CFG.glob("*.json") if SYMBOL_CFG.exists() else []):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                dg = d.get("deployed_genome")
                if dg and dg.get("id"):
                    msg += f"   {d.get('symbol','?')}: {dg['id']} (PF {dg.get('profit_factor','?')})\n"
            except Exception: pass
        return msg if "\n" in msg else "No genomes deployed yet"

    if cmd == "/pause":
        KILL_SWITCH.write_text("paused via Telegram\n", encoding="utf-8")
        return "⏸ kill_switch.txt created — R Executor will stop on next cycle"

    if cmd == "/kill":
        KILL_SWITCH.write_text("EMERGENCY KILL via Telegram\n", encoding="utf-8")
        return "🛑 <b>EMERGENCY KILL</b> — all trading halted"

    if cmd == "/resume":
        try:
            KILL_SWITCH.unlink()
            return "▶️ kill_switch removed — restart R Executor manually to resume"
        except FileNotFoundError:
            return "kill_switch already removed"

    return f"Unknown command: {cmd}. Send /help"


def _poll_loop():
    global _last_update_id
    cfg = load()
    interval = max(5, int(cfg.get("command_polling_seconds", 30)))
    while not _stop.is_set():
        cfg = load()
        if not cfg.get("enabled"):
            _stop.wait(interval); continue
        r = _api("getUpdates", offset=_last_update_id + 1, timeout=25)
        if r and r.get("ok"):
            for upd in r.get("result", []):
                _last_update_id = max(_last_update_id, upd.get("update_id", 0))
                msg = upd.get("message") or {}
                if not msg.get("text", "").startswith("/"): continue
                chat_id = msg["chat"]["id"]
                if chat_id != cfg.get("chat_id"): continue   # ignore strangers
                reply = _handle_command(msg["text"], chat_id)
                if reply:
                    _api("sendMessage", chat_id=chat_id, text=reply,
                         parse_mode="HTML")
        _stop.wait(interval)


def start_command_listener():
    """Start the background command-poll thread."""
    global _polling_thread
    if _polling_thread and _polling_thread.is_alive(): return
    _stop.clear()
    _polling_thread = threading.Thread(target=_poll_loop, daemon=True,
                                       name="telegram-poll")
    _polling_thread.start()


def stop_command_listener():
    _stop.set()


# ── Smoke test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Telegram bot config check:")
    cfg = load()
    print(f"  enabled: {cfg['enabled']}")
    print(f"  token:   {'(set)' if cfg.get('bot_token') else '(missing)'}")
    print(f"  chat_id: {cfg.get('chat_id') or '(missing)'}")
    if cfg.get("enabled") and cfg.get("bot_token") and cfg.get("chat_id"):
        ok = send("🤖 Test message from R Native bot", event="trade_open")
        print(f"  test send: {'✓ ok' if ok else '✗ failed'}")
