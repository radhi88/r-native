"""tick_ws.py — بثّ التيكات لحظياً + لوحة تدفّق احترافية (طلب المستخدم: tick WebSocket + تطويره).

WS على ws://127.0.0.1:8765 يبثّ لكل رمز جلسة: bid/ask/spread/vol + سبريد/ATR (تحذير الفخاخ)
+ مركزنا المفتوح وربحه الحيّ + ميل الدلتا. العارض على http://127.0.0.1:8766 (بطاقات + رسم
مصغّر + سرعة تيكات + تحذير سبريد + P&L حيّ). محلي فقط (127.0.0.1)، للقراءة، DEMO. Windowless.

التشغيل:  pythonw tick_ws.py
"""
from __future__ import annotations
import asyncio, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MT5DIR = Path(r"C:\Users\Radhi\MT5")
RN = MT5DIR / "data" / "r_native"
PORT = 8765          # WebSocket
VIEW_PORT = 8766     # صفحة العرض
for p in (str(MT5DIR), str(MT5DIR / "r_native_v2")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _roster():
    try:
        import multi_trader as mt
        syms = set(mt._genomes())
    except Exception:
        syms = set()
    syms.update(["XAUUSDm", "BTCUSDm", "USDJPYm"])
    return sorted(syms)


def _session():
    try:
        from indicators import session as S
        return S.classify().name
    except Exception:
        return "?"


def _atr(mt5, sym, n=14):
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, n + 2)
    if r is None or len(r) < n:
        return 0.0
    tr = [max(r[i]["high"] - r[i]["low"], abs(r[i]["high"] - r[i - 1]["close"]),
              abs(r[i]["low"] - r[i - 1]["close"])) for i in range(1, len(r))]
    return sum(tr[-n:]) / n


async def _stream(websocket):
    import MetaTrader5 as mt5
    last = {}
    atr_cache, atr_ts = {}, 0.0
    try:
        while True:
            now = time.time()
            roster = _roster()
            # ATR لكل رمز (كل 60ث) لتحذير السبريد كنسبة من ATR
            if now - atr_ts > 60:
                for s in roster:
                    try:
                        atr_cache[s] = _atr(mt5, s)
                    except Exception:
                        pass
                atr_ts = now
            # مراكزنا المفتوحة (كل البوتات) + الدلتا
            posmap = {}
            for p in (mt5.positions_get() or []):
                m = posmap.setdefault(p.symbol, {"n": 0, "lot": 0.0, "profit": 0.0, "side": 0})
                m["n"] += 1; m["lot"] += p.volume; m["profit"] += p.profit
                m["side"] += (1 if p.type == 0 else -1)
            dstate = _load(RN / "delta_state.json", {}) or {}
            batch = []
            for sym in roster:
                t = mt5.symbol_info_tick(sym)
                if not t:
                    continue
                key = (t.time, t.bid, t.ask)
                if last.get(sym) == key:
                    continue
                last[sym] = key
                a = atr_cache.get(sym, 0.0)
                sp = float(t.ask - t.bid)
                pm = posmap.get(sym)
                batch.append({
                    "sym": sym, "t": int(t.time), "bid": float(t.bid), "ask": float(t.ask),
                    "spread": round(sp, 6),
                    "sp_atr": round(sp / a, 3) if a > 0 else None,   # سبريد/ATR (>0.4 فخّ)
                    "pos": ({"side": ("buy" if pm["side"] > 0 else "sell" if pm["side"] < 0 else "mix"),
                             "n": pm["n"], "lot": round(pm["lot"], 2),
                             "profit": round(pm["profit"], 2)} if pm else None),
                    "delta": (dstate.get(sym) or {}).get("bias"),
                })
            if batch:
                await websocket.send(json.dumps({"ts": now, "session": _session(),
                                                 "ticks": batch}, ensure_ascii=False))
            await asyncio.sleep(0.5)
    except Exception:
        return


VIEWER_HTML = """<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8>
<title>📡 تدفّق FRIDAY الحيّ</title><style>
*{box-sizing:border-box;margin:0;font-family:'Segoe UI',Tahoma,sans-serif}
body{background:radial-gradient(1100px 600px at 50% -10%,#12203c,#06080f 62%);color:#e6edf3;padding:16px;min-height:100vh}
.top{display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;margin-bottom:14px}
h1{font-size:18px;color:#e8c46a;text-shadow:0 0 16px #e8c46a55}
.badge{background:#101b38;border:1px solid #2c3c66;border-radius:9px;padding:4px 11px;font-size:12px;color:#9fc1ff;font-weight:700}
.on{color:#3fe07a}.off{color:#ff6b62}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;max-width:1200px;margin:0 auto}
.card{background:linear-gradient(165deg,#121c33,#0b1222);border:1.5px solid #233252;border-radius:14px;padding:12px;transition:border-color .3s}
.card.win{border-color:#2ea04388}.card.loss{border-color:#f8514988}.card.trap{border-color:#ffb24d99}
.ch{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px}
.sym{font-size:16px;font-weight:900;color:#ffd97a}
.sess{font-size:9px;color:#7d8590}
.px{display:flex;gap:10px;align-items:baseline;margin:2px 0}
.bid{font-size:26px;font-weight:900;transition:color .3s}.ask{font-size:13px;color:#8fa3bd}
.up{color:#3fe07a}.dn{color:#ff6b62}.flat{color:#cdd6f4}
.spark{width:100%;height:42px;display:block;margin:6px 0}
.chips{display:flex;gap:6px;flex-wrap:wrap;font-size:10px;margin-top:4px}
.chip{background:#0d1526;border:1px solid #1f2c48;border-radius:6px;padding:2px 7px;color:#9fb0c3}
.sp-ok{color:#3fe07a}.sp-warn{color:#ffb24d}.sp-bad{color:#ff6b62;font-weight:800}
.pos{margin-top:6px;font-size:12px;padding:5px 7px;border-radius:7px;background:#0d1526;border:1px solid #1f2c48}
.pos .pl{font-weight:900}
.dbar{height:5px;border-radius:3px;background:#16203a;margin-top:6px;position:relative;overflow:hidden}
.dbar i{position:absolute;top:0;bottom:0;width:2px;background:#cdd6f4;left:50%}
.dbar b{position:absolute;top:0;bottom:0}
.foot{text-align:center;color:#3d4a63;font-size:10px;margin-top:14px}
</style></head><body>
<div class=top>
  <h1>📡 تدفّق FRIDAY الحيّ</h1>
  <span class=badge id=conn>يتصل…</span>
  <span class=badge id=sess>الجلسة: —</span>
  <span class=badge id=rate>0 تيك/ث</span>
</div>
<div class=grid id=grid></div>
<div class=foot>سبريد/ATR &gt; 0.40 = فخّ سيولة (إطار برتقالي) · البطاقة خضراء/حمراء = ربح/خسارة مركزنا · الشريط السفلي = ميل الدلتا</div>
<script>
const cards={}, hist={}, prevBid={}; let tickCount=0, lastRate=Date.now();
function spark(cv,arr,col){const x=cv.getContext('2d'),W=cv.width=cv.clientWidth,H=42;
 x.clearRect(0,0,W,H);if(!arr||arr.length<2)return;const mn=Math.min(...arr),mx=Math.max(...arr),rg=(mx-mn)||1;
 x.strokeStyle=col;x.lineWidth=1.6;x.beginPath();
 arr.forEach((v,i)=>{const px=i/(arr.length-1)*W,py=H-3-(v-mn)/rg*(H-6);i?x.lineTo(px,py):x.moveTo(px,py);});x.stroke();
 const lp=H-3-(arr[arr.length-1]-mn)/rg*(H-6);x.fillStyle=col;x.beginPath();x.arc(W-2,lp,2.4,0,7);x.fill();}
function card(sym){const d=document.createElement('div');d.className='card';d.id='c_'+sym;
 d.innerHTML='<div class=ch><span class=sym></span><span class=sess></span></div>'+
  '<div class=px><span class=bid>—</span><span class=ask></span></div>'+
  '<canvas class=spark></canvas><div class=chips></div>'+
  '<div class=pos style=display:none></div><div class=dbar><i></i><b></b></div>';
 document.getElementById('grid').appendChild(d);cards[sym]=d;return d;}
function render(t,session){let d=cards[t.sym]||card(t.sym);
 d.querySelector('.sym').textContent=t.sym.replace(/m$/,'');
 d.querySelector('.sess').textContent=session;
 const b=d.querySelector('.bid');const up=prevBid[t.sym]!=null&&t.bid>prevBid[t.sym],dn=prevBid[t.sym]!=null&&t.bid<prevBid[t.sym];
 b.textContent=t.bid;b.className='bid '+(up?'up':dn?'dn':'flat');prevBid[t.sym]=t.bid;
 d.querySelector('.ask').textContent='ask '+t.ask;
 const h=hist[t.sym]||(hist[t.sym]=[]);h.push(t.bid);if(h.length>70)h.shift();
 spark(d.querySelector('.spark'),h,up?'#3fe07a':dn?'#ff6b62':'#7aa2ff');
 // chips: spread + spread/ATR trap
 let spcls='sp-ok',spnote='';if(t.sp_atr!=null){if(t.sp_atr>0.4){spcls='sp-bad';spnote=' ⚠فخّ';}else if(t.sp_atr>0.25){spcls='sp-warn';}}
 d.querySelector('.chips').innerHTML='<span class=chip>سبريد <b class='+spcls+'>'+t.spread+'</b></span>'+
   (t.sp_atr!=null?'<span class=chip>سبريد/ATR <b class='+spcls+'>'+t.sp_atr+spnote+'</b></span>':'');
 d.classList.toggle('trap',t.sp_atr!=null&&t.sp_atr>0.4);
 // our position
 const pe=d.querySelector('.pos');
 if(t.pos){pe.style.display='block';const win=t.pos.profit>0;
  pe.innerHTML='مركزنا: '+(t.pos.side==='buy'?'🟢 شراء':t.pos.side==='sell'?'🔴 بيع':'⚪ مختلط')+' '+t.pos.lot+' لوت ('+t.pos.n+') · <span class="pl '+(win?'up':'dn')+'">'+(t.pos.profit>=0?'+':'')+'$'+t.pos.profit+'</span>';
  d.classList.toggle('win',win);d.classList.toggle('loss',!win);
 }else{pe.style.display='none';d.classList.remove('win','loss');}
 // delta bar
 const bar=d.querySelector('.dbar b');if(t.delta!=null){const v=Math.max(-100,Math.min(100,t.delta));
  if(v>=0){bar.style.left='50%';bar.style.width=(v/2)+'%';bar.style.background='#3fe07a';}
  else{bar.style.right='50%';bar.style.left='';bar.style.width=(-v/2)+'%';bar.style.background='#ff6b62';}}
}
function connect(){const ws=new WebSocket('ws://127.0.0.1:8765');const c=document.getElementById('conn');
 ws.onopen=()=>{c.textContent='متصل 🟢';c.className='badge on';};
 ws.onclose=()=>{c.textContent='انقطع — يعيد…';c.className='badge off';setTimeout(connect,2000);};
 ws.onmessage=ev=>{const d=JSON.parse(ev.data);document.getElementById('sess').textContent='الجلسة: '+(d.session||'—');
  (d.ticks||[]).forEach(t=>{render(t,d.session);tickCount++;});
  const dt=(Date.now()-lastRate)/1000;if(dt>=1){document.getElementById('rate').textContent=Math.round(tickCount/dt)+' تيك/ث';tickCount=0;lastRate=Date.now();}};
}
connect();
</script></body></html>"""


class _Viewer(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = VIEWER_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve_viewer():
    try:
        HTTPServer(("127.0.0.1", VIEW_PORT), _Viewer).serve_forever()
    except Exception as e:
        print(f"[TICKWS] viewer err {e}", flush=True)


async def _main():
    import MetaTrader5 as mt5
    try:
        import websockets
    except Exception:
        print("[TICKWS] websockets غير منصّب — pip install websockets", flush=True)
        return
    if not mt5.initialize() and not mt5.initialize():
        print("[TICKWS] mt5 init failed", flush=True); return
    threading.Thread(target=_serve_viewer, daemon=True).start()
    print(f"[TICKWS] بثّ ws://127.0.0.1:{PORT} · العارض http://127.0.0.1:{VIEW_PORT}", flush=True)
    async with websockets.serve(_stream, "127.0.0.1", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
