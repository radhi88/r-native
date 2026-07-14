#!/usr/bin/env python3
"""
typed-links-extract.py -- your-brain v2 zero-LLM typed-link extractor for your-brain.

Scans the vault, finds wikilinks [[X]] in markdown, and uses a regex pattern
cascade to infer typed edges (works_at, founded, invested_in, advises, etc.).
Writes typed-edges.jsonl at vault root.

Usage:
    python typed-links-extract.py --vault "C:\\Users\\pluto\\Documents\\your-brain"
    python typed-links-extract.py --vault PATH --sample 5 --dry-run

See 05 Skills/typed-links.md for the full spec.

Creator: claude (your-brain v2 upgrade)
Created: <run-date>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PATTERNS = [
    (re.compile(r"\b(?:co[-\s]?founded|founded|co[-\s]?founder of|founder of)\b[^\[]{0,40}\[\[", re.IGNORECASE), "founded", 0.92),
    (re.compile(r"\b(?:invested in|backer of|investor in)\b[^\[]{0,40}\[\[", re.IGNORECASE), "invested_in", 0.90),
    (re.compile(r"\b(?:advises|advisor to|advising)\b[^\[]{0,40}\[\[", re.IGNORECASE), "advises", 0.88),
    (re.compile(r"\b(?:CEO|CTO|CFO|COO|VP|President|Director|Head of|Chief)\b[^\[]{0,60}(?:of|at)\s*\[\[", re.IGNORECASE), "works_at", 0.88),
    (re.compile(r"\b(?:works at|employed by|employed at|works for)\b[^\[]{0,40}\[\[", re.IGNORECASE), "works_at", 0.90),
    (re.compile(r"\b(?:member of|joined|on the team at)\b[^\[]{0,40}\[\[", re.IGNORECASE), "member_of", 0.82),
    (re.compile(r"\bretained\b[^\[]{0,40}\[\[", re.IGNORECASE), "retained", 0.85),
    (re.compile(r"\brepresents\b[^\[]{0,40}\[\[", re.IGNORECASE), "represents", 0.82),
    (re.compile(r"\bclient of\b[^\[]{0,30}\[\[", re.IGNORECASE), "client_of", 0.78),
    (re.compile(r"\battended\b[^\[]{0,40}\[\[", re.IGNORECASE), "attended", 0.75),
    (re.compile(r"\battends\b[^\[]{0,40}\[\[", re.IGNORECASE), "attends_school", 0.70),
    (re.compile(r"\b(?:lives in|lived in|based in|from)\b[^\[]{0,30}\[\[", re.IGNORECASE), "lives_in", 0.70),
    (re.compile(r"\b(?:drives|drove|totaled|crashed)\b[^\[]{0,30}\[\[", re.IGNORECASE), "drives", 0.78),
    (re.compile(r"\b(?:owns|owned|purchased|bought)\b[^\[]{0,30}\[\[", re.IGNORECASE), "owns", 0.72),
    (re.compile(r"\b(?:mentioned|mentions|referenced)\b[^\[]{0,30}\[\[", re.IGNORECASE), "mentions", 0.40),
]

WIKILINK_RE = re.compile(r"\[\[([^\[\]\|]+?)(?:\|[^\[\]]+)?\]\]")
FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
SECTION_DIVIDER = "\n---\n"

SKIP_FOLDERS = {".obsidian", ".git", "node_modules", "media", "lint-reports"}
SKIP_FILES = {"_blocklist.md", "typed-edges.jsonl"}
ENTITY_TYPE_BY_FOLDER = {"people": "person", "companies": "company", "places": "place", "concepts": "concept", "vehicles": "vehicle"}

TYPE_PAIR_PRIORS = {
    ("person", "company"): ("affiliated_with", 0.55),
    ("person", "place"): ("located_in", 0.55),
    ("person", "vehicle"): ("owns", 0.50),
    ("person", "person"): ("knows", 0.45),
    ("company", "person"): ("employs", 0.50),
    ("company", "place"): ("located_in", 0.55),
    ("company", "company"): ("related_to", 0.40),
    ("vehicle", "person"): ("owned_by", 0.55),
    ("place", "company"): ("hosts", 0.40),
    ("concept", "person"): ("associated_with", 0.40),
    ("concept", "company"): ("associated_with", 0.40),
}


def slugify(name):
    s = name.strip().lower()
    s = re.sub(r"[\\/]", "-", s)
    s = re.sub(r"&", "and", s)
    s = re.sub(r"[^\w\-\s]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def strip_for_extraction(text):
    text = FRONTMATTER_RE.sub("", text, count=1)
    text = FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    return text


def get_source_slug(path, vault_root):
    return slugify(path.stem)


def get_source_type(path, vault_root):
    rel_parts = path.relative_to(vault_root).parts
    for part in rel_parts:
        if part in ENTITY_TYPE_BY_FOLDER:
            return ENTITY_TYPE_BY_FOLDER[part]
    return None


def get_section(text, link_position, divider_position):
    if divider_position < 0 or link_position < divider_position:
        return "compiled-truth"
    return "timeline"


def extract_edges(file_path, vault_root, target_type_by_slug):
    try:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"[warn] Could not read {file_path}: {e}", file=sys.stderr)
        return

    if not raw.strip():
        return

    clean = strip_for_extraction(raw)
    divider_idx = clean.find(SECTION_DIVIDER)

    source_path_rel = str(file_path.relative_to(vault_root)).replace("\\", "/")
    source_slug = get_source_slug(file_path, vault_root)
    source_type = get_source_type(file_path, vault_root)

    seen_within_page = {}

    for m in WIKILINK_RE.finditer(clean):
        target_name = m.group(1).strip()
        target_slug = slugify(target_name)

        if target_slug == source_slug:
            continue

        start = max(0, m.start() - 120)
        end = min(len(clean), m.end() + 60)
        context = clean[start:end]
        ctx_lines = context.split("\n")
        offset_in_context = m.start() - start
        running = 0
        relevant_line = ctx_lines[-1]
        for line in ctx_lines:
            if running + len(line) + 1 > offset_in_context:
                relevant_line = line
                break
            running += len(line) + 1
        evidence = relevant_line.strip()
        if len(evidence) > 240:
            evidence = evidence[:240] + "..."

        edge_type = None
        confidence = 0.0
        for pat, etype, conf in PATTERNS:
            if pat.search(context):
                edge_type = etype
                confidence = conf
                break

        if edge_type is None:
            target_type = target_type_by_slug.get(target_slug)
            if source_type and target_type:
                prior = TYPE_PAIR_PRIORS.get((source_type, target_type))
                if prior:
                    edge_type, confidence = prior

        if edge_type is None:
            edge_type = "references"
            confidence = 0.20

        section = get_section(clean, m.start(), divider_idx)
        if section == "timeline" and edge_type != "references":
            confidence = max(0.4, confidence - 0.15)

        key = (target_slug, edge_type)
        seen_within_page[key] = seen_within_page.get(key, 0) + 1

        if seen_within_page[key] > 1:
            continue

        yield {
            "source": source_path_rel,
            "source_slug": source_slug,
            "target_slug": target_slug,
            "target_name": target_name,
            "type": edge_type,
            "confidence": round(confidence, 2),
            "evidence": evidence,
            "section": section,
            "evidence_count": 1,
        }


def walk_vault(vault_root):
    for root, dirs, files in os.walk(vault_root):
        dirs[:] = [d for d in dirs if d not in SKIP_FOLDERS and not d.startswith(".")]
        rel = Path(root).relative_to(vault_root)
        if "scripts" in rel.parts:
            continue
        if "_templates" in rel.parts:
            continue
        for fn in files:
            if not fn.endswith(".md"):
                continue
            if fn in SKIP_FILES:
                continue
            yield Path(root) / fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    vault_root = Path(args.vault).resolve()
    if not vault_root.exists():
        print(f"[error] Vault not found: {vault_root}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else vault_root / "typed-edges.jsonl"

    since_dt = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return 2

    files_to_process = []
    for p in walk_vault(vault_root):
        if since_dt:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < since_dt:
                continue
        files_to_process.append(p)

    if args.sample > 0:
        files_to_process = files_to_process[: args.sample]

    print(f"[info] Vault: {vault_root}")
    print(f"[info] Files to process: {len(files_to_process)}")
    print(f"[info] Output: {out_path} {'(dry-run)' if args.dry_run else ''}")
    print()

    edges = []
    by_target_indegree = {}
    unresolved_targets = set()
    run_id = f"typed-links-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')}"
    extracted_at = datetime.now(timezone.utc).isoformat()

    target_type_by_slug = {}
    existing_slugs = set()
    for p in walk_vault(vault_root):
        slug = get_source_slug(p, vault_root)
        existing_slugs.add(slug)
        t = get_source_type(p, vault_root)
        if t:
            target_type_by_slug[slug] = t

    for i, fp in enumerate(files_to_process, 1):
        if not args.quiet and i % 25 == 0:
            print(f"[progress] {i}/{len(files_to_process)} ({fp.name})")
        for e in extract_edges(fp, vault_root, target_type_by_slug):
            e["extracted_at"] = extracted_at
            e["run_id"] = run_id
            if e["target_slug"] not in existing_slugs:
                e["target_status"] = "unresolved"
                unresolved_targets.add(e["target_slug"])
            else:
                e["target_status"] = "resolved"
            edges.append(e)
            by_target_indegree[e["target_slug"]] = by_target_indegree.get(e["target_slug"], 0) + 1

    if not args.dry_run:
        with out_path.open("w", encoding="utf-8") as f:
            for e in edges:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print()
    print(f"[done] Extracted {len(edges)} edges from {len(files_to_process)} pages")
    print(f"[done] {len(unresolved_targets)} unresolved targets (dead wikilinks)")
    print()

    by_type = {}
    for e in edges:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print("Edges by type:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t:20s} {n}")
    print()

    top = sorted(by_target_indegree.items(), key=lambda x: -x[1])[:10]
    print("Top-10 most-connected entities (in-degree):")
    for slug, n in top:
        print(f"  {slug:50s} {n}")
    print()

    if unresolved_targets:
        print("Unresolved targets (first 20 -- candidates for /refine):")
        for slug in list(unresolved_targets)[:20]:
            print(f"  {slug}")
        print()

    print(f"[run_id] {run_id}")
    if not args.dry_run:
        print(f"[output] {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
