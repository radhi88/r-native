import psutil, datetime, collections, os
KEEP = {21148, 21940, 22604}  # btc scalp, dashboard, gold_live (just restarted)
BS = chr(92)

def norm(cl):
    parts = cl.split()
    out = []
    for p in parts:
        low = p.lower()
        if low.endswith(('python.exe', 'pythonw.exe')):
            out.append('PY'); continue
        if BS in p or '/' in p:
            out.append(p.replace(BS, '/').split('/')[-1])
        else:
            out.append(p)
    return ' '.join(out)

rows = []
for p in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline', 'create_time', 'memory_info']):
    try:
        n = (p.info['name'] or '').lower()
        if 'python' not in n:
            continue
        cl = ' '.join(p.info['cmdline'] or [])
        if any(s in cl for s in ('Claude_pzs8', 'shell-snapshots', 'mcp_server', 'LocalCache', '_dedupe_scan')):
            continue
        rows.append({'pid': p.info['pid'], 'ppid': p.info['ppid'], 'cmd': norm(cl),
                     'ct': p.info['create_time'], 'rss': p.info['memory_info'].rss // (1024 ** 2)})
    except Exception:
        pass

groups = collections.defaultdict(list)
for r in rows:
    groups[r['cmd']].append(r)
pids = {r['pid'] for r in rows}
print('=== %d FRIDAY python procs, %d distinct commands ===' % (len(rows), len(groups)))
total_rss = sum(r['rss'] for r in rows)
print('total RSS: %d MB\n' % total_rss)

dupe_kill = []
for cmd, lst in sorted(groups.items(), key=lambda x: -len(x[1])):
    if len(lst) > 1:
        lst.sort(key=lambda r: r['ct'])
        tags = []
        for r in lst:
            star = '*' if r['ppid'] in pids else ''
            tags.append('pid%d(ppid%d%s,%dMB,%s)' % (r['pid'], r['ppid'], star, r['rss'],
                        datetime.datetime.fromtimestamp(r['ct']).strftime('%H:%M')))
        print('x%d  %s' % (len(lst), cmd[:62]))
        print('      ' + '  '.join(tags))
        for r in lst[1:]:
            if r['pid'] in KEEP:
                continue
            # skip if this proc is a child of another in the same group (launcher pair)
            if any(o['pid'] == r['ppid'] for o in lst):
                continue
            dupe_kill.append((r['pid'], r['rss'], cmd))

print('\n=== duplicate PIDs to kill (keep oldest of each, skip launcher children) ===')
freed = 0
for pid, rss, cmd in dupe_kill:
    print(pid, '%dMB' % rss, cmd[:50]); freed += rss
print('TOTAL: %d procs, ~%d MB to free' % (len(dupe_kill), freed))
# write pid list for the kill step
with open(r'C:\Users\Radhi\MT5\_dedupe_pids.txt', 'w') as f:
    f.write(' '.join(str(pid) for pid, _, _ in dupe_kill))
