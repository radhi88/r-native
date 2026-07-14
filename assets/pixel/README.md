# Pixel Mascot Assets

Drop your 32×32 (or any square size — will be scaled) PNG sprites here.
The `pixel_mascot.py` widget will auto-load them by filename.

## Expected files

| Filename | Emotion | When shown |
|---|---|---|
| `bull_diamond.png` | 💎 DIAMOND HANDS | P/L > +5% |
| `bull_confident.png` | 😎 CONFIDENT | P/L +1% to +5% |
| `bull_active.png` | ⚡ ACTIVE | Position open (overrides P/L) |
| `watcher.png` | 🤔 WATCHING | P/L 0% to +1% |
| `idle.png` | 😴 IDLE | No trades today |
| `bear_worried.png` | 😬 WORRIED | P/L 0% to -2% |
| `bear_fomo.png` | 😨 FOMO | P/L -2% to -5% |
| `bear_capitulation.png` | 💀 CAPITULATION | P/L < -5% |

## Source

These sprites originated in the user's pixel-art trading game project:
https://easy-peasy.ai/share/b7cb74b7-f246-47ce-a681-61290ff6dbbd

## Style guide

- **Resolution**: 32×32 native (will be scaled up nearest-neighbor to 52-80 px in UI)
- **Palette**: dark retro — works on `#0a0a0f` background
- **Transparency**: PNG with alpha (no background fill — let the widget's circle/glow show through)
- **No anti-aliasing**: pixel-art aesthetic requires hard edges

## Fallback

If a sprite is missing, the widget falls back to:
- A colored circle (color per emotion)
- An emoji centered inside

So you can ship the pixel_mascot.py without any sprites and it still works.

## Optional: animation frames

For animated sprites, name them with `_f1`, `_f2`, `_f3` suffix:
```
bull_diamond_f1.png
bull_diamond_f2.png
bull_diamond_f3.png
```
(Animation support is in pixel_mascot.py's TODO — single frame works today.)
