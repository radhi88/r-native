import psutil, time
from collections import defaultdict
COMP=['multi_trader.py','btc_live.py','coordinator.py','friday_v3.algory.r_executor','market_data_collector',
      'paper_prover.py','accuracy_updater','secure_learner','chart_signal_writer','brain_server','_reoptimize']
groups=defaultdict(list)
for p in psutil.process_iter(['pid','name','cmdline','create_time']):
    try:
        cmd=p.info.get('cmdline') or []; cl=' '.join(cmd); nm=(p.info['name'] or '').lower()
        if 'python' not in nm or 'shell-snapshot' in cl or '-c' in cmd[:3] or '_dedupe2' in cl or '_count' in cl: continue
        for k in COMP:
            if k in cl: groups[k].append((p.info['create_time'], p.info['pid']))
    except: pass
killed=[]
for k,lst in groups.items():
    lst.sort()
    for ct,pid in lst[1:]:
        try: psutil.Process(pid).kill(); killed.append((k,pid))
        except Exception: pass
time.sleep(3)
print(f"killed {len(killed)} duplicates")
# verify
g2=defaultdict(int)
for p in psutil.process_iter(['name','cmdline']):
    try:
        cmd=p.info.get('cmdline') or []; cl=' '.join(cmd)
        if 'python' not in (p.info['name'] or '').lower() or 'shell-snapshot' in cl or '-c' in cmd[:3]: continue
        for k in COMP+['app.py']:
            if k in cl: g2[k]+=1
    except: pass
print("after:", {k:v for k,v in g2.items()})
