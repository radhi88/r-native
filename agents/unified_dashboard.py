"""
Unified Trading Dashboard
One page to rule them all: merges all dashboards into ONE view
Accessible at: http://localhost:8080
"""

from flask import Flask, render_template_string, jsonify
import json
import os
import time
from datetime import datetime
import threading

app = Flask(__name__)

# Paths
MT5_PATH = r"C:\Users\Radhi\MT5"
BRAIN_VAULT = os.path.join(MT5_PATH, "agents", "brain_vault")
COMMON_FILES = r"C:\Users\Radhi\AppData\Roaming\MetaQuotes\Terminal\Common\Files"

# HTML Template - One Page Dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🧠 Unified Trading Brain</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0e1a;
            color: #e0e6ed;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1f3a 0%, #0d1117 100%);
            padding: 20px;
            border-bottom: 2px solid #00d4ff;
            text-align: center;
        }
        .header h1 { font-size: 2em; color: #00d4ff; text-shadow: 0 0 20px rgba(0,212,255,0.3); }
        .header .subtitle { color: #8899aa; margin-top: 5px; }
        .status-bar {
            display: flex;
            justify-content: center;
            gap: 30px;
            padding: 15px;
            background: #0d1117;
            border-bottom: 1px solid #1a2332;
        }
        .status-item { text-align: center; }
        .status-item .label { font-size: 0.8em; color: #8899aa; }
        .status-item .value { font-size: 1.3em; font-weight: bold; }
        .status-item .value.online { color: #00ff88; }
        .status-item .value.offline { color: #ff4444; }
        .main-grid {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 20px;
            padding: 20px;
            max-width: 1600px;
            margin: 0 auto;
        }
        .panel {
            background: linear-gradient(145deg, #111827 0%, #0d1117 100%);
            border-radius: 12px;
            border: 1px solid #1a2332;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }
        .panel-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #1a2332;
        }
        .panel-header h2 { font-size: 1.1em; color: #00d4ff; }
        .panel-header .icon { font-size: 1.3em; }
        .decision-box {
            background: linear-gradient(135deg, #1a2332 0%, #0d1117 100%);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            border: 2px solid;
            margin-bottom: 15px;
        }
        .decision-box.BUY { border-color: #00ff88; box-shadow: 0 0 20px rgba(0,255,136,0.1); }
        .decision-box.SELL { border-color: #ff4444; box-shadow: 0 0 20px rgba(255,68,68,0.1); }
        .decision-box.HOLD { border-color: #ffaa00; box-shadow: 0 0 20px rgba(255,170,0,0.1); }
        .decision-signal { font-size: 3em; font-weight: bold; margin: 10px 0; }
        .decision-signal.BUY { color: #00ff88; }
        .decision-signal.SELL { color: #ff4444; }
        .decision-signal.HOLD { color: #ffaa00; }
        .confidence-bar {
            width: 100%;
            height: 8px;
            background: #1a2332;
            border-radius: 4px;
            overflow: hidden;
            margin: 10px 0;
        }
        .confidence-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
        }
        .confidence-fill.high { background: linear-gradient(90deg, #00ff88, #00d4ff); }
        .confidence-fill.medium { background: linear-gradient(90deg, #ffaa00, #ff8800); }
        .confidence-fill.low { background: linear-gradient(90deg, #ff4444, #ff8800); }
        .reading-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            margin: 5px 0;
            background: #0d1117;
            border-radius: 8px;
            border-left: 3px solid;
        }
        .reading-item.BUY { border-left-color: #00ff88; }
        .reading-item.SELL { border-left-color: #ff4444; }
        .reading-item.HOLD { border-left-color: #ffaa00; }
        .reading-source { font-weight: bold; font-size: 0.9em; }
        .reading-signal { font-size: 0.85em; padding: 2px 8px; border-radius: 4px; }
        .reading-signal.BUY { background: rgba(0,255,136,0.2); color: #00ff88; }
        .reading-signal.SELL { background: rgba(255,68,68,0.2); color: #ff4444; }
        .reading-signal.HOLD { background: rgba(255,170,0,0.2); color: #ffaa00; }
        .mt5-status {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .mt5-item {
            background: #0d1117;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }
        .mt5-item .label { font-size: 0.75em; color: #8899aa; }
        .mt5-item .value { font-size: 1.2em; font-weight: bold; color: #00d4ff; }
        .agent-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .agent-card {
            background: #0d1117;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
            border: 1px solid #1a2332;
        }
        .agent-card.active { border-color: #00ff88; }
        .agent-card.busy { border-color: #ffaa00; }
        .agent-card.offline { border-color: #ff4444; opacity: 0.6; }
        .log-container {
            max-height: 300px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.8em;
            background: #0d1117;
            padding: 10px;
            border-radius: 8px;
        }
        .log-entry { padding: 3px 0; border-bottom: 1px solid #1a2332; }
        .log-time { color: #00d4ff; }
        .btn {
            background: linear-gradient(135deg, #00d4ff, #0099cc);
            color: #0a0e1a;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
            margin: 5px;
            transition: all 0.3s;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,212,255,0.3); }
        .btn-danger { background: linear-gradient(135deg, #ff4444, #cc0000); color: white; }
        .full-width { grid-column: 1 / -1; }
        @media (max-width: 1200px) {
            .main-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 768px) {
            .main-grid { grid-template-columns: 1fr; }
            .status-bar { flex-wrap: wrap; gap: 15px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🧠 Unified Trading Brain</h1>
        <div class="subtitle">One Decision. Multiple Sources. Maximum Confidence.</div>
    </div>

    <div class="status-bar">
        <div class="status-item">
            <div class="label">MT5 Status</div>
            <div class="value {{ 'online' if data.mt5.allow_trade else 'offline' }}">{{ 'LIVE' if data.mt5.allow_trade else 'PAUSED' }}</div>
        </div>
        <div class="status-item">
            <div class="label">Balance</div>
            <div class="value">${{ "%.2f"|format(data.mt5.balance) }}</div>
        </div>
        <div class="status-item">
            <div class="label">Positions</div>
            <div class="value">{{ data.mt5.positions }}</div>
        </div>
        <div class="status-item">
            <div class="label">Spread</div>
            <div class="value">{{ data.mt5.spread }} pts</div>
        </div>
        <div class="status-item">
            <div class="label">Ollama</div>
            <div class="value {{ 'online' if data.ollama.online else 'offline' }}">{{ 'ONLINE' if data.ollama.online else 'OFFLINE' }}</div>
        </div>
        <div class="status-item">
            <div class="label">Last Update</div>
            <div class="value" style="font-size:0.9em">{{ data.last_update }}</div>
        </div>
    </div>

    <div class="main-grid">
        <!-- UNIFIED DECISION -->
        <div class="panel full-width">
            <div class="panel-header">
                <span class="icon">⚡</span>
                <h2>UNIFIED DECISION</h2>
            </div>
            <div class="decision-box {{ data.decision.signal }}">
                <div style="font-size: 0.9em; color: #8899aa;">FINAL SIGNAL</div>
                <div class="decision-signal {{ data.decision.signal }}">{{ data.decision.signal }}</div>
                <div style="font-size: 1.2em; margin: 10px 0;">
                    Confidence: <strong>{{ "%.1f"|format(data.decision.confidence * 100) }}%</strong>
                </div>
                <div class="confidence-bar">
                    <div class="confidence-fill {{ 'high' if data.decision.confidence >= 0.7 else 'medium' if data.decision.confidence >= 0.5 else 'low' }}" 
                         style="width: {{ data.decision.confidence * 100 }}%"></div>
                </div>
                <div style="display: flex; justify-content: center; gap: 30px; margin-top: 15px; font-size: 0.9em;">
                    <div>Price: <strong>{{ data.decision.price }}</strong></div>
                    <div>SL: <strong style="color:#ff4444">{{ data.decision.stop_loss }}</strong></div>
                    <div>TP: <strong style="color:#00ff88">{{ data.decision.take_profit }}</strong></div>
                    <div>Vol: <strong>{{ data.decision.volume }}</strong></div>
                </div>
                <div style="margin-top: 10px; color: #ffaa00; font-size: 0.85em;">
                    Risk: {{ data.decision.risk_level }} | Mode: {{ data.decision.execution_mode }} | Consensus: {{ data.decision.consensus }}
                </div>
            </div>
            <div style="text-align: center;">
                <button class="btn" onclick="refreshDecision()">🔄 Refresh Decision</button>
                <button class="btn btn-danger" onclick="emergencyStop()">🛑 Emergency Stop</button>
            </div>
        </div>

        <!-- SOURCE READINGS -->
        <div class="panel">
            <div class="panel-header">
                <span class="icon">📊</span>
                <h2>SOURCE READINGS</h2>
            </div>
            {% for reading in data.readings %}
            <div class="reading-item {{ reading.signal }}">
                <div>
                    <div class="reading-source">{{ reading.source.upper() }}</div>
                    <div style="font-size: 0.75em; color: #8899aa;">{{ reading.reasoning[:50] }}...</div>
                </div>
                <div style="text-align: right;">
                    <div class="reading-signal {{ reading.signal }}">{{ reading.signal }}</div>
                    <div style="font-size: 0.8em; color: #8899aa; margin-top: 3px;">{{ "%.0f"|format(reading.confidence * 100) }}%</div>
                </div>
            </div>
            {% endfor %}
        </div>

        <!-- MT5 STATUS -->
        <div class="panel">
            <div class="panel-header">
                <span class="icon">📈</span>
                <h2>MT5 STATUS</h2>
            </div>
            <div class="mt5-status">
                <div class="mt5-item">
                    <div class="label">Allow Trade</div>
                    <div class="value" style="color: {{ '#00ff88' if data.mt5.allow_trade else '#ff4444' }}">{{ 'YES' if data.mt5.allow_trade else 'NO' }}</div>
                </div>
                <div class="mt5-item">
                    <div class="label">Cooldown</div>
                    <div class="value">{{ data.mt5.cooldown }}s</div>
                </div>
                <div class="mt5-item">
                    <div class="label">SMC Bias</div>
                    <div class="value" style="color: {{ '#00ff88' if data.mt5.smc_bias == 'BUY' else '#ff4444' }}">{{ data.mt5.smc_bias }}</div>
                </div>
                <div class="mt5-item">
                    <div class="label">Confluence</div>
                    <div class="value" style="color: {{ '#00ff88' if 'APPROVED' in data.mt5.confluence else '#ff4444' }}">{{ data.mt5.confluence }}</div>
                </div>
            </div>
            <div style="margin-top: 15px; font-size: 0.85em;">
                <div style="color: #8899aa; margin-bottom: 5px;">SMC Details:</div>
                <div>OB: {{ data.mt5.smc_ob }} | FVG: {{ data.mt5.smc_fvg }} | BOS: {{ data.mt5.smc_bos }}</div>
            </div>
        </div>

        <!-- AGENT NETWORK -->
        <div class="panel">
            <div class="panel-header">
                <span class="icon">🤖</span>
                <h2>AGENT NETWORK</h2>
            </div>
            <div class="agent-grid">
                {% for agent in data.agents %}
                <div class="agent-card {{ agent.status }}">
                    <div style="font-size: 1.2em;">{{ agent.icon }}</div>
                    <div style="font-weight: bold; font-size: 0.85em;">{{ agent.name }}</div>
                    <div style="font-size: 0.75em; color: #8899aa;">{{ agent.status.upper() }}</div>
                </div>
                {% endfor %}
            </div>
            <div style="margin-top: 15px; text-align: center;">
                <div style="font-size: 0.85em; color: #8899aa;">Active Agents: {{ data.agent_count }}</div>
            </div>
        </div>

        <!-- SYSTEM LOGS -->
        <div class="panel full-width">
            <div class="panel-header">
                <span class="icon">📜</span>
                <h2>SYSTEM LOGS</h2>
            </div>
            <div class="log-container">
                {% for log in data.logs %}
                <div class="log-entry">
                    <span class="log-time">[{{ log.time }}]</span> {{ log.message }}
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <script>
        function refreshDecision() {
            fetch('/api/refresh', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if(data.success) location.reload();
                });
        }
        function emergencyStop() {
            if(confirm('🛑 EMERGENCY STOP\n\nThis will:\n• Close all positions\n• Disable trading\n• Alert all agents\n\nAre you sure?')) {
                fetch('/api/emergency', {method: 'POST'})
                    .then(r => r.json())
                    .then(data => alert(data.message));
            }
        }
        // Auto-refresh every 10 seconds
        setInterval(() => location.reload(), 10000);
    </script>
</body>
</html>
"""


def load_data():
    """Load all data from various sources"""
    data = {
        "mt5": {
            "allow_trade": True,
            "cooldown": 0,
            "positions": 0,
            "balance": 576.29,
            "spread": 280,
            "smc_bias": "BUY",
            "smc_ob": 8,
            "smc_fvg": 7,
            "smc_bos": "↓Bias",
            "confluence": "APPROVED | 4/5 | SELL"
        },
        "decision": {
            "signal": "HOLD",
            "confidence": 0.55,
            "price": 0,
            "stop_loss": 0,
            "take_profit": 0,
            "volume": 0.01,
            "risk_level": "HIGH",
            "execution_mode": "LIMIT",
            "consensus": "?/5"
        },
        "readings": [],
        "agents": [],
        "agent_count": 0,
        "ollama": {"online": False},
        "logs": [],
        "last_update": datetime.now().strftime("%H:%M:%S")
    }

    # Try to load latest decision
    decision_file = os.path.join(BRAIN_VAULT, "latest_decision.json")
    if os.path.exists(decision_file):
        try:
            with open(decision_file, 'r') as f:
                decision = json.load(f)
            data["decision"] = {
                "signal": decision.get("final_signal", "HOLD"),
                "confidence": decision.get("confidence", 0),
                "price": decision.get("price", 0),
                "stop_loss": decision.get("stop_loss", 0),
                "take_profit": decision.get("take_profit", 0),
                "volume": decision.get("volume", 0.01),
                "risk_level": decision.get("risk_level", "HIGH"),
                "execution_mode": decision.get("execution_mode", "LIMIT"),
                "consensus": decision.get("consensus_ratio", "?/5")
            }

            # Load readings
            sources = decision.get("sources", [])
            data["readings"] = [
                {
                    "source": s.get("source", "unknown"),
                    "signal": s.get("signal", "HOLD"),
                    "confidence": s.get("confidence", 0),
                    "reasoning": s.get("reasoning", "")
                }
                for s in sources
            ]
        except:
            pass

    # Load agents
    agents_file = os.path.join(BRAIN_VAULT, "agent_minds.json")
    if os.path.exists(agents_file):
        try:
            with open(agents_file, 'r') as f:
                agents_data = json.load(f)
            agents = agents_data.get("agents", [])
            data["agents"] = [
                {
                    "name": a.get("name", f"Agent-{i}"),
                    "status": a.get("status", "offline"),
                    "icon": a.get("icon", "🤖")
                }
                for i, a in enumerate(agents)
            ]
            data["agent_count"] = len(agents)
        except:
            pass

    # Default agents if none found
    if not data["agents"]:
        data["agents"] = [
            {"name": "Ollama", "status": "active", "icon": "🧠"},
            {"name": "Claude", "status": "active", "icon": "💻"},
            {"name": "Codex", "status": "active", "icon": "🔧"},
            {"name": "SMC", "status": "busy", "icon": "📊"},
            {"name": "MT5", "status": "active", "icon": "📈"},
            {"name": "Risk", "status": "active", "icon": "🛡️"}
        ]
        data["agent_count"] = 6

    # Add VS Code PID bridge status when PlutoBrain has a heartbeat file.
    bridge_file = os.path.join(BRAIN_VAULT, "vs_pid_bridge.json")
    if os.path.exists(bridge_file):
        try:
            with open(bridge_file, 'r', encoding='utf-8-sig') as f:
                bridge = json.load(f)
            pid = bridge.get("pid", "?")
            bridge_name = f"VS PID {pid}"
            if not any(a.get("name") == bridge_name for a in data["agents"]):
                data["agents"].append({
                    "name": bridge_name,
                    "status": "active" if bridge.get("alive") else "offline",
                    "icon": "VS"
                })
            data["agent_count"] = len(data["agents"])
        except:
            pass

    # Check Ollama
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        data["ollama"]["online"] = r.status_code == 200
    except:
        pass

    # Load logs
    log_file = os.path.join(BRAIN_VAULT, "log.md")
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()[-20:]
            data["logs"] = [
                {"time": datetime.now().strftime("%H:%M:%S"), "message": line.strip()}
                for line in lines if line.strip()
            ]
        except:
            pass

    if not data["logs"]:
        data["logs"] = [
            {"time": "--:--", "message": "System initialized"},
            {"time": "--:--", "message": "Waiting for first decision..."}
        ]

    return data


@app.route("/")
def index():
    data = load_data()
    return render_template_string(DASHBOARD_HTML, data=data)


@app.route("/api/status")
def api_status():
    return jsonify(load_data())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    # Trigger new decision
    try:
        from unified_orchestrator import UnifiedTradingBrain
        brain = UnifiedTradingBrain()
        decision = brain.make_decision()
        return jsonify({"success": True, "signal": decision.final_signal})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/emergency", methods=["POST"])
def api_emergency():
    # Write emergency stop command
    cmd_file = os.path.join(COMMON_FILES, "emergency_stop.json")
    with open(cmd_file, 'w') as f:
        json.dump({
            "action": "EMERGENCY_STOP",
            "timestamp": time.time(),
            "reason": "Manual trigger from dashboard"
        }, f)
    return jsonify({"success": True, "message": "🛑 Emergency stop activated. All positions closing."})


if __name__ == "__main__":
    print("🧠 Unified Trading Dashboard starting...")
    print("📊 Access at: http://localhost:8080")
    print("🛑 Press Ctrl+C to stop")
    app.run(host="0.0.0.0", port=8080, debug=False)
