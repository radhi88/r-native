from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
PROJECT_MAP_FILE = Path(r"C:\Users\Radhi\MT5\friday_project_map.json")

FAST_MODEL = "llama3:latest"
GENERAL_MODEL = "llama3:latest"
CODER_MODEL = "qwen2.5:3b-instruct"
VISION_MODEL = "llava:latest"

MODEL = FAST_MODEL

MODEL = FAST_MODEL
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:3b-instruct"
FRIDAY_GATEWAY = os.getenv("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8799").rstrip("/")

MEMORY_FILE = Path("friday_chat_memory.json")
PENDING_FILE = Path("friday_pending_dispatch.json")

app = FastAPI(title="FRIDAY Jarvis Chat", version="1.2.0")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "friday_chat",
        "gateway": FRIDAY_GATEWAY,
    }


class ChatRequest(BaseModel):
    message: str


def load_json(path: Path, default):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_memory() -> list[dict[str, str]]:
    return load_json(MEMORY_FILE, [])


def save_memory(memory: list[dict[str, str]]) -> None:
    save_json(MEMORY_FILE, memory[-40:])


def save_pending_task(task: str) -> None:
    save_json(PENDING_FILE, {"task": task})


def load_pending_task() -> str | None:
    data = load_json(PENDING_FILE, {})
    task = data.get("task")

    if isinstance(task, str) and task.strip():
        return task.strip()

    return None


def clear_pending_task() -> None:
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()


def safe_get(url: str, timeout: int = 20) -> Any:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "url": url}


def safe_post(url: str, payload: dict[str, Any], timeout: int = 60) -> Any:
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "url": url}


def live_state() -> dict[str, Any]:
    return {
        "gateway_health": safe_get(f"{FRIDAY_GATEWAY}/health"),
        "context": safe_get(f"{FRIDAY_GATEWAY}/openjarvis/context"),
        "dispatch_jobs": safe_get(f"{FRIDAY_GATEWAY}/dispatch/jobs", timeout=30),
        "dispatch_patches": safe_get(f"{FRIDAY_GATEWAY}/dispatch/patches", timeout=30),
        "pending_dispatch_task": load_pending_task(),
    }


def compact_jobs_text() -> str:
    data = safe_get(f"{FRIDAY_GATEWAY}/dispatch/jobs", timeout=30)
    rows = data.get("rows", []) if isinstance(data, dict) else []

    if not rows:
        return "ما لقيت Jobs حالياً."

    lines = ["آخر مهام الوكلاء:"]

    for row in rows[:8]:
        lines.append(
            f"- Job #{row.get('id')} | {row.get('status')} | "
            f"model={row.get('model')} | report={row.get('report_path') or 'لم يصدر بعد'}"
        )

    return "\n".join(lines)


def compact_patches_text() -> str:
    data = safe_get(f"{FRIDAY_GATEWAY}/dispatch/patches", timeout=30)
    rows = data.get("rows", []) if isinstance(data, dict) else []

    if not rows:
        return "ما لقيت Patch Proposals حالياً."

    lines = ["آخر Patch Proposals:"]

    for row in rows[:12]:
        lines.append(
            f"- Patch #{row.get('id')} | "
            f"{row.get('agent_name')}/{row.get('agent_role')} | "
            f"{row.get('target_file')} | "
            f"risk={row.get('risk')} | "
            f"approved={row.get('approved')} | "
            f"applied={row.get('applied')}"
        )

    return "\n".join(lines)


def find_latest_report() -> tuple[int | None, str | None]:
    jobs = safe_get(f"{FRIDAY_GATEWAY}/dispatch/jobs", timeout=30)
    rows = jobs.get("rows", []) if isinstance(jobs, dict) else []

    for row in rows:
        if row.get("status") == "done" and row.get("report_path"):
            return row.get("id"), row.get("report_path")

    return None, None


def latest_report_text(max_chars: int = 12000) -> str:
    job_id, report_path = find_latest_report()

    if not report_path:
        return "ما لقيت تقرير جاهز حالياً."

    path = Path(report_path)

    if not path.exists():
        return f"لقيت التقرير في قاعدة البيانات لكنه غير موجود على المسار:\n{report_path}"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ما قدرت أقرأ التقرير:\n{e}"

    return (
        f"آخر تقرير هو Job #{job_id}\n"
        f"المسار:\n{report_path}\n\n"
        f"محتوى التقرير:\n\n"
        f"{text[:max_chars]}"
    )


def summarize_latest_report() -> str:
    job_id, report_path = find_latest_report()

    if not report_path:
        return "ما لقيت تقرير جاهز حالياً."

    path = Path(report_path)

    if not path.exists():
        return f"لقيت التقرير في قاعدة البيانات لكنه غير موجود على المسار:\n{report_path}"

    try:
        report = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ما قدرت أقرأ التقرير:\n{e}"

    prompt = f"""
أنت FRIDAY Jarvis.

لخص التقرير التالي بالعربية بشكل عملي وواضح.

المطلوب:
1. ما هدف التقرير؟
2. ما الذي أنجزه الوكلاء؟
3. أهم النتائج.
4. هل توجد patches تحتاج حذر؟
5. أول 5 خطوات آمنة بعدها.
6. قرارك المختصر: نكمل ماذا الآن؟

تقرير Job #{job_id}:
{report[:20000]}
"""

    payload = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": "أنت مساعد محلي ذكي. تحدث بالعربية فقط. لا تقترح تنفيذ أوامر مالية أو أوامر MT5.",
            },
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": 0.25,
            "num_ctx": 12000,
        },
    }

    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=240)
        r.raise_for_status()
        answer = r.json()["message"]["content"]
    except Exception as e:
        return f"قرأت التقرير، لكن لم أستطع تلخيصه عبر Ollama:\n{e}\n\nالمسار:\n{report_path}"

    return (
        f"ملخص آخر تقرير — Job #{job_id}\n"
        f"المسار:\n{report_path}\n\n"
        f"{answer}"
    )



def load_project_map() -> dict[str, Any]:
    if not PROJECT_MAP_FILE.exists():
        return {}

    try:
        return json.loads(PROJECT_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def project_map_text() -> str:
    project_map = load_project_map()

    if not project_map:
        return "FRIDAY Project Map غير موجود. شغلي: python .\\friday_project_map.py"

    summary = project_map.get("summary", {})
    categories = summary.get("categories", {})

    lines = [
        "FRIDAY Project Map",
        "",
        f"Version: {project_map.get('map_version')}",
        f"Generated: {project_map.get('generated_at')}",
        f"Total files: {summary.get('total_files')}",
        "",
        "Categories:",
    ]

    for name, count in categories.items():
        lines.append(f"- {name}: {count}")

    lines.append("")
    lines.append("Safe edit allowlist:")

    for item in summary.get("safe_edit_allowlist", []):
        lines.append(f"- {item}")

    return "\\n".join(lines)


def safe_files_text() -> str:
    project_map = load_project_map()

    if not project_map:
        return "FRIDAY Project Map غير موجود."

    safe_files = project_map.get("summary", {}).get("safe_edit_allowlist", [])

    if not safe_files:
        return "لا توجد ملفات safe edit allowlist."

    lines = ["Safe Edit Files:"]

    for item in safe_files:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("أي تطبيق Patch خارج هذه القائمة يجب رفضه.")

    return "\\n".join(lines)


def sensitive_files_text() -> str:
    project_map = load_project_map()

    if not project_map:
        return "FRIDAY Project Map غير موجود."

    sensitive = project_map.get("summary", {}).get("sensitive_files", [])

    if not sensitive:
        return "لا توجد ملفات حساسة مصنفة."

    lines = ["Sensitive Files — قراءة فقط حالياً:"]

    for item in sensitive[:50]:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("هذه الملفات لا نطبق عليها أي Patch إلا بعد بناء MT5 Safe Controller.")

    return "\\n".join(lines)



def prepare_dispatch_task(user_message: str) -> str:
    task = (
        "افحص مشروع FRIDAY MT5 قراءة فقط. "
        "لا تعدل ملفات. لا تحذف. لا تنفذ أي أوامر مالية أو أوامر MT5. "
        "المطلوب: قيّم حالة ربط OpenJarvis وOpenClaw مع FRIDAY Local Gateway وFRIDAY Dispatch، "
        "واستخرج أول 5 خطوات آمنة لتطوير واجهة FRIDAY Jarvis Chat بحيث تدير الوكلاء والتقارير والـ patches بعد موافقة المستخدم."
    )

    if ":" in user_message:
        extra = user_message.split(":", 1)[1].strip()
        if extra:
            task = (
                extra
                + " اقرأ فقط. لا تعدل ملفات. لا تحذف. لا تنفذ أي أوامر مالية أو أوامر MT5."
            )

    save_pending_task(task)

    return (
        "جهزت مهمة للوكلاء ولم أشغلها بعد.\n\n"
        f"نص المهمة المقترحة:\n{task}\n\n"
        "للتشغيل اكتبي بالضبط:\nوافق، شغل الوكلاء"
    )


def run_pending_dispatch() -> str:
    task = load_pending_task()

    if not task:
        return (
            "ما عندي مهمة جاهزة للتشغيل.\n"
            "اكتبي أولاً: جهز مهمة للوكلاء"
        )

    payload = {
        "task": task,
        "max_agents": 3,
        "files_per_agent": 5,
        "chars_per_file": 2200,
        "ctx": 8192,
    }

    result = safe_post(f"{FRIDAY_GATEWAY}/dispatch/run", payload, timeout=60)

    if isinstance(result, dict) and result.get("error"):
        return f"حاولت أشغل الوكلاء لكن صار خطأ:\n{result.get('error')}"

    clear_pending_task()

    return (
        "تم تشغيل الوكلاء عبر FRIDAY Local Gateway.\n\n"
        f"النتيجة:\n{json.dumps(result, ensure_ascii=False, indent=2)}\n\n"
        "انتظري دقيقة أو دقيقتين، ثم اكتبي: عرض آخر jobs"
    )


def intercept_command(message: str) -> str | None:
    msg = message.strip().lower()

    if "جهز مهمة للوكلاء" in msg or "جهّز مهمة للوكلاء" in msg:
        return prepare_dispatch_task(message)

    if "وافق، شغل الوكلاء" in message or "وافق شغل الوكلاء" in message:
        return run_pending_dispatch()

    if "عرض آخر jobs" in msg or "اعرض آخر jobs" in msg or "عرض الجوبات" in msg:
        return compact_jobs_text()

    if "عرض patches" in msg or "اعرض patches" in msg or "عرض الباتشات" in msg:
        return compact_patches_text()

    if "project map" in msg or "خريطة المشروع" in msg:
        return project_map_text()

    if "safe files" in msg or "الملفات الآمنة" in msg:
        return safe_files_text()

    if "sensitive files" in msg or "الملفات الحساسة" in msg:
        return sensitive_files_text()

    if "ما المهمة الجاهزة" in msg or "وش المهمة الجاهزة" in msg:
        task = load_pending_task()
        return f"المهمة الجاهزة:\n{task}" if task else "لا توجد مهمة جاهزة حالياً."

    if "لخص آخر تقرير" in msg or "ملخص آخر تقرير" in msg:
        return summarize_latest_report()

    if "اعرض آخر تقرير" in msg or "آخر تقرير" in msg:
        return latest_report_text()

    return None


def ask_ollama(message: str) -> str:
    command_answer = intercept_command(message)

    if command_answer is not None:
        memory = load_memory()
        memory.append({"user": message, "assistant": command_answer})
        save_memory(memory)
        return command_answer

    memory = load_memory()
    state = live_state()

    system_prompt = """
أنت FRIDAY Jarvis، مساعد محلي ذكي يشبه ChatGPT.

تتكلم مع المستخدم بالعربية الطبيعية كأنك شخص حي فاهم المشروع.
لا تردد نصوص ثابتة.
لا تقل إنك مجرد سكربت.
حلل الحالة الحالية، اربط المعلومات، واسأل أسئلة ذكية عند الحاجة.

أنت مربوط فكريًا مع:
- FRIDAY MT5
- OpenClaw
- OpenJarvis
- Ollama qwen2.5:3b-instruct
- FRIDAY Local Gateway
- FRIDAY Agent Dispatch
- MySQL Agents DB

قدراتك الآمنة داخل الشات:
- تجهيز مهمة للوكلاء بدون تشغيلها.
- تشغيل Dispatch فقط بعد عبارة موافقة صريحة: "وافق، شغل الوكلاء".
- عرض آخر jobs.
- عرض آخر patches.
- عرض آخر تقرير.
- تلخيص آخر تقرير.

قواعد الأمان:
- لا تنفذ أي أوامر مالية.
- لا تنفذ أوامر MT5.
- لا تعدل ملفات بدون موافقة صريحة.
- لا تحذف ملفات.
- لا تشغل سكربتات طويلة بدون موافقة.
- أي تعديل يكون Patch Proposal قبل التطبيق.

أسلوبك:
- عربي واضح.
- ذكي وعملي.
- تكلم كأنك فاهم السياق كامل.
- إذا كان هناك Job running قل إن الوكلاء يعملون الآن.
- إذا وجدت patches غير معتمدة، قل إنها تحتاج تحقق قبل التطبيق.
"""

    messages = [{"role": "system", "content": system_prompt}]

    for item in memory[-12:]:
        if item.get("user"):
            messages.append({"role": "user", "content": item["user"]})
        if item.get("assistant"):
            messages.append({"role": "assistant", "content": item["assistant"]})

    messages.append(
        {
            "role": "user",
            "content": f"""
رسالة المستخدم:
{message}

الحالة الحية الحالية للأنظمة:
{json.dumps(state, ensure_ascii=False, indent=2)[:18000]}

جاوب كـ FRIDAY Jarvis بالعربية الطبيعية.
""",
        }
    )

    payload = {
        "model": MODEL,
        "stream": False,
        "messages": messages,
        "options": {
            "temperature": 0.45,
            "num_ctx": 12000,
        },
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=240)
    r.raise_for_status()
    answer = r.json()["message"]["content"]

    memory.append({"user": message, "assistant": answer})
    save_memory(memory)

    return answer


@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>FRIDAY Jarvis Chat</title>
  <style>
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #0f1117;
      color: #f5f5f5;
    }

    .wrap {
      max-width: 1050px;
      margin: auto;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }

    header {
      padding: 18px;
      border-bottom: 1px solid #2a2d38;
      font-size: 22px;
      font-weight: bold;
    }

    #chat {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
    }

    .msg {
      padding: 14px 16px;
      border-radius: 14px;
      margin-bottom: 14px;
      line-height: 1.7;
      white-space: pre-wrap;
    }

    .user {
      background: #1f6feb;
      margin-left: 90px;
    }

    .bot {
      background: #20232d;
      margin-right: 90px;
    }

    .tools {
      display: flex;
      gap: 8px;
      padding: 12px 16px;
      border-top: 1px solid #2a2d38;
      flex-wrap: wrap;
    }

    .tools button {
      width: auto;
      padding: 10px 14px;
      background: #30363d;
    }

    .bar {
      display: flex;
      gap: 10px;
      padding: 16px;
      border-top: 1px solid #2a2d38;
    }

    textarea {
      flex: 1;
      resize: none;
      height: 58px;
      border-radius: 12px;
      border: 1px solid #343847;
      padding: 12px;
      background: #151821;
      color: white;
      font-size: 16px;
      direction: rtl;
    }

    button {
      width: 120px;
      border: 0;
      border-radius: 12px;
      background: #2ea043;
      color: white;
      font-size: 16px;
      font-weight: bold;
      cursor: pointer;
    }

    button:hover {
      opacity: 0.9;
    }

    .small {
      font-size: 13px;
      color: #aaa;
      margin-top: 4px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      FRIDAY Jarvis Chat
      <div class="small">محادثة محلية ذكية — Ollama + OpenJarvis + OpenClaw + FRIDAY Dispatch</div>
    </header>

    <div id="chat"></div>

    <div class="tools">
      <button onclick="quick('جهز مهمة للوكلاء')">جهز مهمة للوكلاء</button>
      <button onclick="quick('وافق، شغل الوكلاء')">وافق وشغل</button>
      <button onclick="quick('عرض آخر jobs')">عرض Jobs</button>
      <button onclick="quick('عرض patches')">عرض Patches</button>
      <button onclick="quick('لخص آخر تقرير')">لخص آخر تقرير</button>
      <button onclick="quick('اعرض آخر تقرير')">اعرض آخر تقرير</button>
      <button onclick="quick('وش تشوف الحين؟')">وش الحالة؟</button>
    </div>

    <div class="bar">
      <textarea id="input" placeholder="اكتبي له كأنك تكلمين شخص حي..."></textarea>
      <button onclick="send()">إرسال</button>
    </div>
  </div>

<script>
const chat = document.getElementById("chat");
const input = document.getElementById("input");

function add(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function quick(text) {
  input.value = text;
  send();
}

async function send() {
  const text = input.value.trim();

  if (!text) {
    return;
  }

  input.value = "";

  add("user", text);
  add("bot", "أفكر...");

  const botMsg = chat.lastChild;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text})
    });

    const data = await res.json();

    botMsg.textContent = data.answer || data.error || "ما وصلني رد.";
  } catch (e) {
    botMsg.textContent = "صار خطأ في الاتصال: " + e;
  }
}

input.addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

async function loadHistory() {
  try {
    const res = await fetch("/history");
    const data = await res.json();
    const messages = data.messages || [];

    if (messages.length === 0) {
      add("bot", "أنا FRIDAY Jarvis. كلميني طبيعي. أقدر أجهز مهمة للوكلاء، أشغلها بعد موافقتك، أعرض jobs وpatches، وألخص آخر تقرير.");
      return;
    }

    for (const item of messages) {
      if (item.user) add("user", item.user);
      if (item.assistant) add("bot", item.assistant);
    }
  } catch (e) {
    add("bot", "أنا FRIDAY Jarvis. لم أستطع تحميل المحادثات السابقة، لكنني جاهز الآن.");
  }
}

loadHistory();
</script>
</body>
</html>
"""


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        answer = ask_ollama(req.message)
        return {"answer": answer}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/state")
def state():
    return live_state()

@app.get("/history")
def history():
    memory = load_memory()
    return {"messages": memory[-40:]}


@app.post("/clear-history")
def clear_history():
    save_memory([])
    return {"status": "cleared"}

if __name__ == "__main__":
    uvicorn.run("friday_chat_app:app", host="127.0.0.1", port=8811, reload=False)

