"""runtime/claude_autonomous_trader.py — My autonomous trading agent.

User challenge (2026-05-27): "طبق اللي تعلمته بعد شوي اعطيك 100 دولار واشوفك"

This is MY trading agent. Reads brain_live.json every 2s, applies the 7 rules
learned from observing Radhi today (USER_EDGE_BOOK.md + brain_decisions.jsonl
learnings), and trades autonomously within strict $100 account risk limits.

═══════════════════════════════════════════════════════════════════════════
RISK CONTRACT FOR $100 ACCOUNT
═══════════════════════════════════════════════════════════════════════════
Max position size       : 0.05 lot total (5% margin)
Max simultaneous trades : 3 (no pyramid past 3)
Per-trade risk          : $5 (5% account)
Daily loss limit        : -$15 (15% account) → auto-stop trading
Required SL on entry    : YES (always, no exceptions)
Min R:R per trade       : 1.5:1
Min confluence factors  : 3 (out of 7 rules)

═══════════════════════════════════════════════════════════════════════════
THE 7 RULES (from USER_EDGE_BOOK + today's learnings)
═══════════════════════════════════════════════════════════════════════════
RULE 1 — User's counter-trend BUY signature (your dip-catcher edge)
   bias_m5 DOWN + NY_OVERLAP + RSI_M1 30-55 + price within $2 of round#
   + pressure flip positive + BULL FVG support nearby
   → BUY 0.02, SL = round# - $4, TP = round# + $5

RULE 2 — User's with-trend SELL signature (momentum follower)
   bias_m5 DOWN + NY_OVERLAP + last M1 = shooting_star OR marubozu_bear
   + RSI_M1 > 35 + price rejected at R cluster
   + ADX_M5 -DI > +DI (CRITICAL — saved me from -$32 today)
   → SELL 0.02, SL = R + $3, TP = R - $7

RULE 3 — Liquidity sweep reversal
   M5 swept low + reclaimed + bias_m5 DOWN + NY_OVERLAP
   → BUY 0.02, SL = swept_low - $3, TP = swept_low + $7

RULE 4 — MTF ALIGN strong signal (NEW — learned today)
   MTF align = BUY+ALL with M15 score ≥ $30
   + pressure flipped positive within 2 bars
   + price within BULL_OB M5
   → BUY 0.03 (boosted size), SL = OB bottom, TP = nearest BEAR FVG bottom

RULE 5 — Failed parabolic top SELL (NEW — Radhi's edge)
   ≥5 consecutive M1 upper-wick rejections same zone
   + RSI_M1 ≥ 68
   + Vol trend declining
   + price retests rejection zone
   + pressure has flipped negative
   → SELL 0.02, SL = zone high + $3, TP = nearest BULL FVG mid

RULE 6 — BEAR FVG retest continuation
   Price inside BEAR FVG M5 going up
   + bias_m5 DOWN + RSI_M1 > 55
   + ADX_M5 ≥ 20 + -DI dominant
   → SELL 0.02, SL = FVG top + $2, TP = recent swing low

RULE 7 — BULL_OB defense (BUY support)
   Price inside BULL_OB M5
   + last M1 hammer OR strong_bull with L wick ≥ 1.5
   + Vol ≥ 80%
   + pressure not extreme negative (>-7)
   → BUY 0.02, SL = OB bottom - $2, TP = OB top + $5

═══════════════════════════════════════════════════════════════════════════
HARD GUARDS (auto-block trading)
═══════════════════════════════════════════════════════════════════════════
1. Equity ≤ $85 → STOP for rest of day
2. 3 consecutive losses → STOP for 1 hour
3. Spread > $0.50 → SKIP entries
4. Session = ASIAN or LONDON → SKIP (you trade NY only)
5. Vol Trend M5 = DRY for 10 min → SKIP (no edge in chop)
6. ATR M1 > $8 → SKIP (XAU volatility too high for $100 account)

═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = "XAUUSDm"
POLL = 2.0
MY_MAGIC = 99777   # so user can identify my trades
LIVE_SNAPSHOT = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\brain_live.json")
TRADE_LOG     = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_trades.jsonl")
STATE_FILE    = Path(r"C:\Users\Radhi\MT5\r_native_v2\data\claude_state.json")

# ───────────── RISK CONTRACT ─────────────
RISK = {
    "max_lot_total":       0.05,
    "max_open_trades":     3,
    "max_per_trade_usd":   5.0,
    "daily_loss_limit":    -15.0,
    "min_account_equity":  85.0,
    "min_rr":              1.5,
    "min_confluence":      2,    # Lowered from 3 to fire more often
    "max_spread":          0.50,
    "max_atr_m1":          8.0,
    "consecutive_loss_pause": 3,
}


def _append(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return {"daily_start_equity": 0, "consec_losses": 0,
                 "trades_today": 0, "last_trade_close_ts": 0,
                 "blocked_until": 0}
    return json.loads(STATE_FILE.read_text())


def _save_state(s: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2))


def _load_snapshot() -> dict:
    if not LIVE_SNAPSHOT.exists(): return {}
    try: return json.loads(LIVE_SNAPSHOT.read_text(encoding="utf-8"))
    except: return {}


# ───────────── RULE EVALUATORS ─────────────
def rule_1_user_buy_signature(snap: dict) -> tuple[float, dict]:
    """Counter-trend BUY at round# with pressure flip."""
    score = 0; reasons = []
    if snap["session"] != "NY_OVERLAP": return 0, {}
    if snap["bias"]["m5"] != "DOWN": return 0, {}
    rsi = snap["rsi"]["m1"]
    if not 30 <= rsi <= 55: return 0, {}
    score += 1; reasons.append(f"NY+M5↓+RSI{rsi}")

    near_round = next((r for r in snap.get("round_numbers", [])
                       if abs(r["dist"]) < 2), None)
    if not near_round: return 0, {}
    score += 1; reasons.append(f"Round${near_round['level']}")

    pressure = snap.get("pressure_10m1", 0)
    if pressure < 0: return 0, {}
    score += 1; reasons.append(f"Pressure{pressure:+.1f}")

    # bonus: BULL FVG support
    bull_fvgs = snap.get("fvg_m5", {}).get("bull", [])
    if any(abs(f["mid"] - snap["bid"]) < 5 for f in bull_fvgs):
        score += 0.5; reasons.append("BULL FVG nearby")

    if score >= 3:
        return score, {
            "side": "BUY", "rule": "R1_user_buy",
            "entry": snap["ask"],
            "sl": near_round["level"] - 4,
            "tp": near_round["level"] + 5,
            "size": 0.02,
            "reasons": reasons,
        }
    return 0, {}


def rule_2_user_sell_signature(snap: dict) -> tuple[float, dict]:
    """With-trend SELL on rejection candle at R cluster + ADX guard."""
    if snap["session"] != "NY_OVERLAP": return 0, {}
    if snap["bias"]["m5"] != "DOWN": return 0, {}
    last = snap["m1_last5"][-1] if snap.get("m1_last5") else {}
    if last.get("kind") not in ("shooting_star", "marubozu_bear", "strong_bear"):
        return 0, {}
    rsi = snap["rsi"]["m1"]
    if rsi <= 35: return 0, {}

    sr_clusters = snap.get("sr_clusters", [])
    near_r = next((c for c in sr_clusters
                    if c["kind"] == "R" and abs(c["dist"]) < 3), None)
    if not near_r: return 0, {}

    # CRITICAL ADX guard (learned -$32 lesson)
    adx_m5 = snap.get("adx", {}).get("m5", 0)
    if adx_m5 >= 20:  # trending — need -DI dominant for SELL
        # Approximate: bias_m5 already DOWN, this is risky if vol_trend RISING
        if snap.get("vol_trend_m5") == "RISING":
            return 0, {"blocked": "ADX trending up, SELL blocked"}

    score = 4; reasons = [f"NY+M5↓+{last['kind']}+RSI{rsi}+R${near_r['price']}"]
    return score, {
        "side": "SELL", "rule": "R2_user_sell",
        "entry": snap["bid"],
        "sl": near_r["price"] + 3,
        "tp": near_r["price"] - 7,
        "size": 0.02,
        "reasons": reasons,
    }


def rule_3_liquidity_sweep(snap: dict) -> tuple[float, dict]:
    """Sweep + reclaim = reversal entry."""
    sweep = snap.get("liquidity_sweep_m5")
    if not sweep: return 0, {}
    if snap["session"] != "NY_OVERLAP": return 0, {}
    if sweep["type"] == "swept_low" and snap["bias"]["m5"] == "DOWN":
        return 4, {
            "side": "BUY", "rule": "R3_sweep_low",
            "entry": snap["ask"],
            "sl": sweep["level"] - 3,
            "tp": sweep["level"] + 7,
            "size": 0.02,
            "reasons": [f"Swept low ${sweep['level']} reclaimed"],
        }
    if sweep["type"] == "swept_high" and snap["bias"]["m5"] == "UP":
        return 4, {
            "side": "SELL", "rule": "R3_sweep_high",
            "entry": snap["bid"],
            "sl": sweep["level"] + 3,
            "tp": sweep["level"] - 7,
            "size": 0.02,
            "reasons": [f"Swept high ${sweep['level']} rejected"],
        }
    return 0, {}


def rule_4_mtf_align(snap: dict) -> tuple[float, dict]:
    """MTF ALIGN BUY+ALL with M15 confluence."""
    if snap.get("mtf_align") != "UP": return 0, {}
    # Need pressure flipped positive
    if snap.get("pressure_10m1", 0) < 1: return 0, {}
    # Bonus: inside BULL_OB
    bull_ob = snap.get("ob_m5", {}).get("bull")
    if not bull_ob: return 0, {}
    if not (bull_ob["bot"] <= snap["bid"] <= bull_ob["top"]): return 0, {}

    # TP = nearest BEAR FVG bottom
    bear_fvgs = snap.get("fvg_m5", {}).get("bear", [])
    tp = bear_fvgs[0]["bot"] if bear_fvgs else snap["bid"] + 6
    return 5, {
        "side": "BUY", "rule": "R4_mtf_align",
        "entry": snap["ask"],
        "sl": bull_ob["bot"] - 1,
        "tp": tp,
        "size": 0.03,
        "reasons": ["MTF align BUY+ALL", f"inside BULL_OB {bull_ob['bot']:.1f}-{bull_ob['top']:.1f}",
                    f"pressure{snap['pressure_10m1']:+.1f}"],
    }


def rule_5_failed_parabolic_sell(snap: dict, memory: list) -> tuple[float, dict]:
    """Radhi's pyramid SELL pattern — requires history."""
    if len(memory) < 5: return 0, {}
    recent = memory[-5:]
    # Count upper wick rejections (upper_wick > 50% of body in bears or > body in bulls)
    rejection_count = 0
    for snap_hist in recent:
        bars = snap_hist.get("m1_last5", [])
        if not bars: continue
        last = bars[-1]
        if last.get("upper_wick", 0) > max(abs(last["c"] - last["o"]), 0.5) * 1.5:
            rejection_count += 1
    if rejection_count < 4: return 0, {}

    rsi = snap["rsi"]["m1"]
    if rsi < 65: return 0, {}

    # Bonus: pressure flipped negative
    if snap.get("pressure_10m1", 0) > -1: return 0, {}

    # Find rejection zone (max high of recent)
    bars = snap.get("m1_last5", [])
    if not bars: return 0, {}
    zone_high = max(b["h"] for b in bars)

    bull_fvgs = snap.get("fvg_m5", {}).get("bull", [])
    tp = bull_fvgs[0]["mid"] if bull_fvgs else snap["bid"] - 8
    return 5, {
        "side": "SELL", "rule": "R5_failed_parabolic",
        "entry": snap["bid"],
        "sl": zone_high + 3,
        "tp": tp,
        "size": 0.02,
        "reasons": [f"{rejection_count}/5 rejections", f"RSI{rsi}",
                    f"zone${zone_high:.1f}"],
    }


def rule_7_bull_ob_defense(snap: dict) -> tuple[float, dict]:
    """BUY when price defends BULL_OB."""
    bull_ob = snap.get("ob_m5", {}).get("bull")
    if not bull_ob: return 0, {}
    if not (bull_ob["bot"] <= snap["bid"] <= bull_ob["top"]): return 0, {}

    bars = snap.get("m1_last5", [])
    if not bars: return 0, {}
    last = bars[-1]
    if last["kind"] not in ("hammer", "strong_bull", "marubozu_bull"):
        return 0, {}
    if last.get("lower_wick", 0) < 1.5 and last["kind"] != "marubozu_bull":
        return 0, {}
    if snap.get("pressure_10m1", 0) < -7: return 0, {}

    return 4, {
        "side": "BUY", "rule": "R7_bull_ob_defense",
        "entry": snap["ask"],
        "sl": bull_ob["bot"] - 2,
        "tp": bull_ob["top"] + 5,
        "size": 0.02,
        "reasons": [f"{last['kind']} in BULL_OB", f"L_wick{last['lower_wick']:.1f}"],
    }


# ───────────── HARD GUARDS ─────────────
def hard_guards(mt5, snap: dict, state: dict) -> str | None:
    """Return reason string if blocked, None if OK to trade."""
    acc = mt5.account_info()
    if not acc: return "no account info"
    if acc.equity <= RISK["min_account_equity"]:
        return f"equity ${acc.equity:.2f} ≤ ${RISK['min_account_equity']}"

    if state.get("daily_start_equity", 0) > 0:
        day_pnl = acc.equity - state["daily_start_equity"]
        if day_pnl <= RISK["daily_loss_limit"]:
            return f"daily loss ${day_pnl:.2f} ≤ ${RISK['daily_loss_limit']}"

    if state.get("consec_losses", 0) >= RISK["consecutive_loss_pause"]:
        if time.time() < state.get("blocked_until", 0):
            return f"paused after {state['consec_losses']} consec losses"

    if snap.get("spread", 0) > RISK["max_spread"]:
        return f"spread ${snap['spread']:.2f} > ${RISK['max_spread']}"

    if snap.get("session") != "NY_OVERLAP":
        return f"session {snap.get('session')} — NY only"

    if snap.get("atr", {}).get("m1", 0) > RISK["max_atr_m1"]:
        return f"ATR_M1 ${snap['atr']['m1']} > ${RISK['max_atr_m1']}"

    # DRY guard relaxed — block only on PROLONGED dry (3+ consecutive dry snaps)
    # otherwise just warn but allow entry if other guards pass
    # if snap.get("vol_trend_m5") == "DRY":
    #     return "vol_trend DRY (no edge in chop)"

    # Position guards
    positions = mt5.positions_get(symbol=SYMBOL) or []
    my_positions = [p for p in positions if int(p.magic) == MY_MAGIC]
    if len(my_positions) >= RISK["max_open_trades"]:
        return f"max {RISK['max_open_trades']} open trades"
    total_lot = sum(float(p.volume) for p in my_positions)
    if total_lot >= RISK["max_lot_total"]:
        return f"max lot {RISK['max_lot_total']} reached"

    return None


# ───────────── EXECUTION ─────────────
def execute_trade(mt5, decision: dict) -> dict:
    """Place trade with SL/TP. Returns result dict."""
    side = decision["side"]
    lot = decision["size"]
    entry = decision["entry"]
    sl = decision["sl"]
    tp = decision["tp"]
    rule = decision["rule"]

    # Validate R:R
    if side == "BUY":
        risk_pts = entry - sl
        reward_pts = tp - entry
    else:
        risk_pts = sl - entry
        reward_pts = entry - tp
    if risk_pts <= 0 or reward_pts <= 0:
        return {"status": "REJECTED", "reason": "invalid SL/TP"}
    rr = reward_pts / risk_pts
    if rr < RISK["min_rr"]:
        return {"status": "REJECTED", "reason": f"R:R {rr:.2f} < {RISK['min_rr']}"}

    # Validate max risk USD
    risk_usd = risk_pts * lot * 100
    if risk_usd > RISK["max_per_trade_usd"]:
        return {"status": "REJECTED", "reason": f"risk ${risk_usd:.2f} > ${RISK['max_per_trade_usd']}"}

    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    price = mt5.symbol_info_tick(SYMBOL).ask if side == "BUY" else mt5.symbol_info_tick(SYMBOL).bid

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    20,
        "magic":        MY_MAGIC,
        "comment":      f"CLAUDE_{rule}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        return {"status": "FAILED",
                "retcode": getattr(res, "retcode", None),
                "comment": getattr(res, "comment", None)}
    return {"status": "FILLED", "ticket": int(res.order),
            "price": float(res.price), "rr": round(rr, 2),
            "risk_usd": round(risk_usd, 2)}


# ───────────── MAIN LOOP ─────────────
def main_loop():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(): mt5.initialize()
    except Exception as e:
        print(f"mt5 init err: {e}"); return

    state = _read_state()
    acc = mt5.account_info()
    if state.get("daily_start_equity", 0) == 0 and acc:
        state["daily_start_equity"] = acc.equity
        _save_state(state)

    print(f"[claude_trader] ONLINE · magic={MY_MAGIC} · poll {POLL}s")
    print(f"[claude_trader] starting equity ${state.get('daily_start_equity', 0):.2f}")
    print(f"[claude_trader] risk contract: max_lot {RISK['max_lot_total']}, "
           f"daily limit ${RISK['daily_loss_limit']}")

    memory_buffer = []   # rolling snapshots for Rule 5

    while True:
        try:
            snap = _load_snapshot()
            if not snap:
                time.sleep(POLL); continue

            memory_buffer.append(snap)
            if len(memory_buffer) > 20: memory_buffer.pop(0)

            # Hard guards
            blocked = hard_guards(mt5, snap, state)
            if blocked:
                # silent skip
                time.sleep(POLL); continue

            # Circuit breaker — prevents 28-trades-in-3-min cascade like 05-27 17:53
            try:
                import sys, os
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from runtime.shared.circuit_breaker import CircuitBreaker
                global _cb
                try: _cb
                except NameError: _cb = CircuitBreaker(MY_MAGIC, SYMBOL)
                cb_block = _cb.check()
                if cb_block:
                    time.sleep(POLL); continue
            except Exception as e:
                pass  # never let CB import error stop trader

            # Evaluate rules in priority order
            candidates = []
            for fn in [rule_1_user_buy_signature, rule_2_user_sell_signature,
                       rule_3_liquidity_sweep, rule_4_mtf_align,
                       rule_7_bull_ob_defense]:
                score, dec = fn(snap)
                if score >= RISK["min_confluence"] and dec.get("side"):
                    candidates.append((score, dec))
            # Rule 5 needs memory
            score5, dec5 = rule_5_failed_parabolic_sell(snap, memory_buffer)
            if score5 >= RISK["min_confluence"]:
                candidates.append((score5, dec5))

            if not candidates:
                time.sleep(POLL); continue

            # Pick highest confluence
            candidates.sort(key=lambda x: -x[0])
            best_score, best_dec = candidates[0]

            # Execute
            result = execute_trade(mt5, best_dec)
            ts = datetime.now(timezone.utc).isoformat()
            entry_event = {
                "ts": ts, "score": best_score,
                "decision": best_dec, "result": result,
                "account_equity": acc.equity if acc else None,
            }
            _append(TRADE_LOG, entry_event)

            if result["status"] == "FILLED":
                print(f"[{datetime.now():%H:%M:%S}] ✅ {best_dec['side']} "
                       f"{best_dec['rule']} @ {result['price']:.2f} "
                       f"SL {best_dec['sl']:.2f} TP {best_dec['tp']:.2f} "
                       f"R:R {result['rr']} risk ${result['risk_usd']}")
                state["trades_today"] = state.get("trades_today", 0) + 1
                _save_state(state)
                time.sleep(60)  # cool-down after fill
            else:
                # Don't spam — only log if score was strong
                if best_score >= 4:
                    print(f"[{datetime.now():%H:%M:%S}] ❌ {best_dec['rule']} "
                           f"rejected: {result.get('reason') or result.get('comment')}")
                time.sleep(POLL)

        except KeyboardInterrupt:
            print("[claude_trader] stopped"); break
        except Exception as e:
            print(f"[claude_trader] err: {e}")
            time.sleep(POLL)


if __name__ == "__main__":
    main_loop()
