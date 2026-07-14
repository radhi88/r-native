import psutil
from collections import defaultdict
groups=defaultdict(list)
for p in psutil.process_iter(['pid','name','cmdline']):
    try:
        cmd=p.info.get('cmdline') or []
        cl=' '.join(cmd)
        nm=(p.info['name'] or '').lower()
        if 'python' not in nm: continue
        if 'shell-snapshot' in cl: continue
        if '-c' in cmd[:3]: continue          # exclude inline diagnostics
        if '_count.py' in cl: continue
        for k in ('multi_trader.py','btc_live.py','coordinator.py','friday_v3.algory.r_executor','market_data_collector','paper_prover.py','accuracy_updater','secure_learner','chart_signal_writer','brain_server','app.py','_reoptimize'):
            if k in cl: groups[k].append(p.info['pid'])
    except: pass
for k in sorted(groups, key=lambda x:-len(groups[x])):
    print(f"  {k}: {len(groups[k])}  {groups[k]}")
