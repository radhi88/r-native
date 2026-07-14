from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5


ROOT = Path(r"C:\Users\Radhi\MT5")
GENES_FILE = ROOT / "friday_strategy_genes.json"
STATE_FILE = ROOT / "friday_trade_outcome_learner_state.json"
LOG_FILE = ROOT / "friday_trade_outcome_learner.log"

DEMO_KEYWORDS = ["demo", "trial", "practice", "contest"]

FRIDAY_MAGICS = {
    20260600,  # algory_runner (active)
    20260504,
    20260505,
    20260506,
    20260507,
}

MAX_PROCESSED_DEALS = 50000


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_genes() -> dict[str, Any]:
    return load_json(
        GENES_FILE,
        {
            "version": "0.3",
            "project": "FRIDAY Strategy Genes",
            "created_at": now(),
            "updated_at": now(),
            "global_stats": {
                "events": 0,
                "wins": 0,
                "losses": 0,
                "neutral": 0,
                "genes_count": 0,
                "realized_deals_checked": 0,
            },
            "genes": {},
            "advisor_trust": {},
            "trade_outcomes": [],
        },
    )


def save_genes(genes: dict[str, Any]) -> None:
    genes["updated_at"] = now()
    save_json(GENES_FILE, genes)


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


def classify_profit(profit: float) -> str:
    if profit > 0.02:
        return "win"
    if profit < -0.02:
        return "loss"
    return "neutral"


def outcome_gene_id(symbol: str, side: str, comment: str, magic: int) -> str:
    comment = comment or "no_comment"

    if "TOUCH" in comment.upper():
        family = "touch_level"
    elif "GOV" in comment.upper():
        family = "governor"
    elif "SCALPER" in comment.upper() or "SCAL" in comment.upper():
        family = "realtime_scalper"
    elif "ICT" in comment.upper():
        family = "ict_sweep"
    else:
        family = "unknown_execution"

    return f"{symbol}:{side}:{family}:magic={magic}"


def update_gene(
    genes: dict[str, Any],
    gene_id: str,
    result: str,
    profit: float,
    deal: dict[str, Any],
) -> None:
    gene_map = genes.setdefault("genes", {})

    gene = gene_map.setdefault(
        gene_id,
        {
            "gene_id": gene_id,
            "created_at": now(),
            "updated_at": now(),
            "seen": 0,
            "wins": 0,
            "losses": 0,
            "neutral": 0,
            "score": 1.0,
            "confidence_boost": 0.0,
            "probation": False,
            "examples": [],
        },
    )

    gene["seen"] = int(gene.get("seen", 0) or 0) + 1

    if result == "win":
        gene["wins"] = int(gene.get("wins", 0) or 0) + 1
        gene["score"] = min(10.0, float(gene.get("score", 1.0) or 1.0) + 0.20)
        gene["confidence_boost"] = min(0.45, float(gene.get("confidence_boost", 0.0) or 0.0) + 0.020)

    elif result == "loss":
        gene["losses"] = int(gene.get("losses", 0) or 0) + 1
        gene["score"] = max(0.05, float(gene.get("score", 1.0) or 1.0) - 0.28)
        gene["confidence_boost"] = max(-0.45, float(gene.get("confidence_boost", 0.0) or 0.0) - 0.030)

    else:
        gene["neutral"] = int(gene.get("neutral", 0) or 0) + 1

    gene["probation"] = float(gene["score"]) < 0.75
    gene["updated_at"] = now()

    gene["examples"] = (gene.get("examples") or [])[-50:] + [
        {
            "time": now(),
            "result": result,
            "profit": profit,
            "deal": deal,
        }
    ]

    stats = genes.setdefault("global_stats", {})
    stats["events"] = int(stats.get("events", 0) or 0) + 1
    stats["realized_deals_checked"] = int(stats.get("realized_deals_checked", 0) or 0) + 1
    stats["genes_count"] = len(gene_map)

    if result == "win":
        stats["wins"] = int(stats.get("wins", 0) or 0) + 1
    elif result == "loss":
        stats["losses"] = int(stats.get("losses", 0) or 0) + 1
    else:
        stats["neutral"] = int(stats.get("neutral", 0) or 0) + 1


def update_advisor_trust(
    genes: dict[str, Any],
    source_family: str,
    result: str,
    profit: float,
) -> None:
    trust = genes.setdefault("advisor_trust", {})

    advisor = trust.setdefault(
        source_family,
        {
            "score": 1.0,
            "wins": 0,
            "losses": 0,
            "neutral": 0,
            "probation": False,
            "last_result": None,
        },
    )

    if result == "win":
        advisor["wins"] = int(advisor.get("wins", 0) or 0) + 1
        advisor["score"] = min(5.0, float(advisor.get("score", 1.0) or 1.0) + 0.12)

    elif result == "loss":
        advisor["losses"] = int(advisor.get("losses", 0) or 0) + 1
        advisor["score"] = max(0.05, float(advisor.get("score", 1.0) or 1.0) - 0.18)

    else:
        advisor["neutral"] = int(advisor.get("neutral", 0) or 0) + 1

    advisor["probation"] = float(advisor["score"]) < 0.75
    advisor["last_result"] = {
        "time": now(),
        "result": result,
        "profit": profit,
    }


def source_family_from_comment(comment: str) -> str:
    c = (comment or "").upper()

    if "TOUCH" in c:
        return "touch_level_advisor"
    if "GOV" in c:
        return "governor_advisor"
    if "SCALPER" in c or "SCAL" in c:
        return "scalper_advisor"
    if "ICT" in c:
        return "ict_sweep_advisor"

    return "unknown_advisor"


def deal_side(deal_type: int) -> str:
    if deal_type == mt5.DEAL_TYPE_BUY:
        return "BUY"
    if deal_type == mt5.DEAL_TYPE_SELL:
        return "SELL"
    return "UNKNOWN"


def scan_closed_deals(hours_back: int = 24) -> int:
    ensure_demo()

    state = load_state()
    processed_order = normalize_processed_deals(state.get("processed_deals", []))
    processed = set(processed_order)
    genes = load_genes()

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
        entry = int(getattr(d, "entry", 0) or 0)
        dtype = int(getattr(d, "type", 0) or 0)

        # Only learn from FRIDAY-related closed/out deals.
        if magic not in FRIDAY_MAGICS and "FRIDAY" not in comment.upper():
            continue

        # DEAL_ENTRY_OUT or INOUT means closure. Some brokers may mark it differently,
        # so profit != 0 is also considered a realized outcome.
        if profit == 0.0:
            continue

        side = deal_side(dtype)
        result = classify_profit(profit)
        family = source_family_from_comment(comment)
        gene_id = outcome_gene_id(symbol, side, comment, magic)

        deal_data = {
            "ticket": ticket,
            "symbol": symbol,
            "side": side,
            "magic": magic,
            "comment": comment,
            "profit": profit,
            "entry": entry,
            "type": dtype,
            "time": int(getattr(d, "time", 0) or 0),
        }

        update_gene(genes, gene_id, result, profit, deal_data)
        update_advisor_trust(genes, family, result, profit)

        genes.setdefault("trade_outcomes", []).append(
            {
                "time": now(),
                "ticket": ticket,
                "gene_id": gene_id,
                "family": family,
                "result": result,
                "profit": profit,
                "deal": deal_data,
            }
        )
        genes["trade_outcomes"] = genes["trade_outcomes"][-1000:]

        processed.add(ticket)
        processed_order.append(ticket)
        learned += 1

        log(f"LEARNED {result.upper()} ticket={ticket} symbol={symbol} profit={profit:.2f} gene={gene_id}")

    state["processed_deals"] = processed_order
    state["last_scan"] = now()

    save_state(state)
    save_genes(genes)

    log(f"Scan complete. learned={learned}")
    return learned


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--hours-back", type=int, default=24)
    args = parser.parse_args()

    if args.loop:
        log("FRIDAY Trade Outcome Learner started.")
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
