"""rebuild_hof_live_pnl.py — recompute every HoF entry's live_pnl + live_trades
from real MT5 history. Fixes the broken comment-parsing tracker that was
crediting genomes for trades they didn't open.

Run after fixing the live tracker — or any time HoF gets out of sync
with MT5 reality.

For each ticket in MT5 history (R magic):
  • Read OPEN deal's comment → extract genome_id (R-<gid>-<side>)
  • Sum CLOSE deal P/L for that ticket → genome's live_pnl
  • Count CLOSE deals → genome's live_trades

Then write back to data/r_native/hall_of_fame/index.json.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOF_INDEX = Path(r"C:\Users\Radhi\MT5\data\r_native\hall_of_fame\index.json")
R_MAGIC = 20260605


def main(lookback_hours: int = 48):
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed")
        return

    # 1) Fetch ALL R-magic deals in window
    since = datetime.now() - timedelta(hours=lookback_hours)
    deals = mt5.history_deals_get(since, datetime.now()) or []
    r_deals = [d for d in deals if int(d.magic) == R_MAGIC]
    print(f"Found {len(r_deals)} R-magic deals in last {lookback_hours}h")

    # 2) Build ticket → genome_id map from OPEN deals
    ticket_gid = {}
    for d in r_deals:
        if int(d.entry) != 0:  # opens only
            continue
        m = re.match(r"R-([A-F0-9]{6})-", d.comment or "")
        if not m: continue
        # In MT5 deals, position_id is the trade ticket
        pos_id = int(d.position_id) if hasattr(d, "position_id") else int(d.order)
        ticket_gid[pos_id] = m.group(1)
    print(f"Mapped {len(ticket_gid)} tickets → genome IDs")

    # 3) Aggregate CLOSE deals per genome
    gid_stats = {}  # gid → {trades, pnl, wins}
    for d in r_deals:
        if int(d.entry) != 1:  # closes only
            continue
        pos_id = int(d.position_id) if hasattr(d, "position_id") else int(d.order)
        gid = ticket_gid.get(pos_id)
        if not gid: continue
        rec = gid_stats.setdefault(gid, {"trades": 0, "pnl": 0.0, "wins": 0})
        net = float(d.profit) + float(d.swap) + float(d.commission)
        rec["trades"] += 1
        rec["pnl"]    += net
        if d.profit > 0: rec["wins"] += 1
    print(f"\nComputed stats for {len(gid_stats)} genomes:")
    for gid, s in sorted(gid_stats.items(), key=lambda x: -x[1]["pnl"]):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        print(f"  {gid}: {s['trades']}t  WR {wr:.0f}%  net ${s['pnl']:+.2f}")

    # 4) Write back to HoF
    if not HOF_INDEX.exists():
        print("\nERROR: HoF index missing"); return
    hof = json.load(open(HOF_INDEX))
    updated = 0
    for gid, stats in gid_stats.items():
        if gid not in hof:
            print(f"  ⚠ genome {gid} not in HoF, skipping")
            continue
        hof[gid]["live_trades"] = stats["trades"]
        hof[gid]["live_pnl"]    = round(stats["pnl"], 2)
        hof[gid]["live_wins"]   = stats["wins"]
        hof[gid]["live_wr_pct"] = round(stats["wins"] / max(1, stats["trades"]) * 100, 1)
        hof[gid]["last_synced"] = datetime.now(timezone.utc).isoformat()
        updated += 1
    # Also zero out genomes that USED to have live stats but don't match any current MT5 deals
    for gid, g in hof.items():
        if gid in gid_stats: continue
        # Was it ever credited? Reset if so.
        if g.get("live_trades", 0) > 0 or abs(g.get("live_pnl", 0)) > 0.01:
            print(f"  🧹 zeroing stale stats on {gid} (was {g.get('live_trades')}t ${g.get('live_pnl'):+.2f})")
            g["live_trades"] = 0
            g["live_pnl"]    = 0
            g["live_wins"]   = 0
            g["live_wr_pct"] = 0
            g["last_synced"] = datetime.now(timezone.utc).isoformat()
    json.dump(hof, open(HOF_INDEX, "w"), ensure_ascii=False, indent=2)
    print(f"\n✅ Updated {updated} genome entries in HoF · zeroed stale ones")

    mt5.shutdown()


if __name__ == "__main__":
    import sys
    h = int(sys.argv[1]) if len(sys.argv) > 1 else 48
    main(h)
