"""Quick audio device check + Gemini Live audio test."""
import asyncio
import json
from pathlib import Path
import sounddevice as sd

print("=== Audio Devices ===")
for d in sd.query_devices():
    if d['max_output_channels'] > 0 or d['max_input_channels'] > 0:
        tag = []
        if d['max_output_channels'] > 0:
            tag.append("OUT")
        if d['max_input_channels']  > 0:
            tag.append("IN")
        print(f"  [{d['index']:2d}] {'/'.join(tag):<7} {d['name']}")

try:
    print(f"\nDefault OUT: {sd.query_devices(kind='output')['name']}")
    print(f"Default IN:  {sd.query_devices(kind='input')['name']}")
except Exception as e:
    print(f"Device error: {e}")

# Quick beep test
print("\n=== Playing 440Hz tone for 1s (you should hear a beep) ===")
try:
    import numpy as np
    fs   = 24000
    t    = np.linspace(0, 1, fs, dtype="float32")
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    sd.play(tone, samplerate=fs, blocking=True)
    print("Beep OK — speakers working.")
except Exception as e:
    print(f"Beep FAILED: {e}")

# Gemini Live audio test
print("\n=== Gemini Live connection test ===")
async def test_live():
    from google import genai
    from google.genai import types

    cfg_path = Path(__file__).parent / "config" / "api_keys.json"
    key = json.loads(cfg_path.read_text())["gemini_api_key"]

    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    model  = "models/gemini-2.5-flash-native-audio-latest"

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="Say: مرحباً راضي، أنا جارفيس",
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        ),
    )

    print(f"Connecting to {model}...")
    received_bytes = 0
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send_client_content(
                turns={"parts": [{"text": "مرحباً"}]},
                turn_complete=True,
            )
            stream = sd.RawOutputStream(samplerate=24000, channels=1, dtype="int16", blocksize=1024)
            stream.start()
            async for resp in session.receive():
                if resp.data:
                    received_bytes += len(resp.data)
                    stream.write(resp.data)
                if resp.server_content and resp.server_content.turn_complete:
                    break
            stream.stop()
            stream.close()
    except Exception as e:
        print(f"Live error: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"Received {received_bytes} audio bytes.")
    if received_bytes == 0:
        print("WARNING: No audio data — model may not support audio output.")
    else:
        print("Audio OK — JARVIS should speak.")

asyncio.run(test_live())
