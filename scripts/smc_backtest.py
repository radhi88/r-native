import argparse
import json

import numpy as np
import pandas as pd
import tensorflow as tf

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import CSV_HISTORY, MODEL_PATH, PREPARED_DIR, REPORT_DIR
from mt5_ai.market_structure import add_market_structure
from mt5_ai.strategy_profiles import PROFILES


def load_meta():
    with open(PREPARED_DIR / "meta.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


def context_score(profile, row, side):
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


def evaluate_profile(profile, prob, sequence_meta, smc_df, start, fee_points):
    trades = []
    equity = 1000.0
    next_available = -1

    for local_i, p in enumerate(prob):
        sample_i = start + local_i
        entry_i = int(sequence_meta["entry_index"][sample_i])
        exit_i = int(sequence_meta["exit_index"][sample_i])

        if entry_i < next_available:
            continue

        if profile.max_spread is not None and "spread" in smc_df.columns:
            if float(smc_df["spread"].iloc[entry_i]) > profile.max_spread:
                continue

        if p >= profile.buy_threshold:
            side = 1
        elif p <= profile.sell_threshold:
            side = -1
        else:
            continue

        row = smc_df.iloc[entry_i]
        score, tags = context_score(profile, row, side)
        if score < profile.min_context_score:
            continue

        entry_price = float(sequence_meta["entry_price"][sample_i])
        exit_price = float(sequence_meta["exit_price"][sample_i])
        points = (exit_price - entry_price) * side - fee_points
        equity += points
        next_available = exit_i

        trades.append(
            {
                "strategy": profile.name,
                "sample": int(sample_i),
                "entry_index": entry_i,
                "exit_index": exit_i,
                "side": "BUY" if side == 1 else "SELL",
                "probability": float(p),
                "points": float(points),
                "equity": float(equity),
                "smc_buy_score": float(row["smc_buy_score"]),
                "smc_sell_score": float(row["smc_sell_score"]),
                "smc_bias": float(row["smc_bias"]),
                "context_score": int(score),
                "reason": "+".join(tags),
            }
        )

    wins = [trade for trade in trades if trade["points"] > 0]
    losses = [trade for trade in trades if trade["points"] <= 0]
    net = sum(trade["points"] for trade in trades)
    avg_win = np.mean([trade["points"] for trade in wins]) if wins else 0.0
    avg_loss = np.mean([trade["points"] for trade in losses]) if losses else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss else 0.0

    return {
        "strategy": profile.name,
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "net_points": float(net),
        "avg_points": float(np.mean([trade["points"] for trade in trades])) if trades else 0.0,
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "payoff": float(payoff),
        "trades_detail": trades,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["val", "test"], default="test")
    parser.add_argument("--fee-points", type=float, default=0.291)
    args = parser.parse_args()

    meta = load_meta()
    start = int(meta["val_end"] if args.split == "test" else meta["train_end"])
    end = int(meta["samples"] if args.split == "test" else meta["val_end"])

    X = np.load(PREPARED_DIR / "X.npy", mmap_mode="r")
    sequence_meta = np.load(PREPARED_DIR / "sequence_meta.npz")
    df = pd.read_csv(CSV_HISTORY)
    smc_df = add_market_structure(df)

    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    prob = model.predict(X[start:end], verbose=0, batch_size=256).flatten()

    results = []
    all_trades = []
    for profile in PROFILES.values():
        result = evaluate_profile(profile, prob, sequence_meta, smc_df, start, args.fee_points)
        all_trades.extend(result.pop("trades_detail"))
        results.append(result)

    results = sorted(results, key=lambda row: (row["win_rate"], row["net_points"]), reverse=True)

    REPORT_DIR.mkdir(exist_ok=True)
    out_json = REPORT_DIR / f"smc_profile_backtest_{args.split}.json"
    out_csv = REPORT_DIR / f"smc_profile_trades_{args.split}.csv"

    with open(out_json, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)

    if all_trades:
        pd.DataFrame(all_trades).to_csv(out_csv, index=False)

    print(json.dumps(results, indent=2))
    print("Saved:", out_json)
    print("Trades:", out_csv)


if __name__ == "__main__":
    main()

