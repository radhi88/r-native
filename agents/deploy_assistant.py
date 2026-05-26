"""agents/deploy_assistant.py — auto-deploy qualified new genomes as competitors.

Closes the loop between BREEDING and LIVE TESTING. The LLM strategist
breeds new genomes (now unblocked since cycle 8's alive-only pipeline
fix) but they sit in HoF unused until a human adds them to a symbol's
competitors list. This agent auto-promotes them as soon as they qualify.

Logic (every 30 min):
  For each genome in HoF that is:
    • not killed
    • not pinned  (pinned = explicit user choice, hands off)
    • score >= MIN_DEPLOY_SCORE  (default 30 — same gate as breed-success)
    • has a target `symbol` field
    • NOT already a primary or competitor on ANY symbol
    • born within DEPLOY_AGE_WINDOW_HOURS  (give fresh blood priority)
  →
  add it to that symbol's competitors list (skip if already at 3 max)
  record provenance in cfg["deploy_history"]
  emit ACT insight

Throttle: max ONE deployment per tick (so a sudden HoF flood doesn't
deploy 10 genomes at once → exposure_guard chaos). Bred genomes will
come online one per 30-min cycle, plenty of time to evaluate each.

Cooperates with auto_rotator: this agent puts new blood INTO the
competitor pool. auto_rotator decides which competitor becomes primary
based on LIVE pnl. Together they form: breed → deploy as competitor →
race head-to-head → promote winner.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from r_native.agents.base import Agent, emit_insight


SYMBOL_CFG_DIR = Path(r"C:\Users\Radhi\MT5\data\r_native\symbol_configs")


class DeployAssistant(Agent):
    name = "deploy_assistant"
    description = "Auto-promotes qualified new genomes into symbol competitor slots"
    interval_seconds = 1800       # 30 min
    default_enabled = True

    MIN_DEPLOY_SCORE         = 30.0
    MAX_COMPETITORS_PER_SYM  = 3
    DEPLOY_AGE_WINDOW_HOURS  = 24    # only deploy genomes < 24h old
    MAX_DEPLOYS_PER_TICK     = 1     # one at a time, evaluate before next

    def _load_all_configs(self) -> dict:
        """Return {symbol: cfg_dict}."""
        out = {}
        if not SYMBOL_CFG_DIR.exists(): return out
        for p in SYMBOL_CFG_DIR.glob("*.json"):
            try:
                out[p.stem] = (p, json.loads(p.read_text(encoding="utf-8")))
            except Exception: continue
        return out

    def _genome_is_already_deployed(self, gid: str, all_configs: dict) -> bool:
        """Check primary slot + competitors on every symbol."""
        for _path, cfg in all_configs.values():
            primary = (cfg.get("deployed_genome") or {}).get("id")
            if primary == gid: return True
            for c in cfg.get("competitors") or []:
                cid = c.get("id") if isinstance(c, dict) else c
                if cid == gid: return True
        return False

    def _save_config_atomically(self, path: Path, cfg: dict) -> bool:
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            tmp.replace(path)
            return True
        except Exception:
            return False

    def tick(self):
        try:
            from r_native.hall_of_fame import load_index
            hof = load_index() or {}
        except Exception: return

        all_configs = self._load_all_configs()
        if not all_configs:
            return

        now = datetime.now(timezone.utc)
        candidates = []
        for gid, entry in hof.items():
            if entry.get("killed"): continue
            if entry.get("pinned"): continue
            score = float(entry.get("score") or 0)
            if score < self.MIN_DEPLOY_SCORE: continue
            sym = entry.get("symbol")
            if not sym or sym == "?": continue
            if sym not in all_configs: continue   # symbol not currently deployed

            # Age check — only deploy fresh genomes
            born_at = entry.get("born_at", "")
            try:
                born = datetime.fromisoformat(born_at.replace("Z", "+00:00"))
                age_h = (now - born).total_seconds() / 3600
            except Exception:
                age_h = 999
            if age_h > self.DEPLOY_AGE_WINDOW_HOURS: continue

            # Already deployed anywhere?
            if self._genome_is_already_deployed(gid, all_configs):
                continue

            # Symbol must have room for another competitor
            _path, cfg = all_configs[sym]
            comps = cfg.get("competitors") or []
            if len(comps) >= self.MAX_COMPETITORS_PER_SYM: continue

            candidates.append({
                "id":      gid,
                "score":   score,
                "symbol":  sym,
                "age_h":   round(age_h, 1),
                "nickname": (entry.get("nickname") or gid)[:35],
                "birth":   entry.get("birth_method", "?"),
                "parents": entry.get("parents") or [],
            })

        if not candidates:
            return

        # Highest score first, take MAX_DEPLOYS_PER_TICK
        candidates.sort(key=lambda c: -c["score"])
        deployed = []
        for cand in candidates[:self.MAX_DEPLOYS_PER_TICK]:
            sym = cand["symbol"]
            path, cfg = all_configs[sym]
            comps = list(cfg.get("competitors") or [])
            comps.append({
                "id":            cand["id"],
                "score":         cand["score"],
                "deployed_at":   datetime.now(timezone.utc).isoformat(),
                "deployed_by":   self.name,
                "deploy_reason": f"score {cand['score']:.1f} "
                                  f"({cand['birth']}, age {cand['age_h']}h)",
            })
            cfg["competitors"] = comps

            # Record provenance
            hist = cfg.get("deploy_history") or []
            hist.append({
                "at":         datetime.now(timezone.utc).isoformat(),
                "added":      cand["id"],
                "score":      cand["score"],
                "birth":      cand["birth"],
                "parents":    cand["parents"],
                "by":         self.name,
            })
            cfg["deploy_history"] = hist[-20:]

            if self._save_config_atomically(path, cfg):
                deployed.append(cand)
                emit_insight(self.name, "ACT",
                    f"🆕 deployed {cand['nickname']} ({cand['id']}, "
                    f"score {cand['score']:.1f}) as competitor on {sym} — "
                    f"now {len(comps)}/{self.MAX_COMPETITORS_PER_SYM} slots used",
                    data={"deployed": cand, "comp_count": len(comps)},
                    action="genome_deployed")
            else:
                emit_insight(self.name, "WARN",
                    f"failed to write config for {sym}")
