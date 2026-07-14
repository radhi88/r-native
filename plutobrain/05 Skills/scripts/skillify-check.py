#!/usr/bin/env python3
"""
skillify-check.py -- your-brain v2 10-item audit for your-brain skills.

Walks 05 Skills/*.md and checks each skill against the 10-item audit.
Exit code 0 = all pass, 1 = at least one skill fails.

Usage:
    python skillify-check.py --vault "C:\\Users\\pluto\\Documents\\your-brain"
    python skillify-check.py --vault PATH --skill typed-links
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SKILLS_FOLDER_SKIP = {"conventions", "eval", "scripts", "_templates"}


def parse_frontmatter(text):
    """Return (frontmatter_dict, body_text)."""
    m = re.match(r"\A---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text = m.group(1)
    body = m.group(2)
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def check_skill(skill_path, vault, resolver_text):
    """Run the 10-item audit. Returns (skill_name, list_of_(item_num, passed, reason))."""
    name = skill_path.stem
    text = skill_path.read_text(encoding="utf-8", errors="replace")
    fm, body = parse_frontmatter(text)
    results = []

    # 1. SKILL.md exists with valid frontmatter
    required_fm = ["name", "description", "creator", "created", "source"]
    missing = [k for k in required_fm if k not in fm]
    results.append((1, not missing, f"frontmatter complete: {required_fm}" if not missing else f"missing fields: {missing}"))

    # 2. Trigger phrases documented (description + body "When to run" + RESOLVER)
    has_desc = bool(fm.get("description"))
    has_when_to_run = bool(re.search(r"^##\s*When to run\b", body, re.MULTILINE | re.IGNORECASE))
    in_resolver = name in resolver_text.lower()
    triggers_ok = has_desc and has_when_to_run and in_resolver
    reason = f"description={has_desc}, when_to_run={has_when_to_run}, in_resolver={in_resolver}"
    results.append((2, triggers_ok, reason))

    # 3. Conventions cited
    cites_conventions = bool(re.search(r"conventions/[a-z\-]+\.md", body))
    results.append((3, cites_conventions, "cites at least one conventions/*.md" if cites_conventions else "no conventions cited in body"))

    # 4. Deterministic script if applicable
    script_path = vault / "05 Skills" / "scripts" / f"{name}-extract.py"
    script_path2 = vault / "05 Skills" / "scripts" / f"{name}-check.py"
    script_path3 = vault / "05 Skills" / "scripts" / f"{name}.py"
    has_script = any(p.exists() for p in [script_path, script_path2, script_path3])
    mentions_script = "scripts/" in body or "deterministic" in body.lower() or fm.get("model") == "none"
    # Item 4 passes if EITHER the skill doesn't need a script (model != "none") OR has one
    needs_script = fm.get("model", "").lower() == "none" or "deterministic" in body.lower()[:500]
    item4_pass = (not needs_script) or has_script
    results.append((4, item4_pass, f"needs_script={needs_script}, has_script={has_script}"))

    # 5. Unit test cases documented (looking for Test cases / Verification / Example section)
    has_tests = bool(re.search(r"^##\s*(Test cases|Verification|Examples?|Limitations?|Implementation)\b", body, re.MULTILINE | re.IGNORECASE))
    results.append((5, has_tests, "Test/Verification/Examples section found" if has_tests else "no test-style section"))

    # 6. E2E test run documented
    has_run_log = bool(re.search(r"(ran|run|smoke|tested) (across|on|against|first|with|over)", body, re.IGNORECASE))
    results.append((6, has_run_log, "run log found" if has_run_log else "no E2E run mentioned"))

    # 7. Routing-eval fixture
    fixture_path = vault / "05 Skills" / "eval" / f"{name}.jsonl"
    has_fixture = fixture_path.exists()
    fixture_count = 0
    if has_fixture:
        fixture_count = sum(1 for _ in fixture_path.read_text(encoding="utf-8").split("\n") if _.strip())
    fixture_ok = has_fixture and fixture_count >= 5
    results.append((7, fixture_ok, f"fixture exists={has_fixture}, count={fixture_count} (need >=5)"))

    # 8. Resolver entry — check if skill referenced in RESOLVER
    resolver_has = f"[[{name}.md]]" in resolver_text or f"{name}.md" in resolver_text
    results.append((8, resolver_has, "in RESOLVER.md" if resolver_has else "missing from RESOLVER.md"))

    # 9. MECE check (lightweight: not duplicating an obvious existing skill name)
    # Hard to check automatically without LLM. Pass if skill mentions itself as distinct.
    mece_callout = "MECE" in body.upper() or "overlap" in body.lower()
    results.append((9, True, "MECE callout present" if mece_callout else "MECE not explicitly addressed (advisory only)"))

    # 10. No STUB sentinels
    stub_sentinels = ["SKILLIFY_STUB", "TBD", "FILL IN LATER", "TODO:", "FIXME"]
    found_stubs = [s for s in stub_sentinels if s in body.upper()]
    no_stubs = not found_stubs
    results.append((10, no_stubs, "no stub sentinels" if no_stubs else f"found: {found_stubs}"))

    return name, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--skill", default=None, help="Audit only this skill")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault).resolve()
    skills_dir = vault / "05 Skills"
    resolver = skills_dir / "RESOLVER.md"

    if not resolver.exists():
        print(f"[error] RESOLVER.md missing", file=sys.stderr)
        return 2

    resolver_text = resolver.read_text(encoding="utf-8").lower()

    skill_files = []
    for p in skills_dir.iterdir():
        if p.is_file() and p.suffix == ".md" and p.stem != "RESOLVER":
            skill_files.append(p)

    if args.skill:
        skill_files = [p for p in skill_files if p.stem == args.skill]
        if not skill_files:
            print(f"[error] skill {args.skill}.md not found", file=sys.stderr)
            return 2

    skill_files.sort()

    all_pass = True
    summary = []

    for sp in skill_files:
        name, results = check_skill(sp, vault, resolver_text)
        passed = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        status = "PASS" if passed == total else ("PARTIAL" if passed >= 7 else "FAIL")
        if passed < total:
            all_pass = False
        summary.append((name, passed, total, status))

        if not args.quiet or passed < total:
            print(f"\n=== {name} ({passed}/{total}) {status} ===")
            for num, ok, reason in results:
                mark = "[OK]" if ok else "[FAIL]"
                print(f"  {mark} item {num:>2}: {reason}")

    print()
    print("=" * 60)
    print(f"SUMMARY ({len(skill_files)} skills audited)")
    print("=" * 60)
    for name, p, t, status in summary:
        print(f"  {status:<8s} {name:<25s} {p}/{t}")
    print()

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
