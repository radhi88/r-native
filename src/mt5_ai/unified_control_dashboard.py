"""
unified_control_dashboard.py — لوحة التحكم الموحدة
═════════════════════════════════════════════════

تعرض جميع القرارات والإشارات من جميع الوكلاء في صفحة واحدة.
عقل واحد، هدف واحد، كلمة واحدة.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
import logging

from flask import Flask, render_template_string, jsonify
from flask_cors import CORS

log = logging.getLogger("unified_dashboard")


class UnifiedControlDashboard:
    """لوحة التحكم الموحدة لجميع الوكلاء."""
    
    def __init__(self, decision_center, port: int = 8780, project_root: Path | str = None):
        """
        Args:
            decision_center: UnifiedDecisionCenter instance
            port: Port for Flask server
            project_root: Project root directory
        """
        self.decision_center = decision_center
        self.port = port
        self.project_root = Path(project_root) if project_root else Path.cwd()
        
        self.app = Flask(__name__)
        CORS(self.app)
        self._setup_routes()
        
        log.info(f"🎯 Unified Control Dashboard will start on port {port}")
    
    def _setup_routes(self):
        """إعداد مسارات الـ API."""
        
        @self.app.route("/api/decision", methods=["GET"])
        def get_decision():
            """الحصول على آخر قرار موحد."""
            if not self.decision_center.last_decision:
                return jsonify({"status": "no_decision_yet"}), 200
            
            return jsonify(self.decision_center.get_dashboard_data()), 200
        
        @self.app.route("/api/history", methods=["GET"])
        def get_history():
            """الحصول على سجل القرارات."""
            history = []
            for decision in self.decision_center.decision_history[-100:]:
                history.append({
                    "timestamp": decision.timestamp,
                    "symbol": decision.symbol,
                    "decision": decision.unified_decision.value,
                    "confidence": f"{decision.unified_confidence:.3f}",
                    "consensus": f"{decision.consensus_level * 100:.1f}%",
                    "conflict": decision.conflict_detected,
                })
            return jsonify(history), 200
        
        @self.app.route("/api/agents", methods=["GET"])
        def get_agents_status():
            """حالة جميع الوكلاء."""
            if not self.decision_center.last_decision:
                return jsonify({"agents": []}), 200
            
            agents = []
            for signal in self.decision_center.last_decision.agent_signals:
                agents.append({
                    "name": signal.agent_name,
                    "direction": signal.direction,
                    "confidence": f"{signal.confidence:.3f}",
                    "reason": signal.reason,
                    "timestamp": signal.timestamp,
                })
            return jsonify({"agents": agents}), 200
        
        @self.app.route("/", methods=["GET"])
        def index():
            """لوحة التحكم الرئيسية."""
            return render_template_string(DASHBOARD_HTML)
    
    def run(self, debug: bool = False):
        """تشغيل لوحة التحكم."""
        log.info(f"Starting Unified Control Dashboard on http://127.0.0.1:{self.port}")
        self.app.run(
            host="127.0.0.1",
            port=self.port,
            debug=debug,
            use_reloader=False,
            threaded=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# لوحة التحكم HTML/CSS/JS
# ──────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🧠 مركز القرار الموحد — Unified Decision Center</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #00d4ff;
        }
        
        h1 {
            font-size: 2.5em;
            color: #00d4ff;
            text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
            margin-bottom: 10px;
        }
        
        .subtitle {
            font-size: 1.1em;
            color: #888;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: rgba(30, 30, 40, 0.8);
            border: 1px solid #333;
            border-radius: 10px;
            padding: 20px;
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }
        
        .card:hover {
            border-color: #00d4ff;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
        }
        
        .card-title {
            font-size: 1.3em;
            color: #00d4ff;
            margin-bottom: 15px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .decision-box {
            background: rgba(255, 87, 34, 0.1);
            border-left: 4px solid #ff5722;
            padding: 15px;
            margin: 10px 0;
            border-radius: 5px;
        }
        
        .decision-box.buy {
            background: rgba(76, 175, 80, 0.1);
            border-left-color: #4caf50;
        }
        
        .decision-box.sell {
            background: rgba(244, 67, 54, 0.1);
            border-left-color: #f44336;
        }
        
        .decision-box.hold {
            background: rgba(255, 193, 7, 0.1);
            border-left-color: #ffc107;
        }
        
        .decision-value {
            font-size: 2em;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .buy .decision-value {
            color: #4caf50;
        }
        
        .sell .decision-value {
            color: #f44336;
        }
        
        .hold .decision-value {
            color: #ffc107;
        }
        
        .confidence-bar {
            background: #333;
            height: 30px;
            border-radius: 5px;
            overflow: hidden;
            margin: 10px 0;
        }
        
        .confidence-fill {
            height: 100%;
            background: linear-gradient(90deg, #4caf50, #8bc34a);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #000;
            font-weight: bold;
            transition: width 0.3s ease;
        }
        
        .agent-item {
            background: rgba(50, 50, 60, 0.8);
            padding: 12px;
            margin: 10px 0;
            border-radius: 5px;
            border-left: 3px solid #00d4ff;
        }
        
        .agent-name {
            font-weight: bold;
            color: #00d4ff;
            font-size: 0.95em;
            text-transform: capitalize;
        }
        
        .agent-signal {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            margin-top: 5px;
            font-weight: bold;
        }
        
        .agent-signal.buy {
            background: #4caf50;
            color: white;
        }
        
        .agent-signal.sell {
            background: #f44336;
            color: white;
        }
        
        .agent-signal.hold {
            background: #ffc107;
            color: #000;
        }
        
        .agent-confidence {
            float: left;
            color: #888;
            font-size: 0.85em;
        }
        
        .consensus-badge {
            display: inline-block;
            background: #00d4ff;
            color: #000;
            padding: 8px 12px;
            border-radius: 20px;
            font-weight: bold;
            margin: 10px 5px 0 0;
        }
        
        .conflict-warning {
            background: rgba(244, 67, 54, 0.15);
            border-left: 3px solid #f44336;
            padding: 10px;
            margin: 10px 0;
            border-radius: 3px;
            color: #ff9999;
        }
        
        .market-data {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin: 15px 0;
        }
        
        .market-item {
            background: rgba(50, 50, 60, 0.8);
            padding: 10px;
            border-radius: 5px;
            text-align: center;
        }
        
        .market-label {
            font-size: 0.85em;
            color: #888;
            text-transform: uppercase;
        }
        
        .market-value {
            font-size: 1.3em;
            color: #00d4ff;
            font-weight: bold;
            margin-top: 5px;
        }
        
        .timestamp {
            color: #666;
            font-size: 0.85em;
            margin-top: 10px;
            text-align: right;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #888;
        }
        
        .spinner {
            border: 3px solid #333;
            border-top: 3px solid #00d4ff;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        footer {
            text-align: center;
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #333;
            color: #666;
            font-size: 0.85em;
        }
        
        @media (max-width: 768px) {
            h1 {
                font-size: 1.8em;
            }
            
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🧠 مركز القرار الموحد</h1>
            <p class="subtitle">Unified Decision Center — كل الوكلاء على كلمة واحدة</p>
        </header>
        
        <div class="grid">
            <!-- القرار الموحد -->
            <div class="card">
                <div class="card-title">⚡ القرار الموحد</div>
                <div id="decision-container" class="loading">
                    <div class="spinner"></div>
                    جاري التحميل...
                </div>
            </div>
            
            <!-- إشارات الوكلاء -->
            <div class="card">
                <div class="card-title">👥 إشارات الوكلاء</div>
                <div id="agents-container" class="loading">
                    <div class="spinner"></div>
                    جاري التحميل...
                </div>
            </div>
            
            <!-- بيانات السوق -->
            <div class="card">
                <div class="card-title">📊 بيانات السوق</div>
                <div id="market-container" class="loading">
                    <div class="spinner"></div>
                    جاري التحميل...
                </div>
            </div>
        </div>
        
        <!-- سجل القرارات -->
        <div class="card" style="margin-top: 30px;">
            <div class="card-title">📈 سجل آخر 10 قرارات</div>
            <div id="history-container" class="loading">
                <div class="spinner"></div>
                جاري التحميل...
            </div>
        </div>
        
        <footer>
            تم تحديثه تلقائياً كل ثانية — Auto-refreshing every second
        </footer>
    </div>
    
    <script>
        async function updateDashboard() {
            try {
                // جلب آخر قرار
                const decisionRes = await fetch('/api/decision');
                const decisionData = await decisionRes.json();
                
                if (decisionData.status === 'no_decision_yet') {
                    document.getElementById('decision-container').innerHTML = 
                        '<p>⏳ لا توجد قرارات بعد</p>';
                } else {
                    document.getElementById('decision-container').innerHTML = `
                        <div class="decision-box ${decisionData.unified_decision.toLowerCase()}">
                            <div>القرار: <strong>${decisionData.unified_decision}</strong></div>
                            <div class="decision-value">${decisionData.unified_decision}</div>
                            <div>الثقة: ${decisionData.unified_confidence}</div>
                            <div class="confidence-bar">
                                <div class="confidence-fill" style="width: ${parseFloat(decisionData.unified_confidence) * 100}%">
                                    ${(parseFloat(decisionData.unified_confidence) * 100).toFixed(1)}%
                                </div>
                            </div>
                            <div>السبب: ${decisionData.final_reason}</div>
                            ${decisionData.conflict_detected ? 
                                `<div class="conflict-warning">⚠️ تضارب: ${decisionData.conflict_description}</div>` : 
                                ''}
                            <div class="consensus-badge">🤝 ${decisionData.consensus_level}</div>
                            <div class="timestamp">${new Date(decisionData.timestamp).toLocaleString('ar-SA')}</div>
                        </div>
                    `;
                }
                
                // جلب إشارات الوكلاء
                const agentsRes = await fetch('/api/agents');
                const agentsData = await agentsRes.json();
                
                if (agentsData.agents.length === 0) {
                    document.getElementById('agents-container').innerHTML = 
                        '<p>لا توجد إشارات</p>';
                } else {
                    const agentsHTML = agentsData.agents.map(agent => `
                        <div class="agent-item">
                            <div class="agent-name">🤖 ${agent.name}</div>
                            <span class="agent-signal ${agent.direction.toLowerCase()}">
                                ${agent.direction}
                            </span>
                            <span class="agent-confidence">
                                ثقة: ${agent.confidence}
                            </span>
                            <div style="margin-top: 5px; font-size: 0.85em; color: #aaa;">
                                السبب: ${agent.reason}
                            </div>
                        </div>
                    `).join('');
                    document.getElementById('agents-container').innerHTML = agentsHTML;
                }
                
                // جلب بيانات السوق
                if (decisionData.market) {
                    document.getElementById('market-container').innerHTML = `
                        <div class="market-data">
                            <div class="market-item">
                                <div class="market-label">الطلب (BID)</div>
                                <div class="market-value">${decisionData.market.bid.toFixed(3)}</div>
                            </div>
                            <div class="market-item">
                                <div class="market-label">العرض (ASK)</div>
                                <div class="market-value">${decisionData.market.ask.toFixed(3)}</div>
                            </div>
                            <div class="market-item">
                                <div class="market-label">السبريد</div>
                                <div class="market-value">${decisionData.market.spread.toFixed(3)}</div>
                            </div>
                            <div class="market-item">
                                <div class="market-label">جودة السوق</div>
                                <div class="market-value">${decisionData.market.market_quality}</div>
                            </div>
                        </div>
                    `;
                }
                
                // جلب السجل
                const historyRes = await fetch('/api/history');
                const historyData = await historyRes.json();
                
                if (historyData.length === 0) {
                    document.getElementById('history-container').innerHTML = 
                        '<p>لا توجد قرارات في السجل</p>';
                } else {
                    const historyHTML = historyData.slice(-10).reverse().map(record => `
                        <div class="agent-item">
                            <strong>${record.symbol}</strong> → 
                            <span class="agent-signal ${record.decision.toLowerCase()}">
                                ${record.decision}
                            </span>
                            (ثقة: ${record.confidence}, إجماع: ${record.consensus}
                            ${record.conflict ? ', ⚠️ تضارب' : ''})
                        </div>
                    `).join('');
                    document.getElementById('history-container').innerHTML = historyHTML;
                }
                
            } catch (error) {
                console.error('Error updating dashboard:', error);
                document.getElementById('decision-container').innerHTML = 
                    `<p style="color: #f44336;">خطأ في الاتصال: ${error.message}</p>`;
            }
        }
        
        // تحديث عند التحميل
        updateDashboard();
        
        // تحديث كل ثانية
        setInterval(updateDashboard, 1000);
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    # مثال على الاستخدام
    from unified_decision_center import UnifiedDecisionCenter
    
    # إنشاء مركز القرار والـ dashboard
    center = UnifiedDecisionCenter()
    dashboard = UnifiedControlDashboard(center, port=8780)
    
    # تشغيل لوحة التحكم
    dashboard.run(debug=False)
