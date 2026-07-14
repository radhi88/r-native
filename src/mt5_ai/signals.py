from .config import BUY_THRESHOLD, SELL_THRESHOLD


def generate_signal(prediction, regime=None, session=None):
    probability = float(prediction)
    confidence = abs(probability - 0.5) * 2
    regime = regime or {}
    session = session or {}

    if session.get("session_asia") and confidence < 0.6:
        return "NO_TRADE", confidence

    if regime.get("regime_range") == 1 and confidence < 0.7:
        return "NO_TRADE", confidence

    if probability >= BUY_THRESHOLD:
        return "BUY", confidence

    if probability <= SELL_THRESHOLD:
        return "SELL", confidence

    return "HOLD", confidence
