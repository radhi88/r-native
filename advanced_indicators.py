"""advanced_indicators.py — strong, fast, array-only indicators added to BOTH the live decision
(chart_read) and the genome's backtest vote (market_gate._vote), so the gene is trained on the
SAME engine it trades with. Each returns a directional vote (-1/0/+1). No MT5, no lookahead,
O(window) fast. Includes the user's requested tools: Gann angle, fractal (Hurst) regime, candle
geometry. Their REAL accuracy is measured per symbol and the learned weighting judges them — a
useless one (e.g. Gann) gets down-weighted automatically; an accurate one is amplified.
"""
from __future__ import annotations
import math


def _ema(arr, p):
    if not arr:
        return []
    k = 2.0 / (p + 1); e = arr[0]; out = [e]
    for x in arr[1:]:
        e = x * k + e * (1 - k); out.append(e)
    return out


def fisher(close, n=10):
    """Fisher Transform — sharp turning-point detector. Vote = direction of the transform."""
    if len(close) < n + 2:
        return 0
    w = close[-(n + 1):]
    hi, lo = max(w), min(w)
    if hi == lo:
        return 0
    v = 0.0; f = 0.0; f_prev = 0.0
    for p in w:
        x = 2 * ((p - lo) / (hi - lo)) - 1
        v = 0.66 * x + 0.67 * v
        v = max(-0.999, min(0.999, v))
        f_prev = f
        f = 0.5 * math.log((1 + v) / (1 - v)) + 0.5 * f
    return 1 if f > f_prev else -1 if f < f_prev else 0


def vortex(high, low, close, n=14):
    """Vortex Indicator — fast trend direction (VI+ vs VI-)."""
    if len(close) < n + 2:
        return 0
    vmp = sum(abs(high[-i] - low[-i - 1]) for i in range(1, n + 1))
    vmm = sum(abs(low[-i] - high[-i - 1]) for i in range(1, n + 1))
    tr = sum(max(high[-i] - low[-i], abs(high[-i] - close[-i - 1]), abs(low[-i] - close[-i - 1]))
             for i in range(1, n + 1))
    if tr <= 0:
        return 0
    return 1 if (vmp / tr) > (vmm / tr) else -1


def tsi(close, r=25, s=13):
    """True Strength Index — double-smoothed momentum. Vote = sign."""
    if len(close) < r + s + 2:
        return 0
    m = [close[i] - close[i - 1] for i in range(1, len(close))]
    e2 = _ema(_ema(m, r), s)
    a2 = _ema(_ema([abs(x) for x in m], r), s)
    if not a2 or a2[-1] == 0:
        return 0
    t = 100 * e2[-1] / a2[-1]
    return 1 if t > 0 else -1 if t < 0 else 0


def gann1x1(close, n=20):
    """Gann 1x1 angle — price slope vs the unit (45°) angle scaled by volatility. (Requested;
    typically weak/non-predictive → the learned weighting will down-rank it if so.)"""
    if len(close) < n + 1:
        return 0
    slope = (close[-1] - close[-n]) / n
    vol = sum(abs(close[-i] - close[-i - 1]) for i in range(1, n)) / max(1, n - 1)
    if vol == 0:
        return 0
    ratio = slope / vol
    return 1 if ratio > 0.5 else -1 if ratio < -0.5 else 0


def hurst(close, n=64):
    """Hurst exponent (fractal regime) via rescaled-range. H>0.55 trending → follow; H<0.45
    mean-reverting → fade. (The user's 'fractal' tool, honest regime use.)"""
    if len(close) < n:
        return 0
    w = close[-n:]
    rets = [w[i] - w[i - 1] for i in range(1, len(w))]
    if len(rets) < 8:
        return 0
    mean = sum(rets) / len(rets)
    cum = 0.0; dev = []
    for x in rets:
        cum += x - mean; dev.append(cum)
    R = max(dev) - min(dev)
    var = sum((x - mean) ** 2 for x in rets) / len(rets)
    S = math.sqrt(var)
    if S == 0 or R == 0:
        return 0
    H = math.log(R / S) / math.log(len(rets))
    slope = 1 if w[-1] > w[-5] else -1
    if H > 0.55:
        return slope
    if H < 0.45:
        return -slope
    return 0


def candle_geo(high, low, close, n=5):
    """Candle geometry — average position of close within the bar range (pressure). Closes near
    the high = buyers in control. (The user's candle-engineering tool, open-free.)"""
    if len(close) < n:
        return 0
    pos = []
    for i in range(-n, 0):
        rng = high[i] - low[i]
        if rng > 0:
            pos.append((close[i] - low[i]) / rng)
    if not pos:
        return 0
    avg = sum(pos) / len(pos)
    return 1 if avg > 0.6 else -1 if avg < 0.4 else 0


def chaikin(high, low, close, vol, n=20):
    """Chaikin oscillator — EMA3-EMA10 of the Accumulation/Distribution line (volume pressure)."""
    if len(close) < 30:
        return 0
    adl = 0.0; series = []
    for i in range(len(close)):
        rng = high[i] - low[i]
        mfm = ((close[i] - low[i]) - (high[i] - close[i])) / rng if rng > 0 else 0.0
        adl += mfm * (vol[i] if i < len(vol) else 1.0)
        series.append(adl)
    seg = series[-30:]
    short = _ema(seg, 3)[-1]; long = _ema(seg, 10)[-1]
    return 1 if short > long else -1 if short < long else 0


def elder(high, low, close, n=13):
    """Elder-Ray bull/bear power vs EMA13."""
    if len(close) < n + 1:
        return 0
    e = _ema(close, n)[-1]
    if low[-1] > e:
        return 1            # whole bar above EMA = bulls dominant
    if high[-1] < e:
        return -1           # whole bar below EMA = bears dominant
    return 0


# registry: name -> (callable, args-key, base-weight). args-key tells the caller which arrays to pass.
def swing_profile(close, high, low, vol, L=12, atr_k=0.25, dth=15.0):
    """Swing Profile [BigBeluga] (TV Editors' Pick) → -1/0/+1. Per-SWING volume profile:
    detects CONFIRMED fractal pivots (extreme of L bars each side), takes the last locked swing,
    bins its volume into ATR buckets → POC + leg delta%. CAUSAL/NON-REPAINTING by construction
    (pivots need L right-side bars, so we only read an already-locked swing — never the live one).
    Vote = mean-reversion-to-POC + delta-exhaustion: price below locked POC & sellers exhausted →
    +1; price above POC & buyers exhausted → -1; else 0. ON TRIAL — measured accuracy decides."""
    n = len(close)
    if n < 4 * L + 20:
        return 0
    piv = []
    for p in range(L, n - L):
        wh = high[p - L:p + L + 1]; wl = low[p - L:p + L + 1]
        if high[p] == max(wh) and high[p] != min(wh):
            piv.append((p, 'H'))
        elif low[p] == min(wl) and low[p] != max(wl):
            piv.append((p, 'L'))
    if len(piv) < 2:
        return 0
    (i2, t2) = piv[-1]; (i1, t1) = piv[-2]
    if t1 == t2:
        return 0
    a, b = (i1, i2) if i1 < i2 else (i2, i1)
    if b - a < 3:
        return 0
    sc = close[a:b + 1]; sh = high[a:b + 1]; sl = low[a:b + 1]; sv = vol[a:b + 1]
    trs = [max(sh[k] - sl[k], abs(sh[k] - sc[k - 1]), abs(sl[k] - sc[k - 1])) for k in range(1, len(sc))]
    atr = (sum(trs) / len(trs)) if trs else (max(sh) - min(sl)) / max(1, len(sc))
    bin_w = max(atr * atr_k, 1e-9)
    lo = min(sl); buckets = {}
    for k in range(len(sc)):
        j = int((sc[k] - lo) / bin_w); buckets[j] = buckets.get(j, 0.0) + sv[k]
    if not buckets:
        return 0
    poc = lo + (max(buckets, key=buckets.get) + 0.5) * bin_w
    B = sum(sv[k] for k in range(1, len(sc)) if sc[k] > sc[k - 1])
    S = sum(sv[k] for k in range(1, len(sc)) if sc[k] < sc[k - 1])
    if B + S <= 0:
        return 0
    D = 100.0 * (B - S) / (B + S)
    price = close[-1]
    if price < poc and D < -dth:
        return 1
    if price > poc and D > dth:
        return -1
    return 0


REGISTRY = [
    ("fisher",    "c",    1.2),
    ("vortex",    "hlc",  1.3),
    ("tsi",       "c",    1.2),
    ("gann",      "c",    0.8),   # low base weight — requested but usually weak
    ("hurst",     "c",    1.0),
    ("candle_geo","hlc",  1.1),
    ("chaikin",   "hlcv", 1.0),
    ("elder",     "hlc",  1.1),
    # SMC structure (from the user's video) — ON TRIAL: measured accuracy decides their fate
    ("cisd",      "hlc",  1.0),
    ("choch",     "hlc",  1.0),
    ("ifvg",      "hlc",  0.9),
    # BigBeluga Swing Profile (TV Editors' Pick) — ON TRIAL: measured accuracy decides its fate
    ("swing_profile", "hlcv", 1.0),
]


def vote(name, high, low, close, vol):
    """Dispatch a single advanced indicator by name with the right arrays."""
    if name == "fisher":     return fisher(close)
    if name == "vortex":     return vortex(high, low, close)
    if name == "tsi":        return tsi(close)
    if name == "gann":       return gann1x1(close)
    if name == "hurst":      return hurst(close)
    if name == "candle_geo": return candle_geo(high, low, close)
    if name == "chaikin":    return chaikin(high, low, close, vol)
    if name == "elder":      return elder(high, low, close)
    if name in ("cisd", "choch", "ifvg"):
        import smc_structure as _smc
        return getattr(_smc, name)(close, high, low)
    if name == "swing_profile":
        return swing_profile(close, high, low, vol)
    return 0
