from pathlib import Path
from datetime import datetime
import sys

path = Path("main.py")
if not path.exists():
    raise SystemExit("main.py not found. Run this from C:\\Users\\Radhi\\MT5\\mark_xxxix")

text = path.read_text(encoding="utf-8", errors="replace")
backup = path.with_name("main.py.bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print(f"Backup saved: {backup.name}")

def replace_once(src: str, old: str, new: str, label: str) -> str:
    if old not in src:
        print(f"[SKIP] marker not found: {label}")
        return src
    print(f"[OK] patched: {label}")
    return src.replace(old, new, 1)

# 1) Suppress noisy Gemini mixed response warning only as fallback protection
old = 'warnings.filterwarnings("ignore", category=FutureWarning)'
new = '''warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=r".*non-data parts in the response.*")'''
text = replace_once(text, old, new, "Gemini non-data warning filter")

# 2) Add robust audio extractor to avoid response.data warning
helper = r'''
def _extract_live_audio_data(response: Any) -> bytes:
    """
    Extract audio bytes from Gemini Live responses without using response.data first.
    response.data can emit noisy warnings when the response also includes text/thought parts.
    """
    chunks: List[bytes] = []

    def add(value: Any) -> None:
        if not value:
            return
        if isinstance(value, bytes):
            chunks.append(value)
        elif isinstance(value, bytearray):
            chunks.append(bytes(value))
        elif isinstance(value, str):
            try:
                chunks.append(base64.b64decode(value))
            except Exception:
                chunks.append(value.encode("utf-8", errors="ignore"))

    try:
        server_content = getattr(response, "server_content", None)
        model_turn = getattr(server_content, "model_turn", None) if server_content else None
        parts = getattr(model_turn, "parts", None) if model_turn else None

        for part in parts or []:
            inline_data = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
            if inline_data is not None:
                add(getattr(inline_data, "data", None))
            add(getattr(part, "data", None))
    except Exception:
        pass

    if chunks:
        return b"".join(chunks)

    # Last-resort compatibility fallback for older google-genai versions.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r".*non-data parts in the response.*")
            add(getattr(response, "data", None))
    except Exception:
        pass

    return b"".join(chunks)
'''

marker = '''
def _is_bad_transcript(text: str) -> bool:
'''
if "_extract_live_audio_data" not in text:
    text = text.replace(marker, helper + "\n\n" + marker, 1)
    print("[OK] added: _extract_live_audio_data")
else:
    print("[SKIP] helper already exists")

# 3) Fix mss deprecation: mss.mss() -> MSS()
old = '''    def _capture_screen_png_for_vision(self) -> bytes:
        try:
            import mss
            import mss.tools
        except Exception as exc:
            raise RuntimeError(f"mss is not installed: {exc}") from exc
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)
'''
new = '''    def _capture_screen_png_for_vision(self) -> bytes:
        try:
            from mss import MSS
            import mss.tools
        except Exception as exc:
            raise RuntimeError(f"mss is not installed: {exc}") from exc
        with MSS() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            return mss.tools.to_png(shot.rgb, shot.size)
'''
text = replace_once(text, old, new, "mss.MSS migration")

# 4) Avoid response.data direct access in Gemini Live receiver
old = '''                async for response in self._live_session.receive():
                    if response.data and self.audio_in_queue:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
'''
new = '''                async for response in self._live_session.receive():
                    audio_data = _extract_live_audio_data(response)
                    if audio_data and self.audio_in_queue:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(audio_data)

                    if response.server_content:
'''
text = replace_once(text, old, new, "Gemini Live response.data replacement")

# 5) Make JARVIS more action-first, Claude-Code-like, without bypassing destructive guards
old = '''You are JARVIS running locally on Ollama. No Gemini. No paid API dependency.
'''
new = '''You are JARVIS running locally on Ollama. No Gemini. No paid API dependency.
Act as an action-first local operator similar to Claude Code: when a user asks for a local/project/computer action, choose the correct tool and execute instead of giving generic refusals. If a direct action is blocked by runtime policy or unavailable, attempt the safest valid alternative and report the exact blocker briefly.
'''
text = replace_once(text, old, new, "action-first system behavior")

old = '''- Runtime policy is authoritative. If a request is blocked by guards, state the block briefly and do not bypass it.
'''
new = '''- Runtime policy is authoritative, but do not refuse allowed local/project requests. Execute with tools first. If blocked, state the exact block briefly and offer or run the nearest safe allowed alternative.
'''
text = replace_once(text, old, new, "less false refusal rule")

# 6) Add more deterministic project-agent triggers
old = '''            "اختبر قدراته", "مراقبه", "مراقبة", "كامل الصلاحيات", "mark_xxxix", "jatvis",
'''
new = '''            "اختبر قدراته", "مراقبه", "مراقبة", "كامل الصلاحيات", "mark_xxxix", "jatvis",
            "jarvis", "claude", "claude code", "مثل claude", "يتحكم بكل شيء",
            "تحكم كامل", "كامل التحكم", "ما يرفض", "لا يرفض", "عالج جميع مشاكله",
            "fix all", "control everything", "autonomous", "full control",
'''
text = replace_once(text, old, new, "project request triggers")

path.write_text(text, encoding="utf-8")
print("Patch completed.")
