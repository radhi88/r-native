import MetaTrader5 as mt5, time
from collections import Counter
mt5.initialize()
poss = mt5.positions_get() or []
orders = mt5.orders_get() or []
print("open positions:", len(poss), "| pending orders:", len(orders))
dl = [d for d in (mt5.history_deals_get(int(time.time()-300), int(time.time())) or []) if d.entry == 0]
print("entries last 5min:", len(dl), "| by magic:", dict(Counter(d.magic for d in dl)))
a = mt5.account_info()
print("equity", round(a.equity,2), "balance", round(a.balance,2))
print("positions by magic:", dict(Counter(p.magic for p in poss)))
mt5.shutdown()
