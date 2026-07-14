"""
PlutoBrain Swarm — Worker Library
=================================
Deterministic static-analysis workers. Each takes a Context and returns a dict:

    {"summary": "<one line for the dashboard>", "findings": <int>, "artifact": "<file>"}

No LLM calls. No network. Pure stdlib. These are the roles from the spec that are
actually computable — file mapping, dependency trees, duplicate/hardcode/magic
hunting, health checks. They write JSON artifacts to swarm_state/artifacts/.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Context: shared config passed to every worker
# ---------------------------------------------------------------------------
@dataclass
class Context:
    root: Path                 # MT5 project root
    artifacts: Path            # swarm_state/artifacts
    # dirs we never scan (archives, deps, build junk)
    excludes: tuple = (
        "archive", "archive_root", "_archive", "_trash", "ea_backups",
        "patch_backups", "node_modules", "__pycache__", "dist", "dist_new",
        "build", "vendor", ".git", "capital_brain_backups", "backup",
    )

    _cache: list = field(default=None, repr=False)

    def is_excluded(self, p: Path) -> bool:
        parts = {x.lower() for x in p.parts}
        return any(e in parts for e in self.excludes)

    def mql_files(self) -> list[Path]:
        """Walk once, prune excluded dirs in-place, cache for the cycle.
        os.walk + dirs[:] pruning avoids descending into node_modules/.git/archives."""
        if self._cache is not None:
            return self._cache
        exc = set(self.excludes)
        out = []
        for dirpath, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d.lower() not in exc]  # prune before descending
            for fn in files:
                if fn.endswith((".mq5", ".mqh")):
                    out.append(Path(dirpath) / fn)
        out.sort()
        self._cache = out
        return out

    def write(self, name: str, data) -> str:
        path = self.artifacts / name
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return name


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _rel(ctx: Context, p: Path) -> str:
    try:
        return str(p.relative_to(ctx.root))
    except ValueError:
        return str(p)


# ===========================================================================
# CLUSTER ALPHA workers
# ===========================================================================
def file_mapper(ctx: Context) -> dict:
    """A-01: inventory every .mq5/.mqh — size, lines, mtime."""
    files = ctx.mql_files()
    data = []
    for p in files:
        text = _read(p)
        data.append({
            "path": _rel(ctx, p),
            "ext": p.suffix,
            "bytes": p.stat().st_size,
            "lines": text.count("\n") + 1 if text else 0,
            "mtime": p.stat().st_mtime,
        })
    art = ctx.write("file_map.json", {"generated": time.time(), "files": data})
    return {"summary": f"mapped {len(data)} MQL files", "findings": len(data), "artifact": art}


def code_archaeologist(ctx: Context) -> dict:
    """A-02: extract OrderSend/trade-entry logic signature per EA."""
    pat_buy = re.compile(r"\bORDER_TYPE_BUY\b|\bOP_BUY\b|\.Buy\(", re.I)
    pat_sell = re.compile(r"\bORDER_TYPE_SELL\b|\bOP_SELL\b|\.Sell\(", re.I)
    pat_send = re.compile(r"OrderSend|trade\.(Buy|Sell|PositionOpen)", re.I)
    out = []
    for p in ctx.mql_files():
        if p.suffix != ".mq5":
            continue
        t = _read(p)
        out.append({
            "path": _rel(ctx, p),
            "has_buy": bool(pat_buy.search(t)),
            "has_sell": bool(pat_sell.search(t)),
            "send_calls": len(pat_send.findall(t)),
        })
    art = ctx.write("code_archaeology.json", {"generated": time.time(), "eas": out})
    return {"summary": f"profiled {len(out)} EAs", "findings": len(out), "artifact": art}


def dependency_tracker(ctx: Context) -> dict:
    """A-03: build #include tree. Only QUOTE-style includes ("x.mqh") are local and
    resolvable within the repo; ANGLE-style (<Trade\\Trade.mqh>, <JAson.mqh>) are
    system/library includes resolved from MQL5/Include and are tracked, not flagged."""
    # group 1 = bracket char ('"' or '<'), group 2 = path
    inc = re.compile(r'^\s*#include\s+(["<])([^">]+)[">]', re.M)
    tree, missing, libs = {}, [], set()
    names = {p.name.lower(): _rel(ctx, p) for p in ctx.mql_files()}
    for p in ctx.mql_files():
        deps = [m[1] for m in inc.findall(_read(p))]
        tree[_rel(ctx, p)] = deps
        for bracket, d in inc.findall(_read(p)):
            if bracket == "<":                       # system/library include — not local
                libs.add(d)
                continue
            base = Path(d.replace("\\", "/")).name.lower()
            if base not in names:
                missing.append({"file": _rel(ctx, p), "include": d})
    art = ctx.write("dependency_tree.json", {"generated": time.time(), "tree": tree,
                    "missing_local": missing, "library_includes": sorted(libs)})
    return {"summary": f"{len(tree)} files, {len(missing)} unresolved LOCAL includes "
                       f"({len(libs)} library includes ok)",
            "findings": len(missing), "artifact": art}


def conflict_detector(ctx: Context) -> dict:
    """A-04: heuristic — EAs that trade BOTH directions OR share a magic+symbol."""
    pat_sym = re.compile(r'Symbol\(\)|"([A-Z]{3,6}m?)"')
    conflicts = []
    arch = json.loads(_read(ctx.artifacts / "code_archaeology.json") or "{}").get("eas", [])
    for ea in arch:
        if ea.get("has_buy") and ea.get("has_sell") and ea.get("send_calls", 0) > 2:
            conflicts.append({"path": ea["path"], "kind": "bidirectional",
                              "note": "trades both directions — verify not a hedge/grid conflict"})
    art = ctx.write("conflicts.json", {"generated": time.time(), "conflicts": conflicts})
    return {"summary": f"{len(conflicts)} bidirectional EAs flagged", "findings": len(conflicts), "artifact": art}


def _functions(text: str) -> list[tuple[str, str]]:
    """Return (name, normalized_body) for top-level-ish function defs."""
    pat = re.compile(r"\b(?:void|int|double|bool|string|datetime|long|ulong|color)\s+"
                     r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)
    out = []
    for m in pat.finditer(text):
        name = m.group(1)
        # grab a rough body slice for similarity (first 400 chars after brace)
        body = text[m.end():m.end() + 400]
        norm = re.sub(r"\s+", " ", body).strip()
        out.append((name, norm))
    return out


# MQL5 event handlers every EA legitimately (re)defines — not duplication.
MQL_LIFECYCLE = {
    "OnInit", "OnDeinit", "OnTick", "OnTimer", "OnTrade", "OnTradeTransaction",
    "OnChartEvent", "OnTester", "OnTesterInit", "OnTesterDeinit", "OnTesterPass",
    "OnBookEvent", "OnCalculate", "OnStart",
}


def _full_functions(text: str):
    """Yield (name, full_source) with complete brace-matched bodies (not a slice),
    so duplicate detection compares whole functions — no prefix false positives."""
    sig = re.compile(r"\b(?:void|int|double|bool|string|datetime|long|ulong|color)\s+"
                     r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)
    for m in sig.finditer(text):
        i = m.end() - 1
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group(1), text[m.start():j + 1]


def duplicate_hunter(ctx: Context) -> dict:
    """A-05: real copy-paste detection. MQL lifecycle handlers excluded; matching is
    on FULL brace-matched bodies (byte-exact), so a shared prefix is not a false hit.
    The actionable signal is an identical whole function living in >1 distinct file."""
    import hashlib
    by_name = defaultdict(list)
    by_body = defaultdict(list)
    for p in ctx.mql_files():
        for name, body in _full_functions(_read(p)):
            if name in MQL_LIFECYCLE:
                continue
            rel = _rel(ctx, p)
            by_name[name].append(rel)
            if len(body) > 120:                          # ignore one-liners
                h = hashlib.md5(body.encode("utf-8", "replace")).hexdigest()
                by_body[h].append(f"{rel}::{name}")
    dup_names = {n: sorted(set(fs)) for n, fs in by_name.items() if len(set(fs)) > 1}
    dup_bodies = [sorted(set(locs)) for locs in by_body.values()
                  if len({loc.split("::")[0] for loc in locs}) > 1]
    art = ctx.write("duplicates.json", {"generated": time.time(),
                    "duplicate_bodies": dup_bodies, "duplicate_names": dup_names})
    return {"summary": f"{len(dup_bodies)} byte-exact cross-file dup functions, "
                       f"{len(dup_names)} shared names",
            "findings": len(dup_bodies), "artifact": art}


def standardizer(ctx: Context) -> dict:
    """A-06: check PB_ prefix convention on input/global vars (advisory)."""
    pat = re.compile(r"^\s*(?:input|extern)\s+\w+\s+([A-Za-z_]\w*)", re.M)
    off = []
    for p in ctx.mql_files():
        for m in pat.finditer(_read(p)):
            v = m.group(1)
            if not v.startswith(("PB_", "Inp", "g_")):
                off.append({"file": _rel(ctx, p), "var": v})
    art = ctx.write("naming.json", {"generated": time.time(), "non_standard_inputs": off[:500]})
    return {"summary": f"{len(off)} inputs lack PB_/Inp/g_ prefix", "findings": len(off), "artifact": art}


def header_auditor(ctx: Context) -> dict:
    """A-07: flag files missing a top header comment block."""
    missing = []
    for p in ctx.mql_files():
        head = _read(p)[:300]
        if "//+--" not in head and "/*" not in head:
            missing.append(_rel(ctx, p))
    art = ctx.write("headers.json", {"generated": time.time(), "missing_header": missing})
    return {"summary": f"{len(missing)} files missing header block", "findings": len(missing), "artifact": art}


def config_extractor(ctx: Context) -> dict:
    """A-10: list all input parameters per EA (the surface to centralize)."""
    pat = re.compile(r"^\s*input\s+(\w+)\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", re.M)
    out = {}
    total = 0
    for p in ctx.mql_files():
        rows = [{"type": t, "name": n, "default": d.strip()} for t, n, d in pat.findall(_read(p))]
        if rows:
            out[_rel(ctx, p)] = rows
            total += len(rows)
    art = ctx.write("inputs.json", {"generated": time.time(), "by_file": out})
    return {"summary": f"{total} input params across {len(out)} EAs", "findings": total, "artifact": art}


def backup_guardian(ctx: Context) -> dict:
    """A-12: confirm git is clean-ish / count uncommitted MQL changes."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=ctx.root,
                           capture_output=True, text=True, timeout=20)
        dirty = [l for l in r.stdout.splitlines() if l.strip().endswith((".mq5", ".mqh"))]
    except Exception as e:
        dirty = []
        return {"summary": f"git unavailable: {e}", "findings": 0, "artifact": ""}
    art = ctx.write("backup_status.json", {"generated": time.time(), "uncommitted_mql": dirty})
    return {"summary": f"{len(dirty)} uncommitted MQL files", "findings": len(dirty), "artifact": art}


def path_optimizer(ctx: Context) -> dict:
    """A-13: report EA scatter — how many distinct dirs hold .mq5 files."""
    dirs = defaultdict(int)
    for p in ctx.mql_files():
        if p.suffix == ".mq5":
            dirs[_rel(ctx, p.parent)] += 1
    art = ctx.write("ea_locations.json", {"generated": time.time(), "ea_dirs": dict(dirs)})
    return {"summary": f"EAs scattered across {len(dirs)} dirs", "findings": len(dirs), "artifact": art}


def _fnames(text: str) -> set:
    return {n for n, _ in _functions(text)}


def version_clusterer(ctx: Context) -> dict:
    """A-14: cluster version-families AND classify each so the KPI is actionable:
      identical = byte-same copy (safe to dedup)
      linear    = newer is a superset (safe to archive older)
      divergent = each version holds unique functions (MERGE needed — never auto-cut)"""
    import hashlib
    allow = {}
    try:
        allow = json.loads((Path(__file__).parent / "version_allowlist.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    allow_fams = {k for k in allow if not k.startswith("_")}
    groups = defaultdict(list)
    for p in ctx.mql_files():
        if p.suffix != ".mq5":
            continue
        stem = re.sub(r"[_\- ]?v?\d+([._]\d+)*", "", p.stem, flags=re.I).strip("_- ")
        groups[stem.lower()].append(p)
    families = {}
    actionable = 0
    for fam, paths in groups.items():
        if len(paths) < 2:
            continue
        paths = sorted(paths)
        if fam in allow_fams:                       # intentional family — not drift
            families[fam] = {"files": [_rel(ctx, p) for p in paths],
                             "kind": "intentional", "why": allow.get(fam, ""), "lost_in_newest": {}}
            continue
        texts = {p: _read(p) for p in paths}
        hashes = {p: hashlib.md5(t.encode("utf-8", "replace")).hexdigest() for p, t in texts.items()}
        # identical if all the same hash
        if len(set(hashes.values())) == 1:
            kind = "identical"
        else:
            # newest by version number / name order = last; is it a superset?
            newest = paths[-1]
            new_fns = _fnames(texts[newest])
            lost = {}
            for p in paths[:-1]:
                missing = _fnames(texts[p]) - new_fns
                if missing:
                    lost[_rel(ctx, p)] = sorted(missing)
            kind = "linear" if not lost else "divergent"
        if kind in ("identical", "linear"):
            actionable += 1
        families[fam] = {"files": [_rel(ctx, p) for p in paths], "kind": kind,
                         "lost_in_newest": (lost if kind == "divergent" else {})}
    art = ctx.write("version_clusters.json", {"generated": time.time(),
                    "clusters": {k: v["files"] for k, v in families.items()},
                    "classified": families, "actionable": actionable})
    div = sum(1 for v in families.values() if v["kind"] == "divergent")
    return {"summary": f"{len(families)} families: {actionable} safe-to-consolidate, {div} divergent (need merge)",
            "findings": actionable, "artifact": art}


# ===========================================================================
# CLUSTER BETA workers
# ===========================================================================
def session_auditor(ctx: Context) -> dict:
    """B-06: which EAs reference hour/session gating (the real edge: night discipline)."""
    pat = re.compile(r"TimeHour|Hour\(\)|StartHour|EndHour|session|TimeCurrent", re.I)
    has, missing = [], []
    for p in ctx.mql_files():
        if p.suffix != ".mq5":
            continue
        (has if pat.search(_read(p)) else missing).append(_rel(ctx, p))
    art = ctx.write("session_gating.json", {"generated": time.time(),
                    "has_time_logic": has, "no_time_logic": missing})
    return {"summary": f"{len(missing)} EAs with NO time/session gating", "findings": len(missing), "artifact": art}


def spread_auditor(ctx: Context) -> dict:
    """B-12: which EAs check spread before entry."""
    pat = re.compile(r"SYMBOL_SPREAD|Ask\s*-\s*Bid|spread", re.I)
    missing = [_rel(ctx, p) for p in ctx.mql_files()
               if p.suffix == ".mq5" and not pat.search(_read(p))]
    art = ctx.write("spread_checks.json", {"generated": time.time(), "no_spread_filter": missing})
    return {"summary": f"{len(missing)} EAs with no spread filter", "findings": len(missing), "artifact": art}


def magic_manager(ctx: Context) -> dict:
    """B-13: extract magic numbers, detect collisions across EAs.
    Magics in magic_allowlist.json are SHARED by design (e.g. a strategy family
    tracked by one dashboard magic) and are reported separately, not as collisions."""
    allow = {}
    try:
        allow = json.loads((Path(__file__).parent / "magic_allowlist.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    allow_keys = {k for k in allow if not k.startswith("_")}
    pat = re.compile(r"(?:Magic\w*|MAGIC\w*)\s*=\s*(\d{3,})|SetExpertMagicNumber\((\d{3,})\)", re.I)
    owners = defaultdict(set)
    for p in ctx.mql_files():
        if p.suffix != ".mq5":
            continue
        for a, b in pat.findall(_read(p)):
            mg = a or b
            if mg:
                owners[mg].add(_rel(ctx, p))
    shared = {m: sorted(fs) for m, fs in owners.items() if len(fs) > 1}
    collisions = {m: fs for m, fs in shared.items() if m not in allow_keys}     # real bugs
    intentional = {m: {"files": fs, "why": allow.get(m, "")}
                   for m, fs in shared.items() if m in allow_keys}               # by design
    art = ctx.write("magic_map.json", {"generated": time.time(),
                    "magics": {m: sorted(fs) for m, fs in owners.items()},
                    "collisions": collisions, "intentional_shared": intentional})
    extra = f" ({len(intentional)} intentional)" if intentional else ""
    return {"summary": f"{len(owners)} magics, {len(collisions)} COLLISIONS{extra}",
            "findings": len(collisions), "artifact": art}


def process_watcher(ctx: Context) -> dict:
    """B-14/G-06: count running python/terminal processes (resource pulse)."""
    info = {}
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=20)
        rows = [x.split('","') for x in r.stdout.splitlines() if x]
        py = sum(1 for x in rows if x and "python" in x[0].lower())
        mt = sum(1 for x in rows if x and ("terminal" in x[0].lower() or "metatrader" in x[0].lower()))
        info = {"python_procs": py, "mt5_terminals": mt, "total_procs": len(rows)}
    except Exception as e:
        info = {"error": str(e)}
    art = ctx.write("process_pulse.json", {"generated": time.time(), **info})
    return {"summary": f"py={info.get('python_procs','?')} mt5={info.get('mt5_terminals','?')}",
            "findings": info.get("python_procs", 0), "artifact": art}


def loc_profiler(ctx: Context) -> dict:
    """B-15: largest EAs by LOC (refactor hotspots)."""
    sizes = sorted(((p.stat().st_size, _read(p).count("\n") + 1, _rel(ctx, p))
                    for p in ctx.mql_files()), reverse=True)
    top = [{"path": s[2], "lines": s[1], "bytes": s[0]} for s in sizes[:10]]
    art = ctx.write("loc_hotspots.json", {"generated": time.time(), "top": top})
    return {"summary": f"largest EA: {top[0]['lines'] if top else 0} lines", "findings": len(top), "artifact": art}


# ===========================================================================
# CLUSTER GAMMA workers
# ===========================================================================
def hardcode_hunter(ctx: Context) -> dict:
    """G-07: find suspicious hardcoded lots / price-like literals."""
    lot = re.compile(r"\b(?:lot|Lots?|volume)\s*=\s*(\d+\.\d+)", re.I)
    price = re.compile(r"=\s*(\d{4,5}\.\d{1,5})\b")  # gold/btc-ish literal prices
    hits = []
    for p in ctx.mql_files():
        t = _read(p)
        for m in lot.finditer(t):
            hits.append({"file": _rel(ctx, p), "kind": "lot", "value": m.group(1)})
        for m in price.finditer(t):
            hits.append({"file": _rel(ctx, p), "kind": "price", "value": m.group(1)})
    art = ctx.write("hardcodes.json", {"generated": time.time(), "hits": hits[:500]})
    return {"summary": f"{len(hits)} hardcoded lots/prices", "findings": len(hits), "artifact": art}


def broker_assumptions(ctx: Context) -> dict:
    """G-08: flag broker-specific assumptions (3/5 digit, *10 point math, suffix 'm')."""
    pat = re.compile(r"Digits\(\)\s*==\s*[35]|Point\s*\*\s*10|\"m\"|Suffix", re.I)
    hits = [_rel(ctx, p) for p in ctx.mql_files() if pat.search(_read(p))]
    art = ctx.write("broker_assumptions.json", {"generated": time.time(), "files": hits})
    return {"summary": f"{len(hits)} files with broker-specific assumptions", "findings": len(hits), "artifact": art}


def _strip_code(s: str) -> str:
    """Remove // and /* */ comments, "string" and 'char' literals so brace/paren
    counting doesn't trip on punctuation inside them (the G-11 false-positive source)."""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        nxt = s[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and s[i] != "\n":
                i += 1
        elif c == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
                i += 1
            i += 2
        elif c == '"':
            i += 1
            while i < n and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
        elif c == "'":
            i += 1
            while i < n and s[i] != "'":
                i += 2 if s[i] == "\\" else 1
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def compiler_guard(ctx: Context) -> dict:
    """G-11: brace/paren balance per file. Flags only when BOTH the raw count AND
    the strings/comments-stripped count are unbalanced — a real truncation fails
    both, while a brace inside a string/comment fails only one (false positive).
    This makes the heuristic robust without a full MQL tokenizer."""
    bad = []
    for p in ctx.mql_files():
        raw = _read(p)
        code = _strip_code(raw)
        raw_bad = raw.count("{") != raw.count("}") or raw.count("(") != raw.count(")")
        strip_bad = code.count("{") != code.count("}") or code.count("(") != code.count(")")
        if raw_bad and strip_bad:
            bad.append({"file": _rel(ctx, p),
                        "raw_braces": [raw.count("{"), raw.count("}")],
                        "code_braces": [code.count("{"), code.count("}")],
                        "code_parens": [code.count("("), code.count(")")]})
    art = ctx.write("syntax_balance.json", {"generated": time.time(), "unbalanced": bad})
    return {"summary": f"{len(bad)} files unbalanced in BOTH raw and stripped counts",
            "findings": len(bad), "artifact": art}


def doc_auditor(ctx: Context) -> dict:
    """G-12: comment density per EA (under 5% = under-documented)."""
    low = []
    for p in ctx.mql_files():
        if p.suffix != ".mq5":
            continue
        t = _read(p)
        lines = t.splitlines() or [""]
        comments = sum(1 for l in lines if l.strip().startswith("//"))
        ratio = comments / max(len(lines), 1)
        if ratio < 0.05:
            low.append({"file": _rel(ctx, p), "comment_ratio": round(ratio, 3)})
    art = ctx.write("doc_density.json", {"generated": time.time(), "under_documented": low})
    return {"summary": f"{len(low)} EAs under-documented (<5%)", "findings": len(low), "artifact": art}


def changelog_keeper(ctx: Context) -> dict:
    """G-13: snapshot current MQL file mtimes; report what changed since last snapshot."""
    snap_path = ctx.artifacts / "_changelog_snapshot.json"
    prev = json.loads(_read(snap_path) or "{}")
    cur = {_rel(ctx, p): p.stat().st_mtime for p in ctx.mql_files()}
    changed = [f for f, m in cur.items() if prev.get(f) != m]
    snap_path.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    art = ctx.write("changelog.json", {"generated": time.time(),
                    "changed_since_last_cycle": changed if prev else []})
    return {"summary": f"{len(changed) if prev else 0} MQL files changed since last cycle",
            "findings": len(changed) if prev else 0, "artifact": art}


def setup_auditor(ctx: Context) -> dict:
    """G-14: confirm a setup/launcher exists for the live stack."""
    candidates = list(ctx.root.glob("start_*friday*.ps1")) + list(ctx.root.glob("launchers/*.ps1"))
    art = ctx.write("setup_guides.json", {"generated": time.time(),
                    "launchers": [_rel(ctx, c) for c in candidates]})
    return {"summary": f"{len(candidates)} launcher scripts found", "findings": len(candidates), "artifact": art}


def health_monitor(ctx: Context) -> dict:
    """G-15: top-level heartbeat — file count, artifact freshness, process pulse."""
    files = ctx.mql_files()
    arts = list(ctx.artifacts.glob("*.json"))
    art = ctx.write("health.json", {"generated": time.time(),
                    "mql_files": len(files), "artifacts": len(arts),
                    "root": str(ctx.root)})
    return {"summary": f"{len(files)} MQL files, {len(arts)} artifacts live", "findings": 0, "artifact": art}


# Registry of callables by name -------------------------------------------------
WORKERS = {fn.__name__: fn for fn in [
    file_mapper, code_archaeologist, dependency_tracker, conflict_detector,
    duplicate_hunter, standardizer, header_auditor, config_extractor,
    backup_guardian, path_optimizer, version_clusterer,
    session_auditor, spread_auditor, magic_manager, process_watcher, loc_profiler,
    hardcode_hunter, broker_assumptions, compiler_guard, doc_auditor,
    changelog_keeper, setup_auditor, health_monitor,
]}
