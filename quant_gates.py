"""quant_gates.py — بوّابات كمّية احترافية (من بحث الوكلاء): تجعل التعلّم موثوقاً لرصيد حقيقي.

  • probabilistic_sharpe_ratio / deflated_sharpe_ratio — أقوى حارس ضد خداع البحث الشبكي
    (grid-search selection bias): جين بـSharpe عالٍ صدفةً بين مئات المحاولات يسقط هنا.
  • hurst_regime — بوّابة النظام: ترند (H>0.55) / ارتداد (H<0.45) / عشوائي — تُوجّه الاستراتيجية.
  • garch_sigma — تنبؤ تقلّب الشمعة القادمة (arch) لتحجيم اللوت والوقف بدقّة (أفضل من ATR وحده).

كلها دوال نقية، صفر LLM، صفر تكلفة. تُستهلك من genome_factory / multi_trader / war_room.
"""
from __future__ import annotations
import math


def probabilistic_sharpe_ratio(returns, benchmark_sr=0.0):
    """PSR: احتمال أن Sharpe الحقيقي > المعيار، مع تصحيح الالتواء والتفرطح وعدد العيّنات.
    قيمة >0.95 = ثقة عالية أن الحافة حقيقية لا صدفة."""
    n = len(returns)
    if n < 20:
        return 0.0
    mu = sum(returns) / n
    var = sum((x - mu) ** 2 for x in returns) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0:
        return 0.0
    sr = mu / sd
    # skew + kurtosis
    m3 = sum((x - mu) ** 3 for x in returns) / n
    m4 = sum((x - mu) ** 4 for x in returns) / n
    skew = m3 / sd ** 3 if sd > 0 else 0.0
    kurt = m4 / sd ** 4 if sd > 0 else 3.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - benchmark_sr) * math.sqrt(n - 1) / denom
    return _norm_cdf(z)


def deflated_sharpe_ratio(returns, n_trials):
    """DSR: PSR لكن مع رفع عتبة المعيار حسب عدد الجينات المُجرّبة (n_trials) — كل ما جرّبنا أكثر،
    احتجنا Sharpe أعلى لنصدّق. DSR>0.5 = اجتاز اختبار التعدّدية."""
    n = len(returns)
    if n < 20 or n_trials < 1:
        return 0.0
    mu = sum(returns) / n
    var = sum((x - mu) ** 2 for x in returns) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0:
        return 0.0
    sr = mu / sd
    # عتبة Sharpe المتوقّعة من أفضل بين n_trials محاولة عشوائية (Bailey & López de Prado)
    e = 0.5772156649
    emax = math.sqrt(2 * math.log(max(2, n_trials)))
    sr0 = (1 - e) * _inv_norm(1 - 1.0 / n_trials) + e * _inv_norm(1 - 1.0 / (n_trials * e)) \
        if n_trials > 1 else 0.0
    sr0 = sr0 / math.sqrt(n - 1) if n > 1 else 0.0
    return probabilistic_sharpe_ratio(returns, benchmark_sr=max(0.0, sr0))


def hurst_regime(prices):
    """يعيد (regime, H): trend / meanrev / random. يحاول مكتبة hurst ثم بديل R/S بسيط."""
    if len(prices) < 64:
        return "random", 0.5
    try:
        from hurst import compute_Hc
        H, _, _ = compute_Hc(prices, kind="price", simplified=True)
    except Exception:
        H = _rs_hurst(prices)
    reg = "trend" if H >= 0.55 else "meanrev" if H <= 0.45 else "random"
    return reg, round(float(H), 3)


def garch_sigma(returns):
    """تنبؤ انحراف الشمعة القادمة عبر GARCH(1,1) (arch). يعيد None لو غير متاح."""
    if len(returns) < 100:
        return None
    try:
        import numpy as np
        from arch import arch_model
        r = np.array(returns) * 100.0
        am = arch_model(r, vol="Garch", p=1, q=1, mean="constant", dist="normal")
        res = am.fit(disp="off", show_warning=False)
        f = res.forecast(horizon=1, reindex=False)
        return float(np.sqrt(f.variance.values[-1, 0])) / 100.0
    except Exception:
        return None


# ── helpers ────────────────────────────────────────────────────────────────
def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _inv_norm(p):
    """Acklam inverse normal CDF approximation."""
    if p <= 0:
        return -8.0
    if p >= 1:
        return 8.0
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= 1 - pl:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _rs_hurst(series):
    """Rescaled-range Hurst fallback (no deps)."""
    import math as _m
    ts = list(series); n = len(ts)
    if n < 64:
        return 0.5
    rs = []
    for w in (n // 2, n // 4, n // 8):
        if w < 8:
            continue
        chunks = n // w; vals = []
        for c in range(chunks):
            seg = ts[c*w:(c+1)*w]
            mu = sum(seg)/w
            dev = [sum(seg[:i+1]) - (i+1)*mu for i in range(w)]
            R = max(dev) - min(dev)
            sd = _m.sqrt(sum((x-mu)**2 for x in seg)/w)
            if sd > 0:
                vals.append(R/sd)
        if vals:
            rs.append((_m.log(w), _m.log(sum(vals)/len(vals))))
    if len(rs) < 2:
        return 0.5
    xs = [a for a, _ in rs]; ys = [b for _, b in rs]
    mx = sum(xs)/len(xs); my = sum(ys)/len(ys)
    num = sum((xs[i]-mx)*(ys[i]-my) for i in range(len(xs)))
    den = sum((xs[i]-mx)**2 for i in range(len(xs)))
    return num/den if den > 0 else 0.5


if __name__ == "__main__":
    import random
    random.seed(1)
    good = [random.gauss(0.001, 0.01) for _ in range(200)]
    print("PSR(good):", round(probabilistic_sharpe_ratio(good), 3))
    print("DSR(good, 500 trials):", round(deflated_sharpe_ratio(good, 500), 3))
    trend = [i * 0.01 + random.gauss(0, 0.1) for i in range(200)]
    print("hurst(trend):", hurst_regime(trend))
