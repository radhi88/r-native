import argparse
import json
import math

import numpy as np
import pandas as pd
import tensorflow as tf

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import CSV_HISTORY, MODEL_PATH, PREPARED_DIR, REPORT_DIR
from mt5_ai.market_structure import add_market_structure
from mt5_ai.strategy_profiles import PROFILES


def load_meta(data_dir):
    with open(data_dir / "meta.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


def context_score(row, profile, side):
    score = 0
    tags = []
    if side == 1:
        if row["smc_buy_score"] >= profile.min_smc_score:
            score += 1
            tags.append(f"smc{int(row['smc_buy_score'])}")
        if row["smc_bias"] >= profile.min_bias:
            score += 1
            tags.append(f"bias{int(row['smc_bias'])}")
        if row["bos_up"] >= 1:
            score += 1
            tags.append("bos")
        if row["choch_up"] >= 1:
            score += 1
            tags.append("choch")
        if row["sell_side_liquidity_sweep"] >= 1:
            score += 1
            tags.append("liq_sweep")
        if row["bullish_fvg"] >= 1 or row["ifvg_bull"] >= 1:
            score += 1
            tags.append("fvg")
        if row["in_bullish_ob"] >= 1:
            score += 1
            tags.append("ob")
        if row["demand_zone"] >= 1:
            score += 1
            tags.append("demand")
    else:
        if row["smc_sell_score"] >= profile.min_smc_score:
            score += 1
            tags.append(f"smc{int(row['smc_sell_score'])}")
        if row["smc_bias"] <= -profile.min_bias:
            score += 1
            tags.append(f"bias{int(row['smc_bias'])}")
        if row["bos_down"] >= 1:
            score += 1
            tags.append("bos")
        if row["choch_down"] >= 1:
            score += 1
            tags.append("choch")
        if row["buy_side_liquidity_sweep"] >= 1:
            score += 1
            tags.append("liq_sweep")
        if row["bearish_fvg"] >= 1 or row["ifvg_bear"] >= 1:
            score += 1
            tags.append("fvg")
        if row["in_bearish_ob"] >= 1:
            score += 1
            tags.append("ob")
        if row["supply_zone"] >= 1:
            score += 1
            tags.append("supply")
    return score, tags


def strict_and_allows(row, side, min_smc_score):
    if side == 1:
        return (
            row["smc_buy_score"] >= min_smc_score
            and row["smc_bias"] >= 1
            and row["bos_up"] >= 1
            and row["sell_side_liquidity_sweep"] >= 1
            and (row["bullish_fvg"] >= 1 or row["ifvg_bull"] >= 1 or row["in_bullish_ob"] >= 1)
        )
    return (
        row["smc_sell_score"] >= min_smc_score
        and row["smc_bias"] <= -1
        and row["bos_down"] >= 1
        and row["buy_side_liquidity_sweep"] >= 1
        and (row["bearish_fvg"] >= 1 or row["ifvg_bear"] >= 1 or row["in_bearish_ob"] >= 1)
    )


def max_drawdown(equity_values):
    peak = -math.inf
    worst = 0.0
    for value in equity_values:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return float(worst)


def wilson_interval(wins, total, z=1.96):
    if total == 0:
        return [0.0, 0.0]
    p = wins / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return [float(max(0.0, center - margin)), float(min(1.0, center + margin))]


def summarize(policy, profile, trades, skipped):
    wins = [trade for trade in trades if trade["points"] > 0]
    losses = [trade for trade in trades if trade["points"] <= 0]
    gross_profit = sum(trade["points"] for trade in wins)
    gross_loss = abs(sum(trade["points"] for trade in losses))
    equity = [1000.0] + [trade["equity"] for trade in trades]
    return {
        "policy": policy,
        "strategy": profile.name,
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "win_rate_wilson_95": wilson_interval(len(wins), len(trades)),
        "net_points": float(sum(trade["points"] for trade in trades)),
        "avg_points": float(np.mean([trade["points"] for trade in trades])) if trades else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss else (float("inf") if gross_profit else 0.0),
        "max_drawdown_points": max_drawdown(equity),
        "skipped_overlap": int(skipped),
    }


def evaluate(policy, profile, prob, sequence_meta, smc_df, start, fee_points, strict_min_smc):
    trades = []
    equity = 1000.0
    next_available = -1
    skipped_overlap = 0

    for local_i, probability in enumerate(prob):
        sample_i = start + local_i
        entry_i = int(sequence_meta["entry_index"][sample_i])
        exit_i = int(sequence_meta["exit_index"][sample_i])
        if entry_i < next_available:
            skipped_overlap += 1
            continue

        row = smc_df.iloc[entry_i]
        if profile.max_spread is not None and "spread" in smc_df.columns:
            if float(row["spread"]) > profile.max_spread:
                continue

        if probability >= profile.buy_threshold:
            side = 1
        elif probability <= profile.sell_threshold:
            side = -1
        else:
            continue

        if policy == "context_score":
            score, tags = context_score(row, profile, side)
            allowed = score >= profile.min_context_score
            reason = "+".join(tags)
        else:
            score, tags = context_score(row, profile, side)
            allowed = strict_and_allows(row, side, strict_min_smc)
            reason = "strict_and:" + "+".join(tags)

        if not allowed:
            continue

        entry_price = float(sequence_meta["entry_price"][sample_i])
        exit_price = float(sequence_meta["exit_price"][sample_i])
        points = (exit_price - entry_price) * side - fee_points
        equity += points
        next_available = exit_i
        trades.append(
            {
                "policy": policy,
                "strategy": profile.name,
                "sample": int(sample_i),
                "entry_index": int(entry_i),
                "exit_index": int(exit_i),
                "side": "BUY" if side == 1 else "SELL",
                "probability": float(probability),
                "context_score": int(score),
                "reason": reason,
                "points": float(points),
                "equity": float(equity),
                "smc_buy_score": float(row["smc_buy_score"]),
                "smc_sell_score": float(row["smc_sell_score"]),
                "smc_bias": float(row["smc_bias"]),
            }
        )

    return summarize(policy, profile, trades, skipped_overlap), trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["val", "test"], default="test")
    parser.add_argument("--fee-points", type=float, default=0.291)
    parser.add_argument("--strict-min-smc", type=int, default=3)
    parser.add_argument("--data-dir", default=str(PREPARED_DIR))
    args = parser.parse_args()

    data_dir = PREPARED_DIR if args.data_dir == str(PREPARED_DIR) else type(PREPARED_DIR)(args.data_dir)
    meta = load_meta(data_dir)
    start = int(meta["val_end"] if args.split == "test" else meta["train_end"])
    end = int(meta["samples"] if args.split == "test" else meta["val_end"])

    x = np.load(data_dir / "X.npy", mmap_mode="r")
    sequence_meta = np.load(data_dir / "sequence_meta.npz")
    smc_df = add_market_structure(pd.read_csv(CSV_HISTORY))

    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    prob = model.predict(x[start:end], verbose=0, batch_size=256).flatten()

    summaries = []
    all_trades = []
    for profile in PROFILES.values():
        for policy in ("strict_and", "context_score"):
            summary, trades = evaluate(
                policy=policy,
                profile=profile,
                prob=prob,
                sequence_meta=sequence_meta,
                smc_df=smc_df,
                start=start,
                fee_points=args.fee_points,
                strict_min_smc=args.strict_min_smc,
            )
            summaries.append(summary)
            all_trades.extend(trades)

    summaries.sort(key=lambda item: (item["strategy"], item["policy"]))
    REPORT_DIR.mkdir(exist_ok=True)
    out_json = REPORT_DIR / f"decision_policy_compare_{args.split}.json"
    out_csv = REPORT_DIR / f"decision_policy_compare_trades_{args.split}.csv"
    with open(out_json, "w", encoding="utf-8") as handle:
        json.dump(summaries, handle, indent=2)
    if all_trades:
        pd.DataFrame(all_trades).to_csv(out_csv, index=False)

    print(json.dumps(summaries, indent=2))
    print("Saved:", out_json)
    print("Trades:", out_csv)


if __name__ == "__main__":
    main()
