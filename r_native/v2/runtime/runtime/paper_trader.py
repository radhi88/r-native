"""runtime/paper_trader.py — paper-trade loop for V2 genomes.

Polls live MT5 ticks every 5s. For each registered genome:
  1. Build snapshot via mtf_engine
  2. genome.propose(snapshot, account)
  3. If proposal → council.convene → if approved, simulate fill
  4. Track open paper positions; close on TP/SL/expiry
  5. Append to journal.jsonl + roll up stats

NO real orders are sent. This is a sandbox to validate genomes before
v2 ever touches the live broker. Bridge to mt5.order_send is a separate
later module (live_bridge.py).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from r_native_v2.council import convene
from r_native_v2.council.types import Proposal
from r_native_v2.genomes.claude_apex import ClaudeApex
from r_native_v2.indicators.mtf_engine import build_snapshot


DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
JOURNAL = DATA / "journal.jsonl"
OPEN_POS = DATA / "open_paper_positions.json"
STATS = DATA / "paper_stats.json"
DATA.mkdir(parents=True, exist_ok=True)


@dataclass
class PaperPos:
    id:         str
    genome:     str
    symbol:     str
    side:       str
    entry:      float
    sl:         float
    tp:         float
    lot:        float
    opened_at:  str
    council_summary: str
    thesis:     str


def _load(p: Path, default):
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return default


def _save(p: Path, obj):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    tmp.replace(p)


def _append_journal(entry: dict):
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _account_snapshot() -> dict:
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
        a = mt5.account_info()
        return {"balance": float(a.balance), "equity": float(a.equity)}
    except Exception:
        return {"balance": 100.0, "equity": 100.0}


def _check_closes(open_pos: dict, snapshot, paper_equity: float) -> tuple[dict, float]:
    """For each open paper position, check if SL/TP/expiry hit. Returns
    updated open dict + cumulative paper PnL."""
    bid = snapshot.bid; ask = snapshot.ask
    still_open = {}
    pnl_total = 0.0
    for pid, p in open_pos.items():
        cur_bid = bid; cur_ask = ask
        # Decide fill price for close
        side = p["side"]
        contract = 100.0   # gold default
        try:
            import MetaTrader5 as mt5
            si = mt5.symbol_info(p["symbol"])
            if si: contract = float(si.trade_contract_size)
        except: pass

        closed_reason = None; close_price = None
        if side == "BUY":
            if cur_bid <= p["sl"]: closed_reason = "SL"; close_price = p["sl"]
            elif cur_bid >= p["tp"]: closed_reason = "TP"; close_price = p["tp"]
        else:
            if cur_ask >= p["sl"]: closed_reason = "SL"; close_price = p["sl"]
            elif cur_ask <= p["tp"]: closed_reason = "TP"; close_price = p["tp"]

        # NO EXPIRY (cycle 39 user feedback "لا تحط وقت يا حبيبي").
        # Positions exit only on SL or TP — never on a clock. The
        # market decides when a setup is done, not the calendar.
        # Compute age for logging only.
        opened = datetime.fromisoformat(p["opened_at"])
        if opened.tzinfo is None: opened = opened.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - opened).total_seconds() / 60

        if closed_reason:
            pnl_per_unit = (close_price - p["entry"]) if side == "BUY" else (p["entry"] - close_price)
            pnl = round(pnl_per_unit * p["lot"] * contract, 2)
            pnl_total += pnl
            _append_journal({
                "kind": "CLOSE", "ts": datetime.now(timezone.utc).isoformat(),
                "id": pid, "genome": p["genome"], "symbol": p["symbol"],
                "side": side, "entry": p["entry"], "close_price": close_price,
                "pnl": pnl, "close_reason": closed_reason,
                "held_min": round(age_min, 1) if "age_min" in locals() else None,
            })
            print(f"  [PAPER CLOSE] {p['genome']} {side} pnl={pnl:+.2f} reason={closed_reason}")
        else:
            still_open[pid] = p
    return still_open, pnl_total


_LAST_PROPOSAL_BAR: dict = {}    # {(genome_name, symbol) → last M1 bar timestamp proposed}


def _try_propose_and_fill(genome, snapshot, account, open_pos: dict) -> dict:
    # Dedup: only re-evaluate the genome ONCE per closed M1 bar per symbol.
    # Without this, paper_trader spammed 3000+ identical BLOCKED proposals
    # in 30 min because it runs every 2s on the same forming bar.
    try:
        m1 = snapshot.tfs.get("M1")
        if m1 and m1.last_bar:
            cur_bar_ts = int(m1.last_bar.get("time", 0))
            key = (genome.name, snapshot.symbol)
            if _LAST_PROPOSAL_BAR.get(key) == cur_bar_ts:
                return open_pos    # already evaluated this bar
            _LAST_PROPOSAL_BAR[key] = cur_bar_ts
    except Exception: pass

    proposal = genome.propose(snapshot, account)
    if not proposal: return open_pos

    # Concurrency cap per genome: 1 open paper position at a time
    if any(p["genome"] == genome.name for p in open_pos.values()):
        return open_pos

    result = convene(proposal, snapshot, account)
    _append_journal({
        "kind": "PROPOSAL", "ts": datetime.now(timezone.utc).isoformat(),
        "genome": genome.name, "symbol": proposal.symbol, "side": proposal.side,
        "entry": proposal.entry, "sl": proposal.sl, "tp": proposal.tp,
        "approved": result.approved, "council": result.summary(),
        "dissent": result.dissent(),
        "thesis": proposal.thesis,
        "confluence": proposal.confluence,
    })
    print(f"  [PROPOSE] {result.summary()}")

    if not result.approved: return open_pos

    pid = f"P-{int(time.time()*1000)}"
    open_pos[pid] = {
        "id": pid, "genome": genome.name, "symbol": proposal.symbol,
        "side": proposal.side, "entry": proposal.entry,
        "sl": proposal.sl, "tp": proposal.tp, "lot": proposal.lot,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "council_summary": result.summary(),
        "thesis": proposal.thesis,
    }
    _append_journal({
        "kind": "OPEN", "ts": open_pos[pid]["opened_at"],
        "id": pid, "genome": genome.name, "symbol": proposal.symbol,
        "side": proposal.side, "entry": proposal.entry,
        "sl": proposal.sl, "tp": proposal.tp, "lot": proposal.lot,
    })
    print(f"  [PAPER OPEN] {genome.name} {proposal.side} @ {proposal.entry:.2f} "
          f"SL={proposal.sl:.2f} TP={proposal.tp:.2f}")
    return open_pos


def _update_stats(open_pos: dict):
    """Roll up journal into stats file."""
    if not JOURNAL.exists(): return
    closes = []
    with JOURNAL.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get("kind") == "CLOSE": closes.append(e)
            except: pass
    by_genome = {}
    for c in closes:
        g = c["genome"]
        by_genome.setdefault(g, {"n":0,"wins":0,"pnl":0.0,"closes":[]})
        d = by_genome[g]
        d["n"] += 1
        if (c.get("pnl") or 0) > 0: d["wins"] += 1
        d["pnl"] += (c.get("pnl") or 0)
        d["closes"].append({"r": c.get("close_reason"), "pnl": c.get("pnl")})
    for g in by_genome:
        d = by_genome[g]
        d["wr_pct"] = round(d["wins"]/max(d["n"],1)*100, 1)
        d["avg_per_trade"] = round(d["pnl"]/max(d["n"],1), 3)
        d["pnl"] = round(d["pnl"], 2)
    _save(STATS, {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "open_count": len(open_pos),
        "by_genome": by_genome,
    })


def run_loop(symbols: tuple = ("XAUUSDm",), poll_sec: int = 2):
    print(f"[paper_trader] starting · symbols={symbols} · poll={poll_sec}s")
    genomes = [ClaudeApex()]
    open_pos = _load(OPEN_POS, {})
    while True:
        try:
            account = _account_snapshot()
            for sym in symbols:
                snap = build_snapshot(sym)
                if not snap: continue
                # First handle existing-position closes
                open_pos, _pnl = _check_closes(open_pos, snap, account.get("equity", 100))
                # Then try to propose new entries
                for g in genomes:
                    if sym in g.symbols:
                        open_pos = _try_propose_and_fill(g, snap, account, open_pos)
            _save(OPEN_POS, open_pos)
            _update_stats(open_pos)
        except KeyboardInterrupt:
            print("[paper_trader] stopped"); break
        except Exception as e:
            print(f"[paper_trader] loop err: {e}")
        time.sleep(poll_sec)


if __name__ == "__main__":
    import sys
    syms = tuple(sys.argv[1].split(",")) if len(sys.argv) > 1 else ("XAUUSDm",)
    poll = int(sys.argv[2]) if len(sys.argv) > 2 else 2     # default 2s — near real-time
    run_loop(symbols=syms, poll_sec=poll)
