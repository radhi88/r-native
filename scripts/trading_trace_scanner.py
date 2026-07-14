from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


MT5_ROOT = Path(r"C:\Users\Radhi\MT5")
OUT_FILE = MT5_ROOT / "trading_decision_trace.json"

TARGET_FILES = [
    "src/mt5_ai/execution.py",
    "src/mt5_ai/mt5_gateway.py",
    "scripts/friday_auto_trader.py",
    "scripts/live_paper_trader.py",
    "src/mt5_ai/config.py",
]

DECISION_KEYWORDS = [
    "BUY",
    "SELL",
    "HOLD",
    "signal",
    "direction",
    "action",
    "confidence",
    "probability",
    "decision",
]

EXECUTION_KEYWORDS = [
    "order_send",
    "send_market_order",
    "send_demo_market_order",
    "send_demo_pending_order",
    "TRADE_ACTION_DEAL",
    "TRADE_ACTION_PENDING",
    "allow_live",
    "live",
    "demo",
    "paper",
]

RISK_KEYWORDS = [
    "order_send",
    "allow_live=True",
    "allow_live = True",
    "live",
    "TRADE_ACTION_DEAL",
    "TRADE_ACTION_PENDING",
]


def read_file(rel_path: str) -> str:
    path = MT5_ROOT / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def get_defs(source: str) -> list[dict[str, Any]]:
    defs: list[dict[str, Any]] = []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{"type": "syntax_error", "name": "UNKNOWN", "line": exc.lineno, "detail": str(exc)}]

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            defs.append({"type": "class", "name": node.name, "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append({"type": "function", "name": node.name, "line": node.lineno})

    return sorted(defs, key=lambda x: x.get("line") or 0)


def find_matches(source: str, keywords: list[str]) -> list[dict[str, Any]]:
    matches = []

    for idx, line in enumerate(source.splitlines(), start=1):
        lower = line.lower()

        for keyword in keywords:
            if keyword.lower() in lower:
                matches.append(
                    {
                        "line": idx,
                        "keyword": keyword,
                        "text": line.strip()[:300],
                    }
                )

    return matches


def classify_risk(execution_matches: list[dict[str, Any]]) -> str:
    text = "\n".join(item["text"] for item in execution_matches).lower()

    if "order_send" in text or "trade_action_deal" in text or "trade_action_pending" in text:
        return "High"

    if "send_market_order" in text or "allow_live" in text:
        return "Medium"

    if "send_demo" in text or "paper" in text:
        return "Low"

    return "Unknown"


def build_trace() -> dict[str, Any]:
    result: dict[str, Any] = {
        "trace_version": "0.1",
        "project": "FRIDAY MT5",
        "generated_at": datetime.now().isoformat(),
        "rules": {
            "read_only": True,
            "no_mt5_execution": True,
            "no_live_trading": True,
            "no_demo_or_paper_execution": True,
        },
        "files": [],
        "summary": {
            "decision_locations": [],
            "execution_locations": [],
            "high_risk_locations": [],
            "paper_demo_live_terms": [],
        },
        "safe_test_plan": [
            "python -m py_compile src/mt5_ai/execution.py",
            "python -m py_compile src/mt5_ai/mt5_gateway.py",
            "python -m py_compile scripts/friday_auto_trader.py",
            "python -m py_compile scripts/live_paper_trader.py",
            "python -m py_compile src/mt5_ai/config.py",
        ],
    }

    for rel_path in TARGET_FILES:
        source = read_file(rel_path)

        if not source:
            result["files"].append(
                {
                    "path": rel_path,
                    "exists": False,
                    "risk": "Unknown",
                    "defs": [],
                    "decision_matches": [],
                    "execution_matches": [],
                    "risk_matches": [],
                }
            )
            continue

        defs = get_defs(source)
        decision_matches = find_matches(source, DECISION_KEYWORDS)
        execution_matches = find_matches(source, EXECUTION_KEYWORDS)
        risk_matches = find_matches(source, RISK_KEYWORDS)
        risk = classify_risk(execution_matches)

        file_result = {
            "path": rel_path,
            "exists": True,
            "risk": risk,
            "defs": defs,
            "decision_matches": decision_matches,
            "execution_matches": execution_matches,
            "risk_matches": risk_matches,
        }

        result["files"].append(file_result)

        for item in decision_matches:
            result["summary"]["decision_locations"].append(
                {"file": rel_path, **item}
            )

        for item in execution_matches:
            result["summary"]["execution_locations"].append(
                {"file": rel_path, **item}
            )

        for item in risk_matches:
            result["summary"]["high_risk_locations"].append(
                {"file": rel_path, **item}
            )

        for item in execution_matches:
            if item["keyword"].lower() in {"live", "demo", "paper", "allow_live"}:
                result["summary"]["paper_demo_live_terms"].append(
                    {"file": rel_path, **item}
                )

    return result


def print_summary(trace: dict[str, Any]) -> None:
    print("Trading Decision Trace built.")
    print("File:", OUT_FILE)

    for item in trace["files"]:
        print()
        print("FILE:", item["path"])
        print("Exists:", item["exists"])
        print("Risk:", item["risk"])
        print("Defs:", len(item["defs"]))
        print("Decision matches:", len(item["decision_matches"]))
        print("Execution matches:", len(item["execution_matches"]))
        print("Risk matches:", len(item["risk_matches"]))

        if item["defs"]:
            print("Top defs:")
            for d in item["defs"][:12]:
                print(f"  - {d['type']} {d['name']} line {d.get('line')}")

        if item["execution_matches"]:
            print("Execution evidence:")
            for m in item["execution_matches"][:12]:
                print(f"  - line {m['line']} | {m['keyword']} | {m['text']}")

    print()
    print("Safe test plan:")
    for cmd in trace["safe_test_plan"]:
        print(" ", cmd)


def main() -> None:
    trace = build_trace()
    OUT_FILE.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(trace)


if __name__ == "__main__":
    main()
