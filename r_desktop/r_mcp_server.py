"""r_mcp_server.py - MCP server exposing R Factory to Claude.

Tools exposed:
  - r_status         get full executor + positions snapshot
  - r_trade_gate     ask whether R would trade now + why
  - r_levels         get all detected price levels
  - r_symbols        get ranked symbols + blacklist/whitelist
  - r_account        live account balance, equity, positions
  - r_close_position close a specific R position
  - r_kill_switch    activate kill switch (stops all R trading)
  - r_resume         remove kill switch
  - r_set_mode       switch PAPER/LIVE
  - r_training       run a training-mode session

Run alongside r_app.py - Claude connects via MCP protocol.
"""
import json
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
BRAIN_URL = "http://127.0.0.1:5055"


def _http_get(path: str, timeout: float = 10) -> dict:
    try:
        with urllib.request.urlopen(BRAIN_URL + path, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def r_status() -> dict:
    """Full R Factory snapshot - executor + account + open positions + mode."""
    ex = _http_get("/api/r/executor")
    acc = _http_get("/api/account?hours=24")
    return {"executor": ex, "account": acc}


def r_trade_gate(symbol: str = "XAUUSDm") -> dict:
    """What would R do RIGHT NOW for given symbol? Returns verdict + reasoning + entry plan."""
    return _http_get(f"/api/r/trade_gate?bypass_session=1&bypass_weekend=1&bypass_friday=1&symbol={symbol}")


def r_levels(symbol: str = "XAUUSDm") -> dict:
    """All detected price levels for symbol (PDH/PDL/VWAP/swings/FVGs/round numbers)."""
    return _http_get(f"/api/r/levels?symbol={symbol}")


def r_symbols() -> dict:
    """Ranked tradeable symbols + blacklist + whitelist."""
    return _http_get("/api/r/symbols")


def r_account() -> dict:
    """Account balance, equity, open positions with full detail."""
    return _http_get("/api/account?hours=48")


def r_learning() -> dict:
    """R's adaptive learning state - per-archetype stats + manual overrides."""
    return _http_get("/api/r/learning")


def r_training(symbol: str = "XAUUSDm") -> dict:
    """Run an offline training session - compare actual vs simulated."""
    return _http_get(f"/api/r/training?force=1&symbol={symbol}", timeout=60)


def r_kill_switch() -> dict:
    """Activate kill switch - stops all R trading immediately."""
    kill = PROJECT_ROOT / "kill_switch.txt"
    kill.write_text("kill", encoding="utf-8")
    return {"ok": True, "kill_switch_path": str(kill), "message": "R will exit on next cycle"}


def r_resume() -> dict:
    """Remove kill switch - R can resume on next launch."""
    kill = PROJECT_ROOT / "kill_switch.txt"
    if kill.exists():
        kill.unlink()
        return {"ok": True, "message": "kill switch removed"}
    return {"ok": True, "message": "kill switch was not active"}


def r_close_position(ticket: int) -> dict:
    """Close a specific R position by ticket number."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return {"ok": False, "error": "mt5 init failed"}
        pos = mt5.positions_get(ticket=int(ticket))
        if not pos:
            return {"ok": False, "error": f"position {ticket} not found"}
        p = pos[0]
        tick = mt5.symbol_info_tick(p.symbol)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": p.ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_BUY if p.type == 1 else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if p.type == 1 else tick.bid,
            "deviation": 30,
            "magic": p.magic,
            "comment": "MCP_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        mt5.shutdown()
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            return {"ok": True, "ticket": p.ticket, "close_price": res.price}
        return {"ok": False, "error": f"retcode {res.retcode if res else 'None'}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── MCP server using FastMCP if available, else expose as JSON-RPC ───
try:
    from fastmcp import FastMCP
    mcp = FastMCP("r-factory")

    @mcp.tool()
    def status() -> dict:
        """Get R Factory full status: executor mode, account balance, open positions."""
        return r_status()

    @mcp.tool()
    def trade_gate(symbol: str = "XAUUSDm") -> dict:
        """What R would do RIGHT NOW: GO/WAIT/NO + reasoning + proposed entry/SL/TP."""
        return r_trade_gate(symbol)

    @mcp.tool()
    def price_levels(symbol: str = "XAUUSDm") -> dict:
        """All price levels R has detected: PDH/PDL, VWAP+bands, FVGs, swings."""
        return r_levels(symbol)

    @mcp.tool()
    def symbols_ranking() -> dict:
        """Ranked tradeable symbols + blacklist + whitelist."""
        return r_symbols()

    @mcp.tool()
    def account_info() -> dict:
        """Account: balance, equity, open positions, recent deals."""
        return r_account()

    @mcp.tool()
    def learning_state() -> dict:
        """R's adaptive learning: per-archetype stats + manual override history."""
        return r_learning()

    @mcp.tool()
    def training_session(symbol: str = "XAUUSDm") -> dict:
        """Run an offline training session comparing actual vs simulated trading."""
        return r_training(symbol)

    @mcp.tool()
    def kill() -> dict:
        """EMERGENCY: stop all R trading immediately (creates kill_switch.txt)."""
        return r_kill_switch()

    @mcp.tool()
    def resume() -> dict:
        """Resume R trading (removes kill_switch.txt)."""
        return r_resume()

    @mcp.tool()
    def close_position(ticket: int) -> dict:
        """Manually close one R position by ticket number."""
        return r_close_position(ticket)

    if __name__ == "__main__":
        mcp.run()

except ImportError:
    # FastMCP not installed - expose as simple JSON-RPC HTTP server
    print("[r_mcp] FastMCP not installed. Run: pip install fastmcp")
    print("[r_mcp] Falling back to simple JSON-RPC stub")

    if __name__ == "__main__":
        from http.server import HTTPServer, BaseHTTPRequestHandler
        TOOLS = {
            "r_status": r_status, "r_trade_gate": r_trade_gate, "r_levels": r_levels,
            "r_symbols": r_symbols, "r_account": r_account, "r_learning": r_learning,
            "r_training": r_training, "r_kill_switch": r_kill_switch,
            "r_resume": r_resume, "r_close_position": r_close_position,
        }
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                ln = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(ln) or b"{}")
                tool = body.get("tool"); args = body.get("args", {})
                fn = TOOLS.get(tool)
                out = fn(**args) if fn else {"error": f"unknown tool {tool}"}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(out, default=str).encode())
            def log_message(self, *a, **k): pass
        srv = HTTPServer(("127.0.0.1", 5056), H)
        print("[r_mcp] JSON-RPC server on http://127.0.0.1:5056")
        print(f"[r_mcp] tools: {list(TOOLS.keys())}")
        srv.serve_forever()
