#!/usr/bin/env python3
"""
evolve.py — Layer 2 (evolution).

Crossover + mutation (the same operators as the EA's DNA system) propose new,
untried strategy genomes from the observed population. Since content can't be
backtested, Claude acts as the surrogate fitness model: it predicts each
candidate's performance, flags incoherent trait combos, and names the concrete
content idea. Output is ranked and saved to out/next_generation.json.

    python evolve.py --dna ./out/content_dna.csv --n 8 --mutation 0.25
"""

import json
import argparse
from pathlib import Path

from dna_schema import (load_population, crossover, mutate, tournament,
                        random_genome, GENES)
from analyze_reels import client, MODEL, LANGUAGE


def propose(pop, n, mutation_rate):
    kids, seen, tries = [], set(), 0
    while len(kids) < n and tries < n * 30:
        tries += 1
        child = (mutate(crossover(tournament(pop), tournament(pop)), mutation_rate)
                 if len(pop) >= 2 else random_genome())
        key = tuple(child[g] for g in GENES)
        if key not in seen:
            seen.add(key)
            kids.append(child)
    return kids


def evaluate(candidates):
    prompt = (
        "You are the fitness model for short-form video strategies. Each candidate is a "
        "strategy 'genome' (a combination of content traits). For EACH candidate: predict "
        "performance from 0 to 100, decide whether the trait combination is coherent, and "
        "give the concrete one-line content idea it implies.\n\n"
        f"Candidates:\n{json.dumps(candidates, ensure_ascii=False, indent=2)}\n\n"
        "Return ONLY a JSON array, same order, each item exactly:\n"
        '{"predicted_score": <0-100>, "coherent": true, "idea": "...", "why": "..."}\n'
        f"Write 'idea' and 'why' in {LANGUAGE}."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "["},  # prefill -> JSON array
        ],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    raw = ("[" + text).strip()
    return json.loads(raw[: raw.rfind("]") + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dna", default="./out/content_dna.csv")
    ap.add_argument("--out", default="./out/next_generation.json")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--mutation", type=float, default=0.25)
    args = ap.parse_args()

    try:
        pop = load_population(args.dna)
    except FileNotFoundError:
        pop = []
        print("No content_dna.csv yet — seeding the first generation at random.")

    candidates = propose(pop, args.n, args.mutation)
    evals = evaluate(candidates)
    merged = sorted(
        ({**g, **e} for g, e in zip(candidates, evals)),
        key=lambda r: r.get("predicted_score", 0), reverse=True,
    )

    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\nNext generation (ranked) -> {args.out}\n")
    for r in merged[:5]:
        flag = "" if r.get("coherent", True) else "  [incoherent]"
        print(f"  {str(r.get('predicted_score', '?')):>3}  {r.get('idea', '')}{flag}")


if __name__ == "__main__":
    main()
