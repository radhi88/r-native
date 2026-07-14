# IG Reels → Strategy Analyzer

Downloads videos from an Instagram profile, then analyzes each one with Whisper
(audio transcript) + Claude vision (sampled frames) and writes a structured JSON
breakdown: **hook**, content, **CTA**, editing, and copyable takeaways. A React
Native component renders the result as a feed.

The pipeline is split in two so the fragile part (Instagram) is separate from the
reliable part (analysis):
- `download_reels.py` — optional, pulls videos from a profile.
- `analyze_reels.py` — the core. Works on **any** folder of videos.

**`study_account.py` (recommended)** does it all in one pass, like an agent
going through the account: for each reel it fetches the video, understands it
(frames + transcript → Claude), saves the analysis, **deletes the file**, and
moves to the next — then synthesizes a strategy **playbook** across everything
it learned. Nothing is stored long-term.

    python study_account.py nolan.vader --login YOUR_USERNAME --limit 20

Output: `out/analyses.json` (per-video) plus `out/playbook.json` and
`out/playbook.md` (the recurring hooks, CTA patterns, formats, and copyable
recommendations for your own content).

## 1. Install

```bash
pip install -r requirements.txt
```

`faster-whisper` and `opencv-python` decode audio/video on their own — you do
**not** need to install ffmpeg separately.

## 2. Set your API key

```bash
# Windows (cmd)
set ANTHROPIC_API_KEY=sk-ant-...
# mac / Linux
export ANTHROPIC_API_KEY=sk-ant-...
```

## 3. Get the videos

Either drop your own `.mp4` files into a `./videos` folder, or use the downloader:

```bash
# a few videos, no login (often rate-limited)
python download_reels.py nolan.vader --out ./videos --limit 10

# all videos — log in with YOUR OWN account first to avoid blocks
python download_reels.py nolan.vader --out ./videos --login YOUR_USERNAME
```

Instagram throttles anonymous scraping hard. Start small with `--limit`, and log
in for anything substantial. Only analyze content you have the right to access.

## 4. Analyze

```bash
python analyze_reels.py --videos ./videos --out ./out
```

- One JSON file per video in `./out`, plus a combined `./out/analyses.json`.
- **Resumable**: re-running skips videos already done, so a crash mid-run is fine.

## 5. View in your app

```jsx
import analyses from './out/analyses.json';
import StrategyFeed from './StrategyFeed';

<StrategyFeed analyses={analyses} />
```

(`StrategyFeed.jsx` is plain React Native — no extra UI libraries. For a React
**web** project, the same data works; just swap `View/Text/FlatList` for `div`s.)

## Config (top of `analyze_reels.py`)

| Setting           | Default              | Notes                                        |
|-------------------|----------------------|----------------------------------------------|
| `MODEL`           | `claude-sonnet-4-6`  | Use `claude-opus-4-8` for deeper analysis    |
| `WHISPER_SIZE`    | `base`               | `small`/`medium` = better transcripts, slower|
| `LANGUAGE`        | `Arabic`             | Language of the human-readable text fields   |
| `MAX_FRAMES`      | `12`                 | Frames per video sent to Claude (cost lever) |
| `FRAME_MAX_WIDTH` | `768`                | Frame downscale width (cost lever)           |

## How analysis works (so you can tune it)

- Frames are sampled **densely in the first 3 seconds** (where the hook lives)
  and spread across the rest of the clip.
- The audio transcript catches hooks/CTAs that are *spoken*; the frames catch
  on-screen text and visuals.
- The JSON schema and emphasis (hook + CTA first) live in `SYSTEM_PROMPT` —
  edit it to change what gets extracted.

## The DNA / evolution layer

The same engine as the EA's DNA system, pointed at content. Each analyzed reel
becomes a strategy **genome** (hook, format, value, pacing, length, CTA, audio);
its **fitness** is derived from the post's public engagement. Run these after
`study_account.py` (the gene space + operators live in `dna_schema.py`):

1. **Encode genes** — `python export_dna.py` reads `out/analyses.json`, computes
   engagement fitness, and writes `out/content_dna.csv` (the content analog of
   `gold_dna_memory.csv`). It also prints which gene values correlate with the
   highest engagement on the account.
2. **Evolve** — `python evolve.py --n 8` runs crossover + mutation over the
   population to propose new, untried genomes. Claude is the surrogate fitness
   model (content can't be backtested): it predicts a score, flags incoherent
   combos, and names the concrete idea → ranked `out/next_generation.json`.
3. **Arena** — `python arena.py "your topic"` turns the top genomes into
   competing agents; each drafts a full reel concept in its DNA's style, a judge
   ranks them, and the winner is saved to `out/arena_result.json`.
4. **Close the loop** — after you post, feed the real numbers back:
   `python log_result.py --from-arena out/arena_result.json --likes 1200 --comments 84 --views 30000`.
   This appends your own result to `content_dna.csv` as a `my_post` genome, so the
   next generation evolves from real performance — your data, not just competitors.

**Honest caveat:** engagement is a *proxy* fitness (biased by follower count,
recency, and the algorithm), and a new strategy's score is a *prediction* until
you actually post. The real evolutionary signal is step 4, accumulated over time.

`export_dna.py` and `log_result.py` are pure Python (no API key / heavy deps);
`evolve.py` and `arena.py` call Claude.
