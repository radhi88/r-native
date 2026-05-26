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

    # Eviction thresholds (cycle 11 fix): when slots are full but a strictly
    # better candidate appears, evict the weakest competitor instead of
    # silently dropping the new genome. Without this, a single score-32
    # competitor squatting an idle slot blocks a score-50 newcomer forever.
    EVICT_MIN_SCORE_EDGE     = 10.0   # candidate must beat lowest by ≥10
    EVICT_BIG_SCORE_EDGE     = 15.0   # ≥15 = evict on idle+age (clear upgrade)
    EVICT_MIN_IDLE_HOURS     = 2.0    # standard evict: idle 2h+ AND 0 live trades
    EVICT_BIG_EDGE_MIN_AGE   = 0.5    # even BIG_EDGE waits 30min so new blood
                                       # gets a chance to fire its first trade
                                       # before being shuffled out by next-best
    # Elite fast-track (cycle 20): a candidate scoring ≥ELITE_SCORE skips
    # all age waits — the gene pool has earned that this is high-quality
    # blood worth deploying immediately. Auto_rotator then races it live.
    ELITE_SCORE              = 70.0   # auto-pin threshold = elite tier

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

            # Symbol slot check — if room, just add. If full, see if we can evict.
            _path, cfg = all_configs[sym]
            comps = cfg.get("competitors") or []
            evict_target = None
            if len(comps) >= self.MAX_COMPETITORS_PER_SYM:
                # Find evictable competitor (lowest score with eviction edge)
                ranked = []
                for c in comps:
                    cid = c.get("id") if isinstance(c, dict) else c
                    centry = hof.get(cid) or {}
                    cscore = float(centry.get("score") or 0)
                    cpinned = bool(centry.get("pinned"))
                    clive = int(centry.get("live_trades") or 0)
                    # Age in this slot (from deploy_history or deployed_at)
                    deployed_at = None
                    if isinstance(c, dict):
                        deployed_at = c.get("deployed_at")
                    slot_age_h = 0.0
                    if deployed_at:
                        try:
                            dt = datetime.fromisoformat(deployed_at.replace("Z","+00:00"))
                            slot_age_h = (now - dt).total_seconds() / 3600
                        except Exception: pass
                    ranked.append({
                        "id": cid, "score": cscore, "pinned": cpinned,
                        "live": clive, "slot_age_h": slot_age_h,
                    })
                # Lowest score that ISN'T pinned
                non_pinned = [r for r in ranked if not r["pinned"]]
                if not non_pinned: continue
                weakest = min(non_pinned, key=lambda r: r["score"])
                edge = score - weakest["score"]
                # Eviction triggers (either-or):
                #   BIG_EDGE alone (score gap is huge — always evict)
                #   OR (MIN_EDGE AND idle 2h+ with no live trades)
                # ELITE: candidate score ≥70 — skip ALL age waits, deploy now
                if score >= self.ELITE_SCORE and edge > 0:
                    evict_target = weakest
                # BIG_EDGE: clear upgrade, but still give the squatter at
                # least EVICT_BIG_EDGE_MIN_AGE (default 30 min) to fire its
                # first trade. Otherwise newly-deployed genomes never get
                # to prove themselves before being shuffled out.
                elif (edge >= self.EVICT_BIG_SCORE_EDGE
                        and weakest["slot_age_h"] >= self.EVICT_BIG_EDGE_MIN_AGE):
                    evict_target = weakest
                elif (edge >= self.EVICT_MIN_SCORE_EDGE
                      and weakest["live"] == 0
                      and weakest["slot_age_h"] >= self.EVICT_MIN_IDLE_HOURS):
                    evict_target = weakest
                else:
                    continue   # no room, can't evict — skip silently

            candidates.append({
                "id":      gid,
                "score":   score,
                "symbol":  sym,
                "age_h":   round(age_h, 1),
                "nickname": (entry.get("nickname") or gid)[:35],
                "birth":   entry.get("birth_method", "?"),
                "parents": entry.get("parents") or [],
                "evict":   evict_target,
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
            # If this candidate triggered an eviction, drop the evictee first
            evict_note = ""
            if cand.get("evict"):
                evictee_id = cand["evict"]["id"]
                comps = [c for c in comps
                          if (c.get("id") if isinstance(c, dict) else c) != evictee_id]
                evict_note = (f" (evicted {evictee_id} score "
                              f"{cand['evict']['score']:.1f}, idle "
                              f"{cand['evict']['slot_age_h']:.1f}h)")
            comps.append({
                "id":            cand["id"],
                "score":         cand["score"],
                "deployed_at":   datetime.now(timezone.utc).isoformat(),
                "deployed_by":   self.name,
                "deploy_reason": f"score {cand['score']:.1f} "
                                  f"({cand['birth']}, age {cand['age_h']}h)"
                                  + evict_note,
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
                evict_str = ""
                if cand.get("evict"):
                    evict_str = f" · ⏏ evicted {cand['evict']['id']} (score {cand['evict']['score']:.1f})"
                emit_insight(self.name, "ACT",
                    f"🆕 deployed {cand['nickname']} ({cand['id']}, "
                    f"score {cand['score']:.1f}) as competitor on {sym} — "
                    f"now {len(comps)}/{self.MAX_COMPETITORS_PER_SYM} slots used"
                    + evict_str,
                    data={"deployed": cand, "comp_count": len(comps)},
                    action="genome_deployed")
            else:
                emit_insight(self.name, "WARN",
                    f"failed to write config for {sym}")
