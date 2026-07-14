# Report 12 — Qader Voice Review

**Reviewer:** Claude (supervisor role)  
**Date:** 2026-05-14  
**Scope:** Voice integration, command routing, MT5 safety, confirmation gates

---

## 1. Voice Architecture

Two independent voice stacks exist — they are NOT integrated:

| Stack | Location | Backend | Purpose |
|---|---|---|---|
| Mark-XXXIX voice | `mark_xxxix/main.py` | Gemini Live + Whisper/Vosk | Primary Qader assistant voice |
| FRIDAY voice | `src/mt5_ai/friday_voice/` | Whisper + Vosk | Standalone trading voice (unused by Qader) |

**For Qader, only the mark_xxxix stack matters.** The `friday_voice/` subsystem is a separate standalone app that is not called from `main.py`. It can be ignored for this review.

**mark_xxxix voice flow:**
```
Microphone → sounddevice PCM → Gemini Live API (primary)
                              → Whisper (fallback if Gemini unavailable)
                              → Vosk (Arabic keyword detection)
↓
JarvisLive._process_text() → tool dispatch → response text
↓
Gemini Live audio output (TTS) / edge-tts / pyttsx3
```

---

## 2. Voice Safety — MT5 Order Path

**Finding: MT5Tools is read-only. Confirmed safe.**

`src/mt5_ai/friday_voice/mt5_tools.py` exposes:
- `account_snapshot()` — reads account info
- `tick()` — reads current price
- `positions()` — reads open positions (no write)
- `orders()` — reads pending orders (no write)
- `latest_rates()` — reads OHLCV bars
- `market_snapshot()` — aggregates all of the above
- `system_status()` — checks port liveness

No `order_send`, `order_modify`, `position_close`, or any MT5 write call exists in `mt5_tools.py`. The voice assistant cannot place a trade through the voice layer. ✅

---

## 3. Critical Finding — Stack Restart Without Confirmation

**Priority: CRITICAL**  
**File:** `mark_xxxix/friday_plugin.py` lines 573–603

The `friday_stack_control` tool is declared to Gemini with this description:
> "Controls the local FRIDAY stack scripts. Use status for inspection, start/restart to run the unified stack, and stop to stop FRIDAY services."

When action is `"start"` or `"restart"`, it launches:
```python
subprocess.Popen([
    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", str(FRIDAY_ROOT / "restart_friday.ps1"),
], cwd=str(FRIDAY_ROOT), shell=False)
```

This starts `main_loop.py` (the live trading loop). If `trading_runtime.yaml` is changed from DRY_RUN to DEMO or LIVE, and a voice command triggers this tool, real orders would be placed.

**Triggering phrases (from Gemini's perspective):**
- "Start FRIDAY"
- "Restart the trading system"
- "شغل فرايدي"
- "أعد تشغيل الستاك"

**No confirmation dialog, no PIN, no acknowledgement is required.** The action fires immediately.

**Risk:** Voice misrecognition or ambiguous phrasing could start a trading session. Combined with a config that has live trading enabled, this is a path to unintended real orders.

**Fix:**
```python
# In _friday_stack_control(), before Popen:
if action in {"start", "restart"}:
    # Return a confirmation request instead of executing
    return (
        "⚠️ Action requires confirmation. "
        "Type 'CONFIRM START FRIDAY' or click the stack control button in the UI."
    )
```
Add a dedicated UI button for stack control that requires a physical click (not voice-triggerable). Never allow `start`/`restart` from voice alone.

**Safe to apply now:** YES.

---

## 4. Command Router Analysis

`mark_xxxix/friday_plugin.py` tool declarations feed directly to Gemini. Gemini decides which tool to call based on natural language. There is no explicit command whitelist — any phrase Gemini interprets as matching a tool description will trigger it.

**Risk categories by tool:**

| Tool | Risk Level | Notes |
|---|---|---|
| `friday_state` | SAFE | Read-only account/position data |
| `friday_evolution` | SAFE | Read-only genome stats |
| `friday_genome_status` | SAFE | Read-only file |
| `friday_oracle` | SAFE | Read-only predictions |
| `friday_services` | SAFE | Read-only probe |
| `friday_self_test` | SAFE | Read-only + tool checks |
| `friday_consult` | SAFE | HTTP POST to local brain (no trades) |
| `friday_open_dashboard` | LOW | Opens browser URL — `subprocess.Popen(["cmd", "/c", "start", url])` |
| `friday_system_mesh` | LOW | Can refresh genome files via `subprocess.run(friday_system_mesh.py)` |
| `friday_stack_control` | **CRITICAL** | Can start/restart/stop trading stack |

**`friday_open_dashboard`** uses `cmd /c start url` — this opens the default browser. The `url` variable comes from a fixed dict of local URLs. No user-controlled URL injection possible. LOW risk.

**`friday_system_mesh` with `refresh=True`** runs `friday_system_mesh.py` via `subprocess.run`. This is a read-only status export script — it does not place trades. LOW risk.

---

## 5. FRIDAY SSE Listener

`start_sse_listener(jarvis)` runs a background daemon thread that:
1. Connects to `http://127.0.0.1:8790/events`
2. On trade execution events → calls `jarvis.speak(...)` in Arabic
3. On genome award events → calls `jarvis.speak(...)`
4. On oracle results → calls `jarvis.speak(...)`

**Confirms:** The SSE listener announces events but performs no actions. It cannot place orders, modify config, or start subprocesses. ✅

**Gap:** The minimum announce gap is 12 seconds (`_MIN_ANNOUNCE_GAP`). If the trading loop executes multiple rapid trades, only the first announcement fires. This is a UX design choice, not a safety issue.

---

## 6. Local STT Privacy

- Gemini Live sends raw PCM audio to Google servers
- Whisper runs locally (faster-whisper on CPU)
- Vosk runs locally (Arabic model at `models/voice/vosk-model-ar-mgb2-0.4/`)
- No local audio recording to disk

**Finding:** When using Gemini Live (default), all audio is processed by Google. The onboarding screen does not disclose this. Users should be informed. MEDIUM priority cosmetic/legal concern.

---

## 7. Mute Button

`MainWindow._toggle_mute()` sets `self._muted` and updates `hud.muted`. This controls the UI state and `speak()` calls. The microphone itself (sounddevice stream) is still capturing — mute prevents the AI from responding but does not stop audio capture.

**Risk:** User expects "muted" to stop microphone capture. Actual behavior: capture continues, processing stops. This is a UX misalignment, not a security issue.

---

## 8. Voice Review Summary

| Item | Status |
|---|---|
| Voice → order_send path | ✅ NONE — confirmed safe |
| Stack restart requires confirmation | ❌ CRITICAL — no confirmation |
| SSE listener → trade actions | ✅ READ-ONLY |
| Command router exploitable | ⚠️ HIGH — friday_stack_control |
| Two voice stacks integrated | ❌ NOT INTEGRATED — pick one |
| Audio privacy disclosure | ⚠️ MEDIUM — missing |
| Mute stops microphone capture | ❌ NO — UX misleading |
