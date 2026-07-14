"""Trade environment adapter for reinforcement learning.

Maps the desk's feature vector to an RL state and resolves the reward of an
action (long / flat / short) from the realised net-R outcome of the trade the
confluence engine would have taken. Used to train :class:`rl.q_agent.QAgent`
offline from historical bars or online from journaled outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.ml_signal import _features

# Discrete action space
FLAT, LONG, SHORT = 0, 1, 2
ACTIONS = (FLAT, LONG, SHORT)


@dataclass
class Transition:
    """One RL transition.

    Attributes:
        state: Feature vector at decision time.
        action: Action taken (``FLAT``/``LONG``/``SHORT``).
        reward: Net-R realised by the action.
    """

    state: np.ndarray
    action: int
    reward: float


def state_at(o, h, l, c, i: int) -> np.ndarray:
    """Return the RL state (feature vector) at bar ``i``."""
    return _features(o, h, l, c, i)


def reward_for(action: int, forward_r: float) -> float:
    """Reward of ``action`` given the long's forward net-R.

    Args:
        action: ``FLAT``/``LONG``/``SHORT``.
        forward_r: Net-R the long side would have earned.

    Returns:
        ``forward_r`` for LONG, ``-forward_r`` for SHORT, ``0`` for FLAT.
    """
    if action == LONG:
        return forward_r
    if action == SHORT:
        return -forward_r
    return 0.0
