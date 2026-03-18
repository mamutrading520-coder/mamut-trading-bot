"""Decision mapper for token scoring analysis"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus

logger = setup_logger("DecisionMapper")

# Decision metadata mapping
SCORE_METADATA = {
    "high_potential": {
        "display_name": "HIGH_POTENTIAL",
        "color": "green",
        "emoji": "🟢",
        "description": "High quality token with good potential",
        "action": "SIGNAL_EARLY"
    },
    "medium_potential": {
        "display_name": "MEDIUM_POTENTIAL",
        "color": "yellow",
        "emoji": "🟡",
        "description": "Moderate quality token, worth monitoring",
        "action": "MONITOR"
    },
    "low_potential": {
        "display_name": "LOW_POTENTIAL",
        "color": "orange",
        "emoji": "🟠",
        "description": "Low quality token, high risk",
        "action": "WARN"
    },
    "trash": {
        "display_name": "TRASH",
        "color": "red",
        "emoji": "🔴",
        "description": "Likely scam or rug pull",
        "action": "REJECT"
    }
}


class DecisionMapper:
    """Maps scores to trading decisions"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.decisions_made = 0
        self.high_potential_count = 0
        self.medium_potential_count = 0
        self.low_potential_count = 0

    def _normalize_risk_level(self, risk_level: str) -> str:
        """Normalize risk_level to match SCORE_METADATA keys"""
        if not risk_level:
            return "trash"

        normalized = risk_level.lower().replace("-", "_")

        if normalized not in SCORE_METADATA:
            return "trash"

        return normalized

    def _create_decision_reasoning(self, score_analysis: Dict[str, Any]) -> str:
        """Create human-readable reasoning for the decision"""
        final_score = score_analysis.get("final_score", 0)
        risk_level = score_analysis.get("risk_level", "UNKNOWN")
        confidence = score_analysis.get("confidence", 0)

        reasoning = f"Score: {final_score:.1f}, Risk: {risk_level}, Confidence: {confidence:.2f}"

        component_scores = score_analysis.get("component_scores", {})
        if component_scores:
            components = []
            for key, value in component_scores.items():
                components.append(f"{key}:{value:.1f}")
            reasoning += f" | Components: {', '.join(components)}"

        return reasoning

    def make_decision(self, score_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Make trading decision based on score"""
        try:
            final_score = score_analysis.get("final_score", 0)
            risk_level = score_analysis.get("risk_level", "TRASH")
            confidence = score_analysis.get("confidence", 0)
            mint = score_analysis.get("mint")
            symbol = score_analysis.get("symbol", "UNKNOWN")

            normalized_risk = self._normalize_risk_level(risk_level)
            metadata = SCORE_METADATA.get(normalized_risk, SCORE_METADATA["trash"])

            decision = {
                "mint": mint,
                "symbol": symbol,
                "final_score": final_score,
                "risk_level": risk_level,
                "confidence": confidence,
                "decision": metadata.get("action", "REJECT"),
                "description": metadata.get("description", "Unknown"),
                "reasoning": self._create_decision_reasoning(score_analysis),
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.decisions_made += 1
            if normalized_risk == "high_potential":
                self.high_potential_count += 1
            elif normalized_risk == "medium_potential":
                self.medium_potential_count += 1
            elif normalized_risk == "low_potential":
                self.low_potential_count += 1

            logger.debug(f"Decision made: {mint[:8]}... -> {decision['decision']}")
            return decision

        except Exception as e:
            logger.error(f"Error making decision: {e}", exc_info=True)
            return {
                "mint": score_analysis.get("mint"),
                "symbol": score_analysis.get("symbol", "UNKNOWN"),
                "error": str(e),
                "decision": "REJECT"
            }

    async def map_and_emit(self, event: Event) -> Optional[str]:
        """Map score to decision and emit DecisionMade event"""
        try:
            decision = self.make_decision(event.data)

            if "error" in decision:
                logger.warning(f"Failed to make decision for {event.data.get('mint', 'UNKNOWN')}")
                return None

            decision_action = decision.get("decision", "REJECT")
            risk_level = decision.get("risk_level", "TRASH")

            decision_event = Event(
                event_type="DecisionMade",
                data=decision,
                source="DecisionMapper",
                timestamp=datetime.utcnow()
            )

            await self.event_bus.emit(decision_event)
            logger.info(f"✓ DecisionMade emitted: {decision_action} (risk={risk_level})")

            return decision_action

        except Exception as e:
            logger.error(f"Error in map_and_emit: {e}", exc_info=True)
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        total = self.decisions_made
        high_pct = (self.high_potential_count / total * 100) if total > 0 else 0
        medium_pct = (self.medium_potential_count / total * 100) if total > 0 else 0
        low_pct = (self.low_potential_count / total * 100) if total > 0 else 0

        return {
            "decisions_made": self.decisions_made,
            "high_potential_count": self.high_potential_count,
            "high_potential_pct": f"{high_pct:.1f}%",
            "medium_potential_count": self.medium_potential_count,
            "medium_potential_pct": f"{medium_pct:.1f}%",
            "low_potential_count": self.low_potential_count,
            "low_potential_pct": f"{low_pct:.1f}%",
        }