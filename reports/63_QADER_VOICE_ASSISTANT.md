# Report 63 - Qader Voice Assistant

Generated: 2026-05-14

## Implementation

Voice boundary:

```text
src/qader_app/assistant/qader_voice.py
```

Assistant brain:

```text
src/qader_app/assistant/qader_brain.py
src/qader_app/assistant/intent_router.py
```

## Capabilities

- Text-to-speech through `pyttsx3` when `can_use_speaker` is granted.
- Speech-to-text through `speech_recognition` when `can_use_microphone` is granted.
- Push-to-talk/listen-once style command handling.
- Dangerous command detection and confirmation requirement.
- Local fallback: if voice dependencies or permissions are missing, Qader continues through text UI.

## Reused Components

Inspected and reused design patterns from:
- `mark_xxxix/main.py` local TTS/STT handling
- `src/mt5_ai/voice_io.py` bilingual command parsing
- `src/mt5_ai/friday_voice/voice_input.py` microphone error handling patterns
- `src/mt5_ai/friday_voice/voice_output.py` async TTS queue pattern

No unsafe Mark-XXXIX desktop/browser/file-control tools were copied into Qader.

## Dangerous Commands

These require confirmation:
- enabling demo controlled mode
- changing risk settings
- modifying strategy DNA
- running long sessions
- packaging/build updates
- live trading requests

Live trading remains rejected even with confirmation.

