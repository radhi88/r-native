"""signal_arbiter.py — Structured agent conflict resolution.

Pipeline position:
  Agents → [SignalArbiter] → DecisionRouter → ConflictGuard → RiskManager → ExecutionManager

Weights:
  FractalAgent  — structure / direction bias      : 0.45
  SmcAgent      — entry confirmation / liquidity  : 0.45
  Session filter — trading hours / volatility     : 0.10   max total = 1.00

SmcAgent states understood:
  BUY             — bullish bias + active entry trigger
  SELL            — bearish bias + active entry trigger
  NO_CONFIRMATION — bias exists but no active OB/FVG/sweep/BOS/CHoCH
  absent (None)   — score gap too small, no opinion at all

Primary reason codes (one per decision):
  "structure_without_entry_confirmation"  FractalAgent directional + SmcAgent NO_CONFIRMATION
  "smc_no_active_setup"                   Only SmcAgent present and it says NO_CONFIRMATION
  "agents_aligned"                        Both directional, same direction
  "agents_conflicted"                     Both directional, opposite directions
  "confidence_below_threshold"            Score < active/gene threshold after all other rules

Rules:
  A. No primary signals → HOLD
  B. FractalAgent directional + SmcAgent NO_CONFIRMATION
       → HOLD: "structure_without_entry_confirmation" (max score 0.55 < 0.70)
  C. Both directional, same direction, score ≥ threshold → BUY/SELL: "agents_aligned"
  D. Both directional, same direction, score < threshold → HOLD: "confidence_below_threshold"
  E. Both directional, opposite, delta ≥ 0.12 AND score ≥ threshold → BUY/SELL: "agents_conflicted"
  F. Both directional, opposite, else → HOLD: "agents_conflicted"
  G. Single primary, score ≥ threshold → BUY/SELL: "single_primary"
  H. Single primary, score < threshold → HOLD: "confidence_below_threshold"

Gene weights (arbiter_gene_weights.json):
  Loaded at startup from data/qader/dna/arbiter_gene_weights.json (written by the
  Bayesian feedback daemon).  Each entry is keyed by gene_id and provides:
    min_confidence  — overrides CONFIDENCE_THRESHOLD for that context
    lot_scale       — passed through to the signal proposal features
  Gene matching is fuzzy: symbol > timeframe > direction > session (all optional).
  Falls back to active_genome.json, then hardcoded constants when no file exists.

Every decision logged to logs/arbitration_decisions.jsonl.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .signal_schema import SignalProposal, Direction
from .magic_registry import ALGORY_MAGIC

log = logging.getLogger("signal_arbiter")

# ── Constants ─────────────────────────────────────────────────────────────────

WEIGHT_FRACTAL       = 0.45
WEIGHT_SMC           = 0.45
WEIGHT_SESSION       = 0.10
CONFIDENCE_THRESHOLD = 0.70
MATERIAL_DELTA       = 0.12

from .project_root import PROJECT_ROOT as _ROOT
_LOG_PATH = _ROOT / "logs" / "arbitration_decisions.jsonl"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_ASIAN_ACTIVE = {"XAUUSDm", "XAGUSDm", "BTCUSDm", "ETHUSDm"}

# ── Gene-weight path (written by dna_live_feedback.py) ────────────────────────

def _gene_weights_path() -> Path:
    """Return the canonical path for arbiter_gene_weights.json.

    Uses qader_app.paths.app_root() when available; falls back to _ROOT so the
    module stays self-contained even if qader_app is not on sys.path.
    """
    try:
        from qader_app.paths import app_root
        return app_root() / "data" / "qader" / "dna" / "arbiter_gene_weights.json"
    except Exception:
        return _ROOT / "data" / "qader" / "dna" / "arbiter_gene_weights.json"


_ACTIVE_GENOME_CACHE: Dict[str, Any] = {"path": None, "mtime_ns": None, "genome": {}}


def _active_genome_path() -> Path:
    """Return the active Strategy DNA path used by Qader learning."""
    try:
        from qader_app.paths import app_root
        return app_root() / "data" / "qader" / "dna" / "active_genome.json"
    except Exception:
        return _ROOT / "data" / "qader" / "dna" / "active_genome.json"


def _load_active_genome() -> Dict[str, Any]:
    """Read active_genome.json with a small mtime cache.

    Learning proposals update this file, so the arbiter treats it as the live
    base threshold source. Malformed or missing files fall back to constants.
    """
    path = _active_genome_path()
    try:
        if not path.exists():
            return {}
        mtime_ns = path.stat().st_mtime_ns
        if _ACTIVE_GENOME_CACHE.get("path") == str(path) and _ACTIVE_GENOME_CACHE.get("mtime_ns") == mtime_ns:
            cached = _ACTIVE_GENOME_CACHE.get("genome")
            return cached if isinstance(cached, dict) else {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        _ACTIVE_GENOME_CACHE.update({"path": str(path), "mtime_ns": mtime_ns, "genome": data})
        return data
    except Exception as exc:
        log.warning("active_genome: could not load %s - %s", path, exc)
        return {}


# ── Gene weight helpers ────────────────────────────────────────────────────────

def _load_gene_weights() -> Dict[str, Any]:
    """Read arbiter_gene_weights.json and return its contents as a dict.

    Returns an empty dict when the file is missing, empty, or malformed so that
    the trading loop is never interrupted by a weights-file problem.

    File format (produced by dna_live_feedback.py):
      {
        "<gene_id>": {
          "min_confidence": 0.72,
          "lot_scale":      1.1,
          "sl_atr_mult":    1.5,
          "tp_atr_mult":    2.5,
          "sharpe":         1.3,
          "win_rate_backtest": 0.60,
          "win_rate_live":  0.58,
          "bayesian_posterior": 0.61,
          "active":         true,
          ...
        },
        ...
      }
    Each gene_id encodes its market context, e.g.
    "XAUUSDm_M1_BUY_london_normal" — fields are extracted by splitting on '_'
    only when the gene store metadata is not directly embedded in the weight
    entry.  The arbiter stores the full gene_store group dict when available.
    """
    path = _gene_weights_path()
    try:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            log.warning("gene_weights: expected dict, got %s — ignoring", type(data).__name__)
            return {}
        log.debug("gene_weights: loaded %d entries from %s", len(data), path)
        return data
    except Exception as exc:
        log.warning("gene_weights: could not load %s — %s", path, exc)
        return {}


def _match_gene_weight(
    weights: Dict[str, Any],
    symbol: str,
    timeframe: str,
    direction: str,
    session: str,
) -> Optional[Dict[str, Any]]:
    """Fuzzy-match the best gene entry for the current trading context.

    Scoring (higher = better match):
      symbol    matched → +3
      timeframe matched → +2
      direction matched → +2  (case-insensitive)
      session   matched → +1

    The gene_id is used to infer the group when no explicit ``group`` key is
    present: the id is expected to follow the convention produced by the
    backtest engine — e.g. ``XAUUSDm_M1_BUY_london_normal``.

    Returns the matched gene entry dict (with its original keys) or None when
    no gene scores ≥ 5 (i.e. at least symbol + timeframe + direction must
    match before we trust the entry enough to override the defaults).
    """
    if not weights:
        return None

    best_entry: Optional[Dict[str, Any]] = None
    best_score = -1

    for gene_id, entry in weights.items():
        if not isinstance(entry, dict):
            continue
        # Skip explicitly deactivated genes
        if not entry.get("active", True):
            continue

        # Extract group fields — prefer an embedded "group" sub-dict, then
        # fall back to parsing the gene_id string itself.
        group: Dict[str, str] = {}
        if "group" in entry and isinstance(entry["group"], dict):
            group = {k: str(v) for k, v in entry["group"].items()}
        else:
            # gene_id convention: "SYMBOL_TIMEFRAME_DIRECTION_SESSION_ATRREGIME"
            parts = gene_id.split("_")
            keys  = ("symbol", "timeframe", "direction", "session", "atr_regime")
            for k, v in zip(keys, parts):
                group[k] = v

        score = 0
        if group.get("symbol")    == symbol:              score += 3
        if group.get("timeframe") == timeframe:           score += 2
        if group.get("direction", "").upper() == direction.upper(): score += 2
        if group.get("session")   == session:             score += 1

        if score > best_score:
            best_score = score
            best_entry = entry

    # Require at least symbol + timeframe + direction (score ≥ 7) for a clean
    # match, or symbol + timeframe (score ≥ 5) as the minimum acceptable bar.
    if best_score >= 5 and best_entry is not None:
        return best_entry
    return None

# ── Session quality ───────────────────────────────────────────────────────────

def _session_quality(symbol: str) -> float:
    h = datetime.now(timezone.utc).hour
    if 13 <= h < 17: return 1.00
    if  8 <= h < 13: return 0.85
    if 17 <= h < 22: return 0.80
    if symbol in _ASIAN_ACTIVE: return 0.65
    return 0.50

# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ArbiterDecision:
    symbol:    str
    timeframe: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    final_direction:  Direction = Direction.HOLD
    final_confidence: float     = 0.0
    reason:           str       = ""
    primary_code:     str       = ""   # one of the 5 canonical reason codes

    fractal_direction:  Optional[Direction] = None
    fractal_confidence: float               = 0.0
    fractal_score:      float               = 0.0
    fractal_evidence:   dict                = field(default_factory=dict)

    smc_direction:  Optional[Direction] = None
    smc_state:      str                 = "absent"   # absent|no_confirmation|directional
    smc_confidence: float               = 0.0
    smc_score:      float               = 0.0
    smc_evidence:   dict                = field(default_factory=dict)

    session_quality: float = 0.0
    session_score:   float = 0.0

    agent_conflict:   bool  = False   # True only when both directional and opposite
    buy_agent_score:  float = 0.0
    sell_agent_score: float = 0.0
    delta:            float = 0.0
    effective_threshold: float = CONFIDENCE_THRESHOLD
    threshold_source: str = "default"

    confirmer_directions: list = field(default_factory=list)
    resolved_signals:     list = field(default_factory=list)

    def to_signal_proposal(self) -> Optional[SignalProposal]:
        if self.final_direction not in (Direction.BUY, Direction.SELL):
            return None
        return SignalProposal(
            source="signal_arbiter",
            strategy_id="FRIDAY_ARBITER",
            symbol=self.symbol,
            timeframe=self.timeframe,
            direction=self.final_direction,
            confidence=self.final_confidence,
            strength=self.final_confidence,
            reason=self.reason,
            features={
                "fractal_score":  round(self.fractal_score,  4),
                "smc_score":      round(self.smc_score,      4),
                "session_score":  round(self.session_score,  4),
                "agent_conflict": float(self.agent_conflict),
                "delta":          round(self.delta,          4),
            },
            can_execute=False,
            desired_magic=ALGORY_MAGIC,
            priority=2,
            tags=["arbiter", "resolved"],
        )

    def to_log_record(self) -> dict:
        return {
            "ts":               self.timestamp,
            "symbol":           self.symbol,
            "timeframe":        self.timeframe,
            "final_direction":  self.final_direction.value,
            "final_confidence": round(self.final_confidence, 4),
            "primary_code":     self.primary_code,
            "reason":           self.reason,
            "fractal": {
                "direction":  self.fractal_direction.value if self.fractal_direction else None,
                "confidence": round(self.fractal_confidence, 4),
                "score":      round(self.fractal_score,      4),
                "evidence":   self.fractal_evidence,
            },
            "smc": {
                "state":      self.smc_state,
                "direction":  self.smc_direction.value if self.smc_direction else None,
                "confidence": round(self.smc_confidence, 4),
                "score":      round(self.smc_score,      4),
                "evidence":   self.smc_evidence,
            },
            "session": {
                "quality": round(self.session_quality, 4),
                "score":   round(self.session_score,   4),
            },
            "arbitration": {
                "buy_agent_score":  round(self.buy_agent_score,  4),
                "sell_agent_score": round(self.sell_agent_score, 4),
                "agent_conflict":   self.agent_conflict,
                "delta":            round(self.delta, 4),
                "threshold":        round(self.effective_threshold, 4),
                "threshold_source": self.threshold_source,
                "material_delta":   MATERIAL_DELTA,
            },
            "confirmers": self.confirmer_directions,
        }


# ── SignalArbiter ─────────────────────────────────────────────────────────────

class SignalArbiter:
    """Resolves competing agent signals into a single arbiter decision.

    Gene weights are loaded from arbiter_gene_weights.json at construction and
    can be refreshed at any time by calling ``reload_weights()``.  The trading
    loop calls this every 100 cycles so that Bayesian feedback propagates to
    live decisions without restarting the service.
    """

    def __init__(self) -> None:
        self._gene_weights: Dict[str, Any] = {}
        self._reload_gene_weights()

    # ── Weight management ──────────────────────────────────────────────────────

    def _reload_gene_weights(self) -> None:
        """Internal: read the weights file and store result (never raises)."""
        try:
            self._gene_weights = _load_gene_weights()
            if self._gene_weights:
                log.info("gene_weights: %d active entries loaded", len(self._gene_weights))
        except Exception as exc:  # belt-and-suspenders
            log.warning("gene_weights: unexpected error during reload — %s", exc)
            self._gene_weights = {}

    def reload_weights(self) -> None:
        """Public API: refresh gene weights from disk.

        Called by the real-time loop service every 100 cycles so that updates
        written by dna_live_feedback.py are picked up without restarting.
        Never raises — any file / parse error is logged as a warning.
        """
        self._reload_gene_weights()

    def _get_gene_override(
        self, symbol: str, timeframe: str, direction: str, session: str
    ) -> Optional[Dict[str, Any]]:
        """Return the best matching gene entry or None (never raises)."""
        try:
            return _match_gene_weight(
                self._gene_weights, symbol, timeframe, direction, session
            )
        except Exception as exc:
            log.warning("gene_weights: match error — %s", exc)
            return None

    # ── Core decision logic ────────────────────────────────────────────────────

    def decide(self, signals: list[SignalProposal],
               symbol: str, timeframe: str) -> ArbiterDecision:

        result = ArbiterDecision(symbol=symbol, timeframe=timeframe)

        # ── Extract primary agents ─────────────────────────────────────────
        fractal = next((s for s in signals if s.source == "fractal_agent"), None)
        smc     = next((s for s in signals if s.source == "smc_agent"),     None)
        confirmers = [s for s in signals
                      if s.source not in ("fractal_agent", "smc_agent")
                      and s.direction in (Direction.BUY, Direction.SELL)]

        # ── Classify SmcAgent state ────────────────────────────────────────
        if smc is None:
            result.smc_state = "absent"
        elif smc.direction == Direction.NO_CONFIRMATION:
            result.smc_state = "no_confirmation"
        elif smc.direction in (Direction.BUY, Direction.SELL):
            result.smc_state = "directional"
        else:
            result.smc_state = "hold"

        # ── Populate fractal evidence ──────────────────────────────────────
        if fractal and fractal.direction in (Direction.BUY, Direction.SELL):
            result.fractal_direction  = fractal.direction
            result.fractal_confidence = fractal.confidence
            result.fractal_score      = fractal.confidence * WEIGHT_FRACTAL
            result.fractal_evidence   = {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in fractal.features.items()
            }

        # ── Populate SMC evidence ──────────────────────────────────────────
        if smc:
            result.smc_direction  = smc.direction
            result.smc_confidence = smc.confidence
            # NO_CONFIRMATION and HOLD contribute 0 to directional scores
            if smc.direction in (Direction.BUY, Direction.SELL):
                result.smc_score = smc.confidence * WEIGHT_SMC
            result.smc_evidence = {
                k: round(float(v), 4) if isinstance(v, (int, float)) else v
                for k, v in list(smc.features.items())[:12]
            }

        # ── Confirmer signals ──────────────────────────────────────────────
        result.confirmer_directions = [
            {"source": c.source, "direction": c.direction.value,
             "confidence": round(c.confidence, 4)}
            for c in confirmers
        ]

        # ── Session ────────────────────────────────────────────────────────
        result.session_quality = _session_quality(symbol)
        result.session_score   = result.session_quality * WEIGHT_SESSION

        # ── Agent weighted scores (directional only) ───────────────────────
        for s in (fractal, smc):
            if s is None or s.direction not in (Direction.BUY, Direction.SELL):
                continue
            w = WEIGHT_FRACTAL if s.source == "fractal_agent" else WEIGHT_SMC
            if s.direction == Direction.BUY:
                result.buy_agent_score  += w * s.confidence
            else:
                result.sell_agent_score += w * s.confidence

        # ── Lead direction ─────────────────────────────────────────────────
        if result.buy_agent_score >= result.sell_agent_score:
            lead_dir   = Direction.BUY
            lead_score = result.buy_agent_score  + result.session_score
            lag_score  = result.sell_agent_score
        else:
            lead_dir   = Direction.SELL
            lead_score = result.sell_agent_score + result.session_score
            lag_score  = result.buy_agent_score

        result.delta = lead_score - lag_score

        # Conflict = both have directional opinions AND they oppose each other
        fractal_dir = result.fractal_direction
        smc_dir = smc.direction if smc and smc.direction in (Direction.BUY, Direction.SELL) else None
        result.agent_conflict = (
            fractal_dir in (Direction.BUY, Direction.SELL) and
            smc_dir     in (Direction.BUY, Direction.SELL) and
            fractal_dir != smc_dir
        )

        # ── Classify scenario ──────────────────────────────────────────────
        fractal_is_dir = fractal_dir in (Direction.BUY, Direction.SELL)
        smc_is_dir     = smc_dir     in (Direction.BUY, Direction.SELL)
        smc_is_noconf  = result.smc_state == "no_confirmation"

        if fractal_is_dir and smc_is_noconf:
            scenario = "structure_without_entry_confirmation"
        elif fractal_is_dir and smc_is_dir and not result.agent_conflict:
            scenario = "agents_aligned"
        elif result.agent_conflict:
            scenario = "agents_conflicted"
        elif fractal_is_dir or smc_is_dir:
            scenario = "single_primary"
        else:
            scenario = "no_primary_signals"

        # ── Gene weight lookup ─────────────────────────────────────────────
        # Resolve the session label used by the Bayesian feedback daemon so
        # that gene matching works even before the full session module is in
        # scope (it is optional; match quality degrades gracefully).
        try:
            from mt5_ai.core.market_quality import current_market_session as _session_fn
            _session_label = _session_fn()
        except Exception:
            _session_label = ""

        _active_genome = _load_active_genome()
        _active_threshold = CONFIDENCE_THRESHOLD
        _threshold_source = "default"
        try:
            _active_threshold = float(
                _active_genome.get("confidence_thresholds", {}).get(
                    "arbiter_pass",
                    CONFIDENCE_THRESHOLD,
                )
            )
            if _active_genome:
                _threshold_source = "active_genome"
        except (TypeError, ValueError):
            _active_threshold = CONFIDENCE_THRESHOLD
            _threshold_source = "default"

        _gene_entry = self._get_gene_override(
            symbol    = symbol,
            timeframe = timeframe,
            direction = lead_dir.value,
            session   = _session_label,
        )

        # Effective threshold - active Strategy DNA is the base; matched genes
        # may override it for a specific market context.
        _gene_lot_scale: Optional[float] = None
        if _gene_entry is not None:
            try:
                _effective_threshold = float(_gene_entry.get("min_confidence", _active_threshold))
                _threshold_source = "gene_weights" if "min_confidence" in _gene_entry else _threshold_source
            except (TypeError, ValueError):
                _effective_threshold = _active_threshold
            try:
                _raw_lot = _gene_entry.get("lot_scale")
                if _raw_lot is not None:
                    _gene_lot_scale = float(_raw_lot)
            except (TypeError, ValueError):
                pass
            log.debug(
                "gene_weights: matched entry for %s/%s/%s — min_conf=%.3f lot_scale=%s",
                symbol, timeframe, lead_dir.value,
                _effective_threshold, _gene_lot_scale,
            )
        else:
            _effective_threshold = _active_threshold

        result.effective_threshold = _effective_threshold
        result.threshold_source = _threshold_source

        # ── Apply decision rules ───────────────────────────────────────────
        def _hold(code: str, detail: str) -> None:
            result.final_direction  = Direction.HOLD
            result.final_confidence = lead_score
            result.primary_code     = code
            result.reason           = f"{code}|{detail}"

        def _pass(code: str, detail: str) -> None:
            result.final_direction  = lead_dir
            result.final_confidence = lead_score
            result.primary_code     = code
            result.reason           = f"{code}|{detail}"

        # Rule A
        if scenario == "no_primary_signals":
            _hold("no_primary_signals", "no_fractal_no_smc")

        # Rule B — structure present but SMC has no entry trigger
        # Mathematical note: max lead_score = fractal_max(0.45) + session_max(0.10) = 0.55 < 0.70
        # so confidence_below_threshold always co-fires here, but root cause is smc_no_active_setup
        elif scenario == "structure_without_entry_confirmation":
            _hold(
                "structure_without_entry_confirmation",
                f"fractal={fractal_dir.value}/{result.fractal_confidence:.2f},"
                f"smc=NO_CONFIRMATION|smc_no_active_setup|"
                f"score={lead_score:.4f}<{_effective_threshold}",
            )

        # Rule C/D — agents aligned
        elif scenario == "agents_aligned":
            detail = (
                f"{lead_dir.value}|"
                f"f={result.fractal_score:.3f}+s={result.smc_score:.3f}"
                f"+sess={result.session_score:.3f}={lead_score:.4f}"
            )
            if lead_score >= _effective_threshold:
                _pass("agents_aligned", detail)
            else:
                _hold(
                    "confidence_below_threshold",
                    f"agents_aligned|{detail}|threshold={_effective_threshold}",
                )

        # Rule E/F — agents in direct opposition
        elif scenario == "agents_conflicted":
            detail = (
                f"fractal={fractal_dir.value}/{result.fractal_confidence:.2f},"
                f"smc={smc_dir.value}/{result.smc_confidence:.2f}|"
                f"lead={lead_dir.value}|delta={result.delta:.4f}|score={lead_score:.4f}"
            )
            if lead_score >= _effective_threshold and result.delta >= MATERIAL_DELTA:
                _pass("agents_conflicted", f"material_lead_resolved|{detail}")
            else:
                _hold("agents_conflicted", detail)

        # Rule G/H — single primary (only fractal or only smc directional)
        else:
            detail = (
                f"{lead_dir.value}|score={lead_score:.4f}|"
                f"f={result.fractal_score:.3f}+s={result.smc_score:.3f}"
                f"+sess={result.session_score:.3f}"
            )
            if lead_score >= _effective_threshold:
                _pass("single_primary", detail)
            else:
                _hold("confidence_below_threshold", f"single_primary|{detail}")

        # ── Resolved signal for downstream ────────────────────────────────
        arb_sig = result.to_signal_proposal()
        # Embed gene lot_scale into the signal features so downstream
        # components (risk manager, execution) can pick it up.
        if arb_sig is not None and _gene_lot_scale is not None:
            arb_sig.features["gene_lot_scale"] = round(_gene_lot_scale, 4)
        result.resolved_signals = [arb_sig] if arb_sig is not None else []

        # ── Log ───────────────────────────────────────────────────────────
        _log_decision(result)

        log.info(
            "[ARB] %s %s | F=%s/%.2f  S=%s(%s)/%.2f  sess=%.2f | "
            "conflict=%s delta=%.3f | → %s@%.3f | %s | gene_thresh=%.3f lot_scale=%s",
            symbol, timeframe,
            fractal_dir.value if fractal_dir else "—", result.fractal_confidence,
            result.smc_direction.value if result.smc_direction else "—",
            result.smc_state, result.smc_confidence,
            result.session_quality,
            result.agent_conflict, result.delta,
            result.final_direction.value, result.final_confidence,
            result.primary_code,
            _effective_threshold,
            f"{_gene_lot_scale:.2f}" if _gene_lot_scale is not None else "default",
        )

        return result


def _log_decision(decision: ArbiterDecision) -> None:
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_log_record(),
                               ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        log.warning("arbitration log write failed: %s", exc)
