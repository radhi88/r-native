import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tensorflow as tf

from _bootstrap import bootstrap

bootstrap()

from mt5_ai.config import CSV_HISTORY, MODEL_PATH, PREPARED_DIR, PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)


def load_training_report():
    path = MODEL_PATH.parent / "training_report.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_meta_json():
    with open(PREPARED_DIR / "meta.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


def choose_signal(prob, buy_threshold, sell_threshold):
    if prob >= buy_threshold:
        return 1
    if prob <= sell_threshold:
        return -1
    return 0


def backtest(prob, sequence_meta, start, buy_threshold, sell_threshold, fee_points=0.0):
    trades = []
    equity = [1000.0]
    next_available = -1

    entry_index = sequence_meta["entry_index"]
    exit_index = sequence_meta["exit_index"]
    entry_price = sequence_meta["entry_price"]
    exit_price = sequence_meta["exit_price"]

    for local_i, p in enumerate(prob):
        i = start + local_i
        if entry_index[i] < next_available:
            continue

        signal = choose_signal(float(p), buy_threshold, sell_threshold)
        if signal == 0:
            continue

        points = (float(exit_price[i]) - float(entry_price[i])) * signal
        points_after_fee = points - fee_points
        equity.append(equity[-1] + points_after_fee)
        next_available = int(exit_index[i])

        trades.append(
            {
                "sample": int(i),
                "entry_index": int(entry_index[i]),
                "exit_index": int(exit_index[i]),
                "side": "BUY" if signal == 1 else "SELL",
                "probability": float(p),
                "entry_price": float(entry_price[i]),
                "exit_price": float(exit_price[i]),
                "points": float(points_after_fee),
                "equity": float(equity[-1]),
            }
        )

    return trades, np.array(equity, dtype=np.float32)


def save_trades(trades, path):
    if not trades:
        return

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)


def plot_backtest(df, trades, equity, output_path, max_trades=80):
    if trades:
        visible = trades[-max_trades:]
        start_idx = max(min(t["entry_index"] for t in visible) - 50, 0)
        end_idx = min(max(t["exit_index"] for t in visible) + 50, len(df) - 1)
    else:
        visible = []
        start_idx = max(len(df) - 1000, 0)
        end_idx = len(df) - 1

    chart_df = df.iloc[start_idx : end_idx + 1].copy()
    x = np.arange(start_idx, end_idx + 1)

    fig, (ax_price, ax_equity) = plt.subplots(
        2,
        1,
        figsize=(16, 9),
        gridspec_kw={"height_ratios": [3, 1]},
        constrained_layout=True,
    )

    ax_price.plot(x, chart_df["close"], color="#1f2937", linewidth=1.2, label="Close")

    for trade in visible:
        color = "#16a34a" if trade["side"] == "BUY" else "#dc2626"
        marker = "^" if trade["side"] == "BUY" else "v"
        ax_price.scatter(
            trade["entry_index"],
            trade["entry_price"],
            marker=marker,
            s=90,
            color=color,
            edgecolor="white",
            linewidth=0.8,
            zorder=5,
        )
        ax_price.plot(
            [trade["entry_index"], trade["exit_index"]],
            [trade["entry_price"], trade["exit_price"]],
            color=color,
            linewidth=1.0,
            alpha=0.65,
        )

    ax_price.set_title("MT5 AI Backtest Entries")
    ax_price.set_ylabel("Price")
    ax_price.grid(alpha=0.18)
    ax_price.legend(loc="upper left")

    ax_equity.plot(equity, color="#2563eb", linewidth=1.5)
    ax_equity.set_title("Equity Curve (Price Points)")
    ax_equity.set_xlabel("Trade #")
    ax_equity.set_ylabel("Equity")
    ax_equity.grid(alpha=0.18)

    fig.savefig(output_path, dpi=140)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["val", "test", "all"], default="test")
    parser.add_argument("--buy-threshold", type=float, default=None)
    parser.add_argument("--sell-threshold", type=float, default=None)
    parser.add_argument("--fee-points", type=float, default=0.0)
    args = parser.parse_args()

    meta = load_meta_json()
    report = load_training_report()
    thresholds = report.get("thresholds", {})
    buy_threshold = args.buy_threshold or thresholds.get("buy_threshold", 0.56)
    sell_threshold = args.sell_threshold or thresholds.get("sell_threshold", 0.44)

    train_end = int(meta["train_end"])
    val_end = int(meta["val_end"])

    if args.split == "val":
        start, end = train_end, val_end
    elif args.split == "test":
        start, end = val_end, int(meta["samples"])
    else:
        start, end = 0, int(meta["samples"])

    X = np.load(PREPARED_DIR / "X.npy", mmap_mode="r")
    sequence_meta = np.load(PREPARED_DIR / "sequence_meta.npz")
    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    prob = model.predict(X[start:end], verbose=0, batch_size=256).flatten()

    trades, equity = backtest(
        prob,
        sequence_meta,
        start,
        float(buy_threshold),
        float(sell_threshold),
        fee_points=args.fee_points,
    )

    df = pd.read_csv(CSV_HISTORY)
    df.columns = [column.strip().lower() for column in df.columns]

    output_png = REPORT_DIR / f"backtest_{args.split}.png"
    output_csv = REPORT_DIR / f"backtest_{args.split}_trades.csv"
    output_json = REPORT_DIR / f"backtest_{args.split}_summary.json"

    plot_backtest(df, trades, equity, output_png)
    save_trades(trades, output_csv)

    wins = [trade for trade in trades if trade["points"] > 0]
    summary = {
        "split": args.split,
        "buy_threshold": float(buy_threshold),
        "sell_threshold": float(sell_threshold),
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "net_points": float(sum(trade["points"] for trade in trades)),
        "avg_points": float(np.mean([trade["points"] for trade in trades])) if trades else 0.0,
        "chart": str(output_png),
        "trades_csv": str(output_csv),
    }
    with open(output_json, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
