# -*- coding: utf-8 -*-
"""server.py — يخدم رسم منظومة FRIDAY القوّة-الموجّه الحيّ على :8012 (وصول جوّال عبر Tailscale).
GET / = الواجهة (D3) · GET /graph.json = الطوبولوجيا+الحالة الحيّة · GET /gaps = الفجوات فقط.
قفل مفرد (منفذ 8013) يمنع التكدّس. windowless تحت الوصيّ. قراءة-فقط (لا تداول)."""
from __future__ import annotations
import json, socket, sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
import importlib.util
_spec = importlib.util.spec_from_file_location("sysgraph", HERE / "graph.py")
graph = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(graph)

app = FastAPI()
NOCACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


@app.get("/")
def index():
    return FileResponse(HERE / "index.html", headers=NOCACHE)


@app.get("/graph.json")
def graph_json():
    try:
        return JSONResponse(graph.build(), headers=NOCACHE)
    except Exception as e:
        return JSONResponse({"error": str(e), "nodes": [], "edges": [], "gaps": {}}, headers=NOCACHE)


@app.get("/node")
def node(id: str):
    try:
        return JSONResponse(graph.node_detail(id), headers=NOCACHE)
    except Exception as e:
        return JSONResponse({"error": str(e), "id": id}, headers=NOCACHE)


@app.get("/gaps")
def gaps():
    try:
        return JSONResponse(graph.build()["gaps"], headers=NOCACHE)
    except Exception as e:
        return JSONResponse({"error": str(e)}, headers=NOCACHE)


def _singleton(port=8013):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind(("127.0.0.1", port)); s.listen(1); return s
    except OSError:
        return None


if __name__ == "__main__":
    lock = _singleton()
    if lock is None:
        sys.exit(0)                       # نسخة أخرى تعمل
    # pythonw بلا stdout ⇒ تسجيل uvicorn ينهار. نعيد التوجيه لملفّ أوّلاً (درس rbridge).
    try:
        _lf = open(HERE / "graph_server.out.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = _lf
    except Exception:
        pass
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8012, log_level="warning")
