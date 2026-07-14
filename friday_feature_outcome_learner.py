from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5


ROOT = Path(r"C:\Users\Radhi\MT5")

SNAPSHOT_FILE = ROOT / "friday_feature_snapshots.jsonl"
WEIGHTS_FILE = ROOT / "friday_indicator_weights.json"
GENES_FILE = ROOT / "friday_strategy_genes.json"
STATE_FILE = ROOT / "friday_feature_outcome_learner_state.json"
LOG_FILE = ROOT / "friday_feature_outcome_learner.log"

DEMO_KEYWORDS = ["demo", "trial", "practice", "contest"]

FRIDAY_MAGICS = {
    20260600,  # algory_runner (active)
    20260504,
    20260505,
    20260506,
    20260507,
}

MAX_PROCESSED_DEALS = 50000


DEFAULT_WEIGHTS = {
    "version": "0.1",
    "updated_at": None,
    "groups": {
        "A_TREND_MOMENTUM": {
            "weight": 1.0,
            "score": 1.0,
            "wins": 0,
            "losses": 0,
            "probation": False
        },
        "B_FLOW_VOLUME": {
            "weight": 1.0,
            "score": 1.0,
            "wins": 0,
            "losses": 0,
            "probation": False
        },
        "C_STRUCTURE_BREAKOUT": {
            "weight": 1.0,
            "score": 1.0,
            "wins": 0,
            "losses": 0,
            "probation": False
        }
    },
    "indicators": {
        "EMA": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "RSI": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "ADX": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "MACD": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "VWAP": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "MFI": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "DELTA": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "VOL": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "SPREAD": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "DONCHIAN": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "DEMAND": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "SUPPLY": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "BOS": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "SWEEP": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "CANDLE": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "TOUCH_MEMORY": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        # PHASE 8 — Order Flow indicators
        "VOLUME_PROFILE": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "POC": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "VAH_VAL": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "CVD": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "ABSORPTION": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "EXHAUSTION": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "IMBALANCE": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "ORDERFLOW_EVENT": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "SESSION_VWAP": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        # Wick / FVG / Structure intelligence
        "WICK": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "FVG": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "IFVG": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "ZONE": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "NEAR_TOP": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False},
        "NEAR_BOTTOM": {"weight": 1.0, "score": 1.0, "wins": 0, "losses": 0, "probation": False}
    },
    "feature_signatures": {},
    "recent_learning": []
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_demo() -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    acc = mt5.account_info()
    if acc is None:
        raise RuntimeError("No MT5 account info")

    server = str(getattr(acc, "server", "") or "")
    trade_mode = getattr(acc, "trade_mode", None)

    demo_const = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    demo_by_mode = demo_const is not None and trade_mode == demo_const
    demo_by_server = any(k in server.lower() for k in DEMO_KEYWORDS)

    if not (demo_by_mode or demo_by_server):
        raise RuntimeError(f"BLOCKED: not demo account. server={server}, trade_mode={trade_mode}")


def load_weights() -> dict[str, Any]:
    data = load_json(WEIGHTS_FILE, None)

    if not isinstance(data, dict):
        data = DEFAULT_WEIGHTS
        data["updated_at"] = now()
        save_json(WEIGHTS_FILE, data)
        return data

    changed = False

    for k, v in DEFAULT_WEIGHTS.items():
        if k not in data:
            data[k] = v
            changed = True

    for k, v in DEFAULT_WEIGHTS["groups"].items():
        if k not in data.setdefault("groups", {}):
            data["groups"][k] = v
            changed = True

    for k, v in DEFAULT_WEIGHTS["indicators"].items():
        if k not in data.setdefault("indicators", {}):
            data["indicators"][k] = v
            changed = True

    if changed:
        data["updated_at"] = now()
        save_json(WEIGHTS_FILE, data)

    return data


def load_state() -> dict[str, Any]:
    return load_json(
        STATE_FILE,
        {
            "created_at": now(),
            "updated_at": now(),
            "processed_deals": [],
            "last_scan": None,
        },
    )


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    state["processed_deals"] = normalize_processed_deals(state.get("processed_deals", []))[-MAX_PROCESSED_DEALS:]
    save_json(STATE_FILE, state)


def normalize_processed_deals(items: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    if not isinstance(items, list):
        return out

    for item in items:
        if isinstance(item, dict):
            ticket = str(item.get("ticket") or item.get("deal") or "").strip()
        else:
            ticket = str(item or "").strip()

        if not ticket or ticket in seen:
            continue

        seen.add(ticket)
        out.append(ticket)

    return out


def read_snapshots(limit: int = 5000) -> list[dict[str, Any]]:
    if not SNAPSHOT_FILE.exists():
        return []

    try:
        lines = SNAPSHOT_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    rows = []

    for line in lines[-limit:]:
        try:
            item = json.loads(line)
            dec = item.get("decision") or {}
            if dec:
                rows.append(item)
        except Exception:
            continue

    return rows


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except Exception:
        return None


def nearest_snapshot(symbol: str, deal_time: datetime, max_seconds: int = 240) -> dict[str, Any] | None:
    rows = read_snapshots(limit=8000)

    best = None
    best_delta = 10**9

    for row in rows:
        dec = row.get("decision") or {}

        if dec.get("symbol") != symbol:
            continue

        t = parse_time(dec.get("created_at") or row.get("time"))
        if not t:
            continue

        delta = abs((deal_time - t).total_seconds())

        # Prefer snapshot before deal or close to it.
        if delta < best_delta and delta <= max_seconds:
            best = row
            best_delta = delta

    return best


def classify_profit(profit: float) -> str:
    if profit > 0.02:
        return "win"
    if profit < -0.02:
        return "loss"
    return "neutral"


def deal_side(deal_type: int) -> str:
    if deal_type == mt5.DEAL_TYPE_BUY:
        return "BUY"
    if deal_type == mt5.DEAL_TYPE_SELL:
        return "SELL"
    return "UNKNOWN"


def indicators_from_reasons(reasons: list[str]) -> set[str]:
    out = set()

    joined = " ".join(str(x).upper() for x in reasons)

    mapping = {
        "EMA": ["EMA"],
        "RSI": ["RSI"],
        "ADX": ["ADX"],
        "MACD": ["MACD"],
        "VWAP": ["VWAP", "ABOVE_VWAP", "BELOW_VWAP"],
        "SESSION_VWAP": ["SESSION_VWAP", "VWAP_RECLAIM", "VWAP_REJECTION", "VWAP_BAND"],
        "MFI": ["MFI"],
        "DELTA": ["DELTA", "BAR_DELTA", "DELTA_BUY", "DELTA_SELL"],
        "CVD": ["CVD", "CUMULATIVE_DELTA", "DELTA_DIVERGENCE"],
        "VOL": ["VOL", "VOLUME", "VOL_SPIKE"],
        "SPREAD": ["SPREAD"],
        "DONCHIAN": ["DONCHIAN"],
        "DEMAND": ["DEMAND"],
        "SUPPLY": ["SUPPLY"],
        "BOS": ["BOS"],
        "SWEEP": ["SWEEP"],
        "CANDLE": ["ENGULFING", "REJECTION", "CANDLE"],
        "TOUCH_MEMORY": ["TOUCH", "MEMORY", "SUPPORT_MEMORY", "RESISTANCE_MEMORY"],
        "VOLUME_PROFILE": ["VOLUME_PROFILE", "POC", "VAH", "VAL", "VALUE_AREA", "HVN", "LVN"],
        "POC": ["POC", "POINT_OF_CONTROL"],
        "VAH_VAL": ["VAH", "VAL", "VALUE_AREA"],
        "ABSORPTION": ["ABSORPTION", "ABSORPTION_BUY", "ABSORPTION_SELL"],
        "EXHAUSTION": ["EXHAUSTION", "EXHAUSTION_BUY", "EXHAUSTION_SELL"],
        "IMBALANCE": ["IMBALANCE", "IMBALANCE_RATIO"],
        "ORDERFLOW_EVENT": ["ORDERFLOW", "BIG_BUY_BURST", "BIG_SELL_BURST", "ORDERFLOW_EVENT"],
        "WICK": ["WICK", "SHOOTING_STAR", "HAMMER", "UPPER_REJECTION", "LOWER_REJECTION", "DOJI"],
        "FVG": ["FVG", "FVG_BULL", "FVG_BEAR", "FVG_ENTRY", "FVG_CHASING"],
        "IFVG": ["IFVG", "IFVG_BULL", "IFVG_BEAR"],
        "ZONE": ["ZONE_DISCOUNT", "ZONE_PREMIUM", "DISCOUNT", "PREMIUM"],
        "NEAR_TOP": ["NEAR_TOP", "NEAR_SWING_TOP", "ANTI_TOP"],
        "NEAR_BOTTOM": ["NEAR_BOTTOM", "NEAR_SWING_BOTTOM", "ANTI_BOTTOM"],
    }

    for key, tokens in mapping.items():
        if any(t in joined for t in tokens):
            out.add(key)

    return out



def feature_prediction_from_snapshot(snapshot: dict[str, Any]) -> str:
    dec = snapshot.get("decision") or {}

    action = str(dec.get("action") or "").upper()
    execution = str(dec.get("execution_mode") or "").upper()

    if "BUY" in action or "BUY" in execution:
        return "BUY"

    if "SELL" in action or "SELL" in execution:
        return "SELL"

    group_votes = [
        str((dec.get("group_a") or {}).get("vote") or "").upper(),
        str((dec.get("group_b") or {}).get("vote") or "").upper(),
        str((dec.get("group_c") or {}).get("vote") or "").upper(),
    ]

    if group_votes.count("BUY") >= 2:
        return "BUY"

    if group_votes.count("SELL") >= 2:
        return "SELL"

    return "HOLD"


def aligned_feature_result(snapshot: dict[str, Any], original_side: str, trade_result: str) -> str:
    """
    trade_result = actual MT5 outcome.
    feature_result = whether feature council prediction was correct.

    Example:
    - feature said SELL, original trade BUY, BUY won => feature_result loss.
    - feature said SELL, original trade SELL, SELL won => feature_result win.
    - feature said HOLD and trade won/lost => neutral, because it did not authorize direction.
    """
    prediction = feature_prediction_from_snapshot(snapshot)

    if prediction == "HOLD":
        return "neutral"

    if prediction == original_side and trade_result == "win":
        return "win"

    if prediction == original_side and trade_result == "loss":
        return "loss"

    if prediction != original_side and trade_result == "win":
        return "loss"

    if prediction != original_side and trade_result == "loss":
        return "win"

    return "neutral"



def group_alignment_result(group: dict[str, Any], side: str, trade_result: str) -> str:
    vote = str(group.get("vote", "MIXED") or "MIXED")

    if vote == side and trade_result == "win":
        return "win"
    if vote == side and trade_result == "loss":
        return "loss"
    if vote != side and trade_result == "win":
        return "loss"
    if vote != side and trade_result == "loss":
        return "win"

    return "neutral"


def reward_row(row: dict[str, Any], result: str, win_delta: float = 0.07, loss_delta: float = 0.10) -> None:
    row.setdefault("wins", 0)
    row.setdefault("losses", 0)
    row.setdefault("score", 1.0)
    row.setdefault("weight", 1.0)

    if result == "win":
        row["wins"] = int(row.get("wins", 0) or 0) + 1
        row["score"] = min(10.0, float(row.get("score", 1.0) or 1.0) + win_delta)
    elif result == "loss":
        row["losses"] = int(row.get("losses", 0) or 0) + 1
        row["score"] = max(0.05, float(row.get("score", 1.0) or 1.0) - loss_delta)

    # Weight is derived from score but bounded.
    score = float(row.get("score", 1.0) or 1.0)
    row["weight"] = round(max(0.25, min(2.5, 0.55 + score / 2.2)), 4)
    row["probation"] = score < 0.75
    row["updated_at"] = now()


def update_feature_signature(weights: dict[str, Any], signature: str, result: str, profit: float, side: str, snapshot: dict[str, Any]) -> None:
    sigs = weights.setdefault("feature_signatures", {})

    row = sigs.setdefault(
        signature,
        {
            "signature": signature,
            "seen": 0,
            "wins": 0,
            "losses": 0,
            "neutral": 0,
            "score": 1.0,
            "weight": 1.0,
            "profit": 0.0,
            "probation": False,
            "examples": [],
        },
    )

    row["seen"] = int(row.get("seen", 0) or 0) + 1
    row["profit"] = round(float(row.get("profit", 0.0) or 0.0) + profit, 4)

    if result == "win":
        row["wins"] = int(row.get("wins", 0) or 0) + 1
    elif result == "loss":
        row["losses"] = int(row.get("losses", 0) or 0) + 1
    else:
        row["neutral"] = int(row.get("neutral", 0) or 0) + 1

    reward_row(row, result, win_delta=0.12, loss_delta=0.18)

    row["examples"] = (row.get("examples") or [])[-30:] + [
        {
            "time": now(),
            "result": result,
            "profit": profit,
            "side": side,
            "snapshot_action": (snapshot.get("decision") or {}).get("action"),
            "snapshot_execution": (snapshot.get("decision") or {}).get("execution_mode"),
        }
    ]


def update_weights_from_outcome(weights: dict[str, Any], snapshot: dict[str, Any], side: str, result: str, profit: float) -> dict[str, Any]:
    dec = snapshot.get("decision") or {}

    signature = dec.get("feature_signature") or "UNKNOWN_SIGNATURE"
    reasons = dec.get("reasons") or []

    prediction = feature_prediction_from_snapshot(snapshot)
    feature_result = aligned_feature_result(snapshot, side, result)

    groups = {
        "A_TREND_MOMENTUM": dec.get("group_a") or {},
        "B_FLOW_VOLUME": dec.get("group_b") or {},
        "C_STRUCTURE_BREAKOUT": dec.get("group_c") or {},
    }

    for group_name, group in groups.items():
        group_result = group_alignment_result(group, side, result)
        reward_row(
            weights.setdefault("groups", {}).setdefault(group_name, DEFAULT_WEIGHTS["groups"][group_name].copy()),
            group_result,
            win_delta=0.06,
            loss_delta=0.09,
        )

    indicators = indicators_from_reasons(reasons)

    for name in indicators:
        row = weights.setdefault("indicators", {}).setdefault(name, DEFAULT_WEIGHTS["indicators"][name].copy())
        reward_row(row, feature_result, win_delta=0.05, loss_delta=0.08)

    update_feature_signature(weights, signature, feature_result, profit, side, snapshot)

    weights.setdefault("recent_learning", []).append(
        {
            "time": now(),
            "signature": signature,
            "prediction": prediction,
            "side": side,
            "trade_result": result,
            "feature_result": feature_result,
            "profit": profit,
            "indicators": sorted(indicators),
            "group_votes": {k: v.get("vote") for k, v in groups.items()},
        }
    )

    weights["recent_learning"] = weights["recent_learning"][-200:]
    weights["updated_at"] = now()

    return weights



def infer_original_position_side(deal) -> str:
    """
    MT5 closing deal type is often the opposite side of the original position.
    For learning, we need the original entry direction, not the close deal direction.
    """
    try:
        position_id = int(getattr(deal, "position_id", 0) or 0)
    except Exception:
        position_id = 0

    if position_id <= 0:
        return deal_side(int(getattr(deal, "type", 0) or 0))

    try:
        start = datetime.now() - timedelta(days=7)
        end = datetime.now()
        deals = mt5.history_deals_get(start, end)
    except Exception:
        deals = None

    if not deals:
        return deal_side(int(getattr(deal, "type", 0) or 0))

    same_position = []

    for d in deals:
        try:
            if int(getattr(d, "position_id", 0) or 0) == position_id:
                same_position.append(d)
        except Exception:
            continue

    if not same_position:
        return deal_side(int(getattr(deal, "type", 0) or 0))

    same_position.sort(key=lambda x: int(getattr(x, "time", 0) or 0))

    # Prefer entry-in deal.
    for d in same_position:
        entry = int(getattr(d, "entry", 0) or 0)
        dtype = int(getattr(d, "type", 0) or 0)

        if entry == mt5.DEAL_ENTRY_IN:
            return deal_side(dtype)

    # Fallback: first non-zero volume deal in the position chain.
    first = same_position[0]
    return deal_side(int(getattr(first, "type", 0) or 0))


def infer_entry_time_for_position(deal) -> datetime:
    """
    Use original entry time when matching feature snapshot,
    not the close time. This links the outcome to the decision before entry.
    """
    try:
        position_id = int(getattr(deal, "position_id", 0) or 0)
    except Exception:
        position_id = 0

    close_time = datetime.fromtimestamp(int(getattr(deal, "time", 0) or 0))

    if position_id <= 0:
        return close_time

    try:
        start = datetime.now() - timedelta(days=7)
        end = datetime.now()
        deals = mt5.history_deals_get(start, end)
    except Exception:
        deals = None

    if not deals:
        return close_time

    candidates = []

    for d in deals:
        try:
            if int(getattr(d, "position_id", 0) or 0) == position_id:
                candidates.append(d)
        except Exception:
            continue

    candidates.sort(key=lambda x: int(getattr(x, "time", 0) or 0))

    for d in candidates:
        try:
            if int(getattr(d, "entry", 0) or 0) == mt5.DEAL_ENTRY_IN:
                return datetime.fromtimestamp(int(getattr(d, "time", 0) or 0))
        except Exception:
            continue

    return close_time



def scan_closed_deals(hours_back: int = 24) -> int:
    ensure_demo()

    state = load_state()
    processed_order = normalize_processed_deals(state.get("processed_deals", []))
    processed = set(processed_order)
    weights = load_weights()

    learn_from_after_raw = state.get("learn_from_after")
    learn_from_after = None
    if learn_from_after_raw:
        try:
            learn_from_after = datetime.fromisoformat(str(learn_from_after_raw).replace("Z", ""))
        except Exception:
            learn_from_after = None

    start = datetime.now() - timedelta(hours=hours_back)
    end = datetime.now()

    deals = mt5.history_deals_get(start, end)

    if not deals:
        log("No deals found.")
        return 0

    learned = 0

    for d in deals:
        ticket = str(getattr(d, "ticket", ""))

        if not ticket or ticket in processed:
            continue

        magic = int(getattr(d, "magic", 0) or 0)
        symbol = str(getattr(d, "symbol", "") or "")
        comment = str(getattr(d, "comment", "") or "")
        profit = float(getattr(d, "profit", 0.0) or 0.0)
        dtype = int(getattr(d, "type", 0) or 0)
        dtime = datetime.fromtimestamp(int(getattr(d, "time", 0) or 0))

        if learn_from_after is not None and dtime < learn_from_after:
            processed.add(ticket)
            processed_order.append(ticket)
            continue

        if magic not in FRIDAY_MAGICS and "FRIDAY" not in comment.upper():
            continue

        if profit == 0.0:
            continue

        side = infer_original_position_side(d)
        result = classify_profit(profit)
        entry_time = infer_entry_time_for_position(d)

        snap = nearest_snapshot(symbol=symbol, deal_time=entry_time, max_seconds=420)

        if not snap:
            processed.add(ticket)
            processed_order.append(ticket)
            log(f"NO_SNAPSHOT ticket={ticket} symbol={symbol} profit={profit}")
            continue

        weights = update_weights_from_outcome(
            weights=weights,
            snapshot=snap,
            side=side,
            result=result,
            profit=profit,
        )

        processed.add(ticket)
        processed_order.append(ticket)
        learned += 1

        dec = snap.get("decision") or {}
        log(
            f"LEARNED_FEATURE {result.upper()} ticket={ticket} "
            f"symbol={symbol} original_side={side} profit={profit:.2f} "
            f"prediction={feature_prediction_from_snapshot(snap)} "
            f"feature_result={aligned_feature_result(snap, side, result)} "
            f"sig={dec.get('feature_signature')}"
        )

    state["processed_deals"] = processed_order
    state["last_scan"] = now()

    save_json(WEIGHTS_FILE, weights)
    save_state(state)

    log(f"Feature scan complete. learned={learned}")
    return learned


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=20)
    parser.add_argument("--hours-back", type=int, default=24)
    args = parser.parse_args()

    if args.loop:
        log("FRIDAY Feature Outcome Learner started.")

        while True:
            try:
                scan_closed_deals(hours_back=args.hours_back)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log(f"ERROR: {exc}")

            time.sleep(max(5, args.interval))

    else:
        scan_closed_deals(hours_back=args.hours_back)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
