"""
hub_dashboard.py — B3.1: visual read-only dashboard for the R Native 2 hub.

One page for all markets (the user's "see everything" view). Stdlib only, zero deps,
read-only, zero execution.

Architecture (avoids CORS, keeps the hub the single data source):
  • Binds 127.0.0.1:8801 (loopback).
  • GET /      → an HTML page (inline CSS+JS) that polls /data every 3s.
  • GET /data  → server-side fetch of the hub's http://127.0.0.1:8800/{health,state},
                 merged and returned same-origin. Pure read proxy — never writes/executes.

Run:  python r_native_v2/hub_dashboard.py   (then open http://127.0.0.1:8801)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8801
HUB = "http://127.0.0.1:8800"
ROOT = Path(__file__).resolve().parent
DASH_LOCK = ROOT / "data" / "hub_dash.lock"   # heartbeat + single-instance
HEARTBEAT_INTERVAL = 15


DATA = ROOT / "data"
MARKET_CANDIDATES = DATA / "market_candidates.json"


def _hub_get(path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{HUB}{path}", timeout=4) as r:
            return json.loads(r.read())
    except Exception as exc:  # noqa: BLE001 — fail-closed, surface as error to the page
        return {"_error": str(exc)}


def _read_json(p: Path) -> dict:
    """Read a local data JSON, read-only. Fail-soft: surface the error, never raise."""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def _read_vol_regimes() -> dict:
    """Map symbol -> vol_regime_<SYM>.json (state/target_mult/...). Local read, not the hub."""
    out: dict = {}
    try:
        for f in DATA.glob("vol_regime_*.json"):
            sym = f.stem[len("vol_regime_"):]
            try:
                out[sym] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — skip a single bad file, keep the rest
                continue
    except Exception:  # noqa: BLE001
        pass
    return out


PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>R Native 2 — Hub</title>
<style>
 :root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--tx:#e6edf3;--dim:#8b949e;--grn:#2ea043;--red:#da3633;--amb:#d29922}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 "Segoe UI",system-ui,sans-serif}
 header{padding:14px 20px;border-bottom:1px solid var(--bd);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 h1{font-size:17px;margin:0} .pill{font-size:12px;color:var(--dim)}
 .wrap{padding:18px;display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));max-width:1400px;margin:0 auto}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px}
 .card h2{font-size:13px;margin:0 0 10px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
 table{width:100%;border-collapse:collapse} td,th{padding:6px 8px;text-align:right;border-bottom:1px solid var(--bd);font-size:13px}
 th{color:var(--dim);font-weight:600} .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-left:6px}
 .g{background:var(--grn)} .r{background:var(--red)} .a{background:var(--amb)}
 .pos{color:var(--grn)} .neg{color:var(--red)} .muted{color:var(--dim)}
 .big{font-size:22px;font-weight:700} .row{display:flex;justify-content:space-between;align-items:center;margin:4px 0}
 #err{color:var(--red);padding:0 20px}
</style></head><body>
<header><h1>🏛 R Native 2 — Hub</h1><span class="pill" id="hdr">…</span><span class="pill" id="clock"></span></header>
<div id="err"></div><div class="wrap" id="wrap">loading…</div>
<script>
const fmtAge=s=>s==null?"—":s<90?s.toFixed(0)+"s":s<5400?(s/60).toFixed(0)+"m":(s/3600).toFixed(1)+"h";
const money=v=>v==null?"—":(v>=0?"+":"")+v.toFixed(2);
const dot=(ok,age)=>{let c=!ok?"r":(age!=null&&age<120?"g":"a");return `<span class="dot ${c}"></span>`};
async function tick(){
 try{
  const d=await (await fetch("/data")).json();
  document.getElementById("err").textContent="";
  const h=d.health||{},s=d.state||{};
  document.getElementById("hdr").textContent=`hub ${h.hub||"?"} v${h.version||"?"} · pid ${h.pid||"?"} · hb ${fmtAge(h.hub_heartbeat_age_s)}`;
  document.getElementById("clock").textContent=s.ts||"";
  let H="";
  // live traders + pnl
  const lt=s.live_traders||{},pnl=s.pnl||{};
  // ---- totals (file-only: sum net_today + float across bots; equity needs MT5) ----
  let totNet=0,totFloat=0,haveNet=false,haveFloat=false;
  for(const k in pnl){const p=pnl[k]||{};
    let n=p.today?p.today.net:(p.data?p.data.net_today:null);
    if(n!=null){totNet+=n;haveNet=true}
    let f=p.data?p.data.float:null; if(f!=null){totFloat+=f;haveFloat=true}}
  const nc=v=>v>=0?"pos":"neg";
  H+=`<div class="card"><h2>إجمالي الحساب (ملفات فقط — الحقوق تحتاج MT5)</h2>
    <div class="row"><span class="muted">صافي اليوم (كل البوتات)</span><span class="big ${haveNet?nc(totNet):'muted'}">${haveNet?money(totNet):"—"}</span></div>
    <div class="row"><span class="muted">العائم المفتوح</span><span class="big ${haveFloat?nc(totFloat):'muted'}">${haveFloat?money(totFloat):"—"}</span></div></div>`;
  // ---- per-bot ----
  H+=`<div class="card"><h2>المتداولون المباشرون (PnL)</h2><table><tr><th>بوت</th><th>Magic</th><th>اليوم</th><th>عائم</th><th>صفقات</th><th>حياة</th></tr>`;
  for(const k in lt){const t=lt[k],p=pnl[k]||{};
    let net=p.today?p.today.net:(p.data?p.data.net_today:null);
    let flt=p.data?p.data.float:null;
    let tr=p.today?p.today.trades:(p.data?p.data.closed_today:null);
    H+=`<tr><td>${dot(t.present,t.age_s)}${k}</td><td>${t.magic}</td><td class="${net==null?'muted':nc(net)}">${money(net)}</td><td class="${flt==null?'muted':nc(flt)}">${money(flt)}</td><td>${tr??"—"}</td><td class="muted">${fmtAge(t.age_s)}</td></tr>`;}
  H+=`</table></div>`;
  // markets — trades? / signals? per symbol (F2-a flags) + direction from signal files
  const uni=(s.universe&&s.universe.symbols)||[];
  const sig0=(s.common_files&&s.common_files.signals)||{};
  if(uni.length){
   H+=`<div class="card"><h2>الأسواق (تداول / إشارة)</h2><table><tr><th>رمز</th><th>الحالة</th><th>الاتجاه</th><th>24/7</th></tr>`;
   for(const m of uni){
     let badge=m.enabled?`<span class="dot g"></span>يتداول`:(m.signals?`<span class="dot" style="background:#2f81f7"></span>إشارة فقط`:`<span class="dot" style="background:#6e7681"></span>معطّل`);
     const j=sig0[m.symbol],dd=(j&&j.data)||{},rg=dd.regime||{};
     const dir=(rg.htf_dir||dd.dominant||"").toUpperCase();
     const dc=dir.includes("BUY")||dir.includes("LONG")?"pos":(dir.includes("SELL")||dir.includes("SHORT")?"neg":"muted");
     H+=`<tr><td>${m.symbol}</td><td>${badge}</td><td class="${dc}">${dd.action||dir||"—"}</td><td>${m.always_open?"✓":"—"}</td></tr>`;
   }
   H+=`</table></div>`;
  }
  // personas
  const per=s.personas||{};
  H+=`<div class="card"><h2>الجينات لكل رمز (${Object.keys(per).filter(x=>x[0]!=="_").length})</h2><table><tr><th>رمز</th><th>جين</th><th>Lot</th><th>SL/TP</th><th>24/7</th></tr>`;
  for(const sym in per){if(sym[0]==="_")continue;const v=per[sym];if(!v.ok){H+=`<tr><td>${sym}</td><td class="muted" colspan=4>${v.reason||"—"}</td></tr>`;continue;}
    H+=`<tr><td>${sym}</td><td class="muted">${v.name||"—"}</td><td>${v.lot??"—"}</td><td>${v.sl_pts??"—"}/${v.tp_pts??"—"}</td><td>${v.always_open?"✓":"—"}</td></tr>`;}
  H+=`</table></div>`;
  // HUB-view: per-currency analysis (entry/sl/tp/rr · 5m/15m/1h · vol_regime · votes · chart link)
  const sigAll=(s.common_files&&s.common_files.signals)||{};
  const vrAll=d.vol_regime||{};
  // vol_regime → Arabic label + color (هبوب=expansion, طبيعي=normal, انكماش=contraction)
  const VRM={expansion:["هبوب","#da3633"],normal:["طبيعي","#2ea043"],contraction:["انكماش","#2f81f7"]};
  const num=v=>(v==null?"—":(+v).toLocaleString("en-US",{maximumFractionDigits:5}));
  if(Object.keys(sigAll).filter(x=>x[0]!=="_").length){
   H+=`<div class="card" style="grid-column:1/-1"><h2>تحليل كل عملة — HUB-view (دخول/وقف/هدف · 5m/15m/1h · تذبذب · أصوات)</h2>`;
   const chip=(k,v)=>{const c=v>0.05?"var(--grn)":(v<-0.05?"var(--red)":"#6e7681");return `<span style="display:inline-block;margin:2px;padding:1px 6px;border-radius:6px;background:${c}22;color:${c};font-size:12px">${k} ${(+v).toFixed(2)}</span>`};
   const tfCell=(tfs,k)=>{const v=tfs[k]||"—";const c=v.includes("BUY")?"pos":(v.includes("SELL")?"neg":"muted");return `<span class="${c}" style="display:inline-block;margin-left:8px"><span class="muted">${k}</span> ${v}</span>`};
   for(const sym in sigAll){if(sym[0]==="_")continue;const j=sigAll[sym];if(!j.ok){continue;}
     const sd=j.data||{},rg=sd.regime||{},comp=sd.components||{},bd=sd.breakdown||{},lv=sd.levels||{};
     const ac=sd.action==="BUY"?"pos":(sd.action==="SELL"?"neg":"muted");
     const dir=(rg.htf_dir||sd.dominant||"").toUpperCase();
     const vr=vrAll[sym]||{},vm=VRM[vr.state]||["—","#6e7681"];
     const vrBadge=vr.state?`<span style="display:inline-block;margin-right:6px;padding:1px 7px;border-radius:6px;background:${vm[1]}22;color:${vm[1]};font-size:12px">تذبذب: ${vm[0]} · هدف ×${(vr.target_mult??1).toFixed(1)}</span>`:"";
     const tfs=bd.timeframes||{};
     const tfRow=Object.keys(tfs).length?`<div style="font-size:12px;margin:3px 0">${["5m","15m","1h"].map(k=>tfCell(tfs,k)).join("")}</div>`:"";
     const lvRow=(lv.entry!=null)?`<div style="font-size:12px;margin:3px 0"><span class="muted">دخول</span> ${num(lv.entry)} · <span class="muted">وقف</span> <span class="neg">${num(lv.sl)}</span> · <span class="muted">هدف</span> <span class="pos">${num(lv.tp)}</span> · <span class="muted">R:R</span> ${lv.rr??"—"}</div>`:"";
     H+=`<div style="border-top:1px solid var(--bd);padding:8px 0">
        <div class="row"><span><b>${sym}</b> <span class="${ac}">${sd.action||"—"}</span> ${vrBadge}<span class="muted">conv ${sd.conviction??"—"} · agree ${sd.agree||"—"} · adx ${rg.adx??"—"} · ${dir}</span></span>
        <a href="http://127.0.0.1:8866?sym=${sym}" target="_blank" style="color:#2f81f7;font-size:12px">شارت ↗</a></div>
        ${lvRow}${tfRow}
        <div class="muted" style="font-size:12px">${bd.tf_consensus||""} · ${bd.order_flow||""}</div>
        <div>${Object.keys(comp).map(k=>chip(k,comp[k])).join("")}</div>
        <div class="muted" style="font-size:12px">${(sd.reason||"").slice(0,120)}</div></div>`;
   }
   H+=`</div>`;
  }
  // market candidates — F2-b discovery (display only · "مُكتشَف — غير مفعّل")
  const mc=d.market_candidates||{},mct=(mc.top||[]).slice(0,8);
  if(mct.length){
   H+=`<div class="card" style="grid-column:1/-1"><h2>مرشّحو الأسواق الجدد — اكتشاف فقط (مسح ${mc.scanned??"—"} رمزاً)</h2>
     <table><tr><th>رمز</th><th>score</th><th>سبريد(pts)</th><th>ATR%</th><th>تذبذب</th><th>هدف</th><th>الحالة</th></tr>`;
   for(const c of mct){const vm=VRM[c.vol_state]||["—","#6e7681"];
     H+=`<tr><td><b>${c.symbol}</b></td><td>${c.score??"—"}</td><td>${c.spread_pts??"—"}</td><td>${c.atr_pct??"—"}</td>
        <td style="color:${vm[1]}">${vm[0]}</td><td>×${c.target_mult??"—"}</td>
        <td class="muted"><span class="dot" style="background:#6e7681"></span>مُكتشَف — غير مفعّل</td></tr>`;}
   H+=`</table></div>`;
  }
  // engines + common files
  const eng=h.engines||{},cf=s.common_files||{};
  H+=`<div class="card"><h2>المحرّكات</h2><table>`;
  for(const k in eng){const e=eng[k];H+=`<tr><td>${dot(e.present,e.age_s)}${k}</td><td class="muted">${fmtAge(e.age_s)}</td><td class="muted">${e.alive_source||""}</td></tr>`;}
  H+=`</table></div>`;
  // signals (regime per symbol)
  const sig=(cf.signals)||{};
  H+=`<div class="card"><h2>إشارات الشارت (Common/Files)</h2><table><tr><th>رمز</th><th>action</th><th>regime adx</th><th>عمر</th></tr>`;
  for(const sym in sig){if(sym[0]==="_")continue;const j=sig[sym];if(!j.ok){H+=`<tr><td>${sym}</td><td class="muted" colspan=3>${j.reason||"—"}</td></tr>`;continue;}
    const dd=j.data||{},rg=dd.regime||{};
    const dir=(rg.htf_dir||dd.dominant||"").toUpperCase();
    const rc=dir.includes("BUY")||dir.includes("LONG")?"pos":(dir.includes("SELL")||dir.includes("SHORT")?"neg":"muted");
    const ac=(dd.action==="BUY")?"pos":(dd.action==="SELL"?"neg":"muted");
    H+=`<tr><td>${sym}</td><td class="${ac}">${dd.action||"—"}</td><td class="${rc}">adx ${rg.adx??"—"} ${dir||""}</td><td class="muted">${fmtAge(j.age_s)}</td></tr>`;}
  H+=`</table></div>`;
  // kill switch flag
  const fl=(cf.flags||{})["kill_switch.txt"];
  if(fl&&fl.ok){H+=`<div class="card"><h2>⚠ kill_switch (Brain-EA 20260600)</h2><div class="neg">${(fl.text||"").slice(0,160)}…</div></div>`;}
  document.getElementById("wrap").innerHTML=H;
 }catch(e){document.getElementById("err").textContent="dashboard error: "+e}
}
tick();setInterval(tick,3000);
</script></body></html>"""


class DashHandler(BaseHTTPRequestHandler):
    server_version = "RNativeHubDash/0.1"

    def _send(self, code, body, ctype):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/data":
            merged = {"health": _hub_get("/health"), "state": _hub_get("/state"),
                      "vol_regime": _read_vol_regimes(),
                      "market_candidates": _read_json(MARKET_CANDIDATES)}
            self._send(200, json.dumps(merged, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, json.dumps({"ok": False, "reason": "not found"}), "application/json")

    def log_message(self, *a):  # quiet
        return


class _DashServer(ThreadingHTTPServer):
    allow_reuse_address = False   # authoritative single-instance guard (see hub.py)
    daemon_threads = True


def _write_lock():
    DASH_LOCK.parent.mkdir(parents=True, exist_ok=True)
    DASH_LOCK.write_text(json.dumps({"pid": os.getpid(), "ts": time.time(),
                                     "bind": f"{HOST}:{PORT}"}, ensure_ascii=False), encoding="utf-8")


def _heartbeat_loop(stop):
    while not stop.is_set():
        try:
            _write_lock()
        except OSError:
            pass
        stop.wait(HEARTBEAT_INTERVAL)


def main():
    try:
        srv = _DashServer((HOST, PORT), DashHandler)
    except OSError as exc:
        print(f"[hub_dash] refusing to start — {HOST}:{PORT} in use (another dashboard?). {exc}")
        raise SystemExit(1)
    stop = threading.Event()
    _write_lock()
    threading.Thread(target=_heartbeat_loop, args=(stop,), daemon=True).start()
    print(f"[hub_dash] visual dashboard on http://{HOST}:{PORT}  (reads hub {HUB}, read-only)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[hub_dash] stopped")
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()
