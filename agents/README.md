# 🧠 Unified Trading Brain

> **One Decision. Multiple Sources. Maximum Confidence.**
>
> Unifies SMC + Ollama AI + Agent Network + MT5 into a single trading decision.

---

## 🎯 What This Does

Your current system has **multiple dashboards and decisions**:
- http://127.0.0.1:5173/monitor (Monitor)
- http://localhost:5050/ (SMC Dashboard)  
- http://localhost:7799/ (API)
- MT5 with SMC analysis
- Ollama AI analysis
- Agent network decisions

**This project merges ALL of them into ONE unified decision and ONE dashboard.**

---

## 📊 Current Status

| Metric | Value |
|--------|-------|
| **Balance** | $576.29 |
| **Positions** | 0 |
| **Spread** | 280 points |
| **SMC Bias** | BUY |
| **SMC Confluence** | APPROVED \| 4/5 votes \| **SELL** |
| **SMC OB** | 8 |
| **SMC FVG** | 7 |
| **BOS** | ↓Bias |

**⚠️ Conflict Detected:** SMC Bias says BUY, but Confluence (4/5) says SELL!

The Unified Brain resolves this by weighting all sources and producing ONE clear decision.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    UNIFIED TRADING BRAIN                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│   │   SMC   │  │ Ollama  │  │ Agents  │  │ Technical│      │
│   │  (30%)  │  │  (25%)  │  │  (20%)  │  │  (15%)   │      │
│   └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘      │
│        │            │            │            │             │
│        └────────────┴────────────┴────────────┘             │
│                     │                                       │
│              ┌──────┴──────┐                                │
│              │   MERGE     │ ← Weighted Voting Algorithm    │
│              │   ENGINE    │                                │
│              └──────┬──────┘                                │
│                     │                                       │
│              ┌──────┴──────┐                                │
│              │ ONE DECISION │ → BUY/SELL/HOLD              │
│              │  + SL/TP    │ → Risk Management             │
│              │  + Volume   │ → Position Sizing             │
│              └──────┬──────┘                                │
│                     │                                       │
│              ┌──────┴──────┐                                │
│              │    MT5      │ → Execute Trade               │
│              │   EXECUTOR  │                                │
│              └─────────────┘                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Files

| File | Purpose |
|------|---------|
| `unified_orchestrator.py` | Core brain - merges all sources into one decision |
| `unified_dashboard.py` | One-page dashboard at http://localhost:8080 |
| `Agentic_Profiled_Grid_GOLD_LIVE_v3.mq5` | Enhanced MT5 EA with unified decision support |
| `start_unified.ps1` | PowerShell startup script |
| `unified_config.json` | Configuration for all components |

---

## 🚀 Quick Start

### 1. Install Dependencies

```powershell
pip install flask requests
```

### 2. Start Ollama (with Keep-Alive)

```powershell
$env:OLLAMA_KEEP_ALIVE = "-1"
ollama serve
```

### 3. Start Unified Brain

```powershell
.\start_unified.ps1
```

Or manually:

```powershell
# Terminal 1: Orchestrator
python unified_orchestrator.py

# Terminal 2: Dashboard  
python unified_dashboard.py
```

### 4. Open Dashboard

Go to: **http://localhost:8080**

This ONE page shows:
- ✅ Unified Decision (BUY/SELL/HOLD)
- ✅ All source readings (SMC, AI, Agents, Technical)
- ✅ MT5 status (balance, positions, spread)
- ✅ Agent network status
- ✅ System logs
- ✅ Emergency stop button

---

## 🎮 Dashboard Features

### Unified Decision Panel
- **Final Signal**: Clear BUY/SELL/HOLD
- **Confidence Bar**: Visual confidence indicator
- **Price/SL/TP/Volume**: All levels calculated
- **Risk Level**: LOW/MEDIUM/HIGH/EXTREME
- **Consensus**: X/5 votes

### Source Readings
- SMC: Bias, OB count, FVG count, BOS direction
- Ollama: AI analysis with confidence
- Agents: Network consensus
- Technical: Indicators
- Sentiment: Market mood

### MT5 Status
- Allow Trade: ON/OFF
- Balance & Equity
- Position count
- Spread
- SMC details

### Agent Network
- Ollama: 🧠 Active
- Claude: 💻 Active (PID 2804)
- Codex: 🔧 Active (PID 16616)
- SMC: 📊 Busy
- MT5: 📈 Active
- Risk: 🛡️ Active

---

## ⚙️ Configuration

Edit `unified_config.json`:

```json
{
  "source_weights": {
    "smc": 0.30,      // 30% weight to SMC
    "ollama": 0.25,   // 25% weight to AI
    "agents": 0.20,   // 20% weight to agents
    "technical": 0.15, // 15% weight to indicators
    "sentiment": 0.10  // 10% weight to sentiment
  },
  "min_confidence": 0.65,  // Minimum 65% confidence to trade
  "max_spread": 300,       // Don't trade if spread > 300
  "risk_per_trade": 0.02   // Risk 2% per trade
}
```

---

## 🔧 How It Works

### 1. Reading Phase
Every tick, the system reads from ALL sources:

```python
readings = [
    read_smc(),      # Smart Money Concepts
    read_ollama(),   # AI Analysis
    read_agents(),   # Agent Network
    read_technical(), # Indicators
    read_sentiment()  # Market Sentiment
]
```

### 2. Merging Phase
Weighted voting algorithm:

```python
# SMC says SELL with 80% confidence
# Weight = 30%
# Weighted vote = 0.80 * 0.30 = 0.24

# Ollama says BUY with 70% confidence
# Weight = 25%
# Weighted vote = 0.70 * 0.25 = 0.175

# Final: SELL wins (0.24 > 0.175)
```

### 3. Decision Phase
- If confidence >= 65% → Execute trade
- If confidence < 65% → HOLD (wait)
- If sources conflict → Use consensus

### 4. Execution Phase
- Write decision to `trading_command.json`
- MT5 EA reads and executes
- Update status files

---

## 🛡️ Safety Features

| Feature | Description |
|---------|-------------|
| **Emergency Stop** | One-click stop from dashboard |
| **Max Daily Loss** | Auto-pause if loss > 5% |
| **Cooldown** | Prevent over-trading |
| **Spread Filter** | Don't trade if spread too high |
| **Confidence Gate** | Only trade if confidence >= 65% |
| **Consensus Check** | Require minimum votes |
| **Trailing Stop** | Auto-protect profits |

---

## 📝 MT5 EA Changes (v3)

The new `Agentic_Profiled_Grid_GOLD_LIVE_v3.mq5` adds:

### New Inputs
```mql5
input bool     InpUseAI = true;           // Use AI (Ollama)
input int      InpMinConfidence = 65;     // Min AI Confidence %
input bool     InpRequireConsensus = true; // Require Multi-Agent Consensus
input int      InpMinConsensusVotes = 3;  // Min Consensus Votes
```

### New Functions
- `ReadAIDecision()` — Reads AI decision from brain vault
- `ReadConsensus()` — Reads agent consensus
- `EvaluateTradingConditions()` — Checks ALL conditions before trading
- `CheckEmergencyStop()` — Responds to emergency commands

### Decision Flow
```
Tick → Read SMC → Read AI → Read Consensus → Evaluate → Execute
```

All must approve:
- ✅ SMC: OB >= 3, FVG >= 2
- ✅ AI: Confidence >= 65%
- ✅ Consensus: Votes >= 3/5
- ✅ Risk: Daily loss < 5%
- ✅ Spread: < 300 points

---

## 🔄 Integration with Existing System

This project **enhances** your existing system:

| Existing | This Project | Status |
|----------|-------------|--------|
| http://127.0.0.1:5173/monitor | Reads from it | ✅ Integrated |
| http://localhost:5050/ | Reads from it | ✅ Integrated |
| http://localhost:7799/ | Reads from it | ✅ Integrated |
| `pluto_brain.py` | Uses brain_vault | ✅ Integrated |
| `orchestrator.py` | Replaces/extends | ✅ Enhanced |
| `smc_dashboard.py` | Reads SMC data | ✅ Integrated |
| MT5 EA | New v3 version | ✅ Enhanced |

---

## 📊 Example Decision

### Scenario: Conflict Detected

**SMC says:** Bias = BUY, but Confluence = SELL (4/5)
**Ollama says:** SELL (confidence: 75%)
**Agents say:** SELL (3/5 votes)
**Technical says:** SELL (RSI overbought)
**Sentiment says:** NEUTRAL

### Unified Brain Processing:

```
SMC:     SELL @ 80% × 30% = 0.240
Ollama:  SELL @ 75% × 25% = 0.188
Agents:  SELL @ 60% × 20% = 0.120
Technical: SELL @ 70% × 15% = 0.105
Sentiment: HOLD @ 50% × 10% = 0.050

Total SELL: 0.653 (65.3%)
Total BUY:  0.000 (0%)
Total HOLD: 0.050 (5%)

FINAL DECISION: SELL @ 65.3% confidence
```

### Result:
- ✅ Confidence >= 65% → **EXECUTE**
- ✅ All sources aligned → **HIGH CONFIDENCE**
- ✅ Risk acceptable → **PROCEED**

---

## 🎯 Next Steps

1. **Copy files** to `C:\Users\Radhi\MT5\agents\`
2. **Compile** `Agentic_Profiled_Grid_GOLD_LIVE_v3.mq5` in MT5
3. **Run** `start_unified.ps1`
4. **Open** http://localhost:8080
5. **Watch** the unified decision form

---

## 🐛 Troubleshooting

### Dashboard not loading
```powershell
# Check if port 8080 is free
netstat -ano | findstr :8080

# Try different port
python unified_dashboard.py  # Edit port in file
```

### Ollama not responding
```powershell
# Test Ollama
Invoke-RestMethod -Uri "http://localhost:11434/api/tags"

# Restart Ollama
ollama serve
```

### MT5 not reading decisions
```powershell
# Check file paths in MT5
# Ensure brain_vault exists: C:\Users\Radhi\MT5\agents\brain_vault\
# Check MT5 Journal for errors
```

---

## 📜 License

MIT - Free to use and modify.

---

> **"One brain. One decision. One profit."**
>
> — Unified Trading Brain
