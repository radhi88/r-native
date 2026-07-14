"""
dna_schema.py — shared backbone for the content-DNA system.

Defines the gene space, encodes a reel analysis into a genome, derives fitness
from engagement, provides the genetic operators (crossover / mutation /
selection), and reads & writes content_dna.csv — the content analog of the EA's
gold_dna_memory.csv.
"""

import csv
import random
from pathlib import Path

# Each gene is a categorical dimension of a content strategy.
# Values mirror exactly the enums produced by analyze_reels.py.
GENE_SPACE = {
    "hook_type": ["question", "bold_claim", "shock", "curiosity_gap", "story",
                  "problem", "pattern_interrupt", "relatable", "other"],
    "content_format": ["tutorial", "listicle", "story", "talking_head", "demo",
                       "skit", "tips", "reaction", "other"],
    "value_type": ["educational", "entertaining", "emotional", "inspirational",
                   "promotional"],
    "pacing": ["slow", "medium", "fast"],
    "length_bucket": ["short", "medium", "long", "xlong"],
    "cta_type": ["follow", "comment", "save", "share", "link_in_bio", "dm", "none"],
    "cta_placement": ["start", "middle", "end", "none"],
    "audio_type": ["trending_sound", "voiceover", "music", "original_audio", "none"],
}
GENES = list(GENE_SPACE.keys())
CSV_FIELDS = GENES + ["source", "video", "likes", "comments", "views"]


def length_bucket(seconds):
    seconds = seconds or 0
    if seconds < 15:
        return "short"
    if seconds < 30:
        return "medium"
    if seconds <= 60:
        return "long"
    return "xlong"


def analysis_to_genome(a):
    """Encode one analyze_reels.py record into a genome."""
    hook = a.get("hook") or {}
    content = a.get("content") or {}
    cta = a.get("cta") or {}
    editing = a.get("editing") or {}
    return {
        "hook_type": hook.get("type") or "other",
        "content_format": content.get("format") or "other",
        "value_type": content.get("value") or "educational",
        "pacing": content.get("pacing") or "medium",
        "length_bucket": length_bucket(a.get("duration_sec")),
        "cta_type": cta.get("type") or "none",
        "cta_placement": cta.get("placement") or "none",
        "audio_type": editing.get("audio") or "none",
    }


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def engagement(row):
    """Raw engagement signal from a post's public metrics (a proxy for fitness)."""
    likes, comments, views = _int(row.get("likes")), _int(row.get("comments")), _int(row.get("views"))
    if views > 0:
        return (likes + 3 * comments) / views   # engagement rate, comments weighted
    return float(likes + 3 * comments)           # fallback; normalized across the set


def _normalize(values):
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ---- genetic operators (same idea as the EA's DNA evolution) ----
def random_genome():
    return {g: random.choice(opts) for g, opts in GENE_SPACE.items()}


def crossover(a, b):
    return {g: random.choice([a[g], b[g]]) for g in GENES}


def mutate(genome, rate=0.25):
    return {g: (random.choice(GENE_SPACE[g]) if random.random() < rate else genome[g])
            for g in GENES}


def tournament(pop, k=3):
    """Pick a parent: best of k random contenders (each row has a 'fitness')."""
    best = max(random.sample(pop, min(k, len(pop))), key=lambda r: r["fitness"])
    return {g: best[g] for g in GENES}


# ---- content_dna.csv memory ----
def write_population(rows, path):
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def append_row(row, path):
    p = Path(path)
    exists = p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def load_population(path):
    """Read genomes and attach a normalized fitness (0..1) across the whole set."""
    with Path(path).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    raw = [engagement(r) for r in rows]
    for r, fr, fn in zip(rows, raw, _normalize(raw)):
        r["raw_engagement"] = fr
        r["fitness"] = fn
    return rows
