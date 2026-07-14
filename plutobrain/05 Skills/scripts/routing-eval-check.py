#!/usr/bin/env python3
"""
routing-eval-check.py -- your-brain v2 routing accuracy eval for your-brain.

Loads RESOLVER.md, extracts the routing table, then runs every fixture in
05 Skills/eval/*.jsonl against it. Reports pass/fail counts and lists failures.

Usage:
    python routing-eval-check.py --vault "C:\\Users\\pluto\\Documents\\your-brain"

Creator: claude (your-brain v2 upgrade)
Created: <run-date>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


def parse_resolver(resolver_path):
    """Parse 05 Skills/RESOLVER.md routing table.

    Returns dict: {skill_name: [list of trigger phrases]}.
    Trigger phrases come from the first column of the routing table.
    """
    text = resolver_path.read_text(encoding="utf-8")

    routes = {}

    # Routing table rows look like:
    # | "save this chat", "save the conversation", `/save` | [[save.md]] | brain-first, quality |
    row_re = re.compile(r"^\|(.+?)\|\s*\[\[([^\]]+?)\.md\]\]\s*\|", re.MULTILINE)
    for m in row_re.finditer(text):
        triggers_cell = m.group(1).strip()
        skill = m.group(2).strip().lower()

        # Extract quoted phrases and code-spans
        phrases = []
        for pm in re.finditer(r'"([^"]+)"', triggers_cell):
            phrases.append(pm.group(1).lower())
        for pm in re.finditer(r"`([^`]+)`", triggers_cell):
            phrases.append(pm.group(1).lower())
        # Fallback: split by comma if no quotes
        if not phrases:
            for piece in triggers_cell.split(","):
                p = piece.strip().lower()
                if p:
                    phrases.append(p)

        if skill not in routes:
            routes[skill] = []
        routes[skill].extend(phrases)

    return routes


def score_intent(intent, trigger_phrases):
    """Score how well an intent matches a skill's trigger phrases. Returns 0-1."""
    intent_lower = intent.lower()
    best = 0.0
    for phrase in trigger_phrases:
        phrase_lower = phrase.lower()
        # Slash-command exact match wins
        if phrase_lower.startswith("/") and phrase_lower in intent_lower:
            return 1.0
        # Full phrase substring match
        if phrase_lower in intent_lower:
            score = len(phrase_lower) / max(len(intent_lower), 1)
            best = max(best, min(0.95, 0.5 + score / 2))
            continue
        # Token overlap fallback
        phrase_tokens = set(re.findall(r"\w+", phrase_lower))
        intent_tokens = set(re.findall(r"\w+", intent_lower))
        if phrase_tokens and intent_tokens:
            overlap = len(phrase_tokens & intent_tokens) / len(phrase_tokens)
            best = max(best, overlap * 0.6)
    return best


def predict_skill(intent, routes, ambiguity_threshold=0.15):
    """Return predicted skill, or 'ask' if top match is too close to runner-up."""
    scores = []
    for skill, phrases in routes.items():
        s = score_intent(intent, phrases)
        scores.append((skill, s))
    scores.sort(key=lambda x: -x[1])

    if not scores or scores[0][1] < 0.30:
        return "ask", scores

    if len(scores) > 1 and (scores[0][1] - scores[1][1]) < ambiguity_threshold and scores[0][1] < 0.85:
        return "ask", scores

    return scores[0][0], scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--report", default=None, help="Optional output report path")
    args = ap.parse_args()

    vault = Path(args.vault).resolve()
    resolver = vault / "05 Skills" / "RESOLVER.md"
    eval_dir = vault / "05 Skills" / "eval"

    if not resolver.exists():
        print(f"[error] RESOLVER.md not found at {resolver}", file=sys.stderr)
        return 2

    if not eval_dir.exists():
        print(f"[error] Eval dir not found at {eval_dir}", file=sys.stderr)
        return 2

    routes = parse_resolver(resolver)
    print(f"[routing-eval] vault: {vault}")
    print(f"[routing-eval] RESOLVER skills: {len(routes)}")
    print(f"[routing-eval] skills: {sorted(routes.keys())}")
    print()

    fixtures = sorted(eval_dir.glob("*.jsonl"))
    total = 0
    passed = 0
    failures = []
    skill_miss_count = {}

    for fp in fixtures:
        with fp.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    fixture = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[warn] bad JSON in {fp.name}: {line[:60]}... ({e})")
                    continue

                intent = fixture.get("intent", "")
                expected = fixture.get("expected_skill", "").lower()
                if not intent or not expected:
                    continue

                predicted, scores = predict_skill(intent, routes)
                total += 1
                if predicted == expected:
                    passed += 1
                else:
                    failures.append({
                        "fixture": fp.name,
                        "intent": intent,
                        "expected": expected,
                        "predicted": predicted,
                        "top3_scores": [(s, round(v, 2)) for s, v in scores[:3]],
                        "notes": fixture.get("notes", ""),
                    })
                    skill_miss_count[expected] = skill_miss_count.get(expected, 0) + 1

    pct = (passed / total * 100) if total else 0
    print(f"[routing-eval] fixtures: {len(fixtures)} files, {total} intents")
    print()
    print(f"PASS: {passed} / {total}  ({pct:.0f}%)")
    print(f"FAIL: {total - passed} / {total}")
    print()

    if pct >= 90:
        print("Status: GREEN -- RESOLVER is healthy.")
    elif pct >= 75:
        print("Status: YELLOW -- review failures and tune RESOLVER trigger phrases.")
    else:
        print("Status: RED -- RESOLVER drift; review needed.")
    print()

    if failures:
        print("Failures:")
        for f in failures[:30]:
            top = ", ".join(f"{s}={v}" for s, v in f["top3_scores"])
            note = f"  ({f['notes']})" if f["notes"] else ""
            print(f"  [{f['fixture']}] \"{f['intent']}\"")
            print(f"    expected: {f['expected']}, predicted: {f['predicted']}")
            print(f"    top3: {top}{note}")
        if len(failures) > 30:
            print(f"  ... {len(failures) - 30} more")
        print()

    if skill_miss_count:
        print("Top-misrouted skills:")
        for skill, n in sorted(skill_miss_count.items(), key=lambda x: -x[1]):
            print(f"  {skill:20s} {n} missed intents")

    if args.report:
        report_path = Path(args.report)
        with report_path.open("w", encoding="utf-8") as f:
            f.write(f"# Routing Eval -- {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n")
            f.write(f"PASS: {passed}/{total} ({pct:.0f}%)\n\n")
            for fail in failures:
                f.write(f"- [{fail['fixture']}] \"{fail['intent']}\" expected={fail['expected']} predicted={fail['predicted']}\n")
        print(f"\n[report] {report_path}")

    return 0 if pct >= 75 else 1


if __name__ == "__main__":
    sys.exit(main())
