import json
from collections import Counter

d = json.load(open(r"C:\Users\Radhi\MT5\r_native_v2\data\cot_index.json", encoding="utf-8-sig"))
for mkt in ["GOLD", "BRITISH POUND"]:
    rows = d[mkt]
    dates = [r["date"] for r in rows]
    print(mkt, "weeks:", len(rows), "range:", min(dates), "->", max(dates))
    cc = Counter((r["comm_state"], r["retail_state"]) for r in rows)
    print("  state combos:", dict(cc))
    long_ok = [r["date"] for r in rows if r["comm_state"] == "BULLISH" and r["retail_state"] == "BEARISH"]
    short_ok = [r["date"] for r in rows if r["comm_state"] == "BEARISH" and r["retail_state"] == "BULLISH"]
    print("  comm=BULLISH&retail=BEARISH (long gate) weeks:", len(long_ok), long_ok[:8])
    print("  comm=BEARISH&retail=BULLISH (short gate) weeks:", len(short_ok), short_ok[:8])
print("meta:", d["_meta"])
