import MetaTrader5 as mt5, time, datetime
from collections import Counter
mt5.initialize()
start=int(datetime.datetime.now(datetime.timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
dl=[d for d in (mt5.history_deals_get(start,int(time.time())) or []) if d.entry==0]
print("total entries today:", len(dl), "| by magic:", dict(Counter(d.magic for d in dl)))
mt5.shutdown()
