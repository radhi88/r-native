"""Lightweight, honest ML directional signal.

A dependency-free logistic-regression classifier trained on the visible
window to predict next-bar direction from simple momentum / volatility /
structure features. It is deliberately small and is trained only on past
bars relative to each prediction during the exam (no look-ahead).

Honesty note: on this project's data ML direction prediction has repeatedly
scored NO_EDGE (~50% OOS). The confidence this emits is fed to the confluence
gate as one vote — it is expected to hover near 0.5, and the exam is designed
to expose that rather than hide it.
"""
from __future__ import annotations

import numpy as np


def _features(opens, highs, lows, closes, i: int, lookback: int = 20) -> np.ndarray:
    """Build a causal feature row from bars up to and including ``i``."""
    a = max(0, i - lookback)
    c = closes[a:i + 1]
    if len(c) < 5:
        return np.zeros(5)
    ret = np.diff(np.log(c + 1e-9))
    mom = float(np.sum(ret[-5:]))
    vol = float(np.std(ret) + 1e-9)
    rng = float((highs[i] - lows[i]) / (closes[i] + 1e-9))
    body = float((closes[i] - opens[i]) / (highs[i] - lows[i] + 1e-9))
    pos = float((closes[i] - np.min(lows[a:i + 1])) /
                (np.max(highs[a:i + 1]) - np.min(lows[a:i + 1]) + 1e-9))
    return np.array([mom / (vol + 1e-9), vol, rng, body, pos - 0.5])


class LogisticSignal:
    """Tiny batch-trained logistic regression for next-bar direction."""

    def __init__(self, lr: float = 0.1, epochs: int = 300) -> None:
        """Initialise an untrained model.

        Args:
            lr: Gradient-descent learning rate.
            epochs: Number of full-batch passes.
        """
        self.w = np.zeros(5)
        self.b = 0.0
        self.lr = lr
        self.epochs = epochs
        self.trained = False

    def fit(self, opens, highs, lows, closes, end: int) -> None:
        """Train on bars ``[0, end)`` predicting the next-bar up move.

        Args:
            opens, highs, lows, closes: OHLC arrays.
            end: Exclusive upper bound — only past bars are used.
        """
        xs, ys = [], []
        for i in range(20, end - 1):
            xs.append(_features(opens, highs, lows, closes, i))
            ys.append(1.0 if closes[i + 1] > closes[i] else 0.0)
        if len(ys) < 30:
            return
        x = np.array(xs)
        x = (x - x.mean(0)) / (x.std(0) + 1e-9)
        y = np.array(ys)
        self._mu, self._sd = np.array(xs).mean(0), np.array(xs).std(0) + 1e-9
        for _ in range(self.epochs):
            z = x @ self.w + self.b
            p = 1.0 / (1.0 + np.exp(-z))
            g = p - y
            self.w -= self.lr * (x.T @ g) / len(y)
            self.b -= self.lr * float(np.mean(g))
        self.trained = True

    def predict(self, opens, highs, lows, closes, i: int) -> tuple[int, float]:
        """Predict direction and confidence at bar ``i``.

        Args:
            opens, highs, lows, closes: OHLC arrays.
            i: Bar index to score.

        Returns:
            ``(signal, confidence)`` where signal is ``+1``/``-1`` and
            confidence is ``max(p, 1-p)`` in ``[0.5, 1.0]``. Untrained → flat.
        """
        if not self.trained:
            return 0, 0.5
        f = (_features(opens, highs, lows, closes, i) - self._mu) / self._sd
        p = 1.0 / (1.0 + np.exp(-(f @ self.w + self.b)))
        return (1 if p >= 0.5 else -1), float(max(p, 1 - p))
