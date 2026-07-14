"""agent_bus_view.py — live visual viewer of the VS-agent <-> Claude bus.

Shows, auto-refreshing every 3s:
  • status (waiting for ASK / ASK pending / REPLY ready)
  • current ASK.md (what the VS agent asked)
  • current REPLY.md (Claude's answer)
  • LOG.md (the full agreed history / conversation)

Stdlib only. Run:  python agent_bus_view.py   →   http://127.0.0.1:5057/
"""
import http.server, socketserver, html
from pathlib import Path

BUS = Path(r"C:\Users\Radhi\MT5\r_native_v2\agent_bus")
PORT = 5057


def _read(name):
    try:
        return BUS.joinpath(name).read_text(encoding="utf-8").strip() or "(فارغ)"
    except Exception:
        return "(غير موجود)"


PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>قناة الوكلاء · VS ⇄ Claude</title>
<style>
:root{{--bg:#0b0e14;--card:#11151c;--bd:#1f2630;--fg:#e6edf3;--dim:#8b949e;--g:#3fb950;--y:#d29922;--b:#58a6ff;--p:#bc8cff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.7 system-ui,Segoe UI,Arial}}
.wrap{{max-width:1100px;margin:0 auto;padding:16px}}
h1{{font-size:16px;color:var(--dim);font-weight:700;margin:2px 0 12px}}
.status{{padding:10px 14px;border-radius:10px;font-weight:700;margin-bottom:14px;text-align:center;font-size:15px}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media(max-width:820px){{.row{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px}}
.card h2{{font-size:13px;margin:0 0 8px;font-weight:700}}
.vs h2{{color:var(--b)}}.cl h2{{color:var(--p)}}.log h2{{color:var(--y)}}
pre{{white-space:pre-wrap;word-break:break-word;margin:0;font:13px/1.7 Consolas,monospace;color:#cdd6e0;max-height:46vh;overflow:auto}}
.log{{margin-top:12px}}.log pre{{max-height:40vh}}
.t{{color:var(--dim);font-size:11px;text-align:left;margin-top:8px}}
</style></head><body><div class="wrap">
<h1>🔗 قناة الوكلاء — وكيل VS ⇄ Claude (حيّ، يتحدّث كل ٣ث)</h1>
<div class="status" style="background:{sbg};color:#0b0e14">{status}</div>
<div class="row">
  <div class="card vs"><h2>🟦 سؤال وكيل VS (ASK.md)</h2><pre>{ask}</pre></div>
  <div class="card cl"><h2>🟪 ردّ Claude (REPLY.md)</h2><pre>{reply}</pre></div>
</div>
<div class="card log"><h2>📜 السجل / اللي اتفقنا عليه (LOG.md)</h2><pre>{log}</pre></div>
<div class="t">المنفذ :5057 · يتحدّث تلقائياً</div>
</div></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ask_pending = (BUS / "ASK.flag").exists()
        reply_ready = (BUS / "REPLY.flag").exists()
        if ask_pending:
            status, sbg = "🟡 سؤال من VS بانتظار رد Claude…", "#d29922"
        elif reply_ready:
            status, sbg = "🟢 ردّ Claude جاهز — وكيل VS يقرأه وينفّذ", "#3fb950"
        else:
            status, sbg = "⚪ في انتظار سؤال جديد من وكيل VS", "#8b949e"
        page = PAGE.format(
            status=status, sbg=sbg,
            ask=html.escape(_read("ASK.md")),
            reply=html.escape(_read("REPLY.md")),
            log=html.escape(_read("LOG.md")))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), H) as s:
        print(f"agent_bus viewer → http://127.0.0.1:{PORT}/", flush=True)
        s.serve_forever()
