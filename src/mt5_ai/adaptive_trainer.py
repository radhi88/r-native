"""
adaptive_trainer.py
-------------------
Online learning module for FRIDAY: captures feature sequences at trade entry,
stores (sequence, label, weight) tuples on trade exit, and fine-tunes the
Keras model when the buffer accumulates enough samples.

Thread-safe — designed to be called from the orchestrator's trading thread.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .config import DATA_DIR, MODEL_PATH, SEQ_LEN, FEATURE_COLUMNS

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_BUFFER_NPZ = DATA_DIR / "adaptive_buffer.npz"
_BUFFER_META = DATA_DIR / "adaptive_buffer_meta.json"
_MAX_PENDING_PER_SLOT = 10          # maximum pending entries kept per symbol|side
_CONTINUITY_KEEP = 64               # samples retained after a retrain cycle
_FINE_TUNE_BATCH = 32
_FINE_TUNE_LR = 1e-5
_WEIGHT_NORM_POINTS = 100.0         # normalisation divisor for pnl magnitude
_WEIGHT_BASE = 0.3
_WEIGHT_CAP = 1.0
_WEIGHT_WIN_BONUS = 0.10
_LABEL_SMOOTHING = 0.02


# ---------------------------------------------------------------------------
# AdaptiveTrainer
# ---------------------------------------------------------------------------

class AdaptiveTrainer:
    """
    Continuously fine-tunes the FRIDAY Keras model using real trade outcomes.

    Lifecycle
    ---------
    1. ``record_entry`` is called when a trade opens — the current feature
       sequence (shape SEQ_LEN × FEATURES) is stored in ``_pending_entries``.
    2. ``record_exit`` is called when the trade closes — the outcome is labelled,
       weighted, and pushed into the ring-buffer.
    3. ``_maybe_retrain`` is called automatically; when the buffer holds at
       least ``min_retrain_samples`` examples it fine-tunes the model in-place.
    """

    def __init__(
        self,
        model_path: Path | str | None = None,
        buffer_size: int = 256,
        min_retrain_samples: int = 128,
        fine_tune_epochs: int = 3,
    ) -> None:
        self.model_path: Path = Path(model_path) if model_path is not None else Path(MODEL_PATH)
        self.buffer_size: int = buffer_size
        self.min_retrain_samples: int = min_retrain_samples
        self.fine_tune_epochs: int = fine_tune_epochs

        # Thread safety
        self._lock = threading.Lock()

        # Ring-buffer of (X_seq, label, weight, symbol, side, pnl) named tuples
        # stored as a plain deque of dicts for simplicity
        self._buffer: deque[dict[str, Any]] = deque(maxlen=buffer_size)

        # Open-trade tracking: key → {"sequence": np.ndarray, "ts": str}
        # Full key format: "{symbol}|{side}|{timestamp}" but lookup uses prefix.
        self._pending_entries: dict[str, dict[str, Any]] = {}

        # Metrics
        self._retrain_count: int = 0
        self._last_retrain_time: str | None = None

        # Restore persisted buffer if available
        self._load_buffer()

        log.info(
            "AdaptiveTrainer initialised | model=%s buffer_cap=%d min_retrain=%d epochs=%d",
            self.model_path,
            self.buffer_size,
            self.min_retrain_samples,
            self.fine_tune_epochs,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_entry(self, symbol: str, side: str, sequence: np.ndarray) -> None:
        """
        Store the feature sequence captured at trade entry.

        Parameters
        ----------
        symbol:   MT5 symbol string, e.g. "XAUUSDm"
        side:     "buy" or "sell"
        sequence: numpy array of shape (SEQ_LEN, FEATURES)
        """
        try:
            if sequence is None:
                log.warning("record_entry: sequence is None for %s %s — skipped", symbol, side)
                return

            seq = np.array(sequence, dtype=np.float32)
            expected = (SEQ_LEN, len(FEATURE_COLUMNS))
            if seq.shape != expected:
                log.warning(
                    "record_entry: unexpected sequence shape %s (expected %s) for %s %s",
                    seq.shape, expected, symbol, side,
                )
                # Do not discard — partial sequences can still carry signal

            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            key = f"{symbol}|{side}|{ts}"

            with self._lock:
                self._pending_entries[key] = {"sequence": seq, "ts": ts}

                # Prune oldest entries for this symbol|side slot to cap memory
                slot_prefix = f"{symbol}|{side}|"
                slot_keys = sorted(
                    [k for k in self._pending_entries if k.startswith(slot_prefix)]
                )
                while len(slot_keys) > _MAX_PENDING_PER_SLOT:
                    evicted = slot_keys.pop(0)
                    del self._pending_entries[evicted]
                    log.debug("record_entry: evicted old pending entry %s", evicted)

            log.debug("record_entry: stored entry key=%s seq_shape=%s", key, seq.shape)

        except Exception:
            log.exception("record_entry: unhandled exception for %s %s", symbol, side)

    def record_exit(self, symbol: str, side: str, pnl_points: float) -> None:
        """
        Called when a trade closes.  Matches the most recent pending entry for
        this symbol+side, computes a label and sample weight, appends to the
        buffer, then triggers retraining if the buffer is full enough.

        Parameters
        ----------
        symbol:     MT5 symbol string
        side:       "buy" or "sell"
        pnl_points: profit/loss expressed in price points (positive = win)
        """
        try:
            slot_prefix = f"{symbol}|{side}|"
            matched_key: str | None = None
            matched_entry: dict[str, Any] | None = None

            with self._lock:
                # Find the most recent pending entry for this slot
                slot_keys = sorted(
                    [k for k in self._pending_entries if k.startswith(slot_prefix)]
                )
                if slot_keys:
                    matched_key = slot_keys[-1]          # latest timestamp
                    matched_entry = self._pending_entries.pop(matched_key)

            if matched_entry is None:
                log.warning(
                    "record_exit: no pending entry found for %s %s — trade not tracked",
                    symbol, side,
                )
                return

            # Label: 1 = profitable, 0 = loss / break-even
            label = 1 if pnl_points > 0.0 else 0

            # Weight: base + magnitude component, capped at 1.0
            weight = min(
                _WEIGHT_CAP,
                _WEIGHT_BASE + abs(pnl_points) / _WEIGHT_NORM_POINTS,
            )
            if label == 1:
                weight = min(_WEIGHT_CAP, weight + _WEIGHT_WIN_BONUS)

            record = {
                "sequence": matched_entry["sequence"],
                "label": label,
                "weight": float(weight),
                "symbol": symbol,
                "side": side,
                "pnl": float(pnl_points),
                "ts": matched_entry["ts"],
            }

            with self._lock:
                self._buffer.append(record)
                buf_len = len(self._buffer)

            log.info(
                "record_exit: buffered trade %s %s pnl=%.2f label=%d weight=%.3f "
                "[buffer %d/%d]",
                symbol, side, pnl_points, label, weight, buf_len, self.buffer_size,
            )

            self._maybe_retrain()

        except Exception:
            log.exception("record_exit: unhandled exception for %s %s", symbol, side)

    def status(self) -> dict[str, Any]:
        """
        Return a lightweight status snapshot (no lock held across the return).
        """
        with self._lock:
            pending = len(self._pending_entries)
            buf_len = len(self._buffer)
            retrain_count = self._retrain_count
            last_retrain = self._last_retrain_time

        return {
            "pending_entries": pending,
            "buffer_size": buf_len,
            "buffer_capacity": self.buffer_size,
            "retrain_count": retrain_count,
            "last_retrain_time": last_retrain,
            "model_path": str(self.model_path),
        }

    def save_buffer(self) -> None:
        """
        Persist the current buffer to disk so it survives process restarts.
        Sequences are saved as a compressed .npz; metadata as JSON.
        """
        try:
            with self._lock:
                records = list(self._buffer)

            if not records:
                log.debug("save_buffer: buffer is empty — nothing to save")
                return

            sequences = np.stack([r["sequence"] for r in records], axis=0)
            labels = np.array([r["label"] for r in records], dtype=np.int8)
            weights = np.array([r["weight"] for r in records], dtype=np.float32)

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                str(_BUFFER_NPZ),
                sequences=sequences,
                labels=labels,
                weights=weights,
            )

            meta = [
                {
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "pnl": r["pnl"],
                    "ts": r["ts"],
                    "label": r["label"],
                    "weight": r["weight"],
                }
                for r in records
            ]
            _BUFFER_META.write_text(
                json.dumps({"records": meta, "retrain_count": self._retrain_count}, indent=2),
                encoding="utf-8",
            )
            log.info("save_buffer: saved %d samples to %s", len(records), _BUFFER_NPZ)

        except Exception:
            log.exception("save_buffer: failed to persist buffer")

    def load_buffer(self) -> None:
        """
        Public alias for the internal load routine.
        """
        self._load_buffer()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_buffer(self) -> None:
        """
        Restore a previously persisted buffer from disk.
        Called once during ``__init__``.
        """
        try:
            if not _BUFFER_NPZ.exists():
                log.debug("load_buffer: no persisted buffer found at %s", _BUFFER_NPZ)
                return

            data = np.load(str(_BUFFER_NPZ), allow_pickle=False)
            sequences: np.ndarray = data["sequences"]
            labels: np.ndarray = data["labels"]
            weights: np.ndarray = data["weights"]

            # Load optional metadata for symbol/side/pnl fields
            meta_records: list[dict] = []
            if _BUFFER_META.exists():
                try:
                    payload = json.loads(_BUFFER_META.read_text(encoding="utf-8"))
                    meta_records = payload.get("records", [])
                    self._retrain_count = int(payload.get("retrain_count", 0))
                except Exception:
                    log.warning("load_buffer: could not parse metadata JSON — using defaults")

            n = sequences.shape[0]
            for i in range(n):
                meta = meta_records[i] if i < len(meta_records) else {}
                record = {
                    "sequence": sequences[i],
                    "label": int(labels[i]),
                    "weight": float(weights[i]),
                    "symbol": meta.get("symbol", "unknown"),
                    "side": meta.get("side", "unknown"),
                    "pnl": meta.get("pnl", 0.0),
                    "ts": meta.get("ts", ""),
                }
                self._buffer.append(record)

            log.info("load_buffer: restored %d samples from %s", n, _BUFFER_NPZ)

        except Exception:
            log.exception("load_buffer: failed to restore buffer — starting fresh")
            self._buffer.clear()

    def _maybe_retrain(self) -> None:
        """
        Fine-tune the model if the buffer contains enough samples.
        This method is intentionally exception-safe: any error is logged and
        the calling thread continues unaffected.
        """
        with self._lock:
            buf_len = len(self._buffer)

        if buf_len < self.min_retrain_samples:
            log.debug(
                "_maybe_retrain: buffer has %d/%d — not enough yet",
                buf_len, self.min_retrain_samples,
            )
            return

        try:
            # Lazy TensorFlow import — avoids startup cost / import errors when TF
            # is not installed in the active environment.
            import tensorflow as tf  # noqa: PLC0415

            if not self.model_path.exists():
                log.warning(
                    "_maybe_retrain: model not found at %s — skipping fine-tune",
                    self.model_path,
                )
                return

            log.info("_maybe_retrain: loading model from %s", self.model_path)
            model: tf.keras.Model = tf.keras.models.load_model(str(self.model_path))

            # Build training arrays from the current buffer snapshot
            with self._lock:
                records = list(self._buffer)

            sequences = np.stack([r["sequence"] for r in records], axis=0).astype(np.float32)
            labels = np.array([r["label"] for r in records], dtype=np.float32)
            weights = np.array([r["weight"] for r in records], dtype=np.float32)

            log.info(
                "_maybe_retrain: fine-tuning on %d samples "
                "(wins=%d losses=%d) for %d epochs",
                len(records),
                int(labels.sum()),
                int((1 - labels).sum()),
                self.fine_tune_epochs,
            )

            # Compile with a small learning rate to avoid catastrophic forgetting
            model.compile(
                optimizer=tf.keras.optimizers.Adam(learning_rate=_FINE_TUNE_LR),
                loss=tf.keras.losses.BinaryCrossentropy(label_smoothing=_LABEL_SMOOTHING),
                metrics=["accuracy"],
            )

            history = model.fit(
                sequences,
                labels,
                sample_weight=weights,
                epochs=self.fine_tune_epochs,
                batch_size=_FINE_TUNE_BATCH,
                shuffle=True,
                verbose=0,
            )

            # Persist the updated model
            model.save(str(self.model_path))

            # Update counters
            with self._lock:
                self._retrain_count += 1
                self._last_retrain_time = datetime.now(timezone.utc).isoformat()
                retrain_count = self._retrain_count

            # Log final-epoch metrics
            final_loss = history.history["loss"][-1]
            final_acc = history.history.get("accuracy", [float("nan")])[-1]
            log.info(
                "_maybe_retrain: retrain #%d complete | loss=%.4f acc=%.4f | model saved",
                retrain_count, final_loss, final_acc,
            )

            # Trim buffer: keep the most recent _CONTINUITY_KEEP samples
            # so the next retrain cycle has context continuity
            with self._lock:
                keep = list(self._buffer)[-_CONTINUITY_KEEP:]
                self._buffer.clear()
                self._buffer.extend(keep)
                log.debug(
                    "_maybe_retrain: buffer trimmed — keeping last %d samples",
                    len(self._buffer),
                )

            # Persist the trimmed buffer to disk
            self.save_buffer()

        except ImportError:
            log.error(
                "_maybe_retrain: TensorFlow is not available in this environment — "
                "cannot fine-tune. Install tensorflow to enable adaptive learning."
            )
        except Exception:
            log.exception("_maybe_retrain: unexpected error during fine-tuning")
