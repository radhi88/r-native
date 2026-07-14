from pathlib import Path
from datetime import datetime
import re

path = Path("main.py")
if not path.exists():
    raise SystemExit("main.py not found")

text = path.read_text(encoding="utf-8", errors="replace")

backup = path.with_name("main.py.bak_voice_ollama_actions_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print(f"Backup saved: {backup.name}")

def replace_once(old, new, label):
    global text
    if old in text:
        text = text.replace(old, new, 1)
        print(f"[OK] {label}")
    else:
        print(f"[SKIP] {label}")

# 1) Default: keep Gemini Live voice, but do not let Gemini own the microphone/action brain.
replace_once(
'''LIVE_MIC_ENABLED = os.getenv("JARVIS_LIVE_MIC", "1").strip().lower() in TRUE_VALUES
LOCAL_MIC_FALLBACK_ENABLED = os.getenv("JARVIS_LOCAL_MIC_FALLBACK", "0").strip().lower() in TRUE_VALUES''',
'''LIVE_MIC_ENABLED = os.getenv("JARVIS_LIVE_MIC", "0").strip().lower() in TRUE_VALUES
LOCAL_MIC_FALLBACK_ENABLED = os.getenv("JARVIS_LOCAL_MIC_FALLBACK", "1").strip().lower() in TRUE_VALUES''',
"Gemini voice output + local mic/action brain defaults"
)

# 2) Text commands must always go to local Ollama action brain.
replace_once(
'''        if self._voice_backend == "gemini_live" and self._live_session:
            self.ui.write_log(f"You: {_clean_transcript(text)}")
            asyncio.run_coroutine_threadsafe(self._send_live_text(text), self._loop)
            return
        asyncio.run_coroutine_threadsafe(self.handle_user_text(text), self._loop)''',
'''        # Text commands always go to the local Ollama multi-model action brain.
        # Gemini Live remains the voice/speech layer only.
        asyncio.run_coroutine_threadsafe(self.handle_user_text(text), self._loop)''',
"text input routed to Ollama brain"
)

# 3) Local voice transcript must go to Ollama, not back to Gemini reasoning.
replace_once(
'''        if self._voice_backend == "gemini_live" and self._live_session:
            self.ui.write_log(f"You: {text}")
            await self._send_live_text(text)
            return
        await self.handle_user_text(text)''',
'''        # Voice transcript goes to the local Ollama multi-model action brain.
        # The final answer can still be spoken through Gemini Live via self.speak().
        await self.handle_user_text(text)''',
"voice transcript routed to Ollama brain"
)

# 4) Gemini Live should not receive tool declarations anymore.
# It remains the voice layer only. Ollama owns all action decisions.
replace_once(
'''            tools=[{"function_declarations": TOOL_DECLARATIONS}],''',
'''            tools=[],''',
"disabled Gemini direct tool execution"
)

# 5) Strengthen live voice prompt: voice layer only, no action brain.
old_prompt = '''You may use Gemini Live only for listening and speaking with the user.
All real execution, code work, project agents, web/file/computer actions, FRIDAY actions, and vision must go through tools.'''
new_prompt = '''You are only the voice layer. Do not decide or execute real actions.
Local Ollama is the action brain. Gemini Live is used only to speak assistant messages naturally.'''
replace_once(old_prompt, new_prompt, "voice prompt converted to voice-only layer")

# 6) Make route logging more obvious.
replace_once(
'''        self.ui.write_log(f"SYS: Model route={route}, model={model_name}, elapsed={elapsed:.2f}s")''',
'''        self.ui.write_log(f"SYS: ACTION_BRAIN route={route}, model={model_name}, elapsed={elapsed:.2f}s")''',
"clear action-brain route logging"
)

path.write_text(text, encoding="utf-8")
print("Patch completed.")
