from pathlib import Path
from datetime import datetime
import re

path = Path("main.py")
text = path.read_text(encoding="utf-8", errors="replace")

backup = path.with_name("main.py.bak_screen_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
backup.write_text(text, encoding="utf-8")
print(f"Backup saved: {backup.name}")

# 1) اجعل الراوتر يعتبر أوامر الشاشة أدوات مباشرة
old = '''if any(k in text for k in ["افتح", "شغل", "ارسل", "ذكرني", "ابحث", "open", "send", "search", "click", "type"]):
            return "tool"'''
new = '''if any(k in text for k in [
            "افتح", "شغل", "ارسل", "ذكرني", "ابحث", "open", "send", "search", "click", "type",
            "شوف", "شاشتي", "الشاشة", "سكرين", "screen", "screenshot", "see my screen", "analyze screen"
        ]):
            return "tool"'''
if old in text:
    text = text.replace(old, new, 1)
    print("[OK] router screen keywords added")
else:
    print("[SKIP] router marker not found")

# 2) أضف دالة تعرف طلبات الشاشة مباشرة
marker = '''    async def handle_user_text(self, text: str):'''
method = '''    def _is_screen_request(self, text: str) -> bool:
        lowered = _clean_transcript(text).lower()
        screen_words = [
            "شوف شاشتي", "شوف الشاشة", "حلل شاشتي", "حلل الشاشة",
            "اقرأ شاشتي", "اقرا شاشتي", "وش في الشاشة", "ايش في الشاشة",
            "سكرين", "لقطة الشاشة", "الشاشة", "screen", "screenshot",
            "see my screen", "analyze screen", "read my screen"
        ]
        return any(word in lowered for word in screen_words)

'''
if "_is_screen_request" not in text:
    text = text.replace(marker, method + marker, 1)
    print("[OK] _is_screen_request added")
else:
    print("[SKIP] _is_screen_request already exists")

# 3) خلّه ينفذ screen_process مباشرة قبل ما يسأل الموديل
old = '''                # Deterministic project-agent shortcut prevents weak local models from missing the tool call.
                if self._is_project_request(text):'''
new = '''                # Deterministic screen shortcut prevents weak local models from missing the vision tool call.
                if self._is_screen_request(text):
                    result = await self._execute_tool("screen_process", {"text": text, "angle": "screen"})
                    tool_names_used.append("screen_process")
                    if isinstance(result, dict):
                        final_reply = _clean_transcript(result.get("result") or result.get("response") or str(result))
                    else:
                        final_reply = _clean_transcript(str(result))
                # Deterministic project-agent shortcut prevents weak local models from missing the tool call.
                elif self._is_project_request(text):'''
if old in text:
    text = text.replace(old, new, 1)
    print("[OK] direct screen shortcut added")
else:
    print("[SKIP] handle_user_text marker not found")

# 4) أصلح mss deprecated لو ما تصلح سابقًا
text = text.replace("import mss\\n            import mss.tools", "from mss import MSS\\n            import mss.tools")
text = text.replace("with mss.mss() as sct:", "with MSS() as sct:")

# 5) حسّن رسالة الخطأ إذا llava أو Ollama غير جاهز
old = '''        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))'''
new = '''        try:
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Vision failed: Ollama is not reachable or the vision model is missing. "
                "Run: ollama serve   then: ollama pull llava:latest"
            ) from exc'''
if old in text:
    text = text.replace(old, new, 1)
    print("[OK] vision error message improved")
else:
    print("[SKIP] vision urllib marker not found")

path.write_text(text, encoding="utf-8")
print("Patch completed.")
