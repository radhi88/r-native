"""twoday_snapshot.py — one-shot monitoring snapshot for unattended operation.

Run by the watchdog every few minutes. Appends a JSON line to
data/twoday_monitor.jsonl and regenerates a human-readable data/twoday_report.md
so when Radhi returns he sees exactly what happened: account equity over time,
open positions by system, realized P&L, overlay state, gold trend, and any
safety halts.
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
JSONL = DATA / "twoday_monitor.jsonl"
REPORT = DATA / "twoday_report.md"
OVERLAY_STATUS = DATA / "gold_htf_overlay_status.json"

MAG = {99782: "LIVE_unified_trader", 99783: "GOLD_overlay", 20260600: "ALGORY", 20260605: "r_native"}


def _now():
    return datetime.now(timezone.utc)


def snapshot() -> dict:
    import MetaTrader5 as mt5
    snap = {"ts": _now().isoformat(), "ok": False}
    if not mt5.initialize():
        snap["error"] = "mt5_init_failed"
        return snap
    try:
        ai = mt5.account_info()
        snap.update({
            "ok": True,
            "balance": round(ai.balance, 2),
            "equity": round(ai.equity, 2),
            "open_pl": round(ai.profit, 2),
            "margin": round(ai.margin, 2),
            "margin_free": round(ai.margin_free, 2),
        })
        # open positions grouped by magic
        pos = mt5.positions_get() or []
        by_mag = defaultdict(lambda: {"count": 0, "pl": 0.0, "by_symbol": defaultdict(int)})
        for p in pos:
            g = by_mag[p.magic]
            g["count"] += 1
            g["pl"] += float(p.profit)
            g["by_symbol"][p.symbol] += 1
        snap["positions"] = {
            MAG.get(m, str(m)): {"count": v["count"], "pl": round(v["pl"], 2),
                                 "symbols": dict(v["by_symbol"])}
            for m, v in by_mag.items()
        }
        snap["open_total"] = len(pos)
        # realized today (entries closed in last 24h) by magic
        deals = mt5.history_deals_get(_now() - timedelta(hours=24), _now()) or []
        realized = defaultdict(float)
        closed = defaultdict(int)
        for d in deals:
            if d.entry == 1:  # exit deal carries the realized P&L
                realized[d.magic] += float(d.profit) + float(d.commission) + float(d.swap)
                closed[d.magic] += 1
        snap["realized_24h"] = {MAG.get(m, str(m)): round(v, 2) for m, v in realized.items()}
        snap["closed_24h"] = {MAG.get(m, str(m)): c for m, c in closed.items()}
    except Exception as e:
        snap["error"] = str(e)
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
    # overlay heartbeat
    try:
        snap["overlay"] = json.loads(OVERLAY_STATUS.read_text(encoding="utf-8"))
    except Exception:
        snap["overlay"] = None
    return snap


def write_report(rows: list[dict]) -> None:
    if not rows:
        return
    first = next((r for r in rows if r.get("ok")), rows[0])
    last = next((r for r in reversed(rows) if r.get("ok")), rows[-1])
    start_eq = first.get("equity")
    last_eq = last.get("equity")
    lines = []
    lines.append("# FRIDAY — 2-Day Unattended Monitor")
    lines.append("")
    lines.append(f"_Last update: {last.get('ts')}_  ·  snapshots: {len(rows)}")
    lines.append("")
    lines.append("## Account")
    if start_eq is not None and last_eq is not None:
        chg = last_eq - start_eq
        lines.append(f"- Equity: **${last_eq:.2f}**  (start ${start_eq:.2f}, change **${chg:+.2f}**)")
    lines.append(f"- Balance: ${last.get('balance')}  ·  Open P/L: ${last.get('open_pl')}  ·  Free margin: ${last.get('margin_free')}")
    lines.append("")
    lines.append("## Open positions now (by system)")
    for who, v in (last.get("positions") or {}).items():
        lines.append(f"- **{who}**: {v['count']} open, P/L ${v['pl']:+.2f}  {v['symbols']}")
    if not last.get("positions"):
        lines.append("- (none)")
    lines.append("")
    lines.append("## Realized last 24h (by system)")
    for who, v in (last.get("realized_24h") or {}).items():
        n = (last.get("closed_24h") or {}).get(who, 0)
        lines.append(f"- **{who}**: ${v:+.2f}  ({n} trades closed)")
    if not last.get("realized_24h"):
        lines.append("- (none closed)")
    lines.append("")
    ov = last.get("overlay") or {}
    lines.append("## Gold HTF overlay (magic 99783, our validated edge)")
    tr = (ov.get("trend") or {})
    lines.append(f"- armed: {ov.get('armed')}  ·  in_position: {ov.get('in_position')}  ·  last_action: `{ov.get('last_action')}`")
    if tr:
        d = {1: "UP", -1: "DOWN", 0: "FLAT"}.get(tr.get("dir"), "?")
        lines.append(f"- H4 trend: **{d}**  (EMA50 {tr.get('ema_fast')} vs EMA200 {tr.get('ema_slow')})")
    if ov.get("in_position"):
        lines.append(f"- entry {ov.get('entry')} · sl {ov.get('sl')} · swap ${ov.get('swap')} · P/L ${ov.get('profit')}")
    lines.append("")
    # equity sparkline (text)
    eqs = [r.get("equity") for r in rows if r.get("ok") and r.get("equity") is not None]
    if len(eqs) >= 2:
        lo, hi = min(eqs), max(eqs)
        lines.append(f"## Equity range over window: ${lo:.2f} → ${hi:.2f}  (min/max)")
    lines.append("")
    lines.append("---")
    lines.append("_Auto-generated by twoday_snapshot.py via the watchdog scheduled task._")
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    snap = snapshot()
    DATA.mkdir(parents=True, exist_ok=True)
    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    # rebuild report from full history (keep last 1000 rows)
    rows = []
    try:
        for ln in JSONL.read_text(encoding="utf-8").splitlines()[-1000:]:
            if ln.strip():
                rows.append(json.loads(ln))
    except Exception:
        rows = [snap]
    write_report(rows)
    eq = snap.get("equity")
    print(f"[snapshot] {snap.get('ts')} equity=${eq} open={snap.get('open_total')} "
          f"overlay={(snap.get('overlay') or {}).get('last_action')}")


if __name__ == "__main__":
    main()
