# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

MAIN = Path("main.py")

if not MAIN.exists():
    raise SystemExit("main.py not found. Run this from C:\\Users\\Radhi\\MT5\\mark_xxxix")

text = MAIN.read_text(encoding="utf-8", errors="replace")

# Restore original Gemini Live mic defaults.
text = re.sub(
    r'LIVE_MIC_ENABLED\s*=\s*os\.getenv\("JARVIS_LIVE_MIC",\s*"[^"]*"\)\.strip\(\)\.lower\(\)\s+in\s+TRUE_VALUES',
    'LIVE_MIC_ENABLED = os.getenv("JARVIS_LIVE_MIC", "1").strip().lower() in TRUE_VALUES',
    text,
    count=1,
)

text = re.sub(
    r'LOCAL_MIC_FALLBACK_ENABLED\s*=\s*os\.getenv\("JARVIS_LOCAL_MIC_FALLBACK",\s*"[^"]*"\)\.strip\(\)\.lower\(\)\s+in\s+TRUE_VALUES',
    'LOCAL_MIC_FALLBACK_ENABLED = os.getenv("JARVIS_LOCAL_MIC_FALLBACK", "0").strip().lower() in TRUE_VALUES',
    text,
    count=1,
)

# Restore Gemini Live tool declarations if any previous patch disabled them.
text = text.replace(
    "tools=[],",
    'tools=[{"function_declarations": TOOL_DECLARATIONS}],',
)

# Modernize MSS warning only. This does not affect voice.
text = text.replace(
    "import mss\n            import mss.tools",
    "from mss import MSS\n            import mss.tools",
)

text = text.replace(
    "with mss.mss() as sct:",
    "with MSS() as sct:",
)

# Add UI upgrade loader after JarvisUI construction.
if "apply_qader_ui_upgrade(ui)" not in text:
    marker = '    ui = JarvisUI("face.png")'

    if marker not in text:
        marker = "    ui = JarvisUI('face.png')"

    if marker not in text:
        raise SystemExit('Could not find ui = JarvisUI("face.png") in main.py')

    insert = marker + '''
    
    try:
        from ui_screen_upgrade import apply_qader_ui_upgrade
        apply_qader_ui_upgrade(ui)
    except Exception as exc:
        try:
            ui.write_log(f"ERR: UI upgrade failed to load: {exc}")
        except Exception:
            print(f"ERR: UI upgrade failed to load: {exc}")
'''

    text = text.replace(marker, insert, 1)
    print("[OK] UI upgrade loader inserted")
else:
    print("[SKIP] UI upgrade loader already exists")

# Bind screen callbacks after JarvisOllama instance is created.
if "bind_qader_callbacks(ui, jarvis)" not in text:
    marker = "        jarvis = JarvisOllama(ui)"

    if marker not in text:
        raise SystemExit("Could not find jarvis = JarvisOllama(ui) in main.py")

    insert = marker + '''
        
        try:
            from ui_screen_upgrade import bind_qader_callbacks
            bind_qader_callbacks(ui, jarvis)
        except Exception as exc:
            try:
                ui.write_log(f"ERR: Screen callback binding failed: {exc}")
            except Exception:
                print(f"ERR: Screen callback binding failed: {exc}")
'''

    text = text.replace(marker, insert, 1)
    print("[OK] Screen callbacks binding inserted")
else:
    print("[SKIP] Screen callbacks binding already exists")

MAIN.write_text(text, encoding="utf-8")

print("[OK] main.py patched safely")
print("[OK] Gemini Live mic defaults are restored")
print("[OK] _listen_live_audio and _send_live_text were not modified by this patch")
