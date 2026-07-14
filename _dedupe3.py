import psutil, time, urllib.request
from collections import defaultdict
for k in ('brain_server','friday_v3.algory.r_executor','multi_trader.py'):
    insts=[]
    for p in psutil.process_iter(['pid','name','cmdline','create_time']):
        try:
            cmd=p.info.get('cmdline') or []; cl=' '.join(cmd)
            if 'python' not in (p.info['name'] or '').lower() or 'shell-snapshot' in cl or '-c' in cmd[:3] or 'dedupe' in cl or '_count' in cl: continue
            if k in cl: insts.append((p.info['create_time'],p.info['pid']))
        except: pass
    insts.sort()
    for ct,pid in insts[1:]:   # keep oldest, kill extras
        try: psutil.Process(pid).kill()
        except: pass
time.sleep(4)
# brain still serving?
try: urllib.request.urlopen('http://127.0.0.1:5055/api/r/agents/list',timeout=5); brain='UP'
except: brain='DOWN'
# final count
g=defaultdict(int)
for p in psutil.process_iter(['pid','name','cmdline']):
    try:
        cmd=p.info.get('cmdline') or []; cl=' '.join(cmd)
        if 'python' not in (p.info['name'] or '').lower() or 'shell-snapshot' in cl or '-c' in cmd[:3] or 'dedupe' in cl or '_count' in cl: continue
        for k in ('brain_server','friday_v3.algory.r_executor','multi_trader.py','btc_live.py','coordinator.py','app.py'):
            if k in cl: g[k]+=1
    except: pass
print('brain:',brain,'| counts:',dict(g))
