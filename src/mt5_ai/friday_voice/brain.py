from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any, Iterable

from .config import FridayVoiceConfig, log_event
from .command_router import CommandResult
from .memory import FridayMemory


SYSTEM_PROMPT = """You are FRIDAY — a real-time local AI assistant built for a professional Windows trading workstation.
You are modeled after JARVIS: fast, precise, confident, never verbose.

IDENTITY:
- You are the voice interface of FRIDAY, a live algorithmic trading system
- You only receive commands from the user (Radhi). No other service sends you commands
- You DO NOT execute trades or trigger service restarts unless explicitly ordered

CAPABILITIES:
- Control the Windows device (open apps, take screenshots of multiple monitors, check system health)
- Query live MT5 market data, account balance, positions, and pending orders
- Monitor and report on FRIDAY trading services (gateway :8799, chat :8811, dashboard :8822, agents :8833, brain :8844, jarvis_agent :8855)
- Access conversation memory and trading event history
- Describe what is on screen (single or all monitors)

LIVE SYSTEM CONTEXT:
- Algory genetic trading engine is LIVE on a demo account
- Trading symbols: EURUSDm, GBPUSDm, USDJPYm, AUDUSDm, USDCADm, NZDUSDm, USDCHFm, XAUUSDm
- Timeframes: M15, H1, H4
- Active services: indicator_engine, orderflow_engine, feature_learner, trade_learner, brain_loop, gateway, brain_server, chat, dashboard, agents_browser, autopilot, algory_runner, health_monitor

VOICE RULES (strictly enforced):
- Reply in 1 to 3 short spoken sentences by default — never longer
- No markdown, no bullet points, no headers, no asterisks
- Speak naturally — like a calm, confident assistant
- If the user speaks Arabic, reply entirely in Arabic
- Numbers and symbols (XAUUSDm, $, %, pip) stay as-is in Arabic replies
- Never explain how you work unless directly asked
- When a device action was already executed, confirm it in one sentence

MARKET RULES:
- Do not invent prices, balances, or positions
- If tool context is provided, use it and cite it briefly
- Do not execute trades or modify MT5 without proof from tool context
- Always distinguish READ (observation) from WRITE (execution)

TONE:
- Confident and direct — not robotic
- Helpful without being sycophantic
- Treat the user as a professional trader who values brevity"""


class OllamaBrain:
    def __init__(self, config: FridayVoiceConfig, memory: FridayMemory):
        self.config = config
        self.memory = memory
        self._resolved_model: str | None = None

    def _messages(self, command: CommandResult) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        for item in self.memory.recent_turns(limit=4):
            user = self._short(item.get("user"), 500)
            assistant = self._short(item.get("assistant"), 500)
            if user:
                messages.append({"role": "user", "content": user})
            if assistant:
                messages.append({"role": "assistant", "content": assistant})

        context = ""
        if command.tool_context:
            context = self._compact_tool_context(command)[:2500]

        content = command.user_text
        reply_language_hint = ""
        if self._looks_arabic(command.user_text):
            reply_language_hint = "\n\nFinal instruction: reply in Arabic only. Keep numbers and symbols as-is."
        if context:
            content += f"\n\nTool context:\n{context}"
        if command.direct_response:
            content += f"\n\nRouter note:\n{command.direct_response}"
        content += reply_language_hint

        messages.append({"role": "user", "content": content})
        return messages

    @staticmethod
    def _short(value: Any, limit: int = 240) -> str:
        text = str(value or "").strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _looks_arabic(text: str) -> bool:
        return any("\u0600" <= char <= "\u06ff" for char in text)

    def _compact_tool_context(self, command: CommandResult) -> str:
        if command.category == "STATUS":
            status = command.tool_context.get("system_status") or {}
            mt5 = status.get("mt5") or {}
            services = status.get("services") or {}
            up = [name for name, ok in services.items() if ok]
            down = [name for name, ok in services.items() if not ok]
            return (
                f"STATUS time={status.get('time')} symbol={status.get('symbol')} timeframe={status.get('timeframe')} "
                f"readonly={status.get('readonly')} services_up={up} services_down={down} "
                f"balance={mt5.get('balance')} equity={mt5.get('equity')} profit={mt5.get('profit')} "
                f"trade_allowed={mt5.get('trade_allowed')} trade_expert={mt5.get('trade_expert')}"
            )

        if command.category == "MARKET_ANALYSIS":
            snap = command.tool_context.get("market_snapshot") or {}
            account = snap.get("account") or {}
            tick = snap.get("tick") or {}
            positions = snap.get("positions") or []
            orders = snap.get("orders") or []
            rates = snap.get("rates") or []
            council = ((snap.get("feature_council") or {}).get("latest") or {})
            closes = [row.get("close") for row in rates[-5:] if isinstance(row, dict)]
            order_brief = [
                {
                    "type": row.get("type"),
                    "price": row.get("price"),
                    "sl": row.get("sl"),
                    "tp": row.get("tp"),
                }
                for row in orders[:5]
                if isinstance(row, dict)
            ]
            position_profit = round(sum(float(row.get("profit") or 0.0) for row in positions if isinstance(row, dict)), 2)
            return (
                f"MARKET symbol={snap.get('symbol')} time={snap.get('time')} "
                f"bid={tick.get('bid')} ask={tick.get('ask')} spread_points={tick.get('spread_points')} "
                f"balance={account.get('balance')} equity={account.get('equity')} account_profit={account.get('profit')} "
                f"positions_count={len(positions)} positions_profit={position_profit} orders_count={len(orders)} "
                f"orders={order_brief} closes={closes} "
                f"council_action={council.get('action')} confidence={council.get('confidence')} "
                f"trade_type={council.get('trade_type')} signature={council.get('feature_signature')}"
            )

        if command.category == "MEMORY_QUERY":
            hits = command.tool_context.get("memory_hits") or []
            compact_hits = []
            for hit in hits[:4]:
                if isinstance(hit, dict):
                    compact_hits.append(
                        {
                            "time": hit.get("time"),
                            "category": hit.get("category"),
                            "user": self._short(hit.get("user"), 180),
                            "assistant": self._short(hit.get("assistant"), 180),
                        }
                    )
            return f"MEMORY hits={compact_hits}"

        return json.dumps(command.tool_context, ensure_ascii=False, default=str)[:2000]

    def stream_response(self, command: CommandResult, interrupt: threading.Event | None = None) -> Iterable[str]:
        if command.direct_response and not command.tool_context:
            yield command.direct_response
            return

        model = self._select_model()

        payload = {
            "model": model,
            "stream": True,
            "messages": self._messages(command),
            "options": {
                "temperature": self.config.llm_temperature,
                "num_ctx": self.config.llm_num_ctx,
                "num_predict": self.config.max_response_tokens,
            },
        }

        req = urllib.request.Request(
            f"{self.config.ollama_host.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.llm_timeout_seconds) as response:
                log_event("BRAIN", f"streaming model={model}")
                for raw in response:
                    if interrupt is not None and interrupt.is_set():
                        log_event("BRAIN", "generation interrupted")
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    token = ((data.get("message") or {}).get("content") or "")
                    if token:
                        yield token
                    if data.get("done"):
                        break

        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log_event("ERROR", f"ollama unavailable: {exc}")
            yield self._fallback(command)

    def warmup(self) -> None:
        model = self._select_model()
        payload = {
            "model": model,
            "prompt": "OK",
            "stream": False,
            "options": {"num_predict": 1, "temperature": 0, "num_ctx": 512},
        }
        req = urllib.request.Request(
            f"{self.config.ollama_host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.llm_timeout_seconds):
                log_event("BRAIN", f"warmup complete model={model}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log_event("ERROR", f"warmup skipped: {exc}")

    def _select_model(self) -> str:
        if self._resolved_model:
            return self._resolved_model

        installed = self._installed_models()
        if not installed:
            return self.config.ollama_model

        candidates = [
            self.config.ollama_model,
            "qwen2.5:3b-instruct",
            "qwen2.5:1.5b-instruct",
            "phi3:mini",
            "llama3.2:3b",
            "qwen3:4b",
            "qwen3:2b",
            "llama3:8b-instruct-q4_K_M",
            "llama3:latest",
        ]

        installed_lower = {name.lower(): name for name in installed}
        for candidate in candidates:
            found = installed_lower.get(candidate.lower())
            if found:
                self._resolved_model = found
                if found != self.config.ollama_model:
                    log_event("BRAIN", f"configured model missing; using installed model={found}")
                return found

        self._resolved_model = installed[0]
        log_event("BRAIN", f"using first installed model={self._resolved_model}")
        return self._resolved_model

    def _installed_models(self) -> list[str]:
        req = urllib.request.Request(
            f"{self.config.ollama_host.rstrip('/')}/api/tags",
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            models = data.get("models") if isinstance(data, dict) else []
            if not isinstance(models, list):
                return []
            names = [str(item.get("name") or item.get("model")) for item in models if isinstance(item, dict)]
            return [name for name in names if name and name != "None"]
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return []

    def _fallback(self, command: CommandResult) -> str:
        arabic = self._looks_arabic(command.user_text)

        if command.category == "STATUS" and command.tool_context:
            status = command.tool_context.get("system_status") or {}
            services = status.get("services") or {}
            ok_count = sum(1 for ok in services.values() if ok)
            if arabic:
                return f"الموديل المحلي بطيء لكن أدواتي شغالة. {ok_count} خدمات متاحة."
            return f"Local model is slow, but tools are working. {ok_count} services are reachable."

        if command.category == "MARKET_ANALYSIS" and command.tool_context:
            snap = command.tool_context.get("market_snapshot") or {}
            tick = snap.get("tick") or {}
            positions = snap.get("positions") or []
            orders = snap.get("orders") or []
            if arabic:
                return (
                    f"الموديل المحلي بطيء. {snap.get('symbol')} bid هو {tick.get('bid')}، "
                    f"عندنا {len(positions)} مركز و{len(orders)} أمر معلق."
                )
            return f"Local model slow. {snap.get('symbol')} bid is {tick.get('bid')}, {len(positions)} positions, {len(orders)} orders."

        if arabic:
            return "الموديل المحلي مش متاح الحين. أنا ما زلت أسمعك وأقدر أقرأ بيانات MT5."
        return "The local model is not reachable right now. I can still listen and read local MT5 tools."


