"""export_dossier_status.py — snapshot NR7 forward-trial numbers for the project dossier.

Produces ONE small JSON the dossier's promotion-gate calculator can consume by
copy-paste (the dossier artifact runs under a strict CSP and cannot fetch), from
two independent sources — each fail-open, so a dead brain_server or missing MT5
never blanks the other:

  1. brain_server's honest proof-gate:  GET :5055/api/r/proof_gate?magic=111111
     (dollar-based verdict: n, net, t_stat, verdict, reason)
  2. MT5 history directly (same pairing rule as brain_server: deals grouped by
     position_id, net = profit + swap + commission on the exit deal), plus an
     R estimate the gate needs: per-trade R ≈ net_i / median(|loser net|).
     Honest because the prover holds every loser to EXACTLY 1×ATR = −1R by
     design — the loser median IS the dollar size of 1R at lot 0.01. The
     method is stamped into the output so the reader knows it is an estimate.

Usage (on the trading machine):
    python scripts/export_dossier_status.py [--magic 111111] [--days 60]

Writes runtime/dossier_status.json and prints the same JSON to stdout —
paste either into the dossier's «حاسبة بوابة الترقية».
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = REPO_ROOT / "runtime" / "dossier_status.json"
PROOF_GATE_URL = "http://127.0.0.1:5055/api/r/proof_gate?magic={magic}&days={days}"


def fetch_proof_gate(magic: int, days: int) -> dict:
    try:
        with urllib.request.urlopen(PROOF_GATE_URL.format(magic=magic, days=days), timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # brain_server down is normal on a cold machine
        return {"error": f"proof_gate unreachable: {e}"}


def closed_trade_nets(magic: int, days: int) -> list[float] | dict:
    """Closed-trade net P/Ls straight from MT5 — brain_server's exact pairing rule."""
    try:
        import MetaTrader5 as mt5  # noqa: N813
    except Exception as e:
        return {"error": f"MetaTrader5 module unavailable: {e}"}
    try:
        if not mt5.initialize():
            return {"error": "mt5.initialize failed"}
        now = datetime.now()
        deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
        positions: dict[int, list] = {}
        for d in deals:
            if int(d.magic) == magic:
                positions.setdefault(int(d.position_id), []).append(d)
        nets = []
        for ds in positions.values():
            if len(ds) < 2:  # still open / unpaired
                continue
            exit_deal = sorted(ds, key=lambda x: x.time)[-1]
            nets.append(float(exit_deal.profit) + float(exit_deal.swap) + float(exit_deal.commission))
        return nets
    except Exception as e:
        return {"error": f"mt5 history read failed: {e}"}
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass


def r_estimate(nets: list[float]) -> dict:
    """n / total R / expR / max drawdown in R, using median |loser| as the 1R unit."""
    losses = [abs(x) for x in nets if x < 0]
    if not losses:
        return {"n": len(nets), "error": "no losing trades yet — 1R unit unknown, cannot scale"}
    one_r = statistics.median(losses)
    if one_r <= 0:
        return {"n": len(nets), "error": "degenerate 1R unit"}
    rs = [x / one_r for x in nets]
    cum = peak = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    total = sum(rs)
    return {
        "n": len(rs),
        "total_r": round(total, 2),
        "exp_r": round(total / len(rs), 4),
        "max_dd_r": round(max_dd, 2),
        "one_r_usd": round(one_r, 2),
        "method": "R = net / median(|loser|); losers are held to exactly 1xATR = -1R by design",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export NR7 forward-trial snapshot for the dossier")
    ap.add_argument("--magic", type=int, default=111111)
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()

    out: dict = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "magic": args.magic,
        "days": args.days,
        "proof_gate": fetch_proof_gate(args.magic, args.days),
    }
    nets = closed_trade_nets(args.magic, args.days)
    out["r_estimate"] = r_estimate(nets) if isinstance(nets, list) else nets

    try:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        out_note = str(OUT_FILE)
    except Exception as e:
        out_note = f"write failed: {e}"

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n# saved -> {out_note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
