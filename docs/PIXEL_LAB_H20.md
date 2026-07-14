# H.20 — Pixel Mascots & Retro Sprite Lab

> A reactive 16×16 pixel mascot system that mirrors the engine's mood
> (idle / scanning / profit / loss / panic / liquidated / hodl …) and a
> standalone HTML sprite forge for designing new ones.

---

## Files added by H.20

| File | Purpose |
|---|---|
| `r_native/pixel_sprites.py` | Pure-Python sprite data (palette + 14 presets, 28 frames) — zero dependencies. |
| `r_native/pixel_widget.py`  | PySide6 `PixelMascot` `QWidget` — drop into the Inspector tab next to `DNAHelix`/`EquityCurve`. |
| `dashboard/pixel_lab.html`  | Bilingual (AR/EN) retro arcade + sprite designer served by `brain_server`. |
| `docs/PIXEL_LAB_H20.md`     | This file. |

All data lives in `r_native.pixel_sprites` and is the **single source of
truth** — the PySide6 widget, the HTML lab, and (optionally) the MQL5
EA log icons all consume the same palette and preset dicts.

---

## Palette (locked to R-Factory tokens)

The palette follows the modern dark theme of `app.py` (Phase H.9) so the
mascot blends in:

```
K = #0a0a0f   BG_0 outline       G = #fbbf24   R-Factory GOLD
W = #f1f5f9   TEXT highlight     O = #b45309   GOLD_DIM shadow
V = #22c55e   GREEN bullish      R = #ef4444   RED bearish
U = #a78bfa   VIOLET accent      C = #06b6d4   CYAN live/OOS
P = #ffcca3   skin peach         B = #f7931a   bitcoin orange
F = #2563eb   ethereum blue      M = #94a3b8   muted grey
```

Every preset is hand-pixeled and limited to this 25-color palette — no
anti-aliasing — so it stays crisp at any scale.

---

## State → preset mapping

| Engine state | Preset id | Trigger |
|---|---|---|
| `idle`        | `bull-trader`    | Neutral — no live position |
| `scanning`    | `r-mascot`       | GA campaign in progress |
| `profit`      | `diamond-hands`  | Open P/L > 0 |
| `big-profit`  | `rocket-mode`    | P/L ≥ 5% of equity |
| `loss`        | `emotion-fomo`   | Open P/L < 0 |
| `panic`       | `emotion-panic`  | Loss ≥ daily-cap (`$10`) |
| `liquidated`  | `skull`          | Equity ≤ 0 / kill_switch tripped |
| `hodl`        | `diamond-hands`  | HODL shield manually toggled |
| `deploying`   | `golden-candle`  | Genome deploy in flight |
| `campaign`    | `bull-trader`    | Multi-tribe war active |
| `range`       | `bear-trader`    | Sideways market detected |

This map lives in **one** place (`STATE_TO_PRESET` in `pixel_sprites.py`)
and is referenced by both the Qt widget and the HTML lab.

---

## Integration into `app.py`

In the `RNativeMain` constructor, after the Inspector tab is built:

```python
from r_native.pixel_widget import PixelMascot

self.mascot = PixelMascot(self, scale=8, show_caption=True)
inspector_layout.insertWidget(0, self.mascot)
```

Then, wherever the worker emits an `open_pl` tick, react:

```python
self.mascot.set_pnl(open_pl, equity, hodl=hodl_shield)
```

Or react manually for non-P/L events:

```python
self.mascot.react("scanning")    # GA started
self.mascot.react("deploying")   # deploy action.py call
self.mascot.react("idle")        # back to idle
```

### Wiring into the brain_server (optional)

If you want the HTML dashboard mascot to mirror engine state, add a tiny
endpoint to `brain_server.py`:

```python
@app.get("/pixel_lab/state")
def pixel_lab_state():
    return jsonify({
        "state":   self.r_state,            # one of STATE_TO_PRESET keys
        "preset":  preset_for_state(self.r_state)["id"],
        "pnl":     self.last_open_pl,
        "equity":  self.last_equity,
        "hodl":    self.hodl_active,
    })
```

Then the `pixel_lab.html` page can poll `/pixel_lab/state` once a second
and call `updateMascot()` with the server-sent state. The HTML already
implements the same `STATE_TO_PRESET` map, so the visuals are identical.

---

## Running it

### Standalone PySide6 demo
```powershell
python -m r_native.pixel_widget
```

### Standalone HTML lab (no server)
Just open `dashboard/pixel_lab.html` in any browser — it works offline.

### Via brain_server (production)
1. Drop `pixel_lab.html` next to `r_factory_ui.html` in `dashboard/`.
2. Add a Flask route `@app.get("/r/pixel_lab")` that serves the HTML.
3. Add a back-button link in `r_factory_ui.html`:
   ```html
   <a href="/r/pixel_lab" class="r-back">🎮 Pixel Lab</a>
   ```

---

## Exporting sprites

The HTML lab exports three flavours (button row at the bottom):

| Button | Output | Use case |
|---|---|---|
| **Raw 16×16** | Pixel-accurate transparent PNG | Drop into game engines (Unity, Godot, Phaser). |
| **HD 512×512** | 32× upscaled, no smoothing | Use in slide decks, MQL5 chart objects, README. |
| **Sprite Sheet** | 32×16 (2 frames side-by-side) | Used by CSS `steps(2)` animation: |

```css
.r-mascot {
  width: 16px; height: 16px;
  background-image: url('mascot.png');
  background-size: 32px 16px;
  image-rendering: pixelated;
  animation: r-play 0.4s steps(2) infinite;
}
@keyframes r-play { to { background-position: -32px; } }
```

The PySide6 widget can also export PNGs at any scale:
```python
self.mascot.export_png("/tmp/r_diamond.png", scale=32)
```

---

## ROADMAP integration

This phase ships:

- [x] 14 hand-pixeled presets across 4 categories (symbols, characters, emotions, items)
- [x] Pure-Python data module (zero deps, importable from anywhere)
- [x] PySide6 widget with state-based reactivity
- [x] HTML lab with bilingual UI matching R-Factory styling
- [x] Retro Web Audio sound engine (bleeps, coins, profit fanfare, margin-call boom)
- [x] PNG export at any scale (1× → 32× → sprite sheets)
- [x] Same palette tokens as Phase H.9 modern dark theme

Future ideas:
- [ ] H.20.1 — MQL5 chart object renderer that draws the mascot on the active EA chart based on the current trade's P/L
- [ ] H.20.2 — Telegram bot sticker pack auto-generated from the presets
- [ ] H.20.3 — Optional gif export (uses ImageMagick if installed)
- [ ] H.20.4 — User-uploaded sprite slots (paint your own, save to `data/r_native/user_sprites.json`)
