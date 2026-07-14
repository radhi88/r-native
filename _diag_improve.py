import MetaTrader5 as mt5, time, json
from collections import defaultdict
from pathlib import Path
mt5.initialize()
# 1) per-symbol LIVE P&L of the multi-market bot (last 6h) — which symbols actually lose
dl=[d for d in (mt5.history_deals_get(int(time.time()-6*3600),int(time.time())) or []) if d.entry==1 and d.magic==20260608]
bysym=defaultdict(lambda:[0,0.0])
for d in dl: bysym[d.symbol][0]+=1; bysym[d.symbol][1]+=d.profit+d.commission+d.swap
print("=== أداء multi_trader الحيّ لكل عملة (آخر 6س) ===")
for s,(n,net) in sorted(bysym.items(), key=lambda x:x[1][1]):
    tag='🔴 خاسر' if net<-1 else ('🟢 رابح' if net>1 else '⚪')
    print(f"  {s:9s} {n:3d} صفقة · ${net:+7.2f} {tag}")
tot=sum(v[1] for v in bysym.values())
print(f"  الإجمالي: ${tot:+.2f} عبر {sum(v[0] for v in bysym.values())} صفقة")
mt5.shutdown()
# 2) is self-improvement producing fresh changes?
D=Path('r_native_v2/data'); now=time.time()
print("\n=== هل التعلّم الذاتي يُحدّث فعلاً؟ ===")
for f,lbl in [('genome_factory_summary.json','مصنع الجينات'),('indicator_weights_US30m.json','أوزان US30'),('secure_config_BTCUSDm.json','تأمين BTC')]:
    p=D/f
    if p.exists(): print(f"  {lbl}: محدّث قبل {(now-p.stat().st_mtime)/60:.0f} دقيقة")
