#!/usr/bin/env python3
"""
log_result.py — close the loop.

After you actually post a reel, feed its real numbers back into the gene memory.
This appends your own result to content_dna.csv as a 'my_post' genome, so the
next generation evolves from real performance (your data) — not just observed
competitors. This is the real evolutionary signal.

    # log the winning Arena concept after posting it
    python log_result.py --from-arena ./out/arena_result.json --likes 1200 --comments 84 --views 30000

    # or specify the genome by hand
    python log_result.py --gene hook_type=question --gene pacing=fast ... --likes 900 --views 21000

Pure Python — no API key or heavy dependencies needed.
"""

import json
import argparse
from pathlib import Path

from dna_schema import append_row, GENES, GENE_SPACE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-arena", default="")
    ap.add_argument("--gene", action="append", default=[], help="gene=value (repeatable)")
    ap.add_argument("--likes", type=int, default=0)
    ap.add_argument("--comments", type=int, default=0)
    ap.add_argument("--views", type=int, default=0)
    ap.add_argument("--label", default="my_post")
    ap.add_argument("--dna", default="./out/content_dna.csv")
    args = ap.parse_args()

    genome = {}
    if args.from_arena:
        res = json.loads(Path(args.from_arena).read_text(encoding="utf-8"))
        winner = res.get("winner")
        concept = next((c for c in res.get("concepts", []) if c.get("agent") == winner), None)
        if concept and concept.get("dna"):
            genome = {g: concept["dna"].get(g) for g in GENES}
    for kv in args.gene:
        k, _, v = kv.partition("=")
        if k in GENE_SPACE:
            genome[k] = v

    missing = [g for g in GENES if g not in genome]
    if missing:
        raise SystemExit(f"Genome incomplete (missing: {', '.join(missing)}). "
                         "Use --from-arena, or pass all genes via --gene.")

    row = {**genome, "source": "my_post", "video": args.label,
           "likes": args.likes, "comments": args.comments, "views": args.views}
    append_row(row, args.dna)
    print(f"Logged '{args.label}' -> {args.dna}  (re-run evolve.py to use it next gen)")


if __name__ == "__main__":
    main()
