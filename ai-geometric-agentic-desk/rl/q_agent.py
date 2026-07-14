"""Linear Q-learning agent over the desk's feature space.

A compact, dependency-free function-approximation Q-learner: each action's
value is a linear function of the feature vector. It learns from net-R rewards
(see :mod:`rl.environment`) and persists its weights to JSON so learning
survives restarts. The agent's preferred action and confidence can be surfaced
to the confluence matrix as one more vote.

Honesty note: like the logistic signal, this is expected to converge near
break-even on this market data. It is a *learning scaffold*, not a guaranteed
edge; the exam remains the arbiter of deployability.
"""
from __future__ import annotations

import json
import os

import numpy as np

from rl.environment import ACTIONS, FLAT, LONG, SHORT, reward_for, state_at

_WEIGHTS = os.path.join(os.path.dirname(__file__), "..", "data", "rl_weights.json")
_NDIM = 5


class QAgent:
    """Linear Q-function over 5 features for 3 actions."""

    def __init__(self, lr: float = 0.05, gamma: float = 0.0,
                 epsilon: float = 0.1) -> None:
        """Initialise (or load) the agent.

        Args:
            lr: Learning rate.
            gamma: Discount (0 = contextual bandit; each trade is terminal).
            epsilon: Exploration rate for :meth:`act`.
        """
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.w = np.zeros((len(ACTIONS), _NDIM))
        self.load()

    def q(self, state: np.ndarray) -> np.ndarray:
        """Return Q-values for every action at ``state``."""
        return self.w @ state

    def act(self, state: np.ndarray, explore: bool = False) -> tuple[int, float]:
        """Pick an action and a normalised confidence.

        Args:
            state: Feature vector.
            explore: If True, epsilon-greedy exploration is allowed.

        Returns:
            ``(action, confidence)`` where confidence is the softmax weight of
            the chosen action in ``[0, 1]``.
        """
        qs = self.q(state)
        if explore and np.random.random() < self.epsilon:
            a = int(np.random.choice(ACTIONS))
        else:
            a = int(np.argmax(qs))
        ex = np.exp(qs - qs.max())
        conf = float(ex[a] / (ex.sum() + 1e-12))
        return a, conf

    def learn(self, state: np.ndarray, action: int, reward: float) -> None:
        """Apply a single contextual-bandit Q-update."""
        pred = float(self.w[action] @ state)
        self.w[action] += self.lr * (reward - pred) * state

    def direction(self, state: np.ndarray) -> tuple[int, float]:
        """Map the greedy action to a signed direction and confidence.

        Returns:
            ``(+1/-1/0, confidence)`` for LONG/SHORT/FLAT.
        """
        a, conf = self.act(state, explore=False)
        return ({LONG: 1, SHORT: -1, FLAT: 0}[a], conf)

    def save(self) -> None:
        """Persist weights to JSON."""
        os.makedirs(os.path.dirname(_WEIGHTS), exist_ok=True)
        with open(_WEIGHTS, "w", encoding="utf-8") as fh:
            json.dump({"w": self.w.tolist()}, fh)

    def load(self) -> None:
        """Load weights from JSON if present."""
        try:
            with open(_WEIGHTS, "r", encoding="utf-8") as fh:
                self.w = np.array(json.load(fh)["w"])
        except Exception:
            pass


def train_offline(o, h, l, c, forward_rs: dict[int, float],
                  epochs: int = 5) -> QAgent:
    """Train a :class:`QAgent` from precomputed forward returns.

    Args:
        o, h, l, c: OHLC arrays.
        forward_rs: Map of bar index -> long-side forward net-R.
        epochs: Passes over the data.

    Returns:
        The trained agent (also saved to disk).
    """
    agent = QAgent()
    for _ in range(epochs):
        for i, r in forward_rs.items():
            s = state_at(o, h, l, c, i)
            for a in ACTIONS:
                agent.learn(s, a, reward_for(a, r))
    agent.save()
    return agent
