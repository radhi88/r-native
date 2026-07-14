#!/usr/bin/env python3
"""
arena.py — Layer 3 (agents).

Turns the top-fitness genomes into competing agents (like Claude Arena). Each
agent = a strategy DNA + a persona. Given a TOPIC, every agent drafts a full
Instagram Reel concept executed strictly in its DNA's style; a judge then ranks
them and picks a winner. Saved to out/arena_result.json.

    python arena.py "your topic / niche" --n 5
"""

import json
import argparse
from pathlib import Path

from dna_schema import load_population, GENES
from analyze_reels import client, MODEL, LANGUAGE


def top_genomes(pop, n):
    pop = sorted(pop, key=lambda r: r["fitness"], reverse=True)[:n]
    return [{g: r[g] for g in GENES} for r in pop]


def run_arena(topic, agents):
    prompt = (
        f"Topic: {topic}\n\n"
        f"Below are {len(agents)} content-strategy agents, each defined by its strategy "
        "DNA (a combination of traits). Each agent must produce a full Instagram Reel "
        "concept for the topic, executed strictly in the style its DNA dictates.\n\n"
        f"Agents (index = position in this list):\n{json.dumps(agents, ensure_ascii=False, indent=2)}\n\n"
        "Then act as judge: predict each concept's performance and pick the winner.\n"
        "Return ONLY this JSON object:\n"
        "{\n"
        '  "concepts": [{"agent": <index>, "hook_line": "...", "script_beats": ["..."], '
        '"on_screen_text": ["..."], "cta": "...", "predicted_score": <0-100>}],\n'
        '  "winner": <index>,\n'
        '  "verdict": "why it wins"\n'
        "}\n"
        f"Write all human-readable text in {LANGUAGE}."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"},  # prefill -> JSON
        ],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    raw = ("{" + text).strip()
    return json.loads(raw[: raw.rfind("}") + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--dna", default="./out/content_dna.csv")
    ap.add_argument("--out", default="./out/arena_result.json")
    ap.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

    pop = load_population(args.dna)
    agents = top_genomes(pop, args.n)
    result = run_arena(args.topic, agents)

    # attach each agent's DNA to its concept for traceability + the feedback loop
    for c in result.get("concepts", []):
        idx = c.get("agent")
        if isinstance(idx, int) and 0 <= idx < len(agents):
            c["dna"] = agents[idx]

    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"Winner: agent {result.get('winner')}")
    print(f"Verdict: {result.get('verdict', '')}")
    print(f"\nFull concepts -> {args.out}")


if __name__ == "__main__":
    main()
