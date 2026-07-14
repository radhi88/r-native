"""agents/council_logger.py
Aggregates council vote tallies and dissent patterns.

Reads journal.jsonl and computes per-expert + per-genome statistics:
  - Approval rate per expert (ARCHITECT / QUANT / RISK / EXECUTOR / REVIEWER)
  - Veto reasons most commonly cited
  - Avg confidence per expert
  - Approval rate per genome x symbol pair
  - Unanimous-approval % (all 5 agree)
  - Dissent-caused-loss: trades where a dissenting expert was right (blocked
    a losing setup, or was overruled by a unanimous pass that then lost)

Writes to: data/council_analytics.json (overwritten each run)
           data/council_analytics_history.jsonl  (one snapshot per run)

Usage:
    python -m r_native_v2.agents.council_logger          # run once
    python -m r_native_v2.agents.council_logger --loop   # poll every 60 s
"""
from __future__ import annotations
import json, os, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DATA      = Path(os.path.join('C:', os.sep, 'Users', 'Radhi', 'MT5', 'r_native_v2', 'data'))
JOURNAL   = DATA / 'journal.jsonl'
ANALYTICS = DATA / 'council_analytics.json'
HISTORY   = DATA / 'council_analytics_history.jsonl'
DATA.mkdir(parents=True, exist_ok=True)

EXPERTS = ("ARCHITECT", "QUANT", "RISK", "EXECUTOR", "REVIEWER")


# ─── I/O ───────────────────────────────────────────────────────────────────

def _read_journal() -> list:
    if not JOURNAL.exists(): return []
    out = []
    with JOURNAL.open(encoding="utf-8") as f:
        for line in f:
            try: out.append(json.loads(line.strip()))
            except Exception: pass
    return out

def _save(data: dict) -> None:
    tmp = ANALYTICS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    tmp.replace(ANALYTICS)

def _append_history(snap: dict) -> None:
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False, default=str) + "\n")


# ─── parse council summary string ──────────────────────────────────────────

def _parse_votes(summary: str) -> dict:
    """Return {expert_name: (approved:bool, confidence:int)} from summary string."""
    result = {}
    if not summary: return result
    for token in summary.split():
        if "=" in token:
            name, rest = token.split("=", 1)
            name = name.strip("[]")
            approved = "✓" in rest or "True" in rest
            # extract confidence like (85) from "✓(85)"
            conf = 50
            try:
                conf = int(rest.split("(")[1].split(")")[0])
            except Exception:
                pass
            if name in EXPERTS:
                result[name] = (approved, conf)
    return result


# ─── compute analytics ─────────────────────────────────────────────────────

def compute(events: list) -> dict:
    proposals = [e for e in events if e.get("kind") == "PROPOSAL"]
    closes    = {e.get("id"): e for e in events if e.get("kind") == "CLOSE"}

    expert_stats = {n: {"vetoes": 0, "approvals": 0, "conf_sum": 0, "n": 0,
                         "veto_reasons": []} for n in EXPERTS}
    genome_stats: dict = defaultdict(lambda: {"proposals": 0, "approved": 0,
                                               "unanimous": 0, "vetoed": 0})
    unanimous_total = 0
    dissent_caused_block = 0     # veto on something that would have lost
    dissent_overruled    = 0     # expert vetoed but trade passed + lost

    for p in proposals:
        genome   = p.get("genome", "?")
        approved = p.get("approved", False)
        summary  = p.get("council", "")
        dissent  = p.get("dissent", [])
        votes    = _parse_votes(summary)

        genome_stats[genome]["proposals"] += 1
        if approved: genome_stats[genome]["approved"] += 1
        else:        genome_stats[genome]["vetoed"]   += 1

        all_agree = (len([v for v in votes.values() if not v[0]]) == 0) if votes else False
        if all_agree and approved:
            genome_stats[genome]["unanimous"] += 1
            unanimous_total += 1

        for name, (appr, conf) in votes.items():
            expert_stats[name]["n"]        += 1
            expert_stats[name]["conf_sum"] += conf
            if appr: expert_stats[name]["approvals"] += 1
            else:
                expert_stats[name]["vetoes"] += 1

        # dissent tracking vs outcome
        tid = p.get("id") or ""
        # find by matching genome+ts proximity (proposals don't have id)
        # instead find a close with same genome same side same entry
        entry = p.get("entry"); side = p.get("side"); sym = p.get("symbol")
        for eid, cl in closes.items():
            if (cl.get("genome") == genome and cl.get("side") == side
                    and abs((cl.get("entry") or 0) - (entry or 0)) < 0.01):
                pnl = cl.get("pnl", 0) or 0
                if dissent:
                    # expert vetoed but trade still got approved (shouldn't happen
                    # in V2 — any veto blocks). Record for analysis.
                    if approved and pnl < 0:
                        dissent_overruled += 1      # veto was right
                    elif not approved and pnl < 0:
                        dissent_caused_block += 1   # veto correctly blocked a loser
                break

    # compute rates
    for name in EXPERTS:
        s = expert_stats[name]
        n = max(s["n"], 1)
        s["approval_rate_pct"] = round(s["approvals"] / n * 100, 1)
        s["avg_confidence"]    = round(s["conf_sum"] / n, 1)
        s.pop("conf_sum")

    total_p = len(proposals)
    approved_p = sum(1 for p in proposals if p.get("approved"))

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "proposals":           total_p,
            "approved":            approved_p,
            "blocked":             total_p - approved_p,
            "approval_rate_pct":   round(approved_p / max(total_p, 1) * 100, 1),
            "unanimous_approved":  unanimous_total,
            "dissent_blocked_loser":  dissent_caused_block,
            "dissent_overruled_loser": dissent_overruled,
        },
        "by_expert":  expert_stats,
        "by_genome":  dict(genome_stats),
    }


# ─── public API ────────────────────────────────────────────────────────────

class CouncilLogger:
    """Council analytics agent."""

    def run_once(self) -> dict:
        events    = _read_journal()
        analytics = compute(events)
        _save(analytics)
        _append_history({"ts": analytics["updated_at"], **analytics["totals"]})
        t = analytics["totals"]
        print(f"[council_logger] proposals={t['proposals']}  "
              f"approved={t['approved']}  "
              f"approval_rate={t['approval_rate_pct']}%  "
              f"unanimous={t['unanimous_approved']}")
        return analytics

    def run_loop(self, poll_sec: int = 60) -> None:
        print(f"[council_logger] running  poll={poll_sec}s")
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                print("[council_logger] stopped"); break
            except Exception as e:
                print(f"[council_logger] err: {e}")
            time.sleep(poll_sec)


if __name__ == "__main__":
    agent = CouncilLogger()
    if "--loop" in sys.argv:
        agent.run_loop()
    else:
        agent.run_once()
        print("[council_logger] done")
