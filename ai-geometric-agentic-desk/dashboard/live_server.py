"""Live professional web dashboard with an animated workflow graph.

Serves a single self-contained RTL (Arabic) page that polls ``/state`` and
renders, in real time:

* an animated workflow graph whose agent nodes pulse as they work and whose
  edges flow as data passes through the coordination bus;
* the live equity curve, open positions, and account snapshot;
* the evolving exam scoreboard, the gene hall of fame, the indicator registry;
* a merged live insight feed from every agent.

Stdlib only (``http.server``) — no FastAPI/Flask/websocket dependency. The
client polls once per second, which is comfortably real-time for a desk.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
from data import bus

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover
    mt5 = None

_PORT = 8780
_HTML = os.path.join(os.path.dirname(__file__), "live.html")


def _state() -> dict:
    """Merge all bus slices and add a live account snapshot."""
    data = bus.read_all()
    for name, sl in data.items():
        sl["_age"] = round(bus.age(sl), 1)
    acct = None
    if mt5 is not None:
        ai = mt5.account_info()
        if ai is not None:
            server = (ai.server or "").lower()
            acct = {"login": ai.login, "server": ai.server, "equity": round(ai.equity, 2),
                    "free_margin": round(ai.margin_free, 2),
                    "margin_level": round(ai.margin_level, 1) if ai.margin_level else 0,
                    "demo": ("trial" in server or "demo" in server)}
    return {"slices": data, "account": acct, "magic": config.EXEC_MAGIC,
            "gates": {"require_exam_pass": config.REQUIRE_EXAM_PASS,
                      "min_conf": config.MIN_CONFLUENCES,
                      "ml_gate": config.ML_CONFIDENCE_GATE,
                      "max_pos": config.MAX_CONCURRENT_POSITIONS,
                      "reversal": config.ENABLE_REVERSAL}}


class _Handler(BaseHTTPRequestHandler):
    """Serves the page and the JSON state endpoint."""

    def log_message(self, *args) -> None:  # silence access logging
        pass

    def do_GET(self) -> None:
        """Route ``/`` to the page and ``/state`` to JSON."""
        if self.path.startswith("/state"):
            body = json.dumps(_state(), default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            with open(_HTML, "rb") as fh:
                body = fh.read()
        except OSError:
            body = b"<h1>live.html missing</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = _PORT) -> None:
    """Start the dashboard HTTP server (blocking)."""
    if mt5 is not None:
        mt5.initialize()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[dashboard] live at http://127.0.0.1:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
