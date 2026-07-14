from .ai_brain import TradingBrain
from .regime import detect_regime
from .risk import RiskManager
from .signals import generate_signal


risk = RiskManager()


def run_pipeline(model, df, x):
    if not risk.can_trade():
        return "BLOCKED_RISK"

    regime_df = detect_regime(df)
    regime = regime_df.iloc[-1].to_dict()

    session_keys = ["session_asia", "session_london", "session_ny", "session_overlap"]
    session = {key: regime.get(key, 0) for key in session_keys}

    prediction = float(model.predict(x, verbose=0)[0][0])
    signal, confidence = generate_signal(prediction, regime, session)

    return {
        "signal": signal,
        "confidence": float(confidence),
        "probability": prediction,
        "regime": regime,
    }


def run_ai_brain(model, df, x, profile_name="ict"):
    if not risk.can_trade():
        return {
            "action": "NO_TRADE",
            "reason": "blocked_by_risk",
            "risk_allowed": False,
        }

    brain = TradingBrain(model=model, profile_name=profile_name)
    decision = brain.decide(df=df, sequence=x)
    return decision.to_dict()
