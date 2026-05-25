# R Native — Install on a Fresh Windows Machine

Complete setup from a blank Windows PC to a self-evolving genome trader running 24/7.

## What you'll have when done

- **R Native UI** (PySide6 desktop app) — vault, hall of fame, AI advisors, live tab
- **brain_server** (Flask, port 5055) — REST APIs + 5 always-on agents + auto-evolution
- **R Executor** — autonomous trader that fires when the deployed genome says BUY/SELL
- **Hall of Fame** — every genome ever produced, ranked + with lineage
- **Ollama LLM** (optional) — for the strategist agent's recommendations

All running on **your separate MT5 account** with **independent state**.

---

## Step 1 — Install prerequisites

### A. Python 3.13
1. Download from https://www.python.org/downloads/release/python-3130/
2. Run installer → **CHECK "Add python.exe to PATH"** → Install
3. Verify in PowerShell: `python --version` should show `3.13.x`

### B. MT5 terminal (with your account)
1. Download MetaTrader 5 from your broker (Exness, IC Markets, etc.)
2. Install + log in with the separate account this machine will use
3. **Tools → Options → Expert Advisors** → allow algorithmic trading
4. Make sure the terminal runs while R Native is running

### C. Git (if not already installed)
1. https://git-scm.com/download/win → install with defaults
2. Verify: `git --version`

### D. Ollama (optional but recommended for LLM Strategist agent)
1. https://ollama.com/download/windows → install
2. PowerShell: `ollama pull llama3.1:8b` (≈5GB download)
3. Optionally also: `ollama pull qwen2.5:7b` and `ollama pull qwen2.5:3b` (fallback chain)

---

## Step 2 — Clone the repo

Open PowerShell **as yourself** (not admin) and:

```powershell
# Match the original layout — many absolute paths in the code reference this
New-Item -ItemType Directory -Path "C:\Users\$env:USERNAME\MT5" -Force
cd "C:\Users\$env:USERNAME\MT5"

git clone https://github.com/radhi88/r-native.git r_native
```

> **Important**: if your username is NOT `Radhi`, you'll need to find/replace
> `C:\Users\Radhi\MT5` → `C:\Users\<YourName>\MT5` in a few files. Search:
> ```powershell
> Get-ChildItem -Recurse r_native -Include *.py | Select-String "C:\\Users\\Radhi"
> ```
> Replace those paths with your actual user folder.

---

## Step 3 — Install Python dependencies

```powershell
cd "C:\Users\$env:USERNAME\MT5\r_native"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This installs: `MetaTrader5`, `PySide6`, `flask`, `numpy`, `pandas`,
`psutil`, `requests`, `pyttsx3` (voice alerts), etc.

---

## Step 4 — Create data directory structure

```powershell
cd "C:\Users\$env:USERNAME\MT5"
$dirs = @(
  "data\r_native",
  "data\r_native\symbol_configs",
  "data\r_native\symbol_intel",
  "data\r_native\symbol_learning",
  "data\r_native\hall_of_fame\by_symbol",
  "data\r_native\agents",
  "data\r_native\campaigns",
  "data\r_native\scans"
)
foreach ($d in $dirs) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
Write-Output "✅ data directories created"
```

---

## Step 5 — Run the launcher script

Two terminals required (or use the launcher script):

### Terminal 1 — brain_server (REST API + agents)
```powershell
cd "C:\Users\$env:USERNAME\MT5"
python brain_server.py
```

You should see:
```
🧠 R Native Brain Server starting on http://127.0.0.1:5055
🧬 continuous_evolution loop armed
🤖 agent orchestrator started (5 agents: risk_sentinel, genome_curator,
   market_reader, performance_auditor, llm_strategist)
```

### Terminal 2 — R Native UI
```powershell
cd "C:\Users\$env:USERNAME\MT5"
python -m r_native.app
```

You should see the dark-themed window open with 6 tabs:
🧪 CAMPAIGN · 💎 VAULT · ⚡ LIVE · 🧬 GENES · 🏆 HALL OF FAME · 🤖 AI ADVISORS

### Optional Terminal 3 — R Executor (autonomous trader)
```powershell
cd "C:\Users\$env:USERNAME\MT5"
python -m friday_v3.algory.r_executor
```

This is the process that ACTUALLY fires trades into MT5 when the deployed
genome says BUY/SELL. Without it, the UI works but no trades execute.

---

## Step 6 — First-run setup inside the UI

1. **🧪 CAMPAIGN tab**:
   - Pick symbol (`BTCUSDm` or your broker's BTC name)
   - Click `RUN CAMPAIGN` — takes ~2 minutes on a modern CPU
   - This produces your first 200-300 genomes

2. **💎 VAULT tab**:
   - Select the top-scoring genome
   - Click `DEPLOY` → it becomes the live trader for that symbol

3. **🤖 AI ADVISORS tab**:
   - Click `⚙ AUTONOMOUS: OFF` to flip it ON (LLM auto-applies recommendations)
   - Watch the live insight stream as agents make decisions

4. **🧬 AUTO-EVOLVE button** (in VAULT tab action bar):
   - Click to start the 6-hour evolution cycle
   - System will now generate new genomes + auto-deploy winners forever

---

## Step 7 — Verify it's trading

After 30-60 minutes (depending on market regime), check:

```powershell
# trade_gate verdict
curl http://127.0.0.1:5055/api/r/trade_gate?symbol=BTCUSDm
# look for: verdict=GO, archetype=GENOME, side=BUY/SELL

# current open positions
curl http://127.0.0.1:5055/api/account
# look for: positions with magic=20260605

# agents status
curl http://127.0.0.1:5055/api/r/agents/list
# all 5 should show enabled=true, thread_alive=true
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `MT5 init failed` | Open MT5 terminal manually, log in, leave it running |
| `port 5055 already in use` | Another brain_server instance — kill it: `Get-Process python \| Stop-Process` |
| UI shows `brain offline` | brain_server crashed — check Terminal 1 for errors |
| `no LLM backend available` | Ollama not running — `ollama serve` in another terminal |
| Genome says NO forever | Market is DEAD/quiet — wait for higher volatility |
| Trade fires but no MT5 position | R Executor isn't running — start Terminal 3 |
| `symbol_learning blocks X` | Reset: edit `data/r_native/symbol_intel/X.json` → `trust_score: 50, verdict: OK` |

---

## Daily operation

Once configured, the only thing you need is the 3 terminals running.
The 5 agents will:

- **Risk Sentinel** every 20s — trips kill switch if drawdown > 15%
- **Market Reader** every 5min — swaps to best HoF genome for current regime
- **Genome Curator** every 30min — auto-pins top scorers, prunes failed breeds
- **LLM Strategist** every 15min — recommends pin/kill/breed (autonomous if toggled)
- **Performance Auditor** every 1h — hourly + daily wrap-up reports

And the **Auto-Evolution** runs a fresh GA campaign every 6 hours,
auto-deploying any genome that beats the current by ≥3 points.

---

## Sync with the original machine (Failover-style)

If you want this machine's HoF to learn from the original machine's
discoveries (or vice versa), set up a periodic rsync/robocopy of the
`hall_of_fame/` directory. Each machine still trades its own MT5 account
independently — only the genome library is shared.

```powershell
# Example: pull HoF nightly from primary machine
robocopy \\PRIMARY-PC\MT5_share\data\r_native\hall_of_fame `
         C:\Users\$env:USERNAME\MT5\data\r_native\hall_of_fame `
         /MIR /R:3 /W:5
```
