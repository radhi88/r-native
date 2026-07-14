"""runtime/palace_council.py — 5-Expert Trade Voting System.

Before ANY trade fires (from claude_trader, genome, or EA), it passes
through the council. 5 expert agents each return APPROVE / VETO / NEUTRAL.

Quorum: needs 3/5 APPROVE + 0 hard VETO to execute.

THE 5 EXPERTS:
  1. ARCHITECT  — pattern integrity (does the structural setup make sense)
  2. QUANT      — math and probability (R:R, expected value, sharpe-like)
  3. RISK       — position sizing, account exposure, drawdown impact
  4. EXECUTOR   — practical execution (spread, ATR, slippage risk)
  5. REVIEWER   — historical similarity (similar setups in brain_memory)

Each expert has VETO power on its dimension only — e.g., RISK can veto
even if the other 4 approve, if equity floor would be breached.

This is the "ضمير" of the trading system — prevents emotional/buggy entries.

Run as imported module: `from runtime.palace_council import council_vote`
Or as standalone process to evaluate incoming signals from genome_signals.jsonl.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

VOTES_LOG = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\council_votes.jsonl")
BRAIN_LIVE = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
BRAIN_MEMORY = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_memory.jsonl")
SIGNALS = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\genome_signals.jsonl")
EXECUTIONS = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\council_executions.jsonl")

# Trade execution settings
COUNCIL_MAGIC = 99779   # different from trader (99777) and EA (99778)
SYMBOL = "XAUUSDm"
EXECUTE_APPROVED_SIGNALS = True   # actually place trades, not just log
COOLDOWN_AFTER_TRADE_SEC = 90     # don't fire again immediately


def _append(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


# ───────────── EXPERT 1: ARCHITECT (pattern integrity) ─────────────
def expert_architect(decision: dict, snap: dict) -> tuple[str, str]:
    """Does the structural setup make sense?"""
    side = decision.get("side")
    rule = decision.get("rule", "")
    reasons = []

    # Check if decision side aligns with overall structure
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    bias_m15 = snap.get("bias", {}).get("m15", "?")

    # Counter-trend setups need stronger justification
    if side == "BUY" and bias_m5 == "DOWN" and bias_m15 == "DOWN":
        if "counter" not in rule.lower() and "sweep" not in rule.lower() and "demand" not in rule.lower():
            return ("VETO", f"BUY against M5+M15 DOWN with non-counter rule {rule}")

    if side == "SELL" and bias_m5 == "UP" and bias_m15 == "UP":
        if "parabolic" not in rule.lower() and "sweep" not in rule.lower() and "supply" not in rule.lower():
            return ("VETO", f"SELL against M5+M15 UP with non-counter rule {rule}")

    # Check if entry near key levels makes sense
    fp = snap.get("footprint", {})
    if side == "BUY" and fp.get("in_supply_zone"):
        return ("VETO", "BUY inside SUPPLY zone is structurally backwards")
    if side == "SELL" and fp.get("in_demand_zone"):
        return ("VETO", "SELL inside DEMAND zone is structurally backwards")

    return ("APPROVE", f"structure aligned: {side} with bias M5={bias_m5}")


# ───────────── EXPERT 2: QUANT (probability + R:R) ─────────────
def expert_quant(decision: dict, snap: dict) -> tuple[str, str]:
    """Math check — is the expected value positive?"""
    entry = decision.get("entry", 0)
    sl = decision.get("sl", 0)
    tp = decision.get("tp", 0)
    side = decision.get("side")
    if not all([entry, sl, tp, side]): return ("VETO", "missing entry/SL/TP")

    if side == "BUY":
        risk = entry - sl
        reward = tp - entry
    else:
        risk = sl - entry
        reward = entry - tp

    if risk <= 0 or reward <= 0:
        return ("VETO", f"invalid R:R risk={risk:.2f} reward={reward:.2f}")
    rr = reward / risk
    if rr < 1.0:
        return ("VETO", f"R:R {rr:.2f} below 1:1")
    if rr < 1.5:
        return ("NEUTRAL", f"R:R {rr:.2f} marginal")

    # Probability estimate from confluence
    confidence = decision.get("confluence", 3)
    win_prob = min(0.7, 0.4 + confidence * 0.05)   # 3 conf = 55%, 7 conf = 70%
    ev = win_prob * reward - (1 - win_prob) * risk
    if ev <= 0:
        return ("VETO", f"EV ${ev:.2f} negative (p={win_prob:.0%}, RR={rr:.2f})")

    return ("APPROVE", f"R:R {rr:.2f}, p={win_prob:.0%}, EV ${ev:.2f}")


# ───────────── EXPERT 3: RISK (sizing + exposure) ─────────────
def expert_risk(decision: dict, snap: dict, mt5_state: dict) -> tuple[str, str]:
    """Sizing and exposure check — adapts to account size."""
    lot = decision.get("size", 0)
    side = decision.get("side")
    entry = decision.get("entry", 0)
    sl = decision.get("sl", 0)

    equity = mt5_state.get("equity", 0)
    balance = mt5_state.get("balance", 0)
    if equity <= 0 or balance <= 0:
        return ("NEUTRAL", "no account state available")

    # Per-trade risk in USD
    if side == "BUY":
        risk_pts = entry - sl
    else:
        risk_pts = sl - entry
    risk_usd = risk_pts * lot * 100
    risk_pct = (risk_usd / balance) * 100

    # Daily loss limit — adapt to balance (15% of balance, $15 minimum)
    daily_limit = -max(15.0, balance * 0.15)
    day_pnl = mt5_state.get("day_pnl", 0)
    if day_pnl <= daily_limit:
        return ("VETO", f"daily PnL ${day_pnl:.2f} ≤ ${daily_limit:.2f} limit")

    # Equity floor — adapt to balance (15% drawdown or $15 minimum)
    floor = balance - max(15.0, balance * 0.15)
    if equity < floor:
        return ("VETO", f"equity ${equity:.2f} below floor ${floor:.2f}")

    # Risk per trade threshold — adapt to balance size
    # Tiny accounts (<$150): allow up to 10% per trade (0.01 lot is still min)
    # Small ($150-$500): 6% cap
    # Medium ($500-$2000): 4% cap
    # Large (>$2000): 2% cap
    if balance < 150:
        veto_pct = 10.0; warn_pct = 7.0
    elif balance < 500:
        veto_pct = 6.0;  warn_pct = 4.0
    elif balance < 2000:
        veto_pct = 4.0;  warn_pct = 2.5
    else:
        veto_pct = 2.0;  warn_pct = 1.0

    # Special case: if lot is already at minimum 0.01 and risk is reasonable USD,
    # don't veto — micro accounts can't go smaller
    if lot <= 0.01 and risk_usd <= 5.0 and balance < 200:
        return ("APPROVE", f"micro acct: ${risk_usd:.2f} risk @ min lot (balance ${balance:.0f})")

    if risk_pct > veto_pct:
        return ("VETO", f"risk {risk_pct:.1f}% > {veto_pct:.0f}% cap (bal ${balance:.0f})")
    if risk_pct > warn_pct:
        return ("NEUTRAL", f"risk {risk_pct:.1f}% > {warn_pct:.0f}% warn")

    return ("APPROVE", f"risk ${risk_usd:.2f} ({risk_pct:.1f}% of ${balance:.0f})")


# ───────────── EXPERT 4: EXECUTOR (practical fills) ─────────────
def expert_executor(decision: dict, snap: dict) -> tuple[str, str]:
    """Practical execution conditions."""
    spread = snap.get("spread", 0)
    atr_m1 = snap.get("atr", {}).get("m1", 0)

    if spread > 0.60:
        return ("VETO", f"spread ${spread:.2f} too wide")
    if spread > 0.40:
        return ("NEUTRAL", f"spread ${spread:.2f} elevated")

    # Check if SL/TP distance is achievable vs spread
    entry = decision.get("entry", 0)
    sl = decision.get("sl", 0)
    sl_distance = abs(entry - sl)
    if sl_distance < spread * 3:
        return ("VETO", f"SL distance ${sl_distance:.2f} < 3× spread")

    # ATR sanity check
    if atr_m1 > 8:
        return ("NEUTRAL", f"ATR_M1 ${atr_m1:.2f} high — volatile")

    return ("APPROVE", f"spread ${spread:.2f} OK, ATR ${atr_m1:.2f}")


# ───────────── EXPERT 5: REVIEWER (historical similarity) ─────────────
def expert_reviewer(decision: dict, snap: dict, memory: list) -> tuple[str, str]:
    """Look for similar setups in brain_memory and their outcomes."""
    if len(memory) < 20:
        return ("APPROVE", "insufficient history, accepting on faith")

    side = decision.get("side")
    rule = decision.get("rule", "")
    rsi_m1 = snap.get("rsi", {}).get("m1", 50)
    bias_m5 = snap.get("bias", {}).get("m5", "?")
    session = snap.get("session", "?")

    # Count similar conditions in memory
    similar = 0
    for s in memory[-100:]:
        if (s.get("bias", {}).get("m5") == bias_m5 and
            abs(s.get("rsi", {}).get("m1", 50) - rsi_m1) < 5 and
            s.get("session") == session):
            similar += 1

    if similar < 3:
        return ("NEUTRAL", f"only {similar} similar setups in history")
    if similar > 20:
        return ("NEUTRAL", f"{similar} very common pattern (low edge)")
    return ("APPROVE", f"{similar} similar setups in last 100 snapshots")


# ───────────── COUNCIL VOTE (main entry point) ─────────────
def council_vote(decision: dict, snap: dict, mt5_state: dict | None = None,
                  memory: list | None = None) -> dict:
    """Aggregate 5 expert votes. Returns dict with verdict + breakdown."""
    if mt5_state is None: mt5_state = {}
    if memory is None: memory = []

    votes = {
        "architect": expert_architect(decision, snap),
        "quant":     expert_quant(decision, snap),
        "risk":      expert_risk(decision, snap, mt5_state),
        "executor":  expert_executor(decision, snap),
        "reviewer":  expert_reviewer(decision, snap, memory),
    }

    approves = sum(1 for v, _ in votes.values() if v == "APPROVE")
    vetos    = sum(1 for v, _ in votes.values() if v == "VETO")

    verdict = "EXECUTE" if (approves >= 3 and vetos == 0) else "BLOCK"

    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "decision": {
            "side": decision.get("side"),
            "rule": decision.get("rule"),
            "lot": decision.get("size"),
            "entry": decision.get("entry"),
        },
        "votes": {k: {"vote": v[0], "reason": v[1]} for k, v in votes.items()},
        "approves": approves,
        "vetos":    vetos,
        "verdict":  verdict,
    }
    _append(VOTES_LOG, result)
    return result


# ───────────── EXECUTE APPROVED TRADE ─────────────
def execute_approved(mt5, decision: dict) -> dict:
    """Place trade for a council-approved decision."""
    side = decision.get("side")
    lot = float(decision.get("size", 0.01))
    entry = float(decision.get("entry", 0))
    sl = float(decision.get("sl", 0))
    tp = float(decision.get("tp", 0))
    rule = decision.get("rule", "GENOME_unk")

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return {"status": "no_tick"}
    price = tick.ask if side == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    50,
        "magic":        COUNCIL_MAGIC,
        "comment":      f"COUNCIL_{rule}"[:31],
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    res = mt5.order_send(req)
    ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    if not ok:
        req["type_filling"] = mt5.ORDER_FILLING_IOC
        res = mt5.order_send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
    return {
        "status": "FILLED" if ok else "FAILED",
        "ticket": int(res.order) if ok else 0,
        "price":  float(res.price) if ok else 0,
        "retcode": getattr(res, "retcode", None) if res else None,
        "comment": getattr(res, "comment", None) if res else None,
    }


# ───────────── STANDALONE MODE: process genome signals ─────────────
def main_loop():
    """Standalone: read genome_signals.jsonl, vote on each new signal."""
    import MetaTrader5 as mt5
    if not mt5.initialize(): mt5.initialize()

    print(f"[council] ONLINE — processing genome signals")
    print(f"  EXECUTION: {'ENABLED' if EXECUTE_APPROVED_SIGNALS else 'DISABLED'}")
    print(f"  Council magic: {COUNCIL_MAGIC}")
    print(f"  Cooldown after trade: {COOLDOWN_AFTER_TRADE_SEC}s")
    # On boot: skip to end of file so we don't replay hours of historical signals
    last_offset = SIGNALS.stat().st_size if SIGNALS.exists() else 0
    if last_offset > 0:
        print(f"  [boot] skipping {last_offset} bytes of historical signals — starting from tail")
    last_trade_ts = 0
    last_review_ts = 0.0
    REVIEW_EVERY_SEC = 60     # how often the council weighs in on governance
    MAX_SIGNAL_AGE_SEC = 60  # ignore signals older than this

    while True:
        try:
            if not SIGNALS.exists():
                time.sleep(2); continue
            text = SIGNALS.read_text(encoding="utf-8")
            if len(text) <= last_offset:
                time.sleep(2); continue
            new_lines = text[last_offset:].splitlines()
            last_offset = len(text)

            snap = json.loads(BRAIN_LIVE.read_text(encoding="utf-8")) if BRAIN_LIVE.exists() else {}
            acc = mt5.account_info()
            mt5_state = {
                "balance": acc.balance if acc else 0,
                "equity":  acc.equity if acc else 0,
                "day_pnl": (acc.equity - acc.balance) if acc else 0,
            }
            memory = []
            if BRAIN_MEMORY.exists():
                for line in BRAIN_MEMORY.read_text(encoding="utf-8").splitlines()[-100:]:
                    try: memory.append(json.loads(line))
                    except: pass

            for line in new_lines:
                if not line.strip(): continue
                try: sig = json.loads(line)
                except: continue

                # Skip signals older than MAX_SIGNAL_AGE_SEC (stale)
                sig_ts = sig.get("ts", "")
                if sig_ts:
                    try:
                        from datetime import datetime, timezone
                        t = datetime.fromisoformat(sig_ts.replace("Z", "+00:00"))
                        age = (datetime.now(timezone.utc) - t).total_seconds()
                        if age > MAX_SIGNAL_AGE_SEC:
                            continue  # silently skip stale signal
                    except Exception:
                        pass

                # CRITICAL: use CURRENT tick price, not signal's stale price
                tick = mt5.symbol_info_tick(SYMBOL)
                if not tick: continue
                action = sig.get("action")
                live_entry = tick.ask if action == "BUY" else tick.bid

                # Balance-adaptive sizing: cap risk at 3% of balance
                balance = mt5_state.get("balance", 100)
                max_risk_usd = balance * 0.03      # 3% per trade cap
                sl_pts = 3.0                        # tight SL for genome signals
                # XAU: 1pt × 0.01 lot ≈ $1, so risk = sl_pts × lot × 100
                # Solve for lot: lot = max_risk_usd / (sl_pts × 100)
                adaptive_lot = round(max_risk_usd / (sl_pts * 100), 2)
                adaptive_lot = max(0.01, min(0.05, adaptive_lot))
                decision = {
                    "side": action,
                    "rule": f"GENOME_{sig.get('genome', 'unk')}",
                    "size": adaptive_lot,
                    "entry": live_entry,
                    "sl":    live_entry - sl_pts if action == "BUY" else live_entry + sl_pts,
                    "tp":    live_entry + sl_pts * 2.0 if action == "BUY" else live_entry - sl_pts * 2.0,
                    "confluence": max(3, int(sig.get("confidence", 0.5) * 7)),
                }
                result = council_vote(decision, snap, mt5_state, memory)
                mark = "✅" if result["verdict"] == "EXECUTE" else "❌"
                print(f"[{datetime.now():%H:%M:%S}] {mark} {sig.get('genome'):18} {sig.get('action'):4} "
                       f"approves {result['approves']}/5 vetos {result['vetos']} "
                       f"→ {result['verdict']}")
                if result["verdict"] == "BLOCK":
                    blocked_by = [k for k, v in result["votes"].items() if v["vote"] == "VETO"]
                    print(f"    blocked by: {', '.join(blocked_by)}")
                    continue

                # EXECUTE — but respect cooldown + max open positions
                if not EXECUTE_APPROVED_SIGNALS: continue
                now_ts = time.time()
                if now_ts - last_trade_ts < COOLDOWN_AFTER_TRADE_SEC:
                    print(f"    ⏸ cooldown ({int(COOLDOWN_AFTER_TRADE_SEC - (now_ts - last_trade_ts))}s remaining)")
                    continue
                # Max 3 open council positions
                positions = mt5.positions_get(symbol=SYMBOL) or []
                council_pos = [p for p in positions if int(p.magic) == COUNCIL_MAGIC]
                if len(council_pos) >= 3:
                    print(f"    ⛔ max 3 council positions open already")
                    continue

                exec_result = execute_approved(mt5, decision)
                if exec_result["status"] == "FILLED":
                    print(f"    🎯 EXECUTED #{exec_result['ticket']} @ {exec_result['price']:.2f} "
                          f"SL {decision['sl']:.2f} TP {decision['tp']:.2f}")
                    last_trade_ts = now_ts
                else:
                    print(f"    ❌ exec failed: {exec_result.get('retcode')} {exec_result.get('comment')}")
                _append(EXECUTIONS, {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "decision": decision,
                    "council": result,
                    "execution": exec_result,
                })

            # Operator duty: the council also reviews its peers' governance
            # proposals (throttled). Same gate philosophy as its trade votes —
            # approve safe peer changes, abstain on money/code (Claude's call).
            now = time.time()
            if now - last_review_ts >= REVIEW_EVERY_SEC:
                last_review_ts = now
                try:
                    from runtime.shared.agent_operator import AgentOperator
                    votes = AgentOperator("palace_council").review_peers()
                    if votes:
                        print(f"[council] peer-review: {len(votes)} proposals → {votes}")
                except Exception as _e:
                    pass

        except KeyboardInterrupt:
            print("[council] stopped"); break
        except Exception as e:
            print(f"[council] err: {e}")
        time.sleep(2)


if __name__ == "__main__":
    main_loop()
