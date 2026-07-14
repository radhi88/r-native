#!/usr/bin/env python3
"""
export_dna.py — Layer 1 (genes).

Reads out/analyses.json, computes engagement fitness, and writes
out/content_dna.csv (the content analog of gold_dna_memory.csv). Then prints
which gene value correlates with the highest engagement, per gene.

    python export_dna.py --analyses ./out/analyses.json --out ./out/content_dna.csv

Pure Python — does not need the API key or the heavy analysis dependencies.
"""

import json
import argparse
import statistics
from pathlib import Path

from dna_schema import analysis_to_genome, write_population, load_population, GENES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyses", default="./out/analyses.json")
    ap.add_argument("--out", default="./out/content_dna.csv")
    args = ap.parse_args()

    analyses = json.loads(Path(args.analyses).read_text(encoding="utf-8"))

    rows = []
    for a in analyses:
        m = a.get("metrics") or {}
        rows.append({
            **analysis_to_genome(a),
            "source": "observed",
            "video": a.get("video", ""),
            "likes": m.get("likes", ""),
            "comments": m.get("comments", ""),
            "views": m.get("views", ""),
        })
    write_population(rows, args.out)
    print(f"Wrote {len(rows)} genomes -> {args.out}\n")

    pop = load_population(args.out)
    print("Highest-fitness value per gene (your account's winning patterns):")
    for gene in GENES:
        buckets = {}
        for r in pop:
            buckets.setdefault(r[gene], []).append(r["fitness"])
        best_val, best_scores = max(buckets.items(), key=lambda kv: statistics.mean(kv[1]))
        print(f"  {gene:15s} -> {best_val:14s} (avg {statistics.mean(best_scores):.2f}, n={len(best_scores)})")


if __name__ == "__main__":
    main()
