"""
friday_claude_agents.py — FRIDAY AI Pipeline (3 Claude agents via CLI)

يستخدم Claude Code CLI (claude -p) مباشرةً — لا يحتاج ANTHROPIC_API_KEY.
المصادقة من نفس حساب Claude Code الموجود.

الوكلاء:
  1. STRATEGIST — يقرأ vault + swarm + سوق → يضع الخطة
  2. ANALYST    — يقيّم الإشارة → GO/NO-GO
  3. EXECUTOR   — ينفذ المهام → يسجل في الـ vault

تشغيل:
    python friday_claude_agents.py
    python friday_claude_agents.py --query "حلل السوق الآن"
    python friday_claude_agents.py --mode live
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.live import Live
from rich.text import Text

# ── Paths ──────────────────────────────────────────────────────────────────────
MT5_ROOT  = Path(r"C:\Users\Radhi\MT5")
VAULT     = Path(r"C:\Users\Radhi\MT5\plutobrain")
INBOX     = VAULT / "inbox"
MT5_DATA  = Path(r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files")

console = Console()


# ── Context loaders ────────────────────────────────────────────────────────────

def _read(p: Path, limit: int = 900) -> str:
    try:
        return p.read_text(encoding="utf-8")[:limit]
    except Exception:
        return f"(not found: {p})"


def load_vault() -> str:
    return (
        f"=== hot.md ===\n{_read(VAULT/'hot.md')}\n\n"
        f"=== GOALS.md ===\n{_read(VAULT/'GOALS.md', 600)}\n\n"
        f"=== patterns.md ===\n{_read(VAULT/'patterns.md', 500)}"
    )


def load_swarm() -> str:
    for p in [MT5_DATA / "friday_agents.json", MT5_ROOT / "friday_agents.json"]:
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                agents = d.get("agents", [])
                coord  = d.get("coordinator", {})
                lines  = [f"Coordinator: {coord.get('decision','?')} ({coord.get('confidence','?')}%)"]
                for a in agents:
                    lines.append(
                        f"  {a.get('emoji','')} {a.get('role','?')}: "
                        f"{a.get('decision','?')} ({a.get('confidence','?')}%) — "
                        f"{a.get('thought','')[:80]}"
                    )
                return "\n".join(lines)
            except Exception:
                pass
    return "(swarm غير مشغّل — شغّل friday_agents.py أولاً)"


def load_market() -> str:
    for p in [MT5_DATA / "ea_realtime_status.json",
               MT5_DATA / "ea_bar_history.json",
               MT5_DATA / "friday_realtime_bar.json"]:
        if p.exists():
            try:
                d   = json.loads(p.read_text(encoding="utf-8"))
                cur = d.get("current", d)
                return (
                    f"Symbol: XAUUSDm | Price: {cur.get('close', cur.get('price','?'))}\n"
                    f"ATR: {cur.get('atr_points','?')}pt | RSI: {cur.get('rsi','?')} | "
                    f"Spread: {cur.get('spread_points','?')}pt\n"
                    f"Mode: {'Swing' if cur.get('market_mode')==1 else 'Scalp'} | "
                    f"Gap: {cur.get('dna_gap','?')}pt | "
                    f"TP: {cur.get('dna_tp','?')}$ | SL: {cur.get('dna_sl','?')}$\n"
                    f"Balance: {cur.get('balance','?')} | Equity: {cur.get('equity','?')} | "
                    f"Losses: {cur.get('loss_streak','?')}"
                )
            except Exception:
                pass
    return "(لا بيانات MT5 — EA غير مشغّل)"


# ── Claude CLI runner — streams JSON and prints live ──────────────────────────

def run_agent(name: str, color: str, system_prompt: str,
              user_prompt: str, cwd: str = str(MT5_ROOT)) -> str:
    """
    Calls:  claude -p "<prompt>" --output-format stream-json --print
    Streams the JSON events and prints thinking + text live.
    Returns the final text response.
    """
    console.print()
    console.print(Rule(f"[bold {color}]{name}[/bold {color}]", style=color))

    # Build the full prompt (system + user merged, since --system-prompt may need escaping)
    full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

    # stream-json requires --verbose; use json for single-shot output
    cmd = [
        "claude", "-p", full_prompt,
        "--output-format", "json",
        "--print",
        "--dangerously-skip-permissions",
    ]

    result_text: list[str] = []

    try:
        console.print(f"[dim italic]◆ {name} يعمل...[/]")
        proc = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )

        if proc.returncode != 0:
            console.print(f"[red]Agent error (code {proc.returncode}):[/red] {proc.stderr[:400]}")
        else:
            stdout = proc.stdout.strip()
            # JSON output format wraps in {"result": "...", "type": "result"}
            try:
                data = json.loads(stdout)
                text = data.get("result", stdout)
            except json.JSONDecodeError:
                text = stdout

            result_text.append(text)
            # Print colored with a blank line before each section
            for paragraph in text.split("\n"):
                if paragraph.startswith("##"):
                    console.print()
                console.print(f"[{color}]{paragraph}[/{color}]")

    except subprocess.TimeoutExpired:
        console.print(f"[red]Agent timeout (300s): {name}[/red]")
    except FileNotFoundError:
        console.print("[red]خطأ: claude CLI غير موجود. تأكد من تثبيت Claude Code.[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]خطأ: {e}[/red]")

    console.print()
    return "".join(result_text)


# ── Agent prompts ──────────────────────────────────────────────────────────────

def make_strategist_prompt(vault: str, swarm: str, market: str, query: str) -> tuple[str, str]:
    system = """أنت وكيل الاستراتيجية في نظام FRIDAY.
مهمتك: اقرأ سياق الـ vault + حالة الوكلاء + السوق، ثم أنتج خطة منظمة بثلاثة أقسام:

## التقييم الآن
- ما حالة النظام؟ هل هناك bugs مفتوحة (SL، kill-switch، LIVE_TRADING_ENABLED)؟
- هل نسير نحو أهداف GOALS.md؟
- هل يظهر أي نمط من patterns.md الآن؟

## الأولوية الواحدة اليوم
- الإجراء ذو أعلى تأثير الآن على FRIDAY.

## مهام للمنفذ
قائمة مرقمة بإجراءات محددة قابلة للتنفيذ.

كن مباشراً. لا ثرثرة. الإجابة بالعربية."""

    user = f"""سياق الـ vault:
{vault}

حالة الوكلاء:
{swarm}

بيانات السوق:
{market}

سؤال المستخدم: {query}

أنتج الخطة الآن."""
    return system, user


def make_analyst_prompt(plan: str, market: str) -> tuple[str, str]:
    system = """أنت وكيل التحليل في FRIDAY.
أنتج:
## جودة الإشارة
- قيّم الإشارة: ثقة LOW/MEDIUM/HIGH + السبب + البنية (SMC/fractal).
## المخاطر
- خطر العمل vs عدم العمل. مشاكل SL/kill-switch؟
## التوصية
- GO / NO-GO / WAIT + شرط التغيير.
الإجابة بالعربية. XAUUSDm M1. Paper trading افتراضياً."""

    user = f"""خطة الاستراتيجي:
{plan}

بيانات السوق:
{market}

أنتج التقرير الآن."""
    return system, user


def make_executor_prompt(plan: str, analysis: str, mode: str) -> tuple[str, str]:
    system = """أنت وكيل التنفيذ في FRIDAY.
أنتج:
## الإجراءات
لكل مهمة: [DONE] / [SKIPPED] / [FLAGGED] / [QUEUED] + السبب.
## تحديثات الـ Vault
ما يُكتب في inbox. أي تحديثات hot.md.
## تمهيد الجلسة التالية
جملتان: ما حدث + ما التالي.
لا تُفعّل live trading إلا بتأكيد. علّم دائماً على SL/kill-switch. الإجابة بالعربية."""

    user = f"""خطة الاستراتيجي:
{plan}

تقرير المحلل:
{analysis}

وضع التداول: {mode.upper()}

نفّذ الآن."""
    return system, user


# ── Session save ───────────────────────────────────────────────────────────────

def save_session(symbol: str, query: str, mode: str,
                 plan: str, analysis: str, execution: str) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d-%H%M%S")
    body = f"""---
type: agent-session
captured: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
source: friday-claude-agents
symbol: {symbol}
mode: {mode}
---

# جلسة FRIDAY الذكية — {datetime.now().strftime('%Y-%m-%d %H:%M')}

**الرمز:** {symbol} | **الوضع:** {mode} | **السؤال:** {query}

---

## الاستراتيجي

{plan}

---

## المحلل

{analysis}

---

## المنفذ

{execution}
"""
    fp = INBOX / f"{ts}-agent-session.md"
    fp.write_text(body, encoding="utf-8")

    log = VAULT / "log.md"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M')} — /agents — "
                f"pipeline ran | {symbol} | {mode} | {query[:50]}")

    console.print(f"[green]✓[/] محفوظ → [dim]inbox/{fp.name}[/]")


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(symbol: str, query: str, mode: str) -> None:
    console.print()
    console.print(Panel(
        f"[bold white]FRIDAY — الوكلاء الذكيون[/bold white]\n"
        f"الرمز: [cyan]{symbol}[/cyan]  |  الوضع: [magenta]{mode.upper()}[/magenta]\n"
        f"السؤال: [italic]{query}[/italic]\n"
        f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        title="[bold]3 وكلاء يفكرون ويخططون وينفذون[/bold]",
        border_style="white", expand=False
    ))

    with console.status("[dim]جارٍ تحميل السياق...[/]"):
        vault  = load_vault()
        swarm  = load_swarm()
        market = load_market()

    console.print(f"[dim]vault: {len(vault)} ح | swarm: {len(swarm)} ح | market: {len(market)} ح[/]")

    # Agent 1
    sys1, usr1 = make_strategist_prompt(vault, swarm, market, query)
    plan = run_agent("STRATEGIST — الاستراتيجي", "blue", sys1, usr1)

    # Agent 2 (fed by Agent 1)
    sys2, usr2 = make_analyst_prompt(plan, market)
    analysis = run_agent("ANALYST — المحلل", "yellow", sys2, usr2)

    # Agent 3 (fed by Agents 1+2)
    sys3, usr3 = make_executor_prompt(plan, analysis, mode)
    execution = run_agent("EXECUTOR — المنفذ", "green", sys3, usr3)

    save_session(symbol, query, mode, plan, analysis, execution)

    console.print()
    console.print(Panel(
        "[bold green]Pipeline اكتمل.[/bold green]\n\n"
        "الخطوات التالية:\n"
        "  [cyan]cd plutobrain && claude[/cyan]  → افتح vault في Claude Code\n"
        "  [cyan]/sync[/cyan]                    → وجّه inbox إلى vault graph\n"
        "  [cyan]/query[/cyan] [سؤالك]          → اسأل الـ vault أي سؤال",
        border_style="green", expand=False
    ))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSDm")
    ap.add_argument("--mode",   default="paper", choices=["paper", "live"])
    ap.add_argument("--query",  default="حلل الوضع الحالي وأعطني الأولوية الواحدة لهذا اليوم")
    args = ap.parse_args()

    if args.mode == "live":
        console.print("[bold red]تحذير: وضع LIVE.[/bold red]")
        console.print("[red]⚠ SL on entry: BUG مفتوح | Kill-switch: غير مكتمل[/red]")
        ok = input("اكتب 'CONFIRM LIVE': ")
        if ok.strip() != "CONFIRM LIVE":
            args.mode = "paper"

    run_pipeline(args.symbol, args.query, args.mode)


if __name__ == "__main__":
    main()
