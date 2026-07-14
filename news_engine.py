"""news_engine.py — MULTI-SOURCE news → instant veto + long-term bias, weighted into decisions.

User ask (2026-06-08):
  "نضيف مصادر للاخبار من اكثر من مصدر ونستفيد منه في مؤشراتنا اللحظية وطويلة المدى
   وانت تكون المغذي للاخبار وتعطيه وزن اكبر"
=> pull news from SEVERAL sources, feed BOTH the instant indicators (veto/spike) AND a
   long-term rolling bias, and let a CLAUDE-CURATED feed carry the HIGHEST weight.

THREE TIERS (weight multipliers on the injected news vote):
  Tier 1  CLAUDE-CURATED  (news_curated.json, written by the Claude layer)  → weight 5.0  [highest]
  Tier 2  OFFICIAL/CALENDAR (Forex-Factory red folder, Fed/ECB)             → weight 3.0
  Tier 3  SCRAPED RETAIL RSS (ForexLive, FXStreet, Investing, CoinDesk)     → weight 1.5

Outputs (atomic write; readers already swallow JSON errors):
  data/r_native/agents/news_signals.json   — rich per-symbol {dir,score,bias,tier,conviction,hot,veto,reason}
  data/r_native/news_blocked_symbols.json  — LEGACY veto contract multi_trader._agent_inputs() already reads
  data/r_native/agents/news_ewma.json      — persisted rolling bias (decays on load by elapsed time)

Fail-OPEN everywhere: any feed 403/timeout contributes nothing; a dead feed NEVER halts trading.
Mostly stdlib (urllib + xml.etree). Read-only on the market. Windowless.  Run:  python news_engine.py --loop
"""
from __future__ import annotations
import argparse, json, time, re, html, math
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

RN = Path(r"C:\Users\Radhi\MT5\data\r_native")
AG = RN / "agents"
SIGNALS   = AG / "news_signals.json"
CURATED   = AG / "news_curated.json"          # ← the Claude-fed, highest-weight tier
EWMA_FILE = AG / "news_ewma.json"
BLOCKED   = RN / "news_blocked_symbols.json"   # legacy veto file (keep writing it)
FF_CAL    = Path(r"C:\Users\Radhi\MT5\friday_v3\data\news_calendar.json")  # existing calendar (if fresh)

# ── config (retune freely, no logic edits) ──────────────────────────────────
TIER_WEIGHT = {1: 5.0, 2: 3.0, 3: 1.5}
BASE_NEWS_WEIGHT = 3.0          # base weight of the injected news vote (× tier × conviction)
VETO_MIN_DEFAULT = 15           # block ± this many minutes around a HIGH-impact event
VETO_MIN_BIG     = 20           # wider window for the biggest releases (CPI/NFP/FOMC)
HOT_ITEMS        = 3            # this many fresh items in HOT_WINDOW_S → "hot" (headline spike)
HOT_WINDOW_S     = 600
HOT_VETO_S       = 480
EWMA_HALFLIFE_S  = 8 * 3600     # long-term bias half-life ≈ 8h
FAST_EVERY_TICKS = 1            # fast feeds every tick
SLOW_EVERY_TICKS = 15           # slow feeds every ~15 ticks
TICK_S           = 60
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FRIDAY-news/1.0"

# No-key RSS feeds. tier 3 unless noted. (Any that 403/timeout just contribute nothing.)
FEEDS = [
    {"name": "ForexLive",   "url": "https://www.forexlive.com/feed/news",                       "tier": 3, "fast": True},
    {"name": "FXStreet",    "url": "https://www.fxstreet.com/rss/news",                          "tier": 3, "fast": False},
    {"name": "Investing-Commodities", "url": "https://www.investing.com/rss/news_11.rss",        "tier": 3, "fast": False},
    {"name": "Investing-Indices",     "url": "https://www.investing.com/rss/news_25.rss",        "tier": 3, "fast": False},
    {"name": "CoinDesk",    "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",            "tier": 3, "fast": True},
    {"name": "Fed-press",   "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",    "tier": 2, "fast": True},
]

# Keyword → [(symbol, sign)]. sign encodes INTER-MARKET DIRECTION vs the headline polarity:
# +1 = moves WITH the headline subject, -1 = moves INVERSE. A USD-strong macro headline
# (hawkish/strong-jobs) lifts USD pairs (+1) but pressures gold & EUR/GBP (-1) — the user's
# point: "اذا صعد الدولار نزل الذهب". Asset-specific keywords (gold/oil/btc) are direct (+1).
KW_SYMBOLS = {
    r"\b(gold|xau|bullion)\b":                       [("XAUUSDm", 1), ("XAGUSDm", 1)],
    r"\b(silver|xag)\b":                             [("XAGUSDm", 1)],
    r"\b(oil|crude|wti|brent|opec)\b":               [("USOILm", 1), ("UKOILm", 1)],
    r"\b(bitcoin|btc|crypto|ether|ethereum|etf)\b":  [("BTCUSDm", 1), ("ETHUSDm", 1)],
    # USD MACRO: polarity ≈ USD strength → gold/EUR/GBP inverse, USDJPY direct.
    r"\b(fed|fomc|powell|cpi|nfp|payroll|inflation|treasury|dxy|dollar|rate cut|rate hike)\b":
        [("XAUUSDm", -1), ("EURUSDm", -1), ("GBPUSDm", -1), ("USDJPYm", 1)],
    r"\b(nasdaq|s&p|s & p|dow|wall street|equities|stocks)\b":
        [("US30m", 1), ("NAS100m", 1), ("USTECm", 1), ("US500m", 1)],
    r"\b(nvidia|nvda)\b": [("NVDAm", 1)], r"\b(tesla|tsla)\b": [("TSLAm", 1)],
    r"\b(ecb|lagarde|eurozone|euro)\b": [("EURUSDm", 1)],   # euro-positive = EURUSD up
    r"\b(boe|pound|sterling|gbp)\b": [("GBPUSDm", 1)],
    r"\b(yen|jpy|boj)\b": [("USDJPYm", -1)],                # yen-positive = USDJPY down
}
CCY_SYMBOLS = {
    "USD": ["XAUUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "US30m", "NAS100m", "USTECm", "US500m"],
    "EUR": ["EURUSDm"], "GBP": ["GBPUSDm"], "JPY": ["USDJPYm"],
    "AUD": ["AUDUSDm"], "NZD": ["NZDUSDm"], "CAD": ["USDCADm", "USOILm"], "CHF": ["USDCHFm"],
}
BULL = re.compile(r"\b(surge|rally|jump|soar|beat|hawkish|rebound|gain|rise|strong|upbeat|boost|record high)\b", re.I)
BEAR = re.compile(r"\b(plunge|slump|tumble|miss|dovish|selloff|sell-off|fall|drop|weak|crash|cut|recession|fear)\b", re.I)
BIG_EVENT = re.compile(r"\b(cpi|non-?farm|nfp|payroll|fomc|rate decision|gdp|interest rate)\b", re.I)


def _now() -> float:
    return time.time()


def fetch(url: str, timeout: int = 8) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def parse_rss(xml_text: str) -> list[dict]:
    out = []
    if not xml_text:
        return out
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for it in root.iter():
        tag = it.tag.lower().rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = summary = ts = None
        for ch in it:
            ct = ch.tag.lower().rsplit("}", 1)[-1]
            if ct == "title":
                title = html.unescape((ch.text or "").strip())
            elif ct in ("description", "summary"):
                summary = html.unescape((ch.text or "").strip())
            elif ct in ("pubdate", "published", "updated", "date"):
                ts = _parse_ts(ch.text)
        if title:
            out.append({"title": title, "summary": summary or "", "ts": ts or _now()})
    return out


def _parse_ts(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def relevance(text: str) -> dict[str, int]:
    """Map a headline to {symbol: directional polarity(-1/0/+1)} via keyword maps (with
    inter-market sign) + a bull/bear lexicon. A symbol's vote = headline_polarity × sign."""
    pol = (1 if BULL.search(text) else 0) - (1 if BEAR.search(text) else 0)
    if pol == 0:
        return {}
    out: dict[str, int] = {}
    for pat, pairs in KW_SYMBOLS.items():
        if re.search(pat, text, re.I):
            for sym, sign in pairs:
                out[sym] = pol * sign      # last keyword wins on conflict (rare)
    return out


# ── calendar (Forex-Factory style) ──────────────────────────────────────────
def load_calendar() -> list[dict]:
    """Use the existing news_calendar.json ONLY if fresh (<24h); else fetch the FF weekly JSON
    live (a stale local file was hiding today's CPI from the veto + straddle hunter)."""
    evs = []
    try:
        if FF_CAL.exists() and (time.time() - FF_CAL.stat().st_mtime) < 86400:
            d = json.loads(FF_CAL.read_text(encoding="utf-8"))
            evs = d.get("events", []) or []
    except Exception:
        evs = []
    if not evs:
        txt = fetch("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=8)
        if txt:
            try:
                raw = json.loads(txt)
                for e in raw:
                    evs.append({"title": e.get("title"), "country": e.get("country"),
                                "impact": e.get("impact"), "date": e.get("date")})
                # CACHE back to the local file (fresh mtime) — callers poll every few seconds
                # and hammering the source gets us rate-limited (events 'vanish' mid-day).
                try:
                    FF_CAL.parent.mkdir(parents=True, exist_ok=True)
                    FF_CAL.write_text(json.dumps(
                        {"fetched_at": datetime.now(timezone.utc).isoformat(), "events": evs},
                        ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            except Exception:
                pass
    return evs


def calendar_veto(evs: list[dict], now: float) -> tuple[set, list]:
    blocked, active = set(), []
    for ev in evs:
        impact = str(ev.get("impact") or "").lower()
        if impact not in ("high", "h", "3"):
            continue
        ts = _parse_ts(ev.get("date") or ev.get("time"))
        if ts is None:
            continue
        mins = (ts - now) / 60.0
        win = VETO_MIN_BIG if BIG_EVENT.search(str(ev.get("title") or "")) else VETO_MIN_DEFAULT
        if abs(mins) <= win:
            ccy = (ev.get("country") or ev.get("currency") or "").upper()
            ss = CCY_SYMBOLS.get(ccy, [])
            blocked.update(ss)
            active.append({"title": ev.get("title"), "currency": ccy,
                           "minutes_to_event": round(mins, 1)})
    return blocked, active


# ── rolling long-term bias (EWMA, decays by elapsed time) ───────────────────
def load_ewma() -> dict:
    try:
        d = json.loads(EWMA_FILE.read_text(encoding="utf-8"))
        now = _now()
        for s, st in d.items():
            dt = max(0.0, now - float(st.get("ts", now)))
            st["bias"] = float(st.get("bias", 0.0)) * math.exp(-dt / EWMA_HALFLIFE_S)  # decay-on-load
        return d
    except Exception:
        return {}


def update_ewma(state: dict, sym: str, pol: int) -> None:
    now = _now()
    st = state.setdefault(sym, {"bias": 0.0, "samples": 0, "ts": now})
    dt = max(0.0, now - float(st.get("ts", now)))
    decay = math.exp(-dt / EWMA_HALFLIFE_S)
    alpha = 0.10
    st["bias"] = round(float(st["bias"]) * decay * (1 - alpha) + alpha * pol, 4)
    st["samples"] = int(st.get("samples", 0)) + 1
    st["ts"] = now


def load_curated() -> dict:
    """Claude-curated tier-1 feed: {symbols:{SYM:{dir,conviction,reason,ttl_s,ts}}}."""
    try:
        d = json.loads(CURATED.read_text(encoding="utf-8"))
        now = _now(); out = {}
        for s, v in (d.get("symbols", {}) or {}).items():
            if now - float(v.get("ts", 0)) <= float(v.get("ttl_s", 6 * 3600)):
                out[s] = v
        return out
    except Exception:
        return {}


def _atomic_write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, path)


_tick = 0


def run_once() -> dict:
    global _tick
    _tick += 1
    now = _now()
    ewma = load_ewma()

    # 1) gather headlines from the due feeds
    items = []   # (tier, title, ts)
    for f in FEEDS:
        if not f["fast"] and (_tick % SLOW_EVERY_TICKS) != 1:
            continue
        txt = fetch(f["url"])
        for it in parse_rss(txt or ""):
            items.append((f["tier"], it["title"] + " " + it.get("summary", ""), it["ts"]))

    # 2) per-symbol instant aggregation + EWMA update
    inst = {}   # sym -> {"score":float,"n":int,"tier":int,"recent":int,"reason":str}
    for tier, text, ts in items:
        rel = relevance(text)
        for sym, pol in rel.items():
            d = inst.setdefault(sym, {"score": 0.0, "n": 0, "tier": 3, "recent": 0, "reason": ""})
            w = TIER_WEIGHT.get(tier, 1.0)
            d["score"] += pol * w
            d["n"] += 1
            d["tier"] = min(d["tier"], tier)
            if now - ts <= HOT_WINDOW_S:
                d["recent"] += 1
            if pol != 0 and not d["reason"]:
                d["reason"] = text[:80]
            update_ewma(ewma, sym, pol)

    # 3) calendar veto
    evs = load_calendar()
    cal_blocked, active_events = calendar_veto(evs, now)

    # 4) Claude-curated tier-1 override (highest weight / can set direction)
    curated = load_curated()

    # 5) build the per-symbol contract
    all_syms = set(inst) | set(cal_blocked) | set(curated) | set(ewma)
    symbols, blocked = {}, set(cal_blocked)
    clusters = {"USD_bias": 0.0, "gold_bias": 0.0, "crypto_bias": 0.0, "equity_bias": 0.0}
    for sym in all_syms:
        d = inst.get(sym, {})
        hot = d.get("recent", 0) >= HOT_ITEMS
        score = d.get("score", 0.0)
        ndir = 1 if score > 0.5 else -1 if score < -0.5 else 0
        tier = d.get("tier", 3)
        conv = min(1.0, abs(score) / 6.0 + (0.15 if d.get("n") else 0.0))
        reason = d.get("reason", "")
        veto = sym in cal_blocked or hot
        # CLAUDE TIER overrides direction + conviction (highest authority)
        c = curated.get(sym)
        if c:
            ndir = int(c.get("dir", ndir)); tier = 1
            conv = max(conv, float(c.get("conviction", 0.7)))
            reason = f"🧠 {c.get('reason','curated')}"
        bias = round(float(ewma.get(sym, {}).get("bias", 0.0)), 4)
        if veto:
            blocked.add(sym)
        symbols[sym] = {"news_dir": ndir, "news_score": round(score, 2), "news_bias": bias,
                        "tier": tier, "conviction": round(conv, 2), "hot": hot,
                        "veto": veto, "reason": reason[:120],
                        "samples": int(ewma.get(sym, {}).get("samples", 0))}
    # cluster roll-up
    def _avg(keys):
        v = [symbols[s]["news_bias"] for s in symbols if s in keys]
        return round(sum(v) / len(v), 3) if v else 0.0
    clusters["gold_bias"]   = _avg({"XAUUSDm", "XAGUSDm"})
    clusters["crypto_bias"] = _avg({"BTCUSDm", "ETHUSDm"})
    clusters["equity_bias"] = _avg({"US30m", "NAS100m", "USTECm", "US500m"})
    clusters["USD_bias"]    = _avg({"EURUSDm", "GBPUSDm", "USDJPYm"})

    out = {"updated_at": datetime.now(timezone.utc).isoformat(),
           "n_items": len(items), "symbols": symbols, "clusters": clusters,
           "active_events": active_events}

    # 6) write the rich contract + the LEGACY veto file (zero changes for multi_trader)
    _atomic_write(SIGNALS, out)
    _atomic_write(EWMA_FILE, ewma)
    _atomic_write(BLOCKED, {"blocked_symbols": sorted(blocked),
                            "active_events": active_events,
                            "updated_at": out["updated_at"]})
    return out


def news_vote(symbol: str):
    """Helper chart_read imports: returns (news_dir, injected_weight, veto, reason) for a symbol,
    or (0, 0.0, False, '') if no fresh news. injected_weight = BASE × tier × conviction."""
    try:
        d = json.loads(SIGNALS.read_text(encoding="utf-8"))
        if (_now() - _parse_ts(d.get("updated_at")) ) > 1800:   # stale > 30min → ignore
            return 0, 0.0, False, ""
        s = (d.get("symbols", {}) or {}).get(symbol)
        if not s:
            return 0, 0.0, False, ""
        # blend instant dir with long-term bias direction (bias only nudges, never alone)
        nd = int(s.get("news_dir", 0))
        if nd == 0 and abs(float(s.get("news_bias", 0))) >= 0.25:
            nd = 1 if s["news_bias"] > 0 else -1
        w = BASE_NEWS_WEIGHT * TIER_WEIGHT.get(int(s.get("tier", 3)), 1.0) * float(s.get("conviction", 0.0))
        return nd, round(w, 3), bool(s.get("veto", False)), str(s.get("reason", ""))
    except Exception:
        return 0, 0.0, False, ""


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--loop", action="store_true"); a = ap.parse_args(argv)
    while True:
        try:
            o = run_once()
            hot = [s for s, v in o["symbols"].items() if v["hot"]]
            veto = [s for s, v in o["symbols"].items() if v["veto"]]
            print(f"[NEWS] {o['n_items']} عنصر · {len(o['symbols'])} رمز · veto {veto or '—'} · hot {hot or '—'} "
                  f"· ذهب-bias {o['clusters']['gold_bias']:+.2f} USD-bias {o['clusters']['USD_bias']:+.2f}", flush=True)
        except Exception as e:
            print(f"[NEWS] err {e}", flush=True)
        if not a.loop:
            break
        time.sleep(TICK_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
