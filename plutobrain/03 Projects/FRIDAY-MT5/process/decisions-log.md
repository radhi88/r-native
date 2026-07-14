---
type: decisions-log
project: FRIDAY-MT5
created: 2026-05-21
tags: [decisions, architecture, FRIDAY]
---

# FRIDAY-MT5 — Decisions Log

> Record of significant architecture and strategy decisions. Append-only — never edit existing entries.

---

## 2026-05-21 — PlutoBrain as knowledge OS

**Decision:** Install PlutoBrain vault at `C:\Users\Radhi\MT5\plutobrain` as the knowledge and session memory layer for FRIDAY development.

**Why:** `.planning/codebase/` docs are code-adjacent. PlutoBrain adds: session hot-cache (hot.md), trade journal, research accumulation, pattern tracking across sessions.

**Trade-off:** Adds a second system to maintain. Worth it if `/weekly-update` runs consistently.

---

## 2026-05-21 — Local AI only for M1 scalping decisions

**Decision:** All AI inference for real-time trading signals uses local models (Ollama/llama.cpp). No cloud API calls in the hot path.

**Why:** M1 scalping requires <500ms response. Cloud API latency (200-2000ms) is incompatible. No per-trade API cost. Offline resilience.

**Trade-off:** Limited to models that fit local VRAM. Accept smaller, quantized models (GGUF Q4/Q5).

---

## 2026-05-21 — Paper trading gate before live

**Decision:** LIVE_TRADING_ENABLED remains False until: (1) SL-on-entry bug fixed, (2) kill-switch fully enforced, (3) 500+ paper trades with documented positive expectancy.

**Why:** Three known safety gaps make live trading irresponsible right now.

**Trade-off:** Delays live revenue. Worth it — a blown account ends the project.

---

## 2026-05-21 — HuggingFace skills scoped to 5 only

**Decision:** From the full HuggingFace skill set, only use: `huggingface-local-models`, `hf-cli`, `huggingface-tool-builder`, `huggingface-trackio`, `train-sentence-transformers`.

**Why:** Only these directly serve FRIDAY (local inference, model management, training tracking, semantic trade search). Others (vision, Gradio, papers) add noise.

**Trade-off:** May need to revisit if dashboard needs browser-side AI.
