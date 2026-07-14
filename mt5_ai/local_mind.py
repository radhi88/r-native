import json
import os
import urllib.error
import urllib.request

from .capabilities import CapabilityBroker
from .hardware import hardware_report
from .neural_memory import NeuralMemory


class LlamaCppClient:
    """HTTP client for a local llama.cpp server.

    Expected server:
      llama-server -m model.gguf --host 127.0.0.1 --port 8080
    """

    def __init__(self, model=None, host=None):
        self.model = model or os.environ.get("MT5_AI_LOCAL_MODEL", "qwen2.5-7b-instruct-q4_k_m")
        self.host = (host or os.environ.get("LLAMA_CPP_HOST", "http://127.0.0.1:8080")).rstrip("/")

    def available(self):
        for path in ("/health", "/v1/models"):
            try:
                with urllib.request.urlopen(f"{self.host}{path}", timeout=2) as response:
                    if response.status < 500:
                        return True
            except Exception:
                continue
        return False

    def generate(self, messages):
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.35,
                "max_tokens": 700,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            return f"llama.cpp error: {body}"
        except Exception as exc:
            return f"llama.cpp unavailable: {exc}"


class LocalMind:
    def __init__(self, memory=None, llm=None, broker=None, event_bus=None):
        self.memory = memory or NeuralMemory()
        self.llm = llm or LlamaCppClient()
        self.broker = broker or CapabilityBroker(memory=self.memory)
        self.event_bus = event_bus

    def status(self):
        return {
            "identity": "FRIDAY Private Local Neural Assistant",
            "cloud": False,
            "llama_cpp_available": self.llm.available(),
            "llama_cpp_host": self.llm.host,
            "llama_cpp_model": self.llm.model,
            "memory": self.memory.stats(),
            "capabilities": {
                "project_files": "brokered",
                "system": "brokered",
                "mt5": "paper_by_default",
                "live_trading": "locked",
            },
        }

    def chat(self, text, assistant):
        self.memory.record_command(text, status="received")
        self.memory.remember("user", text, tags=["chat"], importance=1.0)
        self._event("thinking", {"message": "processing_command"})

        tool_result = self._maybe_use_tool(text, assistant)
        memories = [
            item for item in self.memory.search(text, limit=8)
            if item.get("content") != text
        ]

        if tool_result is not None:
            answer = self._summarize_tool(tool_result)
        elif self.llm.available():
            answer = self._llama_answer(text, tool_result, memories, assistant)
        else:
            answer = self._local_answer(text, tool_result, memories, assistant)

        self.memory.remember("friday", answer, tags=["chat"], importance=0.8)
        self.memory.record_command(text, result=answer[:1000], status="ok")
        self._event("answer", {"answer": answer, "tool_result": tool_result})
        return {
            "answer": answer,
            "tool_result": tool_result,
            "mind": self.status(),
        }

    def _event(self, event_type, payload=None):
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload or {})

    def _maybe_use_tool(self, text, assistant):
        lowered = text.lower()
        if any(
            phrase in lowered
            for phrase in [
                "تجاوز السبريد",
                "تجاهل السبريد",
                "الغاء فلتر السبريد",
                "إلغاء فلتر السبريد",
                "ignore spread",
                "override spread",
            ]
        ):
            return {"type": "risk_override", "data": assistant.set_spread_override(True)}

        if any(
            phrase in lowered
            for phrase in [
                "فعل فلتر السبريد",
                "فعّل فلتر السبريد",
                "ارجع فلتر السبريد",
                "رجع فلتر السبريد",
                "enable spread filter",
                "respect spread",
            ]
        ):
            return {"type": "risk_override", "data": assistant.set_spread_override(False)}

        if any(phrase in lowered for phrase in ["اطيع", "أطيع", "طيعني", "طيعيني", "obey", "ذهب سكالب", "سكالبينج الذهب", "خله يطيعني", "خليها تطيعني"]):
            symbol = "XAUUSDm" if any(word in lowered for word in ["ذهب", "gold", "xau"]) else assistant.state.symbol
            data = assistant.obey_aggressive_scalping(symbol=symbol, mode="demo")
            self._event("tool", {"tool": "obey_aggressive_scalping", "mode": assistant.state.mode})
            return {"type": "obey", "data": data}

        wants_all_markets = any(
            phrase in lowered
            for phrase in [
                "كل الاسواق",
                "كل الأسواق",
                "جميع الاسواق",
                "جميع الأسواق",
                "all markets",
                "market scan",
                "scan markets",
            ]
        )
        wants_trade = any(word in lowered for word in ["تداول", "ادخل", "ادخلي", "دخول", "نفذ", "نفذي", "افتح", "افتحي", "trade", "execute", "open"])
        wants_demo = any(phrase in lowered for phrase in ["demo", "demo mt5", "ديمو", "ديمو mt5", "تجريبي", "تجريبي mt5", "حساب وهمي"])
        wants_paper = any(phrase in lowered for phrase in ["paper", "ورقي"])

        # Critical fix: do not treat "نفذي ديمو MT5" as a mode-only command.
        # It means: switch to Demo MT5, then execute the last/next suitable decision.
        if wants_trade and wants_demo:
            assistant.state.source = "mt5"
            assistant.set_mode("demo")
            decision = assistant.last_decision or assistant.analyze()
            gate = self.broker.authorize("mt5", "demo_trade", {"decision": decision})
            if not gate.allowed:
                return {"type": "blocked", "data": gate.__dict__, "decision": decision}
            self._event("tool", {"tool": "demo_trade", "mode": assistant.state.mode})
            result = assistant.execute_decision(decision)
            self.memory.record_trade(
                mode=assistant.state.mode,
                symbol=assistant.state.symbol,
                side=decision.get("action", "NO_TRADE"),
                payload=json.dumps(result, ensure_ascii=True),
                sent=bool(result.get("executed")),
            )
            return {"type": "execution", "data": result}

        if wants_trade and wants_paper:
            assistant.set_mode("paper")
            decision = assistant.last_decision or assistant.analyze()
            gate = self.broker.authorize("mt5", "paper_trade", {"decision": decision})
            if not gate.allowed:
                return {"type": "blocked", "data": gate.__dict__, "decision": decision}
            self._event("tool", {"tool": "paper_trade", "mode": assistant.state.mode})
            result = assistant.execute_decision(decision)
            self.memory.record_trade(
                mode=assistant.state.mode,
                symbol=assistant.state.symbol,
                side=decision.get("action", "NO_TRADE"),
                payload=json.dumps(result, ensure_ascii=True),
                sent=bool(result.get("executed")),
            )
            return {"type": "execution", "data": result}

        if "demo mt5" in lowered or "ديمو mt5" in lowered or "حساب وهمي" in lowered or (wants_demo and not wants_trade):
            return {"type": "mode", "data": {"message": assistant.set_mode("demo")}}

        if "paper" in lowered or "ورقي" in lowered:
            return {"type": "mode", "data": {"message": assistant.set_mode("paper")}}

        if wants_all_markets and wants_trade:
            broker_action = "demo_trade" if assistant.state.mode == "demo" else "paper_trade"
            gate = self.broker.authorize("mt5", broker_action, {"scope": "all_markets"})
            if not gate.allowed:
                return {"type": "blocked", "data": gate.__dict__}
            self._event("tool", {"tool": "market_scan_trade", "mode": assistant.state.mode})
            if assistant.state.mode == "demo":
                return {"type": "market_scan_execution", "data": assistant.execute_market_scan_demo()}
            return {"type": "market_scan_execution", "data": assistant.execute_market_scan_paper()}

        if wants_all_markets:
            decision = self.broker.authorize("mt5", "analyze", {"scope": "all_markets"})
            if not decision.allowed:
                return {"type": "blocked", "data": decision.__dict__}
            self._event("tool", {"tool": "market_scan"})
            return {"type": "market_scan", "data": assistant.scan_markets()}

        if any(word in lowered for word in ["حلل", "analyze", "تحليل", "السوق"]):
            decision = self.broker.authorize("mt5", "analyze", {"source": assistant.state.source})
            if not decision.allowed:
                return {"type": "blocked", "data": decision.__dict__}
            self._event("tool", {"tool": "analyze"})
            return {"type": "analysis", "data": assistant.analyze()}

        if wants_trade:
            decision = assistant.analyze()
            if assistant.state.mode == "paper":
                action = "paper_trade"
            elif assistant.state.mode == "demo":
                action = "demo_trade"
            else:
                action = "live_trade"
            gate = self.broker.authorize("mt5", action, {"decision": decision})
            if not gate.allowed:
                return {"type": "blocked", "data": gate.__dict__, "decision": decision}
            self._event("tool", {"tool": "trade", "mode": assistant.state.mode})
            result = assistant.execute_decision(decision)
            self.memory.record_trade(
                mode=assistant.state.mode,
                symbol=assistant.state.symbol,
                side=decision.get("action", "NO_TRADE"),
                payload=json.dumps(result, ensure_ascii=True),
                sent=bool(result.get("executed")),
            )
            return {"type": "execution", "data": result}

        if any(word in lowered for word in ["حالة", "status"]):
            return {"type": "status", "data": assistant.status()}

        if any(word in lowered for word in ["gpu", "كرت", "الشاشة"]):
            gate = self.broker.authorize("system", "hardware_status", {})
            if not gate.allowed:
                return {"type": "blocked", "data": gate.__dict__}
            return {"type": "hardware", "data": hardware_report()}

        if any(word in lowered for word in ["النظام", "صلاحيات", "جهازي", "system"]):
            return {"type": "system", "data": self.broker.system_snapshot()}

        remember_intents = [
            "تذكري أن",
            "تذكري ان",
            "تذكر أن",
            "تذكر ان",
            "احفظ ",
            "احفظي",
            "remember that",
            "remember:",
        ]
        if any(phrase in lowered for phrase in remember_intents):
            gate = self.broker.authorize("memory", "remember", {"text": text})
            if not gate.allowed:
                return {"type": "blocked", "data": gate.__dict__}
            if any(word in lowered for word in ["أفضل", "افضل", "prefer"]):
                self.memory.set_fact("trading_preference", text)
            self.memory.remember("user_fact", text, tags=["explicit_memory"], importance=2.0)
            return {"type": "memory", "data": {"saved": True}}

        return None

    def _llama_answer(self, text, tool_result, memories, assistant):
        messages = self._build_messages(text, tool_result, memories, assistant)
        return self.llm.generate(messages)

    def _build_messages(self, text, tool_result, memories, assistant):
        memory_text = "\n".join(
            f"- [{item['role']}] {item['content']}" for item in memories
        )
        tool_text = json.dumps(tool_result, ensure_ascii=False, indent=2) if tool_result else "No tool used."
        status_text = json.dumps(assistant.status(), ensure_ascii=False, indent=2)
        system = """
أنت FRIDAY — مساعد تداول محلي خاص. تعمل دون إنترنت. تتحدث العربية بشكل مختصر ودقيق.
لديك: ذاكرة محلية، نموذج Keras للتنبؤ، مؤشرات SMC (Smart Money Concepts)، ومنفذ صفقات ورقية/ديمو.

مهمتك الأساسية: تحليل ذهب XAUUSDm وتقديم قرارات تداول واضحة بناءً على:
- احتمالية النموذج (prob): > 0.68 = BUY، < 0.32 = SELL
- SMC Score: نقاط BOS + CHoCH + FVG + OB = جودة الإشارة
- ADX > 20 = ترند قوي، RSI (30-70 = محايد، خارج = متطرف)

قواعد الرد:
1. إذا كان الاحتمال قوياً → قل البيانات ثم القرار مباشرة
2. اذكر السبب بجملة واحدة فقط
3. لا تحتاج مقدمات، لا إطناب، لا ترحيب
4. التداول الحقيقي محظور — الديمو والورقي مسموح فقط
""".strip()
        user = f"""
System status:
{status_text}

Relevant local memory:
{memory_text}

Tool result:
{tool_text}

User said:
{text}

Reply briefly and practically. If there is a trading decision, explain the reason.
""".strip()
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _local_answer(self, text, tool_result, memories, assistant):
        if tool_result:
            return self._summarize_tool(tool_result)

        lowered = text.lower()
        if any(word in lowered for word in ["تفضيل", "صفقات", "prefer"]):
            preference = self.memory.get_fact("trading_preference")
            if preference:
                return f"أتذكر تفضيلك المحلي: {preference}"
        if "من انت" in lowered or "who are you" in lowered:
            return (
                "أنا FRIDAY المحلي الخاص بك: ذاكرة عصبية SQLite، عقل تداول، "
                "وموصل MT5 وصلاحيات عبر بوابة أمان. نموذج المحادثة الكبير سيعمل عبر llama.cpp "
                "بعد تثبيت GGUF محلي."
            )
        if "نموذج" in lowered or "model" in lowered:
            return (
                "نموذج التداول الخاص بك موجود في models/hybrid_model.keras. "
                "نموذج المحادثة المحلي المستهدف هو GGUF عبر llama.cpp على 127.0.0.1:8080. "
                "الذاكرة الخاصة موجودة في data/journal/jarvis_memory.sqlite3."
            )
        if memories:
            remembered = self._select_memory(memories)["content"]
            return f"استرجعت من ذاكرتي المحلية: {remembered}\nقل لي: حللي السوق، أو اعرضي حالة النظام."
        return (
            "أنا FRIDAY شغالة محليًا بذاكرة وأدوات تداول. نموذج llama.cpp غير متصل بعد، "
            "لكن أقدر أحلل السوق، أحفظ ذاكرة، وأدير Paper Trading."
        )

    def _select_memory(self, memories):
        explicit = [item for item in memories if "explicit_memory" in (item.get("tags") or "")]
        if explicit:
            return explicit[0]
        conversational = [
            item for item in memories
            if not self._looks_like_question(item.get("content", ""))
        ]
        return (conversational or memories)[0]

    @staticmethod
    def _looks_like_question(text):
        lowered = (text or "").strip().lower()
        return (
            "؟" in lowered
            or "?" in lowered
            or lowered.startswith(("ما ", "وش ", "هل ", "what ", "which "))
        )

    def _summarize_tool(self, tool_result):
        data = tool_result.get("data")
        kind = tool_result.get("type")
        if kind == "analysis":
            action = data.get("action")
            reason = self._arabic_reason(data.get("reason"))
            probability = data.get("probability")
            spread = data.get("spread")
            ignored = data.get("spread_filter_ignored")
            probability_text = f"{float(probability):.3f}" if probability is not None else "غير متاح"
            spread_text = "غير متاح" if spread is None else str(spread)
            override_text = " تم تجاهل فلتر السبريد لهذا التحليل." if ignored else ""
            return (
                f"حللت السوق: القرار {action}. الاحتمال {probability_text}، "
                f"السبريد {spread_text}. السبب: {reason}.{override_text}"
            )
        if kind == "execution":
            executed = data.get("executed")
            reason = self._arabic_reason(data.get("reason") or data.get("result", {}).get("reason"))
            decision = data.get("decision") or {}
            symbol = decision.get("symbol", "")
            action = decision.get("action", "")
            return f"أمر التنفيذ انتهى. التنفيذ={executed}. الرمز {symbol}، القرار {action}. السبب: {reason}."
        if kind == "market_scan":
            return self._summarize_market_scan(data)
        if kind == "market_scan_execution":
            scan = data.get("scan", {})
            executions = data.get("executions", [])
            base = self._summarize_market_scan(scan)
            sent = sum(1 for item in executions if item.get("executed"))
            mode = data.get("mode", "paper")
            return f"{base}\nوضع التنفيذ: {mode}. أوامر منفذة: {sent} من {len(executions)}."
        if kind == "blocked":
            return f"أوقفت الأمر عبر بوابة الصلاحيات: {data.get('reason')}."
        if kind in {"status", "hardware", "system"}:
            return json.dumps(data, ensure_ascii=False, indent=2)
        if kind == "memory":
            return "حفظت المعلومة في ذاكرتي المحلية."
        if kind == "mode":
            return data.get("message", "تم تغيير الوضع.")
        if kind == "risk_override":
            return data.get("message", "تم تحديث فلتر السبريد.")
        return json.dumps(tool_result, ensure_ascii=False, indent=2)

    @staticmethod
    def _summarize_market_scan(data):
        scanned = data.get("scanned", 0)
        tradable = data.get("tradable", [])
        top = data.get("top", [])
        if tradable:
            picks = ", ".join(
                f"{item['symbol']} {item['action']} ({LocalMind._arabic_reason(item.get('reason'))})"
                for item in tradable[:5]
            )
            return f"مسحت {scanned} سوق. أفضل فرص قابلة للتنفيذ: {picks}."
        if top:
            picks = ", ".join(
                f"{item['symbol']} {item['action']} ({LocalMind._arabic_reason(item.get('reason'))})"
                for item in top[:5]
            )
            return f"مسحت {scanned} سوق. لا توجد BUY/SELL الآن. أعلى المرشحين: {picks}."
        errors = data.get("errors", [])
        return f"لم أجد رموزًا قابلة للمسح. الأخطاء: {len(errors)}."

    @staticmethod
    def _arabic_reason(reason):
        if not reason:
            return "غير محدد"
        text = str(reason)
        if text.startswith("spread_too_high:"):
            value = text.split(":", 1)[1]
            return f"السبريد مرتفع ({value})"
        translations = {
            "filters_not_aligned": "الفلاتر لم تتوافق بعد",
            "model_and_smc_buy": "النموذج و SMC متوافقان على الشراء",
            "model_and_smc_sell": "النموذج و SMC متوافقان على البيع",
            "no_trade": "لا توجد صفقة مناسبة الآن",
            "decision_not_tradeable": "القرار غير قابل للتنفيذ",
        }
        return translations.get(text, text)
