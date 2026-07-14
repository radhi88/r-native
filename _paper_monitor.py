"""Watcher for the forward paper proof. Prints ONLY noteworthy lines (each becomes a
notification): a symbol reaching PROVEN, a progress milestone (every 20 closed trades),
or the prover process going down. Polls every 10 min (local, cheap)."""
import json, time, sys
import psutil

PROOF = r'C:\Users\Radhi\MT5\r_native_v2\data\paper_proof.json'
last_proven = set()
last_bucket = 0
was_down = False

print('monitor armed: watching forward paper proof (US30/BTCJPY/BTCUSD)', flush=True)
while True:
    try:
        alive = any('paper_prover.py' in ' '.join(p.info.get('cmdline') or [])
                    for p in psutil.process_iter(['cmdline']))
    except Exception:
        alive = True
    if not alive and not was_down:
        print('ALERT: paper_prover process is DOWN — needs restart', flush=True); was_down = True
    elif alive and was_down:
        print('paper_prover back up', flush=True); was_down = False
    try:
        d = json.load(open(PROOF, encoding='utf-8'))
        syms = d.get('symbols', {})
        proven = set(s for s, x in syms.items() if x.get('status') == 'PROVEN')
        total = sum(x.get('fwd_trades', 0) for x in syms.values())
        new = proven - last_proven
        if new:
            det = '; '.join('%s PF%s %sR/%dt' % (s, syms[s]['pf'], syms[s]['net_R'], syms[s]['fwd_trades'])
                            for s in sorted(new))
            print('PROVEN forward: %s' % det, flush=True)
            last_proven = proven
        bucket = total // 20
        if bucket > last_bucket:
            summary = ' · '.join('%s:%dt/%sPF/%sR' % (s, x['fwd_trades'], x['pf'], x['net_R'])
                                 for s, x in syms.items())
            print('progress: %d paper trades closed | %s' % (total, summary), flush=True)
            last_bucket = bucket
    except Exception:
        pass
    sys.stdout.flush()
    time.sleep(600)
