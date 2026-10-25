"""employee_link.py — route R-Native entries through Radhi's employee instead of MT5.

R-Native no longer sends its own orders. Every entry the executor decides on is
written here as one JSON line in the employee's inbox
(C:\\Users\\Radhi\\MT5\\employee\\data\\rnative\\signals.jsonl by default).

The employee reads that inbox with rnative_pb.py (integrations/employee/), so
each R-Native strategy becomes a trainee playbook named rn_<strategy>:
- the trainee grades it on paper like every other playbook;
- a real demo order happens only if Radhi arms that playbook in
  data/trainee/playbook_gate.json, and then it goes through the central
  gateway (risk per trade, daily_dd, demo-only account check).

Nothing here talks to MT5 or to the broker. It is a plain file append.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

DEFAULT_INBOX = Path(r"C:\Users\Radhi\MT5\employee\data\rnative")
SIGNALS = "signals.jsonl"
HEARTBEAT = "heartbeat.json"
MAX_BYTES = 20 * 1024 * 1024   # rotate the inbox at 20 MB so the employee reads a small file


def inbox() -> Path:
    return Path(os.environ.get("R_EMPLOYEE_INBOX") or DEFAULT_INBOX)


def strategy_name(comment: str) -> str:
    """Playbook name for the trainee: rn_ + a short slug of the R comment."""
    slug = re.sub(r"[^a-z0-9]+", "_", (comment or "").lower()).strip("_")[:24]
    return "rn_" + (slug or "signal")


def _rotate(path: Path) -> None:
    try:
        if path.stat().st_size > MAX_BYTES:
            os.replace(path, path.with_suffix(f".{time.strftime('%Y%m%d%H%M%S')}.jsonl"))
    except FileNotFoundError:
        pass


def submit(symbol: str, side: str, lot: float, sl: float, tp: float,
           comment: str, price: float | None = None, extra: dict | None = None) -> tuple[bool, dict]:
    """Queue one entry for the employee. Same (ok, dict) shape as _send_order.

    ok=True means the signal is in the inbox, not that an order was sent.
    """
    side = (side or "").upper()
    if side not in ("BUY", "SELL"):
        return False, {"reason": f"employee_link: bad side {side!r}"}
    if not symbol:
        return False, {"reason": "employee_link: empty symbol"}
    row = {
        "id": uuid.uuid4().hex,
        "ts": time.time(),
        "source": "r-native",
        "symbol": symbol,
        "side": side,
        "lot": float(lot),
        "sl": float(sl or 0.0),
        "tp": float(tp or 0.0),
        "price": float(price) if price else None,
        "strategy": strategy_name(comment),
        "comment": (comment or "")[:64],
    }
    if extra:
        row["extra"] = {k: v for k, v in extra.items() if isinstance(v, (str, int, float, bool)) or v is None}
    d = inbox()
    try:
        d.mkdir(parents=True, exist_ok=True)
        path = d / SIGNALS
        _rotate(path)
        line = json.dumps(row, ensure_ascii=False) + "\n"
        # one write() per line: appends of a short line are atomic on NTFS/ext4
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        return False, {"reason": f"employee_link: inbox write failed ({e})"}
    return True, {"order": 0, "queued": row["id"], "strategy": row["strategy"],
                  "price": row["price"], "comment": "queued for employee"}


def heartbeat(state: dict | None = None) -> None:
    """Let the employee see that R-Native is alive (shown in its status)."""
    d = inbox()
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (HEARTBEAT + ".tmp")
        tmp.write_text(json.dumps({"ts": time.time(), "pid": os.getpid(),
                                   "last_action": (state or {}).get("last_action")},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / HEARTBEAT)
    except OSError:
        pass


def read_since(offset: int = 0, path: Path | None = None) -> tuple[list[dict], int]:
    """Rows appended after byte offset, plus the new offset. Partial last lines wait."""
    path = path or (inbox() / SIGNALS)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return [], 0
    if size < offset:          # rotated
        offset = 0
    rows = []
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1
    for raw in data[:end].splitlines():
        try:
            rows.append(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
    return rows, offset + end
