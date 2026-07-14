"""reflect.py - FRIDAY's scientific-method reflection cycle.

Every `reflection_every` closed trades it:
  1. scores the last 25 realized trades against goal.json
  2. resolves the PRIOR hypothesis (was its prediction right?) - reverts the change if it hurt
  3. proposes exactly ONE discipline-variable change with a falsifiable prediction
  4. bumps strategy version, archives the prior to state/history/, logs the hypothesis

Modes:
  --fallback   deterministic policy (default). Protect downside -> enforce discipline -> chase return.
  --hermes     hand the scored context to a `hermes` subprocess and apply its single-variable hypothesis.
  --force      run even if fewer than reflection_every new trades have closed (for demonstration).
  --refresh    ask friday_trade_outcome_learner to pull fresh closed deals from MT5 first.

Writes ONLY inside the reflection/ directory. Never sends orders. Never edits goal.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import score as score_mod          # noqa: E402
import trade_source                # noqa: E402

GOAL_FILE = HERE / "goal.json"
STRAT_FILE = HERE / "strategy.json"
STATE_FILE = HERE / "reflection_state.json"
HIST_DIR = HERE / "state" / "history"
HYP_FILE = HERE / "state" / "hypotheses.jsonl"

WINDOW = 25  # trades scored per reflection


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic-ish on Windows/NTFS


def default_state() -> dict[str, Any]:
    return {
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "reflection_count": 0,
        "trades_seen_at_last_reflection": 0,
        "last_reflection_at": None,
        "open_hypothesis": None,
    }


def append_hypothesis(record: dict[str, Any]) -> None:
    HYP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HYP_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def archive_strategy(strat: dict[str, Any]) -> Path:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    ver = str(strat.get("version", "00"))
    dest = HIST_DIR / f"v{ver}.json"
    write_json(dest, strat)
    return dest


def bump_version(ver: str) -> str:
    try:
        return f"{int(ver) + 1:02d}"
    except (TypeError, ValueError):
        return "02"


# ---------------------------------------------------------------------------
# Deterministic fallback policy: ONE variable per cycle.
# Priority: protect downside  ->  enforce discipline  ->  chase return.
# ---------------------------------------------------------------------------
def propose_fallback(
    strat: dict[str, Any],
    goal: dict[str, Any],
    result: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any] | None:
    bounds = strat.get("_bounds", {})
    bd = result["breakdown"]
    composite = result["composite"]
    dd = bd["drawdown"]
    ret30 = bd["return_30d"]
    max_dd = float(goal.get("max_drawdown", 0.08))
    target = float(goal.get("target_return_30d", 0.05))
    fail_score = float(goal.get("failure_below_score", -0.30))

    def chg(var, old, new, pred, why):
        return {"variable": var, "old_value": old, "new_value": new,
                "predicted_score_direction": pred, "rationale": why}

    # --- 1. PROTECT: drawdown breaching or close to the cap -> de-risk ---
    if dd > max_dd * 0.9:
        r = float(strat.get("risk_per_trade_r", 0.5))
        b = bounds.get("risk_per_trade_r", {})
        lo, step = float(b.get("min", 0.1)), float(b.get("step", 0.1))
        if r - step >= lo:
            return chg("risk_per_trade_r", r, round(r - step, 3), "+",
                       f"Drawdown {dd:.1%} near/over cap {max_dd:.1%}. Cutting risk per trade "
                       f"should shrink the equity swings and lift the drawdown sub-score.")
        cap = float(strat.get("daily_loss_cap_pct", 25.0))
        cb = bounds.get("daily_loss_cap_pct", {})
        clo, cstep = float(cb.get("min", 5.0)), float(cb.get("step", 5.0))
        if cap - cstep >= clo:
            return chg("daily_loss_cap_pct", cap, round(cap - cstep, 1), "+",
                       f"Risk already at floor but drawdown {dd:.1%} still high. Tightening the "
                       f"daily-loss cap halts losing days sooner.")
        return None

    # --- 2. DISCIPLINE: are losers clustering in the blocked night window? ---
    nb = strat.get("night_trade_block", {})
    losers = [t for t in trades if t.get("profit", 0.0) < 0]
    night_losers = [
        t for t in losers
        if trade_source.is_night_trade(t.get("time_epoch", 0),
                                       int(nb.get("start_hour", nb.get("start_utc", 22))),
                                       int(nb.get("end_hour", nb.get("end_utc", 8))))
    ]
    if losers and len(night_losers) / len(losers) >= 0.30 and not nb.get("enabled", True):
        new_nb = dict(nb)
        new_nb["enabled"] = True
        return chg("night_trade_block", nb, new_nb, "+",
                   f"{len(night_losers)}/{len(losers)} losing trades fell in 22:00-08:00 UTC. "
                   f"Re-enabling the night block - the strongest measured FRIDAY edge.")

    sharpe = bd.get("sharpe")
    every = int(goal.get("reflection_every", 20))
    enough_evidence = result["n_trades"] >= every

    # --- 3. STOP THE BLEEDING: net-losing or negative risk-adjusted return ---
    # A low drawdown vs a large equity base can flatter the composite even while the
    # system loses every trade, so gate on the raw return / Sharpe, not the composite.
    losing = ret30 < 0 or (sharpe is not None and sharpe < 0)
    if enough_evidence and losing:
        cd = float(strat.get("cooldown_minutes_after_loss", 0))
        cdb = bounds.get("cooldown_minutes_after_loss", {})
        cdstep, cdmax = float(cdb.get("step", 15)), float(cdb.get("max", 120))
        if cd <= 0 and cd + cdstep <= cdmax:
            return chg("cooldown_minutes_after_loss", cd, round(cd + cdstep), "+",
                       f"Window is net-losing (30d {ret30:+.1%}, sharpe {sharpe}). The deals show "
                       f"rapid back-to-back losses; a post-loss cooldown spaces trades out to break "
                       f"revenge-loss streaks.")
        r = float(strat.get("risk_per_trade_r", 0.5))
        b = bounds.get("risk_per_trade_r", {})
        lo, step = float(b.get("min", 0.1)), float(b.get("step", 0.1))
        if r - step >= lo:
            return chg("risk_per_trade_r", r, round(r - step, 3), "+",
                       f"Window is net-losing (30d {ret30:+.1%}, sharpe {sharpe}) and cooldown already "
                       f"set. Cutting risk per trade shrinks each loss while the edge is negative.")
        return None

    # --- 4. CHASE RETURN: only when genuinely profitable AND risk-adjusted-healthy ---
    healthy = (ret30 > 0 and sharpe is not None and sharpe > 0
               and composite >= 0.20 and dd < max_dd * 0.5)
    if enough_evidence and healthy and ret30 < target:
        r = float(strat.get("risk_per_trade_r", 0.5))
        b = bounds.get("risk_per_trade_r", {})
        hi, step = float(b.get("max", 2.0)), float(b.get("step", 0.1))
        if r + step <= hi:
            return chg("risk_per_trade_r", r, round(r + step, 3), "+",
                       f"Profitable and risk-adjusted-healthy (30d {ret30:+.1%}, sharpe {sharpe}, "
                       f"score {composite:+.2f}, dd {dd:.1%}) but below target {target:.1%}. "
                       f"Nudging risk up one step.")
        return None

    return None  # hold - nothing safe and useful to change this cycle


# ---------------------------------------------------------------------------
# Self-tuning: hill-climb the LIVE scalp knobs (unified_trader reads these).
# Round-robins one knob per cycle, nudges it one step (alternating direction
# across passes). The hypothesis-resolution loop KEEPS the nudge if next cycle's
# score improved and REVERTS it if it got worse — so only profitable values
# survive ("يتعلّم القيم المربحة ويحفظها").
# ---------------------------------------------------------------------------
SCALP_KNOBS = ["scalp_min_confidence", "scalp_ml_base_pwin", "scalp_global_max_open",
               "scalp_trail_trigger_pt", "scalp_trail_distance_pt"]


def explore_scalp(strat: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    cfg = strat.get("_self_tune", {}) or {}
    if not (cfg.get("enabled") and cfg.get("explore_scalp")):
        return None
    bounds = strat.get("_bounds", {})
    knobs = [k for k in SCALP_KNOBS if k in strat and k in bounds]
    if not knobs:
        return None
    n = int(state.get("reflection_count", 0))
    knob = knobs[n % len(knobs)]
    b = bounds.get(knob, {})
    lo, hi, step = float(b.get("min", 0)), float(b.get("max", 1)), float(b.get("step", 0.05))
    cur = float(strat.get(knob, lo))
    direction = 1.0 if ((n // len(knobs)) % 2 == 0) else -1.0
    new = cur + direction * step
    if new > hi:
        new = cur - step
    if new < lo:
        new = cur + step
    if new < lo or new > hi or abs(new - cur) < 1e-9:
        return None
    new = round(new) if knob == "scalp_global_max_open" else round(new, 4)
    if abs(new - cur) < 1e-9:
        return None
    return {"variable": knob, "old_value": cur, "new_value": new,
            "predicted_score_direction": "+",
            "rationale": f"Self-tune: probing {knob} {cur}->{new} for a more profitable value "
                         f"(kept if next cycle's score improves, auto-reverted if it worsens)."}


# ---------------------------------------------------------------------------
# Hermes mode: hand scored context to the `hermes` CLI, parse one-variable JSON.
# ---------------------------------------------------------------------------
def propose_hermes(
    strat: dict[str, Any],
    goal: dict[str, Any],
    result: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any] | None:
    prompt = {
        "task": "Propose exactly ONE variable to change in the FRIDAY strategy.",
        "goal": goal,
        "current_strategy": {k: v for k, v in strat.items() if not k.startswith("_")},
        "bounds": strat.get("_bounds", {}),
        "score": result,
        "recent_trades": trades[-WINDOW:],
        "output_contract": {
            "variable": "<one key from current_strategy>",
            "old_value": "<current value>",
            "new_value": "<new value within bounds>",
            "predicted_score_direction": "+ or -",
            "rationale": "<one sentence>",
        },
        "rules": ["Change exactly one variable.", "Stay within bounds.",
                  "Respect failure_below_score: never raise risk when score is below it.",
                  "Return ONLY a JSON object matching output_contract."],
    }
    try:
        proc = subprocess.run(
            ["hermes", "--json"],
            input=json.dumps(prompt), capture_output=True, text=True, timeout=180,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  hermes unavailable ({type(exc).__name__}); falling back to deterministic policy.")
        return propose_fallback(strat, goal, result, trades)

    out = (proc.stdout or "").strip()
    try:
        start, end = out.index("{"), out.rindex("}") + 1
        cand = json.loads(out[start:end])
        if cand.get("variable") in strat:
            return cand
    except (ValueError, json.JSONDecodeError):
        pass
    print("  hermes output unparseable; falling back to deterministic policy.")
    return propose_fallback(strat, goal, result, trades)


# ---------------------------------------------------------------------------
def resolve_open_hypothesis(
    state: dict[str, Any], strat: dict[str, Any], composite_now: float
) -> dict[str, Any] | None:
    """Judge the previous cycle's prediction. Returns a revert-change if it backfired."""
    hyp = state.get("open_hypothesis")
    if not hyp:
        return None

    prior = float(hyp.get("score_at_proposal", 0.0))
    pred = hyp.get("predicted_score_direction", "+")
    moved = composite_now - prior
    improved = moved > 0 if pred == "+" else moved < 0

    hyp["resolved_at"] = now_iso()
    hyp["score_after"] = round(composite_now, 4)
    hyp["score_delta"] = round(moved, 4)
    hyp["status"] = "confirmed" if improved else "refuted"
    append_hypothesis({"event": "resolution", **hyp})

    print(f"  Prior hypothesis [{hyp.get('variable')}]: predicted {pred}, "
          f"score moved {moved:+.3f} -> {hyp['status'].upper()}")

    # Revert only a refuted change that actually made things worse.
    if hyp["status"] == "refuted" and moved < -0.01 and "old_value" in hyp:
        var = hyp["variable"]
        return {"variable": var, "old_value": strat.get(var), "new_value": hyp["old_value"],
                "predicted_score_direction": "+",
                "rationale": f"Reverting {var}: last cycle's change refuted (score {moved:+.3f}). "
                             f"Restoring the prior value.",
                "_is_revert": True}
    return None


def apply_change(strat: dict[str, Any], change: dict[str, Any]) -> None:
    strat[change["variable"]] = change["new_value"]
    strat["updated_at"] = now_iso()


def run_cycle(mode: str, force: bool, refresh: bool) -> int:
    goal = read_json(GOAL_FILE, {})
    strat = read_json(STRAT_FILE, {})
    state = read_json(STATE_FILE, default_state())
    if not goal or not strat:
        print("ERROR: goal.json or strategy.json missing/empty.")
        return 1

    trades, src_note = trade_source.load_realized_trades(refresh=refresh)
    if src_note:
        print(f"  trade source: {src_note}")

    n_total = len(trades)
    new_since = n_total - int(state.get("trades_seen_at_last_reflection", 0))
    every = int(goal.get("reflection_every", 20))

    print(f"Reflection check: {n_total} realized trades total, {new_since} new since last cycle "
          f"(cadence = every {every}).")

    if new_since < every and not force:
        print(f"  Not enough new trades to reflect ({new_since}/{every}). Use --force to run anyway.")
        return 0

    window = trades[-WINDOW:]
    result = score_mod.score(window, goal)
    bd = result["breakdown"]
    print(f"  SCORE {result['composite']:+.3f}  (confidence={result['confidence']}, n={result['n_trades']})")
    print(f"    return_30d={bd['return_30d']:+.1%}  drawdown={bd['drawdown']:.1%}  "
          f"sharpe={bd['sharpe']}  pnl={bd['total_pnl']:+.2f}")
    for note in result["notes"]:
        print(f"    ! {note}")

    # 1) judge last cycle's prediction
    revert = resolve_open_hypothesis(state, strat, result["composite"])

    # 2) decide this cycle's single change (a revert pre-empts a new proposal)
    if revert is not None:
        change = revert
    elif mode == "hermes":
        change = propose_hermes(strat, goal, result, window)
    else:
        change = propose_fallback(strat, goal, result, window)
        # discipline rules take priority; if they hold, hill-climb a scalp knob
        # so the engine keeps learning profitable scalp values over time.
        if change is None:
            change = explore_scalp(strat, state)

    state["reflection_count"] = int(state.get("reflection_count", 0)) + 1
    state["trades_seen_at_last_reflection"] = n_total
    state["last_reflection_at"] = now_iso()

    if change is None:
        print("  DECISION: hold - no safe, useful single change this cycle.")
        state["open_hypothesis"] = None
        append_hypothesis({"event": "hold", "time": now_iso(),
                           "score_at_proposal": result["composite"],
                           "version": strat.get("version"), "n_trades": result["n_trades"]})
        write_json(STATE_FILE, state)
        return 0

    prior_ver = str(strat.get("version", "01"))
    archived = archive_strategy(strat)
    new_ver = bump_version(prior_ver)
    apply_change(strat, change)
    strat["version"] = new_ver
    write_json(STRAT_FILE, strat)

    hyp = {
        "event": "proposal",
        "time": now_iso(),
        "mode": mode,
        "version_from": prior_ver,
        "version_to": new_ver,
        "variable": change["variable"],
        "old_value": change.get("old_value"),
        "new_value": change.get("new_value"),
        "predicted_score_direction": change.get("predicted_score_direction", "+"),
        "rationale": change.get("rationale", ""),
        "is_revert": bool(change.get("_is_revert", False)),
        "score_at_proposal": result["composite"],
        "n_trades": result["n_trades"],
        "status": "open",
    }
    append_hypothesis(hyp)
    state["open_hypothesis"] = hyp
    write_json(STATE_FILE, state)

    tag = "REVERT" if hyp["is_revert"] else "CHANGE"
    print(f"  {tag}: {change['variable']}  {change.get('old_value')} -> {change.get('new_value')}  "
          f"(v{prior_ver} -> v{new_ver})")
    print(f"    why: {change.get('rationale')}")
    print(f"    prior archived to {archived}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FRIDAY reflection cycle")
    ap.add_argument("--fallback", action="store_true", help="deterministic policy (default)")
    ap.add_argument("--hermes", action="store_true", help="use the hermes CLI to propose the change")
    ap.add_argument("--force", action="store_true", help="run even below the trade-count cadence")
    ap.add_argument("--refresh", action="store_true", help="pull fresh closed deals from MT5 first")
    ap.add_argument("--loop", action="store_true", help="run continuously (self-improve over time)")
    ap.add_argument("--interval", type=int, default=600, help="seconds between cycles in --loop mode")
    args = ap.parse_args()
    mode = "hermes" if args.hermes else "fallback"

    if args.loop:
        import time
        print(f"[reflect] continuous self-tuning loop — every {args.interval}s "
              f"(mode={mode}, refresh={args.refresh}). Ctrl-C to stop.")
        while True:
            try:
                run_cycle(mode=mode, force=args.force, refresh=args.refresh)
            except KeyboardInterrupt:
                print("\n[reflect] stopped."); return 0
            except Exception as exc:
                print(f"[reflect] cycle error: {exc}")
            time.sleep(max(30, args.interval))

    return run_cycle(mode=mode, force=args.force, refresh=args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
