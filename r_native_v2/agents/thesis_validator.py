"""agents/thesis_validator.py
Compares each genome DECLARED thesis vs its ACTUAL live results.

Checks per genome:
  - Win-rate: does the genome beat its declared target?
  - Profit factor: meets thesis contract?
  - Side purity: BUY-only genome never proposed SELL?
  - Consecutive-loss health: under max threshold?
  - Confluence discipline: are wins tagged with expected setup keywords?

Writes:
  data/thesis_health.json   -- current health per genome (overwritten)
  data/thesis_health.jsonl  -- history (one snapshot per run)

Usage:
    python -m r_native_v2.agents.thesis_validator          # run once
    python -m r_native_v2.agents.thesis_validator --loop   # poll every 5 min
"""
from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

DATA     = Path(os.path.join('C:', os.sep, 'Users', 'Radhi', 'MT5', 'r_native_v2', 'data'))
JOURNAL  = DATA / 'journal.jsonl'
HEALTH_F = DATA / 'thesis_health.json'
HIST_F   = DATA / 'thesis_health.jsonl'
DATA.mkdir(parents=True, exist_ok=True)


# Genome contracts -- mirrors each Genome subclass declared targets.
# Update whenever a new genome is added to genomes/.
GENOME_CONTRACTS = {
    "CLAUDE-XAU-G1": {
        "description": (
            "XAU BUY-only M1 pullback scalper. Refuses Bear-OB tops; "
            "waits for BULL FVG retest with BUY+ pressure; aborts on bearish marubozu."
        ),
        "symbol":              "XAUUSDm",
        "sides":               ["BUY"],
        "target_winrate_pct":  60.0,
        "target_profit_factor": 1.3,
        "max_consecutive_losers": 4,
        "min_trades_to_judge": 10,
        "confluence_keywords": ["BULL FVG", "pressure BUY+", "no Bear OB"],
    },
}


def _read_journal() -> list:
    if not JOURNAL.exists(): return []
    out = []
    with JOURNAL.open(encoding="utf-8") as f:
        for line in f:
            try: out.append(json.loads(line.strip()))
            except Exception: pass
    return out

def _save_health(data: dict) -> None:
    tmp = HEALTH_F.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    tmp.replace(HEALTH_F)

def _append_hist(snap: dict) -> None:
    with HIST_F.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False, default=str) + chr(10))


def _analyze_genome(gname: str, contract: dict,
                    proposals: list, closes: list) -> dict:
    g_props  = [p for p in proposals if p.get("genome") == gname]
    g_closes = [c for c in closes    if c.get("genome") == gname]
    n_trades = len(g_closes)
    n_props  = len(g_props)
    issues   = []; warnings = []

    min_trades = contract.get("min_trades_to_judge", 10)
    if n_trades < min_trades:
        return {"genome": gname, "status": "INSUFFICIENT_DATA",
                "n_trades": n_trades, "n_proposals": n_props,
                "needed": min_trades, "issues": [], "warnings": [], "metrics": {}}

    wins   = [c for c in g_closes if (c.get("pnl") or 0) > 0]
    losses = [c for c in g_closes if (c.get("pnl") or 0) < 0]
    wr_pct = round(len(wins) / max(n_trades, 1) * 100, 1)
    target_wr = contract.get("target_winrate_pct", 60.0)
    if wr_pct < target_wr - 10:
        issues.append(f"Win-rate {wr_pct}% below target {target_wr}% over {n_trades} trades")
    elif wr_pct < target_wr:
        warnings.append(f"Win-rate {wr_pct}% slightly below target {target_wr}%")

    gross_win  = sum((c.get("pnl") or 0) for c in wins)
    gross_loss = abs(sum((c.get("pnl") or 0) for c in losses)) or 1e-9
    pf = round(gross_win / gross_loss, 2)
    target_pf = contract.get("target_profit_factor", 1.3)
    if pf < target_pf - 0.2:
        issues.append(f"Profit factor {pf} below target {target_pf}")
    elif pf < target_pf:
        warnings.append(f"Profit factor {pf} slightly below target {target_pf}")

    expected_sides = set(contract.get("sides", ["BUY", "SELL"]))
    for p in g_props:
        if p.get("side") not in expected_sides:
            issues.append(f"Side purity violation: proposed {p.get("side")} but genome declares sides={list(expected_sides)}")
            break

    max_consec = contract.get("max_consecutive_losers", 4)
    streak = 0; max_streak = 0
    for c in g_closes:
        if (c.get("pnl") or 0) < 0:
            streak += 1; max_streak = max(max_streak, streak)
        else:
            streak = 0
    if max_streak > max_consec:
        issues.append(f"Max consecutive losers {max_streak} exceeded threshold {max_consec}")
    elif max_streak == max_consec:
        warnings.append(f"Max consecutive losers at threshold ({max_consec}), monitor")

    keywords = contract.get("confluence_keywords", [])
    if keywords and g_props:
        sample = g_props[-10:]
        passing = sum(
            1 for p in sample
            if all(kw.lower() in " ".join(p.get("confluence", [])).lower()
                   for kw in keywords)
        )
        kw_rate = round(passing / max(len(sample), 1) * 100, 0)
        if kw_rate < 70:
            warnings.append(f"Only {kw_rate}% of last {len(sample)} proposals have all confluence keywords")

    if issues:      status = "DEGRADED"
    elif warnings:  status = "WARNING"
    else:           status = "HEALTHY"

    return {
        "genome": gname, "status": status,
        "n_trades": n_trades, "n_proposals": n_props,
        "issues": issues, "warnings": warnings,
        "metrics": {
            "win_rate_pct":          wr_pct,
            "target_win_rate_pct":   target_wr,
            "profit_factor":         pf,
            "target_profit_factor":  target_pf,
            "max_consecutive_losers": max_streak,
            "gross_win":   round(gross_win, 2),
            "gross_loss":  round(gross_loss, 2),
        },
    }


class ThesisValidator:
    """Checks all registered genomes against their thesis contracts."""

    def run_once(self) -> dict:
        events    = _read_journal()
        proposals = [e for e in events if e.get("kind") == "PROPOSAL"]
        closes    = [e for e in events if e.get("kind") == "CLOSE"]
        results   = {}
        for gname, contract in GENOME_CONTRACTS.items():
            r = _analyze_genome(gname, contract, proposals, closes)
            results[gname] = r
            icon = {"HEALTHY": "OK", "WARNING": "WARN",
                    "DEGRADED": "DEGRADED", "INSUFFICIENT_DATA": "..."}[r["status"]]
            print(f"[thesis_validator] [{icon}] {gname}  trades={r["n_trades"]}")
            for iss in r.get("issues", []):
                print(f"  ISSUE: {iss}")
        health = {"updated_at": datetime.now(timezone.utc).isoformat(), "genomes": results}
        _save_health(health)
        _append_hist({"ts": health["updated_at"],
                      "summary": {g: r["status"] for g, r in results.items()}})
        return health

    def run_loop(self, poll_sec: int = 300) -> None:
        print(f"[thesis_validator] running  poll={poll_sec}s")
        while True:
            try: self.run_once()
            except KeyboardInterrupt: print("[thesis_validator] stopped"); break
            except Exception as e:    print(f"[thesis_validator] err: {e}")
            time.sleep(poll_sec)


if __name__ == "__main__":
    agent = ThesisValidator()
    if "--loop" in sys.argv: agent.run_loop()
    else: agent.run_once(); print("[thesis_validator] done")
