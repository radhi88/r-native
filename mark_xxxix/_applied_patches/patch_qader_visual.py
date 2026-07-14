# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

MAIN = Path("main.py")

if not MAIN.exists():
    raise SystemExit("main.py not found. Run from C:\\Users\\Radhi\\MT5\\mark_xxxix")

text = MAIN.read_text(encoding="utf-8", errors="replace")

# Keep original Gemini Live listening defaults.
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

# Restore Gemini tool declarations if an earlier patch disabled them.
text = text.replace(
    "tools=[],",
    'tools=[{"function_declarations": TOOL_DECLARATIONS}],',
)

# Insert direct visual upgrade after ui construction.
if "apply_qader_visual_upgrade(ui)" not in text:
    pattern = re.compile(r'(?m)^(\s*ui\s*=\s*JarvisUI\([^\n]*\)\s*)$')
    match = pattern.search(text)

    if not match:
        raise SystemExit("Could not find ui = JarvisUI(...) line in main.py")

    indent = re.match(r"\s*", match.group(1)).group(0)

    block = (
        match.group(1)
        + "\n\n"
        + indent + "try:\n"
        + indent + "    from qader_visual_upgrade import apply_qader_visual_upgrade\n"
        + indent + "    apply_qader_visual_upgrade(ui)\n"
        + indent + "except Exception as exc:\n"
        + indent + "    try:\n"
        + indent + "        ui.write_log(f\"ERR: Qader visual upgrade failed: {exc}\")\n"
        + indent + "    except Exception:\n"
        + indent + "        print(f\"ERR: Qader visual upgrade failed: {exc}\")"
    )

    text = text[:match.start()] + block + text[match.end():]
    print("[OK] Visual upgrade loader inserted")
else:
    print("[SKIP] Visual upgrade loader already exists")

# Bind callbacks after JarvisOllama instance creation.
if "bind_qader_visual_callbacks(ui, jarvis)" not in text:
    pattern = re.compile(r'(?m)^(\s*jarvis\s*=\s*JarvisOllama\(ui\)\s*)$')
    match = pattern.search(text)

    if not match:
        raise SystemExit("Could not find jarvis = JarvisOllama(ui) line in main.py")

    indent = re.match(r"\s*", match.group(1)).group(0)

    block = (
        match.group(1)
        + "\n\n"
        + indent + "try:\n"
        + indent + "    from qader_visual_upgrade import bind_qader_visual_callbacks\n"
        + indent + "    bind_qader_visual_callbacks(ui, jarvis)\n"
        + indent + "except Exception as exc:\n"
        + indent + "    try:\n"
        + indent + "        ui.write_log(f\"ERR: Qader visual callbacks failed: {exc}\")\n"
        + indent + "    except Exception:\n"
        + indent + "        print(f\"ERR: Qader visual callbacks failed: {exc}\")"
    )

    text = text[:match.start()] + block + text[match.end():]
    print("[OK] Visual callbacks binding inserted")
else:
    print("[SKIP] Visual callbacks binding already exists")

MAIN.write_text(text, encoding="utf-8")

print("[OK] main.py patched")
print("[OK] Voice/microphone defaults preserved")
print("[OK] Direct paint overlay will be visible on the existing UI")
