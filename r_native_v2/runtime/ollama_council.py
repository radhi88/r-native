"""runtime/ollama_council.py — Local-LLM deliberation council (ADVISORY, DEMO).

Born 2026-07-13: multiple local Ollama models deliberate on every market pair,
with Claude as their manager via the governance layer (agent_governance).

DOCTRINE — honest measurement:
  • Every individual model vote is APPENDED to data/ollama_predictions.jsonl
    WITH the bid at verdict time, so it can be scored against price 15/60 min
    later. No claims, just a ledger.
  • The council NEVER trades. Its only side-effect beyond advisory files is a
    LOW-risk governance proposal (set_override) when all models unanimously
    agree with strength >= 0.7 — and even that only becomes live after the
    governance gate (consensus/Claude) clears it.

LOOP: every CYCLE_SEC pick XAUUSDm+BTCUSDm plus 2 round-robin symbols (all 12
covered every ~7.5 min), build a COMPACT prompt from brain_live__<SYM>.json,
ask each council model SEQUENTIALLY (one 7B at a time — no VRAM thrash) for
strict JSON {"verdict","confidence","reason"}, then write consensus.

Outputs:
  data/ollama_council.json         latest consensus per symbol (atomic)
  data/ollama_predictions.jsonl    append-only per-model vote ledger
  data/ollama_council_status.json  heartbeat
"""
from __future__ import annotations
import json
import os
import socket
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(r"C:\Users\Radhi\MT5\r_native_v2\data")
OUT_FILE      = DATA / "ollama_council.json"
LEDGER_FILE   = DATA / "ollama_predictions.jsonl"
STATUS_FILE   = DATA / "ollama_council_status.json"

OLLAMA_URL  = "http://127.0.0.1:11434/api/chat"
COUNCIL     = ["qwen2.5:7b", "llama3.2:3b", "qwen2.5:3b"]   # diverse families/sizes
FALLBACK    = "qwen2.5:1.5b"      # swapped in if a model keeps timing out
KEEP_ALIVE  = "10m"                # keep a model resident between its votes (no thrash)
CALL_TIMEOUT       = 45            # s per WARM model call (real answer ~1.5s)
FIRST_VOTE_TIMEOUT = 180           # s for the FIRST vote after a model switch (VRAM
                                   #  swap: single-slot GPU reloads a model each cycle)
WARMUP_TIMEOUT     = 240           # s to cold-load a model once at startup; drop if slower
SLOW_STRIKES = 3                   # consecutive timeouts before fallback swap

CYCLE_SEC   = 90
PRIORITY    = ["XAUUSDm", "BTCUSDm"]          # every cycle
ROTATION    = ["EURUSDm", "GBPUSDm", "USDJPYm", "USDCADm", "AUDUSDm",
               "NZDUSDm", "USDCHFm", "EURJPYm", "GBPJPYm", "XAGUSDm"]
ROTATE_N    = 2                                # rotating slots per cycle (4 total)

PROPOSE_MIN_STRENGTH = 0.7
PROPOSE_COOLDOWN_S   = 1800        # max 1 governance proposal / symbol / 30 min
SNAPSHOT_MAX_AGE_S   = 300         # skip stale market snapshots

LOCK_PORT = 8791                   # singleton guard (fleet convention)

VERDICTS = ("BUY", "SELL", "WAIT")
SYSTEM_MSG = ('You are a scalping market analyst. Reply ONLY with strict JSON: '
              '{"verdict":"BUY"|"SELL"|"WAIT","confidence":0.0-1.0,'
              '"reason":"<=15 words"}. WAIT is a valid answer when unclear.')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    os.replace(tmp, path)


def _append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


# ──────────────────────────────────────────────────────────
# Market snapshot → compact prompt (small models!)
# ──────────────────────────────────────────────────────────
def load_snapshot(sym: str) -> dict | None:
    p = DATA / f"brain_live__{sym}.json"
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        ts = datetime.fromisoformat(str(snap.get("ts")))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > SNAPSHOT_MAX_AGE_S:
            return None
    except Exception:
        pass
    return snap


def build_prompt(snap: dict) -> str:
    bias = snap.get("bias") or {}
    rsi = snap.get("rsi") or {}
    kinds = [c.get("kind", "?") for c in (snap.get("m1_last5") or [])[-3:]]
    return (
        f"{snap.get('symbol')} bid={snap.get('bid')} spread={snap.get('spread')} "
        f"session={snap.get('session')} regime={snap.get('regime')}\n"
        f"bias: m1={bias.get('m1')} m5={bias.get('m5')} m15={bias.get('m15')} "
        f"h1={bias.get('h1')}\n"
        f"rsi_m1={rsi.get('m1')} pressure_10m1={snap.get('pressure_10m1')}\n"
        f"last3 m1 candles: {', '.join(kinds) or 'n/a'}\n"
        f"Direction for the next 15-60 minutes? JSON only."
    )


# ──────────────────────────────────────────────────────────
# Ollama call (urllib, no external deps) — fail-soft
# ──────────────────────────────────────────────────────────
def ask_model(model: str, prompt: str, timeout: float = CALL_TIMEOUT) -> dict | None:
    """One chat call. Returns {"verdict","conf","reason","ms"} or None."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_MSG},
                     {"role": "user", "content": prompt}],
        "format": "json",
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0.2, "num_predict": 80},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode("utf-8"))
        content = ((resp.get("message") or {}).get("content") or "").strip()
        v = json.loads(content)
        verdict = str(v.get("verdict", "")).upper()
        if verdict not in VERDICTS:
            return None
        conf = max(0.0, min(1.0, float(v.get("confidence", 0.0))))
        reason = str(v.get("reason", ""))[:120]
        return {"verdict": verdict, "conf": round(conf, 3), "reason": reason,
                "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        _log(f"  vote FAILED {model}: {type(e).__name__}: {e}")
        return None


# ──────────────────────────────────────────────────────────
# Consensus + governance hook (Claude is the manager)
# ──────────────────────────────────────────────────────────
def consensus_of(votes: list[dict]) -> tuple[str, float]:
    """Majority verdict; strength = mean conf of majority voters; ties → WAIT."""
    if not votes:
        return "WAIT", 0.0
    tally: dict[str, list[float]] = {}
    for v in votes:
        tally.setdefault(v["verdict"], []).append(v["conf"])
    best = max(tally.items(), key=lambda kv: len(kv[1]))
    top_n = len(best[1])
    if sum(1 for confs in tally.values() if len(confs) == top_n) > 1:
        return "WAIT", 0.0                      # tie
    return best[0], round(sum(best[1]) / top_n, 3)


_last_proposal: dict[str, float] = {}          # sym -> monotonic ts


def maybe_propose(sym: str, verdict: str, strength: float,
                  votes: list[dict], n_models: int, bid: float) -> str | None:
    """File a LOW governance proposal on unanimous strong consensus. The
    council never trades — this only puts a signal override in front of the
    governance gate (peer consensus / Claude). Rate-limited per symbol."""
    if verdict == "WAIT" or strength < PROPOSE_MIN_STRENGTH:
        return None
    if len(votes) < n_models or any(v["verdict"] != verdict for v in votes):
        return None                             # must be ALL models, unanimous
    now = time.monotonic()
    if now - _last_proposal.get(sym, -1e9) < PROPOSE_COOLDOWN_S:
        return None
    try:
        from runtime.shared import agent_governance as gov
        pid = gov.propose(
            "ollama_council", "set_override",
            f"override:ollama_council_signal_{sym}",
            payload={"value": {"symbol": sym, "verdict": verdict,
                               "strength": strength, "bid": bid, "ts": _now(),
                               "models": [v["model"] for v in votes]}},
            rationale=(f"unanimous {len(votes)}-model local-LLM council: {verdict} "
                       f"{sym} strength={strength} @ bid {bid} — advisory signal"),
            risk=gov.RISK_LOW)
        _last_proposal[sym] = now
        _log(f"  governance proposal filed {sym} {verdict} s={strength} id={pid}")
        return pid
    except Exception as e:
        _log(f"  governance propose failed: {type(e).__name__}: {e}")
        return None


# ──────────────────────────────────────────────────────────
# Warm-up — cold-load each council model ONCE before the loop.
# Drop any model that can't load within WARMUP_TIMEOUT so a dead
# model can never wedge the deliberation loop. Honest per-model timing.
# ──────────────────────────────────────────────────────────
WARMUP_PROMPT = ('XAUUSDm bid=0 spread=0 session=warmup regime=flat\n'
                 'Direction for the next 15-60 minutes? JSON only.')


def warmup(models: list[str]) -> list[str]:
    alive: list[str] = []
    _log(f"WARM-UP starting — probing {models} (timeout {WARMUP_TIMEOUT}s each)")
    for m in models:
        t0 = time.time()
        v = ask_model(m, WARMUP_PROMPT, timeout=WARMUP_TIMEOUT)
        dt = time.time() - t0
        if v is None:
            _log(f"  WARM-UP DROP {m}: no valid load/answer within {WARMUP_TIMEOUT}s "
                 f"({dt:.1f}s elapsed) — removed from active council")
        else:
            alive.append(m)
            _log(f"  WARM-UP OK {m}: loaded+answered in {dt:.1f}s "
                 f"(verdict={v['verdict']} conf={v['conf']})")
    # spec: a too-slow model drops to the smaller fallback — try it once
    if len(alive) < len(models) and FALLBACK not in alive:
        t0 = time.time()
        v = ask_model(FALLBACK, WARMUP_PROMPT, timeout=WARMUP_TIMEOUT)
        if v is not None:
            alive.append(FALLBACK)
            _log(f"  WARM-UP FALLBACK {FALLBACK} joins council "
                 f"({time.time()-t0:.1f}s) — replacing a dropped model")
    _log(f"WARM-UP complete — active council={alive} "
         f"(dropped={[m for m in models if m not in alive]})")
    return alive


# ──────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────
def main() -> None:
    # singleton lock (fleet convention: bind a port; second copy exits quietly)
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        _log(f"another ollama_council holds port {LOCK_PORT} — exiting")
        return

    # WARM-UP: cold-load each model once; drop any that can't load in time so
    # a dead model never wedges the loop. This picks the final active council.
    council = warmup(list(COUNCIL))
    if not council:
        _log("WARM-UP: no council model could load — nothing to deliberate, exiting")
        _atomic_write(STATUS_FILE, {"ts": _now(), "cycle": 0, "ok_models": [],
                                    "error": "warmup_all_dropped"})
        return

    strikes = {m: 0 for m in council}          # consecutive-timeout counters
    cooloff: dict[str, int] = {}               # model -> benched until cycle N
    dropped = [m for m in COUNCIL if m not in council]
    results: dict[str, dict] = {}              # latest consensus per symbol
    cycle = 0
    rot_i = 0
    _log(f"ollama_council up — models={council} cycle={CYCLE_SEC}s (ADVISORY, never trades)")

    while True:
        cycle += 1
        t_cycle = time.time()

        # RE-PROBE: every 20 cycles (~30+ min) retry ONE dropped model — the
        # Ollama server is shared (another council session hammers it); when
        # contention eases, dropped models rejoin and diversity self-heals.
        if dropped and cycle % 20 == 0 and len(council) < len(COUNCIL):
            m = dropped.pop(0)
            v = ask_model(m, WARMUP_PROMPT, timeout=WARMUP_TIMEOUT)
            if v is not None:
                council.append(m)
                strikes[m] = 0
                _log(f"  RE-PROBE: {m} answers again — rejoining council {council}")
            else:
                dropped.append(m)               # back of the queue, retry later
        batch = list(PRIORITY) + [ROTATION[(rot_i + k) % len(ROTATION)]
                                  for k in range(ROTATE_N)]
        rot_i = (rot_i + ROTATE_N) % len(ROTATION)

        # snapshot + prompt per symbol, gathered once up front
        work: dict[str, dict] = {}
        for sym in batch:
            snap = load_snapshot(sym)
            if snap:
                work[sym] = {"snap": snap, "prompt": build_prompt(snap),
                             "votes": []}

        # MODEL-MAJOR order: each model answers ALL symbols before the next
        # model loads — exactly ONE VRAM swap per model per cycle (8GB GPU:
        # symbol-major order caused 12 swaps/cycle and universal timeouts).
        ok_models: set[str] = set()
        for i, model in enumerate(list(council)):
            if cooloff.get(model, 0) >= cycle:
                continue                        # benched — stop burning timeouts
            first = True                        # first call pays the VRAM load
            for sym, w in work.items():
                v = ask_model(model, w["prompt"],
                              timeout=FIRST_VOTE_TIMEOUT if first else CALL_TIMEOUT)
                first = False
                if v is None:
                    strikes[model] = strikes.get(model, 0) + 1
                    if strikes[model] >= SLOW_STRIKES:
                        if model != FALLBACK and FALLBACK not in council:
                            _log(f"  model {model} failed x{strikes[model]} → "
                                 f"swapping to fallback {FALLBACK}")
                            council[i] = FALLBACK
                            strikes[FALLBACK] = 0
                        else:                   # nothing to swap to — bench it
                            cooloff[model] = cycle + 5
                            strikes[model] = 0
                            _log(f"  model {model} failed x{SLOW_STRIKES} → "
                                 f"benched until cycle {cooloff[model]}")
                        break
                    continue                    # skipped vote — fail-soft
                strikes[model] = 0
                ok_models.add(model)
                v["model"] = model
                w["votes"].append(v)
                snap = w["snap"]
                _append_jsonl(LEDGER_FILE, {    # honesty ledger — score later
                    "ts": _now(), "model": model, "sym": sym,
                    "verdict": v["verdict"], "conf": v["conf"],
                    "bid": snap.get("bid"), "spread": snap.get("spread")})

        line_bits: list[str] = []
        for sym in batch:
            if sym not in work:
                line_bits.append(f"{sym}:no-snap")
                continue
            votes = work[sym]["votes"]
            bid = work[sym]["snap"].get("bid")
            verdict, strength = consensus_of(votes)
            pid = maybe_propose(sym, verdict, strength, votes, len(council), bid)
            results[sym] = {"ts": _now(), "verdict": verdict, "strength": strength,
                            "votes": votes, "bid_at_verdict": bid,
                            "proposal": pid}
            line_bits.append(f"{sym}:{verdict}@{strength}({len(votes)}v)")

        _atomic_write(OUT_FILE, {"ts": _now(), "cycle": cycle, "models": council,
                                 "symbols": results})
        last_ms = int((time.time() - t_cycle) * 1000)
        _atomic_write(STATUS_FILE, {"ts": _now(), "cycle": cycle,
                                    "ok_models": sorted(ok_models),
                                    "last_cycle_ms": last_ms})
        _log(f"cycle {cycle} {last_ms}ms  " + "  ".join(line_bits))
        time.sleep(max(5.0, CYCLE_SEC - (time.time() - t_cycle)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
