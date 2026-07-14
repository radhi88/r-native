"""agents/smc_narrator.py — generate Arabic SMC narratives for trades.

For every fresh entry the brain emits, this agent composes a short Arabic
explanation referencing the SMC structure that justified the trade (OB
touch, FVG fill, liquidity sweep, IDM swept, BOS/CHoCH direction). The
narrative is attached to the brain JSON `drawings` array as a label
anchored at the entry candle so it appears directly on the MT5 chart.

Pipeline:
   1. read latest /api/r/trade_gate verdict (has side, entry, smc_anchors)
   2. read snap.h1.smc (live SMC dict)
   3. build a hypothesis sentence
   4. (optional) refine via LLM if backend available
   5. validate that referenced prices match snap (hallucination guard)
   6. emit insight + write narrative dict to brain drawings file
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from r_native.agents.base import Agent, emit_insight


# Where the brain writes its narrative drawings (a tiny JSON file the EA
# reads alongside brain.json — keeps the narrator decoupled from the
# main brain pipeline).
NARRATIVE_PATH = Path(r"C:\Users\Radhi\MT5\data\r_native\smc_narratives.json")


class SMCNarrator(Agent):
    name = "smc_narrator"
    description = "Generates Arabic SMC narratives for entries and renders them on MT5"
    interval_seconds = 30      # check every 30s
    default_enabled = True

    BRAIN_API     = "http://127.0.0.1:5055/api/r/trade_gate"
    SNAPSHOT_API  = "http://127.0.0.1:5055/api/snapshot"
    MAX_RECENT    = 20         # keep last 20 narratives on disk
    LLM_TIMEOUT_S = 12
    USE_LLM       = True       # try LLM refinement, fall back to template
    _last_seen_id = ""         # avoid re-narrating the same verdict

    # ────────────────────────────────────────────────────────────
    def tick(self):
        gate    = self._fetch_json(self.BRAIN_API)
        if not gate or gate.get("verdict") != "GO": return
        side    = (gate.get("side") or "").upper()
        entry   = gate.get("entry") or 0
        if side not in ("BUY", "SELL") or not entry: return

        # Dedupe — only narrate each verdict once
        ver_id = f"{side}-{entry:.5f}-{gate.get('reason_ar','')[:30]}"
        if ver_id == self._last_seen_id: return
        self._last_seen_id = ver_id

        sym  = gate.get("symbol") or "XAUUSDm"
        snap = self._fetch_json(f"{self.SNAPSHOT_API}?symbol={sym}") or {}
        smc  = (((snap.get("multi_tf") or {}).get("tfs") or {}).get("H1")
                or {}).get("smc") or {}

        # 1. Template narrative (always works, no LLM dep)
        headline, rationale, risk = self._template_narrative(side, entry, smc, gate)

        # 2. Optional LLM polish
        if self.USE_LLM:
            polished = self._llm_polish(side, entry, smc, gate, headline, rationale)
            if polished:
                headline, rationale, risk = polished

        # 3. Hallucination guard — every price mentioned must exist in snap
        if not self._validate_prices(rationale + " " + risk, snap):
            emit_insight(self.name, "WARN",
                f"narrative referenced an off-chart price; falling back to template",
                action="smc_narr_hallucinated")
            headline, rationale, risk = self._template_narrative(side, entry, smc, gate)

        # 4. Persist + announce
        self._save_narrative(sym, side, entry, headline, rationale, risk)
        emit_insight(self.name, "ACT",
            f"📖 {sym} {side}@{entry:.5f} — {headline}",
            data={"headline": headline, "rationale": rationale, "risk": risk,
                  "symbol": sym, "side": side, "entry": entry},
            action="smc_narrative_emitted")

    # ── Template narrative (deterministic, always coherent) ─────
    def _template_narrative(self, side: str, entry: float, smc: dict,
                            gate: dict) -> tuple[str, str, str]:
        parts: list[str] = []
        if side == "BUY":
            ob = smc.get("fresh_ob_below")
            if ob: parts.append(f"ارتداد من OB صاعد عند [{ob['bottom']:.5f}-{ob['top']:.5f}]")
            for fvg in smc.get("fresh_fvg_bull", []) or []:
                parts.append(f"إغلاق FVG صاعد عند [{fvg['bottom']:.5f}-{fvg['top']:.5f}]")
                break
        else:
            ob = smc.get("fresh_ob_above")
            if ob: parts.append(f"رفض من OB هابط عند [{ob['bottom']:.5f}-{ob['top']:.5f}]")
            for fvg in smc.get("fresh_fvg_bear", []) or []:
                parts.append(f"إغلاق FVG هابط عند [{fvg['bottom']:.5f}-{fvg['top']:.5f}]")
                break

        bos = smc.get("last_bos")
        if bos:
            d = "صاعد" if bos["direction"] == "UP" else "هابط"
            parts.append(f"BOS {d} عند {bos['level']:.5f} (عمره {bos.get('age_bars','?')} شمعة)")
        ch = smc.get("last_choch")
        if ch:
            d = "صاعد" if ch["direction"] == "UP" else "هابط"
            parts.append(f"CHoCH {d} حديث عند {ch['level']:.5f}")
        sw = smc.get("recent_liq_sweep")
        if sw and sw.get("reclaim"):
            parts.append(f"كسر سيولة {sw['side']} مع إعادة إغلاق فوق المستوى")
        idm = smc.get("idm_status")
        if idm and idm.get("swept"):
            parts.append(f"تم اصطياد الإحضار IDM عند {idm['level']:.5f}")

        side_ar = "شراء" if side == "BUY" else "بيع"
        headline = f"{side_ar} مبني على " + (" + ".join(parts[:2]) if parts else "بنية SMC")
        if not parts:
            rationale = f"دخول {side_ar} عند {entry:.5f} — بنية H1 محايدة، الاعتماد على إشارة الجينوم."
        else:
            rationale = f"دخول {side_ar} عند {entry:.5f}. " + "؛ ".join(parts) + "."
        sl  = gate.get("sl") or 0
        tp  = gate.get("far_tp") or gate.get("tp") or 0
        risk = (f"وقف الخسارة {sl:.5f} وهدف الربح {tp:.5f}." if sl and tp
                else "إدارة المخاطر حسب إعدادات الجينوم.")
        return headline, rationale, risk

    # ── LLM polish (optional) ───────────────────────────────────
    def _llm_polish(self, side, entry, smc, gate, headline_seed,
                    rationale_seed) -> Optional[tuple[str, str, str]]:
        try:
            from r_native.agents.llm import ask, extract_json
        except Exception:
            return None
        sys_prompt = (
            "أنت مساعد تداول. اشرح الصفقة بثلاث جمل عربية مختصرة بأسلوب SMC/ICT. "
            "لا تخترع أرقاماً غير موجودة في الـSMC المعطى. أعد JSON فقط بالحقول: "
            "headline_ar, rationale_ar, risk_ar."
        )
        user = json.dumps({
            "side": side, "entry": round(entry, 5),
            "sl": gate.get("sl"), "tp": gate.get("far_tp") or gate.get("tp"),
            "smc": smc,
            "draft_headline": headline_seed,
            "draft_rationale": rationale_seed,
        }, ensure_ascii=False)
        out = ask(prompt=user, system=sys_prompt,
                  preferred_backend="auto", temperature=0.2)
        if not out.get("ok"): return None
        parsed = extract_json(out.get("text") or "")
        if not parsed: return None
        h = parsed.get("headline_ar")
        r = parsed.get("rationale_ar")
        risk = parsed.get("risk_ar")
        if h and r and risk:
            return str(h), str(r), str(risk)
        return None

    # ── Hallucination guard ─────────────────────────────────────
    def _validate_prices(self, text: str, snap: dict) -> bool:
        """Extract every float-looking price from the text and verify each
        lies within ±0.5% of *some* level the snapshot actually knows
        about. Wide tolerance so we don't false-positive on rounding."""
        import re
        prices_in_text = [float(m) for m in re.findall(r"\d{2,5}\.\d{2,6}", text)]
        if not prices_in_text: return True
        known: list[float] = []
        for tf in (((snap.get("multi_tf") or {}).get("tfs") or {}).values()):
            if not isinstance(tf, dict): continue
            for k in ("current", "swing_high", "swing_low"):
                v = tf.get(k)
                if isinstance(v, (int, float)): known.append(float(v))
            smc = tf.get("smc") or {}
            for k in ("fresh_ob_above", "fresh_ob_below"):
                ob = smc.get(k)
                if ob:
                    known.append(ob.get("top", 0))
                    known.append(ob.get("bottom", 0))
            for k in ("last_bos", "last_choch", "recent_liq_sweep", "idm_status"):
                d = smc.get(k)
                if d and "level" in d: known.append(d["level"])
            for k in ("liq_above", "liq_below"):
                for px in smc.get(k, []) or []:
                    known.append(px)
            for k in ("fresh_fvg_bull", "fresh_fvg_bear"):
                for f in smc.get(k, []) or []:
                    known.append(f.get("top", 0))
                    known.append(f.get("bottom", 0))
        known = [k for k in known if k > 0]
        if not known: return True   # nothing to compare against — let it pass
        for p in prices_in_text:
            ok = any(abs(p - k) / max(k, 1e-9) <= 0.005 for k in known)
            if not ok: return False
        return True

    # ── I/O ─────────────────────────────────────────────────────
    def _save_narrative(self, sym: str, side: str, entry: float,
                        headline: str, rationale: str, risk: str) -> None:
        try:
            NARRATIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            arr = []
            if NARRATIVE_PATH.exists():
                try: arr = json.loads(NARRATIVE_PATH.read_text(encoding="utf-8"))
                except Exception: arr = []
            arr.append({
                "ts":       datetime.now(timezone.utc).isoformat(),
                "symbol":   sym,
                "side":     side,
                "entry":    entry,
                "headline_ar":  headline,
                "rationale_ar": rationale,
                "risk_ar":      risk,
            })
            NARRATIVE_PATH.write_text(
                json.dumps(arr[-self.MAX_RECENT:], ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            print(f"[smc_narrator] save err: {e}", flush=True)

    @staticmethod
    def _fetch_json(url: str, timeout: int = 5) -> Optional[dict]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None
