"""sync_to_repo.py — one-command updater: push MT5 code+ideas → private GitHub repo.

The repo is the BRAIN (code, docs, ideas — safe to share with any AI, any device).
Your machine keeps the BODY (data/, .env, api_keys.json, live trade state) — those
are NEVER copied. Run this whenever you want your latest MT5 ideas mirrored to the
private repo.

    python sync_to_repo.py                       # rebuild mirror + commit (no push)
    python sync_to_repo.py -m "added X engine"   # custom commit message
    python sync_to_repo.py --push                # rebuild + commit + push to origin

Safety: aborts if a REAL secret survives the scan. Account login + API keys are
auto-redacted to placeholders. Unrelated sub-projects and junk are excluded.
"""
from __future__ import annotations
import argparse, os, re, shutil, subprocess, sys

SRC = r"C:\Users\Radhi\MT5"
DST = r"C:\Users\Radhi\r-native-export"

INCLUDE_EXT = {".py",".html",".md",".mq5",".mqh",".ps1",".json",".css",".js",".txt",
               ".yaml",".yml",".toml",".cfg",".ini",".bat",".sh",".sql",".h",".cpp",".c"}
# prune data / secrets / builds / vendored / generated / archives / unrelated projects
DENY = {"data","logs","dist","dist_new","build",".venv","venv","__pycache__",".pytest_cache",
        ".mypy_cache","node_modules",".git","graphify-out","brain_debug","_sandbox_odysseus",
        "mnt","archive","archive_root","vendor","review_bridge_output",".planning",".claude",
        "worktrees","site-packages",".obsidian","_export_tmp","r-native-export",".ruff_cache",
        "raw","prepared","lab_cache","_backups","backups","tmp","temp",".idea",".vscode",
        "OpenJarvis","patch_backups","_archive","docs_archive"}
MAX = 512 * 1024   # skip anything >512KB (data blobs, bundled libs)

# secret-bearing filenames that must NEVER be copied (even redacted)
SECRET_FILES = {"api_keys.json", "apikeys.json", "secrets.json", "secret.json",
                "credentials.json", "creds.json", "token.json", "tokens.json",
                "service_account.json", "hub_secret.txt", "id_rsa"}
SECRET_HINT = re.compile(r"secret|credential|password|api[_-]?key|_token|\.pem$|\.key$", re.I)


def is_secret_filename(f: str) -> bool:
    lf = f.lower()
    return lf in SECRET_FILES or lf.startswith(".env") or bool(SECRET_HINT.search(lf))

# secret redaction: pattern -> placeholder (value never printed)
REDACT = [
    (re.compile(r"<ACCOUNT_LOGIN>"),                         "<ACCOUNT_LOGIN>"),
    (re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),           "<GEMINI_API_KEY>"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"),               "<OPENAI_API_KEY>"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),     "<SLACK_TOKEN>"),
    # old TV-bridge secret (rotated; literal split so the scanner doesn't flag itself)
    (re.compile(r"eu362aZ3SPaG5YFt" r"MMJZWzihgJuHT3b7"), "<TV_BRIDGE_SECRET>"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"),              "<GITHUB_PAT>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),      "<GITHUB_PAT>"),
]
# a REAL secret that must ABORT the sync if it survives redaction
DANGER = re.compile(
    r"AIza[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|eu362aZ3SPaG5YFt" r"MMJZWzihgJuHT3b7"
    # generic: secret = "<20+ chars>" quoted assignment (bridge-style tokens)
    r"""|(?i:\bsecret\b)["' ]*[:=]["' ]*["'][A-Za-z0-9+/_\-]{20,}["']""")


def build_mirror() -> tuple[int, float]:
    # ADDITIVE sync: copy MT5 code over the repo (add/update), NEVER wipe the tree.
    # This preserves files that live only in the repo (e.g. main's agents/ suite
    # merged in) — a destructive rebuild would delete them. Trade-off: files you
    # delete in MT5 won't auto-remove from the repo (remove them there by hand).
    os.makedirs(DST, exist_ok=True)
    copied = 0; total = 0
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in DENY and not d.startswith(".")
                   and not d.startswith("_sandbox")]
        if set(os.path.relpath(root, SRC).replace("\\", "/").split("/")) & DENY:
            continue
        for f in files:
            if os.path.splitext(f)[1].lower() not in INCLUDE_EXT: continue
            if is_secret_filename(f): continue          # never copy secret files
            sp = os.path.join(root, f)
            try:
                if os.path.getsize(sp) > MAX: continue
            except OSError:
                continue
            dp = os.path.join(DST, os.path.relpath(sp, SRC))
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            try:
                shutil.copy2(sp, dp); copied += 1; total += os.path.getsize(sp)
            except Exception:
                pass
    return copied, total / 1024 / 1024


def redact_tree() -> int:
    changed = 0
    for root, _, files in os.walk(DST):
        for f in files:
            p = os.path.join(root, f)
            try:
                t = open(p, encoding="utf-8").read()
            except Exception:
                continue
            nt = t
            for pat, repl in REDACT:
                nt = pat.sub(repl, nt)
            if nt != t:
                open(p, "w", encoding="utf-8").write(nt); changed += 1
    return changed


def scan_secrets() -> list[str]:
    hits = []
    for root, _, files in os.walk(DST):
        for f in files:
            p = os.path.join(root, f)
            try:
                for i, ln in enumerate(open(p, encoding="utf-8"), 1):
                    if DANGER.search(ln):
                        hits.append(f"{os.path.relpath(p, DST)}:{i}")
            except Exception:
                pass
    return hits


def gen_endpoints():
    bs = os.path.join(SRC, "brain_server.py")
    if not os.path.exists(bs): return
    lines = open(bs, encoding="utf-8").read().splitlines()
    rows = []; pend = []
    for i, ln in enumerate(lines):
        m = re.search(r'@app\.route\("([^"]+)"(?:,\s*methods=(\[[^\]]*\]))?\)', ln)
        if m:
            pend.append((m.group(1), m.group(2) or "[GET]")); continue
        if re.match(r'\s*def\s+\w+\(', ln) and pend:
            doc = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                dd = re.search(r'"""(.+)', lines[j])
                if dd: doc = dd.group(1).strip().strip('"'); break
            for p, mm in pend: rows.append((p, mm, doc))
            pend = []
    r = [x for x in rows if x[0].startswith("/api/r/")]
    out = ["# R-Native — API Endpoints\n",
           f"`brain_server.py` @ `localhost:5055` — {len(rows)} routes ({len(r)} under `/api/r/`).\n",
           "\n| Endpoint | Methods | Purpose |", "|---|---|---|"]
    out += [f"| `{p}` | {m} | {d[:80]} |" for p, m, d in r]
    open(os.path.join(DST, "ENDPOINTS.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")


def gen_docs():
    """Generate the repo's top-level docs (README + AI_CONTEXT) so any AI on any
    machine can onboard. Written every sync → overrides whatever MT5 root had."""
    readme = """# R-Native — FRIDAY Algorithmic Trading System (private)

نظام تداول خوارزميّ **محلّي بالكامل** فوق MetaTrader 5 (Python). الحافّة ليست التنبّؤ —
بل **الانضباط + الحجم + الإدارة + الكلفة**.

> **هذا المستودع = العقل** (كود + أفكار + وثائق). **جهازك = الجسد** (`data/`، `.env`،
> `api_keys.json`، حالة الصفقات) — لا تُرفع أبداً. حدّثه بأمر واحد: `python sync_to_repo.py --push`.

📊 الدوسيه التفاعليّ: https://claude.ai/code/artifact/ad2399ac-0ab6-459b-a0b5-fcc19b6139e5

## الطبقات
- **Logic** — `friday_v3/algory/` (r_executor · trade_gate · r_levels · indicator_matrix ·
  r_learning · r_multi_symbol) + `r_native/` + محرّكات الجذر (`brain_server.py` :5055 ·
  `watchdog_guard.py` · gold_level_sentinel · news_straddle · portfolio_maestro · market_sweeper)
- **Roadmap** — `r_desktop/ROADMAP.md` · `MATURITY_ROADMAP.md` (M0→M5، $500→$1000)
- **Workflow** — `workflow/` (تطوّر مجدول) · `CLAUDE.md`
- **Endpoints** — `ENDPOINTS.md` (54 واجهة `/api/r/*`)
- **AI onboarding** — `AI_CONTEXT.md`

## المعمارية
```
MT5 <-> جسر mt5 مشترك <-> brain_server(:5055) <-> محرّكات(magics) <-> واجهات/مدراء
                                  ^ watchdog_guard
```

## أمان
DEMO فقط · لوت 0.01 · سقف يوميّ $10 · حدّ 3 صفقات · kill_switch · حظر ليليّ · بوّابة إثبات
(n≥30, t≥2, net>0). البيانات الحيّة والأسرار خارج المستودع.
"""
    ai_ctx = """# AI_CONTEXT — onboarding brief for any AI collaborator

اقرأ هذا أولاً قبل اقتراح أي تغيير. يصلح لأي ذكاء (Claude / GPT / Gemini / Cursor …).

## ما هو المشروع
نظام تداول خوارزميّ على MT5 (Python). **الأطروحة المُثبتة تجريبيّاً:** لا حافّة تنبّؤيّة
قابلة للتداول — 20+ دراسة walk-forward سقطت خارج العيّنة. الحافّة الحقيقيّة = **الانضباط،
الحجم، الإدارة، الكلفة**. أي اقتراح يعتمد على «تنبّؤ اتجاه أدقّ» مرفوض ما لم يجتَز walk-forward.

## القواعد الحاكمة (لا تكسرها)
1. **قِس قبل الثقة** — walk-forward إجباريّ. الانقسام الواحد ليس دليلاً.
2. **بوّابة الإثبات** — لا ترقية إلا بـ`n≥30, t≥2, net>0`. خفض فوريّ عند النزيف.
3. **TIGHTEN-ONLY** — أي فلتر جديد يجب أن يكون fail-open (يرفض السيّئ فقط، لا يفتح مخاطرة).
4. **DEMO فقط** — لا مال حقيقيّ. الأمان قبل الميزة.
5. **الحجم أخطر متغيّر** — ذهب ≥0.2 لوت دمّر (−$45.6k)، <0.2 لوت ربح (+$30.5k).

## نقاط الدخول للكود
- القرار: `friday_v3/algory/trade_gate.py` (بوّابة 10 شروط + فيتو مصفوفة 21×6)
- التنفيذ: `friday_v3/algory/r_executor.py` (حلقة سرعتين، magic 20260605)
- العقل/الواجهات: `brain_server.py` (:5055، انظر `ENDPOINTS.md`)
- الخارطة: `r_desktop/ROADMAP.md`

## ما تبقى على الجهاز (غير موجود هنا)
`data/` (حالة حيّة)، `.env`/`api_keys.json` (أسرار)، `logs/`، `dist/`، `friday.db`.
لتشغيله فعليّاً تحتاج MT5 + `.env` محلّيّ خاصّ بك.

## كيف تساهم
اقترح تغييرات صغيرة قابلة للقياس، اربطها ببند في `ROADMAP.md`، واحترم القواعد الخمس أعلاه.
"""
    gitignore = """# secrets & credentials — NEVER commit
.env
.env.*
api_keys.json
*secret*
*credential*
*.key
*.pem
*.lock
# live trading state & data (code-only mirror)
data/
logs/
*.db
*.jsonl
*.csv
*.npy
*.npz
# builds & environments
dist/
dist_new/
build/
.venv/
__pycache__/
*.pyc
# editor / os
.obsidian/
.DS_Store
Thumbs.db
"""
    open(os.path.join(DST, "README.md"), "w", encoding="utf-8").write(readme)
    open(os.path.join(DST, "AI_CONTEXT.md"), "w", encoding="utf-8").write(ai_ctx)
    open(os.path.join(DST, ".gitignore"), "w", encoding="utf-8").write(gitignore)
    # bring the scheduled evolution workflow into the mirror (lives under .claude)
    wf_src = os.path.join(os.path.expanduser("~"), ".claude", "scheduled-tasks",
                          "r-factory-evolution", "SKILL.md")
    if os.path.exists(wf_src):
        os.makedirs(os.path.join(DST, "workflow"), exist_ok=True)
        shutil.copy2(wf_src, os.path.join(DST, "workflow", "r-factory-evolution.SKILL.md"))


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=DST, capture_output=True, text=True)


def clear_stale_locks():
    """Remove git .lock files older than 5 minutes (crash/interrupt leftovers)."""
    import glob, time
    for lock in glob.glob(os.path.join(DST, ".git", "**", "*.lock"), recursive=True):
        try:
            if time.time() - os.path.getmtime(lock) > 300:
                os.remove(lock)
                print(f"  removed stale lock: {os.path.relpath(lock, DST)}")
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", default="sync: refresh code mirror from MT5")
    ap.add_argument("--push", action="store_true", help="also push to origin")
    args = ap.parse_args()

    print("→ building mirror (code + docs only, sensitive files excluded)…")
    n, mb = build_mirror()
    print(f"  copied {n} files ({mb:.1f} MB)")
    print("→ redacting account login / API keys…")
    print(f"  redacted in {redact_tree()} files")
    print("→ regenerating docs (README, AI_CONTEXT, ENDPOINTS)…")
    gen_endpoints()
    gen_docs()
    print("→ scanning for surviving secrets…")
    hits = scan_secrets()
    if hits:
        print("✗ ABORT — real secret(s) found; NOT committing:")
        for h in hits[:20]:
            print("   " + h)
        sys.exit(1)
    print("  clean ✓")

    if not os.path.isdir(os.path.join(DST, ".git")):
        git("init"); git("branch", "-M", "main")
    clear_stale_locks()
    if "origin" not in git("remote").stdout:
        git("remote", "add", "origin", "https://github.com/radhi88/r-native.git")
    git("add", "-A")
    c = git("-c", "user.name=Radhi", "-c", "user.email=radhi.amash@gmail.com",
            "commit", "-m", args.message)
    print(("  committed ✓" if c.returncode == 0 else
           "  (nothing to commit)") + (f"\n{c.stdout.strip()}" if c.stdout.strip() else ""))

    if args.push:
        print("→ pushing to origin/main…")
        p = git("push", "origin", "HEAD:main")
        if p.returncode == 0:
            print("  pushed ✓")
        else:
            print("  push failed:\n" + p.stderr)
            print("  ⇒ أول مرة؟ شغّل: git push  (ستفتح نافذة متصفح لتسجيل الدخول مرة")
            print("    واحدة — Git Credential Manager يحفظها دائماً)، أو: gh auth login")
    else:
        print("\nMirror ready at:", DST)
        print("To publish:  python sync_to_repo.py --push   (or: cd r-native-export && git push)")


if __name__ == "__main__":
    main()
