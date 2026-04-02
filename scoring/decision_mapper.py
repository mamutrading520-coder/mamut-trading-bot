"""Decision mapper for token scoring analysis"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus

logger = setup_logger("DecisionMapper")


DECISION_METADATA = {
    "SIGNAL_EARLY": {
        "display_name": "HIGH_POTENTIAL",
        "color": "green",
        "description": "High quality token with good early-entry potential",
    },
    "MONITOR": {
        "display_name": "MEDIUM_POTENTIAL",
        "color": "yellow",
        "description": "Moderate quality token, worth monitoring",
    },
    "WARN": {
        "display_name": "LOW_POTENTIAL",
        "color": "orange",
        "description": "Low quality token, high caution required",
    },
    "REJECT": {
        "display_name": "TRASH",
        "color": "red",
        "description": "Insufficient quality for signal generation",
    },
}


class DecisionMapper:
    """Maps score outputs to trading decisions."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        self.decisions_made = 0
        self.signal_early_count = 0
        self.monitor_count = 0
        self.warn_count = 0
        self.reject_count = 0

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _make_reasoning(self, score_analysis: Dict[str, Any], decision: str) -> str:
        final_score = self._safe_float(score_analysis.get("final_score", 0))
        confidence = self._safe_float(score_analysis.get("confidence", 0))
        aggregate_risk = self._safe_float(score_analysis.get("aggregate_risk_score", 0))

        breakdown = score_analysis.get("score_breakdown", {}) or {}
        notes = breakdown.get("notes", []) or []

        reasoning = (
            f"Decision={decision} | "
            f"Score={final_score:.2f} | "
            f"Confidence={confidence:.2f} | "
            f"AggregateRisk={aggregate_risk:.2f}"
        )

        if score_analysis.get("creator_resolved") is False:
            reasoning += " | creator_resolved=False"

        if notes:
            reasoning += f" | Notes: {', '.join(notes)}"

        return reasoning

    def _map_decision(self, score_analysis: Dict[str, Any]) -> Dict[str, Any]:
        final_score = self._safe_float(score_analysis.get("final_score", 0))
        confidence = self._safe_float(score_analysis.get("confidence", 0))
        aggregate_risk = self._safe_float(score_analysis.get("aggregate_risk_score", 50))

        mint = score_analysis.get("mint")
        symbol = score_analysis.get("symbol", "UNKNOWN")

        high_threshold = float(self.settings.score_threshold_high_potential)
        medium_threshold = float(self.settings.score_threshold_medium_potential)
        low_threshold = float(self.settings.score_threshold_low_potential)

        signal_early_min_confidence = float(self.settings.signal_early_min_confidence)
        signal_early_max_aggregate_risk = float(self.settings.signal_early_max_aggregate_risk)
        monitor_min_confidence = float(self.settings.monitor_min_confidence)
        monitor_max_aggregate_risk = float(self.settings.monitor_max_aggregate_risk)

        if (
            final_score >= high_threshold
            and confidence >= signal_early_min_confidence
            and aggregate_risk <= signal_early_max_aggregate_risk
        ):
            decision = "SIGNAL_EARLY"
        elif (
            final_score >= medium_threshold
            and confidence >= monitor_min_confidence
            and aggregate_risk <= monitor_max_aggregate_risk
        ):
            decision = "MONITOR"
        elif final_score >= low_threshold:
            decision = "WARN"
        else:
            decision = "REJECT"

        if decision == "SIGNAL_EARLY" and score_analysis.get("creator_resolved") is False:
            decision = "MONITOR"
            logger.debug(
                f"Downgraded {symbol} SIGNAL_EARLY → MONITOR: creator_resolved=False"
            )

        meta = DECISION_METADATA[decision]

        return {
            "mint": mint,
            "symbol": symbol,
            "final_score": final_score,
            "confidence": confidence,
            "decision": decision,
            "classification": meta["display_name"],
            "color": meta["color"],
            "description": meta["description"],
            "aggregate_risk_score": aggregate_risk,
            "score_breakdown": score_analysis.get("score_breakdown", {}),
            "reasoning": self._make_reasoning(score_analysis, decision),
            "decision_gates": {
                "signal_early_min_score": high_threshold,
                "signal_early_min_confidence": signal_early_min_confidence,
                "signal_early_max_aggregate_risk": signal_early_max_aggregate_risk,
                "monitor_min_score": medium_threshold,
                "monitor_min_confidence": monitor_min_confidence,
                "monitor_max_aggregate_risk": monitor_max_aggregate_risk,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    def make_decision(self, score_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Make decision based on score + confidence + residual risk."""
        try:
            decision = self._map_decision(score_analysis)

            self.decisions_made += 1
            action = decision["decision"]
            if action == "SIGNAL_EARLY":
                self.signal_early_count += 1
            elif action == "MONITOR":
                self.monitor_count += 1
            elif action == "WARN":
                self.warn_count += 1
            else:
                self.reject_count += 1

            logger.debug(
                f"Decision made: {decision.get('mint', 'UNKNOWN')} -> {action}"
            )
            return decision

        except Exception as e:
            logger.error(f"Error making decision: {e}", exc_info=True)
            return {
                "mint": score_analysis.get("mint"),
                "symbol": score_analysis.get("symbol", "UNKNOWN"),
                "error": str(e),
                "decision": "REJECT",
            }

    async def map_and_emit(self, event: Event) -> Optional[str]:
        """Map score to decision and emit DecisionMade event."""
        try:
            decision = self.make_decision(event.data)
            if "error" in decision:
                logger.warning(
                    f"Failed to make decision for {event.data.get('mint', 'UNKNOWN')}"
                )
                return None

            decision_event = Event(
                event_type="DecisionMade",
                data=decision,
                source="DecisionMapper",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(decision_event)
            logger.info(
                f"DecisionMade emitted: {decision['decision']} "
                f"(score={decision['final_score']:.2f}, conf={decision['confidence']:.2f}, risk={decision['aggregate_risk_score']:.2f})"
            )
            return decision["decision"]

        except Exception as e:
            logger.error(f"Error in map_and_emit: {e}", exc_info=True)
            return None

    def get_stats(self) -> Dict[str, Any]:
        total = self.decisions_made
        return {
            "decisions_made": total,
            "signal_early_count": self.signal_early_count,
            "monitor_count": self.monitor_count,
            "warn_count": self.warn_count,
            "reject_count": self.reject_count,
            "signal_early_pct": f"{(self.signal_early_count / total * 100):.1f}%" if total else "0.0%",
            "monitor_pct": f"{(self.monitor_count / total * 100):.1f}%" if total else "0.0%",
            "warn_pct": f"{(self.warn_count / total * 100):.1f}%" if total else "0.0%",
            "reject_pct": f"{(self.reject_count / total * 100):.1f}%" if total else "0.0%",
        }
