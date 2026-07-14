"""
unified_decision_center.py — مركز قيادة موحد لجميع الوكلاء
═══════════════════════════════════════════════════════════

كل الوكلاء يعملون تحت عقل واحد ويقررون معاً.
خاتم واحد ليحكمهم جميعاً.

بنية القرار الموحدة:
  1. جمع إشارات من جميع الوكلاء (Fractal, SMC, ICT, Touch, Session)
  2. مركز القرار الموحد يحلل التضارب والتوافق
  3. إصدار قرار واحد موحد
  4. جميع الوكلاء ينفذون نفس القرار
  5. لوحة تحكم موحدة لمراقبة الجميع

الوزن الموحد:
  - Fractal Agent (الهيكل)         : 0.40
  - SMC Agent (تأكيد الدخول)       : 0.35
  - ICT Agent (اختراقات عميقة)     : 0.15
  - Touch Agent (مستويات اللمس)    : 0.10
  ────────────────────────────────────────
  المجموع                            : 1.00
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List
from enum import Enum

log = logging.getLogger("unified_decision_center")


class UnifiedDecision(Enum):
    """القرار الموحد النهائي."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class AgentSignal:
    """إشارة واحدة من وكيل واحد."""
    agent_name: str
    direction: str  # BUY, SELL, HOLD, NONE
    confidence: float  # 0.0 - 1.0
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    strength: float = 0.0  # مدى قوة الإشارة


@dataclass
class UnifiedDecisionResult:
    """النتيجة النهائية الموحدة."""
    timestamp: str
    symbol: str
    timeframe: str
    
    # القرار النهائي الموحد
    unified_decision: UnifiedDecision
    unified_confidence: float
    
    # تفاصيل المساهمة من كل وكيل
    agent_signals: List[AgentSignal] = field(default_factory=list)
    
    # التحليل
    consensus_level: float = 0.0  # % اتفاق الوكلاء
    conflict_detected: bool = False
    conflict_description: str = ""
    
    # السبب النهائي
    final_reason: str = ""
    
    # معلومات السوق المشتركة
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    market_quality: float = 0.0  # 0-1
    
    # الحالة
    approved_by_safety: bool = False
    safety_notes: str = ""
    
    # للتتبع
    cycle_number: int = 0
    execution_status: str = "pending"  # pending, approved, blocked, executed


class UnifiedDecisionCenter:
    """مركز القرار الموحد لجميع الوكلاء."""
    
    # الأوزان الثابتة لكل وكيل
    AGENT_WEIGHTS = {
        "fractal": 0.40,
        "smc": 0.35,
        "ict": 0.15,
        "touch": 0.10,
    }
    
    CONFIDENCE_THRESHOLD = 0.65  # الحد الأدنى للثقة
    CONSENSUS_THRESHOLD = 0.70   # % اتفاق الوكلاء
    
    def __init__(self, project_root: Path | str = None):
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.log_path = self.project_root / "logs" / "unified_decisions.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.last_decision: Optional[UnifiedDecisionResult] = None
        self.decision_history: List[UnifiedDecisionResult] = []
        
        log.info(f"🧠 Unified Decision Center initialized at {self.log_path}")
    
    def process_signals(
        self,
        symbol: str,
        timeframe: str,
        fractal_signal: AgentSignal | None = None,
        smc_signal: AgentSignal | None = None,
        ict_signal: AgentSignal | None = None,
        touch_signal: AgentSignal | None = None,
        market_data: Dict | None = None,
        cycle_number: int = 0,
    ) -> UnifiedDecisionResult:
        """
        معالجة الإشارات من جميع الوكلاء وإصدار قرار موحد.
        
        Args:
            symbol: الرمز (XAUUSDm, EUR/USD, etc)
            timeframe: الإطار الزمني (M1, H1, etc)
            fractal_signal: إشارة من Fractal Agent
            smc_signal: إشارة من SMC Agent
            ict_signal: إشارة من ICT Agent
            touch_signal: إشارة من Touch Agent
            market_data: بيانات السوق (bid, ask, spread, etc)
            cycle_number: رقم الدورة
        
        Returns:
            UnifiedDecisionResult: النتيجة الموحدة
        """
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # جمع الإشارات
        signals = []
        if fractal_signal:
            signals.append(fractal_signal)
        if smc_signal:
            signals.append(smc_signal)
        if ict_signal:
            signals.append(ict_signal)
        if touch_signal:
            signals.append(touch_signal)
        
        # معالجة بيانات السوق
        market_data = market_data or {}
        bid = market_data.get("bid", 0.0)
        ask = market_data.get("ask", 0.0)
        spread = ask - bid if ask and bid else 0.0
        market_quality = market_data.get("market_quality", 0.5)
        
        # حساب القرار الموحد
        result = self._calculate_unified_decision(
            symbol=symbol,
            timeframe=timeframe,
            signals=signals,
            bid=bid,
            ask=ask,
            spread=spread,
            market_quality=market_quality,
            cycle_number=cycle_number,
        )
        result.timestamp = timestamp
        
        # تسجيل في السجل
        self._log_decision(result)
        
        # الاحتفاظ بآخر قرار
        self.last_decision = result
        self.decision_history.append(result)
        if len(self.decision_history) > 1000:
            self.decision_history = self.decision_history[-1000:]
        
        return result
    
    def _calculate_unified_decision(
        self,
        symbol: str,
        timeframe: str,
        signals: List[AgentSignal],
        bid: float,
        ask: float,
        spread: float,
        market_quality: float,
        cycle_number: int,
    ) -> UnifiedDecisionResult:
        """حساب القرار الموحد من الإشارات."""
        
        result = UnifiedDecisionResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            timeframe=timeframe,
            agent_signals=signals,
            bid=bid,
            ask=ask,
            spread=spread,
            market_quality=market_quality,
            cycle_number=cycle_number,
        )
        
        if not signals:
            result.unified_decision = UnifiedDecision.HOLD
            result.unified_confidence = 0.0
            result.final_reason = "no_signals"
            return result
        
        # حساب الأوزان والنقاط
        buy_score = 0.0
        sell_score = 0.0
        total_weight = 0.0
        buy_count = 0
        sell_count = 0
        hold_count = 0
        
        for signal in signals:
            agent_name = signal.agent_name.lower()
            weight = self.AGENT_WEIGHTS.get(agent_name, 0.1)
            confidence = signal.confidence * weight
            
            total_weight += weight
            
            if signal.direction == "BUY":
                buy_score += confidence
                buy_count += 1
            elif signal.direction == "SELL":
                sell_score += confidence
                sell_count += 1
            else:
                hold_count += 1
        
        # تطبيع النقاط
        if total_weight > 0:
            buy_score /= total_weight
            sell_score /= total_weight
        
        # حساب مستوى الإجماع (% الوكلاء المتفقة)
        total_signals = len(signals)
        if total_signals > 0:
            result.consensus_level = max(buy_count, sell_count, hold_count) / total_signals
        
        # تحديد التضارب
        if buy_count > 0 and sell_count > 0:
            result.conflict_detected = True
            result.conflict_description = f"BUY: {buy_count} agents vs SELL: {sell_count} agents"
            log.warning(f"⚠️ Conflict in signals: {result.conflict_description}")
        
        # اتخاذ القرار النهائي الموحد
        if buy_score > sell_score and buy_score > 0.65:
            result.unified_decision = UnifiedDecision.BUY
            result.unified_confidence = buy_score
            result.final_reason = f"consensus_buy_score_{buy_score:.3f}"
        elif sell_score > buy_score and sell_score > 0.65:
            result.unified_decision = UnifiedDecision.SELL
            result.unified_confidence = sell_score
            result.final_reason = f"consensus_sell_score_{sell_score:.3f}"
        else:
            result.unified_decision = UnifiedDecision.HOLD
            result.unified_confidence = max(buy_score, sell_score)
            result.final_reason = "insufficient_consensus"
        
        # إذا كان هناك تضارب، خفض الثقة
        if result.conflict_detected:
            result.unified_confidence *= 0.8
            result.final_reason += "_with_conflicts"
        
        return result
    
    def get_dashboard_data(self) -> Dict:
        """الحصول على بيانات لوحة التحكم الموحدة."""
        if not self.last_decision:
            return {"status": "no_decision_yet"}
        
        result = self.last_decision
        
        return {
            "timestamp": result.timestamp,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            
            # القرار النهائي
            "unified_decision": result.unified_decision.value,
            "unified_confidence": f"{result.unified_confidence:.3f}",
            "final_reason": result.final_reason,
            
            # الإجماع
            "consensus_level": f"{result.consensus_level * 100:.1f}%",
            "conflict_detected": result.conflict_detected,
            "conflict_description": result.conflict_description,
            
            # إشارات الوكلاء
            "agent_signals": [
                {
                    "agent": s.agent_name,
                    "direction": s.direction,
                    "confidence": f"{s.confidence:.3f}",
                    "reason": s.reason,
                }
                for s in result.agent_signals
            ],
            
            # بيانات السوق
            "market": {
                "bid": result.bid,
                "ask": result.ask,
                "spread": result.spread,
                "market_quality": f"{result.market_quality:.2f}",
            },
            
            # الحالة الأمنية
            "safety": {
                "approved": result.approved_by_safety,
                "notes": result.safety_notes,
            },
            
            "cycle": result.cycle_number,
        }
    
    def get_formatted_report(self) -> str:
        """تقرير مرسوم للعرض في الـ terminal/dashboard."""
        data = self.get_dashboard_data()
        
        if data["status"] == "no_decision_yet":
            return "🧠 مركز القرار الموحد: لا توجد قرارات بعد"
        
        report = f"""
╔═══════════════════════════════════════════════════════════════════╗
║          🧠 مركز القرار الموحد — UNIFIED DECISION CENTER          ║
╚═══════════════════════════════════════════════════════════════════╝

📊 القرار النهائي الموحد:
  │ الإشارة: {data['unified_decision']:12} │ الثقة: {data['unified_confidence']:>6} │
  │ السبب: {data['final_reason']}
  
🤝 مستوى الإجماع:
  │ النسبة: {data['consensus_level']:>6}
  │ تضارب؟ {'نعم ⚠️' if data['conflict_detected'] else 'لا ✓'}
  {f'│ التفاصيل: {data["conflict_description"]}' if data['conflict_detected'] else ''}

👥 إشارات الوكلاء:
"""
        for signal in data["agent_signals"]:
            report += f"  │ {signal['agent']:12} → {signal['direction']:6} (ثقة: {signal['confidence']:6}) {signal['reason']}\n"
        
        report += f"""
📈 بيانات السوق:
  │ الطلب (BID): {data['market']['bid']:10.3f}
  │ العرض (ASK): {data['market']['ask']:10.3f}
  │ السبريد: {data['market']['spread']:10.3f}
  │ جودة السوق: {data['market']['market_quality']:6}
  
🔒 الفحص الأمني:
  │ معتمد: {'✓' if data['safety']['approved'] else '✗'}
  │ الملاحظات: {data['safety']['notes']}

📍 الدورة: {data['cycle']}
⏰ الوقت: {data['timestamp']}

╚═══════════════════════════════════════════════════════════════════╝
"""
        return report
    
    def _log_decision(self, result: UnifiedDecisionResult):
        """تسجيل القرار في ملف JSONL."""
        try:
            record = {
                "timestamp": result.timestamp,
                "symbol": result.symbol,
                "timeframe": result.timeframe,
                "unified_decision": result.unified_decision.value,
                "unified_confidence": result.unified_confidence,
                "consensus_level": result.consensus_level,
                "conflict_detected": result.conflict_detected,
                "conflict_description": result.conflict_description,
                "final_reason": result.final_reason,
                "cycle_number": result.cycle_number,
                "bid": result.bid,
                "ask": result.ask,
                "spread": result.spread,
                "market_quality": result.market_quality,
                "agent_signals": [
                    {
                        "agent": s.agent_name,
                        "direction": s.direction,
                        "confidence": s.confidence,
                        "reason": s.reason,
                    }
                    for s in result.agent_signals
                ],
            }
            
            with open(self.log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.error(f"Failed to log decision: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# مثال على الاستخدام
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # إعداد logging
    logging.basicConfig(level=logging.INFO)
    
    # إنشاء مركز القرار
    center = UnifiedDecisionCenter()
    
    # نموذج إشارات من الوكلاء
    fractal_signal = AgentSignal(
        agent_name="fractal",
        direction="BUY",
        confidence=0.85,
        reason="bullish_structure_identified",
        strength=0.8,
    )
    
    smc_signal = AgentSignal(
        agent_name="smc",
        direction="BUY",
        confidence=0.70,
        reason="order_block_break_confirmed",
        strength=0.7,
    )
    
    ict_signal = AgentSignal(
        agent_name="ict",
        direction="BUY",
        confidence=0.65,
        reason="deep_liquidity_sweep",
        strength=0.6,
    )
    
    touch_signal = AgentSignal(
        agent_name="touch",
        direction="HOLD",
        confidence=0.50,
        reason="no_significant_touch_level",
        strength=0.3,
    )
    
    market_data = {
        "bid": 4700.50,
        "ask": 4700.80,
        "market_quality": 0.85,
    }
    
    # معالجة الإشارات والحصول على القرار الموحد
    decision = center.process_signals(
        symbol="XAUUSDm",
        timeframe="M1",
        fractal_signal=fractal_signal,
        smc_signal=smc_signal,
        ict_signal=ict_signal,
        touch_signal=touch_signal,
        market_data=market_data,
        cycle_number=1,
    )
    
    # طباعة التقرير
    print(center.get_formatted_report())
    
    # طباعة بيانات JSON
    print("\nJSON Data:")
    print(json.dumps(center.get_dashboard_data(), indent=2))
