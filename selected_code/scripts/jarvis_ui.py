import argparse
import json
import mimetypes
import queue
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from _bootstrap import bootstrap

ROOT = bootstrap()

from mt5_ai.jarvis_assistant import JarvisAssistant, JarvisState
from mt5_ai.auto_paper_trader import AutoPaperTrader
from mt5_ai.event_bus import EventBus
from mt5_ai.local_mind import LocalMind
from mt5_ai.local_speaker import LocalSpeaker
from mt5_ai.local_voice import LocalVoiceService
from mt5_ai.agents import AgentRunner
from mt5_ai.heatmap import build_heatmap_payload
from mt5_ai.market_structure import add_market_structure
from mt5_ai.config import JOURNAL_DIR
from mt5_ai.polymarket import get_btc_markets


WEB_DIR = ROOT / "web" / "jarvis"
DB_PATH = JOURNAL_DIR / "jarvis_memory.sqlite3"


def fetch_rows(conn, query, params=()):
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def supervisor_snapshot():
    if not DB_PATH.exists():
        return {"available": False, "reason": "memory_db_missing", "path": str(DB_PATH)}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "available": True,
            "heartbeat": fetch_rows(
                conn,
                "SELECT * FROM autonomous_heartbeat ORDER BY updated_at DESC LIMIT 3",
            ),
            "symbol_profile_state": fetch_rows(
                conn,
                """
                SELECT symbol, profile, confidence, observations, wins, losses, net_points, updated_at
                FROM autonomous_symbol_profile_state
                ORDER BY confidence DESC, net_points DESC
                LIMIT 20
                """,
            ),
            "research_summary": fetch_rows(
                conn,
                """
                SELECT symbol, profile, COUNT(*) AS observations,
                       SUM(CASE WHEN points > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(points) AS net_points
                FROM autonomous_research_outcomes
                GROUP BY symbol, profile
                ORDER BY net_points DESC
                LIMIT 20
                """,
            ),
            "open_positions": fetch_rows(
                conn,
                "SELECT * FROM autonomous_positions WHERE status = 'open' ORDER BY opened_at DESC",
            ),
            "agent_adjustments": fetch_rows(
                conn,
                """
                SELECT profile, symbol, side, points, close_reason, thresholds_json, updated_at
                FROM autonomous_agent_adjustments
                ORDER BY id DESC
                LIMIT 10
                """,
            ),
        }
    finally:
        conn.close()


class JarvisWebApp:
    def __init__(
        self,
        source,
        profile,
        symbol,
        timeframe,
        allow_live,
        auto_voice=False,
        auto_paper=False,
        speak=True,
    ):
        self.events = EventBus()
        state = JarvisState(
            source=source,
            profile=profile,
            symbol=symbol,
            timeframe=timeframe,
        )
        self.assistant = JarvisAssistant(state=state, allow_live=allow_live)
        self.mind = LocalMind(event_bus=self.events)
        self.speaker = LocalSpeaker(enabled=speak)
        self.voice = LocalVoiceService(
            event_bus=self.events,
            command_callback=self.handle_voice_command,
        )
        self.auto_paper = AutoPaperTrader(
            assistant=self.assistant,
            event_bus=self.events,
        )
        self.agent_runner = AgentRunner(
            symbol=symbol,
            event_bus=self.events,
            assistant=self.assistant,
            auto_start=True,          # starts immediately — no user command needed
        )
        if auto_voice:
            self.voice.start()
        if auto_paper:
            self.auto_paper.start()

    def handle_voice_command(self, command):
        result = self.mind.chat(command, self.assistant)
        answer = result.get("answer")
        if answer:
            self.speaker.speak(answer)
        return {
            "command": command,
            "answer": answer,
            "tool_result": result.get("tool_result"),
        }

    def close(self):
        self.voice.stop()
        self.auto_paper.stop()
        self.agent_runner.stop()
        self.speaker.stop()
        self.assistant.close()


def _mt5_deep_inspect(app) -> dict:
    """Expose every useful MT5 API surface — all account, position, history, and feed data."""
    feed = getattr(app.agent_runner, "_live_feed", None)
    if not (feed and feed._connected):
        return {"error": "MT5 not connected"}
    mt5 = feed._mt5
    try:
        acc   = mt5.account_info()
        term  = mt5.terminal_info()
        pos   = mt5.positions_get() or []
        hist  = mt5.history_deals_get(
            __import__("datetime").datetime.now() - __import__("datetime").timedelta(hours=24),
            __import__("datetime").datetime.now(),
        ) or []
        orders = mt5.orders_get() or []

        def _acc(a):
            if not a: return {}
            return {k: getattr(a, k, None) for k in [
                "login","server","balance","equity","margin","margin_free","margin_level",
                "profit","credit","currency","leverage","name","company","trade_mode"
            ]}

        def _pos(p):
            return {k: getattr(p, k, None) for k in [
                "ticket","symbol","type","volume","price_open","sl","tp",
                "price_current","profit","swap","comment","time"
            ]}

        def _deal(d):
            return {k: getattr(d, k, None) for k in [
                "ticket","order","time","type","entry","symbol",
                "volume","price","profit","swap","fee","comment"
            ]}

        def _ord(o):
            return {k: getattr(o, k, None) for k in [
                "ticket","symbol","type","volume_initial","price_open","sl","tp","comment","time_setup"
            ]}

        return {
            "account":       _acc(acc),
            "terminal":      dict(term._asdict()) if term else {},
            "positions":     [_pos(p) for p in pos],
            "pending_orders": [_ord(o) for o in orders],
            "last_24h_deals": [_deal(d) for d in list(hist)[-50:]],
            "last_error":    mt5.last_error(),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _mt5_process_inspect() -> dict:
    """Read MT5 terminal64.exe process stats — CPU, RAM, threads, handles, modules."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "exe", "memory_info",
                                          "cpu_percent", "num_threads", "status",
                                          "create_time"]):
            if proc.info["name"] and "terminal64" in proc.info["name"].lower():
                p = psutil.Process(proc.info["pid"])
                p.cpu_percent()   # prime the counter
                import time; time.sleep(0.3)
                mem   = p.memory_info()
                conns = []
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        if hasattr(p, "net_connections"):
                            raw_conns = p.net_connections()
                        else:
                            raw_conns = p.connections()
                    for c in raw_conns:
                        conns.append({
                            "local":  f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                            "remote": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
                            "status": getattr(c, "status", ""),
                        })
                except Exception:
                    pass
                return {
                    "pid":          proc.info["pid"],
                    "name":         proc.info["name"],
                    "exe":          proc.info["exe"],
                    "status":       proc.info["status"],
                    "cpu_pct":      round(p.cpu_percent(), 2),
                    "ram_mb":       round(mem.rss / 1e6, 1),
                    "virtual_mb":   round(mem.vms / 1e6, 1),
                    "threads":      p.num_threads(),
                    "connections":  conns,
                    "uptime_min":   round((__import__("time").time() - proc.info["create_time"]) / 60, 1),
                }
        return {"error": "terminal64.exe not found — is MT5 running?"}
    except Exception as exc:
        return {"error": str(exc)}


_MT5_LOG_DIR = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\53785E099C927DB68A545C249CDBCE06\logs")


def _mt5_log_tail(lines: int = 40) -> dict:
    """Read the last N lines from MT5 terminal log (UTF-16 LE format)."""
    import datetime
    try:
        today = datetime.datetime.now().strftime("%Y%m%d")
        log_file = _MT5_LOG_DIR / f"{today}.log"
        if not log_file.exists():
            # try yesterday
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
            log_file = _MT5_LOG_DIR / f"{yesterday}.log"
        if not log_file.exists():
            return {"error": "log file not found", "path": str(log_file)}
        raw  = log_file.read_bytes()
        text = raw.decode("utf-16-le", errors="replace")
        all_lines = [" ".join(l.split()) for l in text.splitlines() if l.strip()]
        tail = all_lines[-lines:]
        # Parse into structured records
        records = []
        for line in tail:
            parts = line.split(None, 4)
            if len(parts) >= 4:
                records.append({
                    "code": parts[0],
                    "flag": parts[1],
                    "time": parts[2],
                    "module": parts[3],
                    "message": parts[4] if len(parts) > 4 else "",
                })
            else:
                records.append({"raw": line})
        return {"lines": records, "file": log_file.name, "total": len(all_lines)}
    except Exception as exc:
        return {"error": str(exc)}


def _mt5_symbols(app) -> dict:
    """Return all tradable symbols with current bid/ask/spread."""
    feed = getattr(app.agent_runner, "_live_feed", None)
    if not (feed and feed._connected):
        return {"error": "MT5 not connected"}
    mt5 = feed._mt5
    try:
        symbols = mt5.symbols_get() or []
        result = []
        for s in symbols:
            if not s.visible:
                continue
            tick = mt5.symbol_info_tick(s.name)
            result.append({
                "name":   s.name,
                "bid":    round(float(tick.bid), 5) if tick else None,
                "ask":    round(float(tick.ask), 5) if tick else None,
                "spread": round((tick.ask - tick.bid) * 10, 1) if tick else None,
                "digits": s.digits,
                "category": s.path.split("\\")[0] if s.path else "",
            })
        result.sort(key=lambda x: x["name"])
        return {"symbols": result, "count": len(result)}
    except Exception as exc:
        return {"error": str(exc)}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw or "{}")

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/status":
                self._send_json(
                    {
                        "assistant": app.assistant.status(),
                        "mind": app.mind.status(),
                        "voice": app.voice.status(),
                        "speaker": app.speaker.status(),
                        "auto_paper": app.auto_paper.status(),
                        "agents": app.agent_runner.status(),
                        "supervisor": supervisor_snapshot(),
                    }
                )
                return
            if parsed.path == "/api/supervisor/status":
                self._send_json(supervisor_snapshot())
                return
            if parsed.path == "/api/agents/status":
                self._send_json(app.agent_runner.status())
                return
            if parsed.path == "/api/mt5/stream":
                feed = getattr(app.agent_runner, "_live_feed", None)
                if feed and feed._connected:
                    self._send_json(feed.get_tick_snapshot())
                else:
                    self._send_json({"error": "MT5 feed not connected"}, status=503)
                return
            if parsed.path == "/api/mt5/deep":
                self._send_json(_mt5_deep_inspect(app))
                return
            if parsed.path == "/api/mt5/symbols":
                self._send_json(_mt5_symbols(app))
                return
            if parsed.path == "/api/mt5/process":
                self._send_json(_mt5_process_inspect())
                return
            if parsed.path == "/api/mt5/log":
                from urllib.parse import parse_qs
                qs = parse_qs(parsed.query)
                n  = int((qs.get("n") or ["40"])[0])
                self._send_json(_mt5_log_tail(n))
                return
            if parsed.path == "/api/polymarket":
                try:
                    self._send_json(get_btc_markets())
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=500)
                return
            if parsed.path == "/api/multiscan":
                self._send_json(getattr(app.agent_runner, "_last_scan_result", {"markets": []}))
                return
            if parsed.path == "/api/heatmap":
                try:
                    df = app.assistant.load_market_data()
                    enriched = add_market_structure(df)
                    payload = build_heatmap_payload(enriched)
                    self._send_json(payload)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=500)
                return
            if parsed.path == "/api/events":
                self._send_events()
                return

            path = "index.html" if parsed.path in {"/", ""} else parsed.path.lstrip("/")
            file_path = (WEB_DIR / path).resolve()
            if not str(file_path).startswith(str(WEB_DIR.resolve())) or not file_path.exists():
                self.send_error(404)
                return

            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_events(self):
            subscriber = app.events.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            app.events.publish("client_connected", {"message": "sse_connected"})
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=15)
                    except queue.Empty:
                        event = {"type": "ping", "payload": {}, "timestamp": time.time()}
                    self.wfile.write(app.events.encode_sse(event))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                app.events.unsubscribe(subscriber)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/chat":
                    text = payload.get("text") or payload.get("message") or ""
                    app.events.publish("thinking", {"source": "chat"})
                    result = app.mind.chat(text, app.assistant)
                    answer = result.get("answer", "")
                    app.speaker.speak(answer)
                    app.events.publish("speaking", {"answer": answer})
                    self._send_json(result)
                    return
                if parsed.path == "/api/analyze":
                    decision = app.assistant.analyze()
                    app.events.publish("analysis", decision)
                    self._send_json({"decision": decision})
                    return
                if parsed.path == "/api/scan":
                    limit = int(payload.get("limit", 60) or 60)
                    scan = app.assistant.scan_markets(limit=limit)
                    app.events.publish("market_scan", scan)
                    self._send_json({"scan": scan})
                    return
                if parsed.path == "/api/trade":
                    decision = app.assistant.analyze()
                    result = app.assistant.execute_decision(decision)
                    app.events.publish("trade", result)
                    self._send_json(result)
                    return
                if parsed.path == "/api/trade/scan":
                    limit = int(payload.get("limit", 60) or 60)
                    max_orders = int(payload.get("max_orders", 3) or 3)
                    result = app.assistant.execute_market_scan_paper(limit=limit, max_orders=max_orders)
                    app.events.publish("market_scan_trade", result)
                    self._send_json(result)
                    return
                if parsed.path == "/api/autopaper/start":
                    self._send_json(app.auto_paper.start())
                    return
                if parsed.path == "/api/autopaper/stop":
                    self._send_json(app.auto_paper.stop())
                    return
                if parsed.path == "/api/autopaper/status":
                    self._send_json(app.auto_paper.status())
                    return
                if parsed.path == "/api/autopaper/mode":
                    mode = payload.get("mode", "paper")
                    self._send_json(app.auto_paper.set_execution_mode(mode))
                    return
                if parsed.path == "/api/autopaper/promote-demo":
                    self._send_json(app.auto_paper.promote_open_positions_to_demo())
                    return
                if parsed.path == "/api/mode":
                    self._send_json({"message": app.assistant.set_mode(payload.get("mode", "paper"))})
                    return
                if parsed.path == "/api/profile":
                    self._send_json({"message": app.assistant.set_profile(payload.get("profile", ""))})
                    return
                if parsed.path == "/api/source":
                    source = payload.get("source")
                    if source not in {"csv", "mt5"}:
                        self._send_json({"error": "source must be csv or mt5"}, status=400)
                        return
                    app.assistant.state.source = source
                    self._send_json({"message": f"source set to {source}"})
                    return
                if parsed.path == "/api/agents/start":
                    self._send_json(app.agent_runner.start())
                    return
                if parsed.path == "/api/agents/stop":
                    self._send_json(app.agent_runner.stop())
                    return
                if parsed.path == "/api/trade/market":
                    side   = payload.get("side", "BUY").upper()
                    lot    = float(payload.get("lot", 0.01))
                    sl     = float(payload["sl"]) if payload.get("sl") else None
                    tp     = float(payload["tp"]) if payload.get("tp") else None
                    decision = app.assistant.analyze()
                    price  = float(decision.get("close", 0))
                    result = app.assistant.paper_executor.execute(
                        symbol=app.assistant.state.symbol,
                        side=side, price=price, lot=lot, sl=sl, tp=tp,
                    )
                    app.events.publish("agent_trade_open", {
                        "agent": "manual", "side": side, "order_type": "MARKET",
                        "price": price, "lot": lot, "sl": sl, "tp": tp,
                        "symbol": app.assistant.state.symbol,
                    })
                    self._send_json({"result": result.to_dict() if hasattr(result, "to_dict") else result})
                    return
                if parsed.path == "/api/trade/pending":
                    side        = payload.get("side", "BUY").upper()
                    order_type  = payload.get("order_type", "LIMIT").upper()
                    limit_price = float(payload.get("limit_price", 0))
                    lot         = float(payload.get("lot", 0.01))
                    sl          = float(payload["sl"]) if payload.get("sl") else None
                    tp          = float(payload["tp"]) if payload.get("tp") else None
                    app.events.publish("agent_trade_open", {
                        "agent": "manual", "side": side, "order_type": order_type,
                        "price": limit_price, "lot": lot, "sl": sl, "tp": tp,
                        "symbol": app.assistant.state.symbol,
                    })
                    self._send_json({"queued": True, "side": side,
                                     "order_type": order_type, "limit_price": limit_price,
                                     "lot": lot, "sl": sl, "tp": tp})
                    return
                if parsed.path == "/api/voice/start":
                    self._send_json(app.voice.start())
                    return
                if parsed.path == "/api/voice/stop":
                    self._send_json(app.voice.stop())
                    return
                if parsed.path == "/api/voice/status":
                    self._send_json(app.voice.status())
                    return
                if parsed.path == "/api/speaker/status":
                    self._send_json(app.speaker.status())
                    return
                if parsed.path == "/api/speaker/say":
                    self._send_json(app.speaker.speak(payload.get("text", "")))
                    return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
                return

            self.send_error(404)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source", choices=["csv", "mt5"], default="mt5")
    parser.add_argument("--profile", default="scalping")
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--timeframe", default="M1")
    parser.add_argument("--allow-live", action="store_true", help="Ignored; live mode is disabled.")
    parser.add_argument("--auto-voice", action="store_true")
    parser.add_argument("--auto-paper", action="store_true")
    parser.add_argument("--no-speak", action="store_true")
    args = parser.parse_args()

    app = JarvisWebApp(
        source=args.source,
        profile=args.profile,
        symbol=args.symbol,
        timeframe=args.timeframe,
        allow_live=args.allow_live,
        auto_voice=args.auto_voice,
        auto_paper=args.auto_paper,
        speak=not args.no_speak,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    url = f"http://{args.host}:{args.port}"
    print(f"Jarvis UI running: {url}")
    print("Open it in a browser. Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()


if __name__ == "__main__":
    main()
