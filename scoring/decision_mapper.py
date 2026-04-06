"""Decision mapper for token scoring analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

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
    """Maps score outputs to pipeline decisions."""

    _STRICT_SIGNAL_EARLY_FLAGS: Set[str] = {
        "routing_context_phrase",
        "deictic_generic_construct",
        "numeric_generic_construct",
        "generic_context_construct",
        "low_identity_short_name",
        "status_update_phrase",
        "announcement_phrase",
        "title_like_narrative_phrase",
        "role_claim_phrase",
        "generic_prefix_branding",
        "aspirational_generic_branding",
        "profane_symbol",
        "profane_phrase",
        "promo_slogan",
        "cta_phrase",
    }
    _REVIEW_SIGNAL_EARLY_FLAGS: Set[str] = {
        "context_heavy_short_name",
        "inflated_all_caps_phrase",
        "sentence_like_name",
        "weak_lead_phrase",
        "linking_verb_structure",
        "all_caps_claim",
        "multiword_name",
    }

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

    def _safe_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _get_breakdown(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload.get("score_breakdown", {}) or {}

    def _get_semantic_flags(self, payload: Dict[str, Any]) -> Set[str]:
        breakdown = self._get_breakdown(payload)
        flags = breakdown.get("semantic_flags")
        if flags is None:
            flags = payload.get("semantic_risk_flags", []) or []
        return {str(flag) for flag in flags if flag}

    def _make_reasoning(self, score_analysis: Dict[str, Any], decision: str) -> str:
        final_score = self._safe_float(score_analysis.get("final_score", 0))
        confidence = self._safe_float(score_analysis.get("confidence", 0))
        aggregate_risk = self._safe_float(score_analysis.get("aggregate_risk_score", 0))

        breakdown = self._get_breakdown(score_analysis)
        notes = breakdown.get("notes", []) or []
        adjustments = score_analysis.get("decision_adjustments", []) or []

        reasoning = (
            f"Decision={decision} | "
            f"Score={final_score:.2f} | "
            f"Confidence={confidence:.2f} | "
            f"AggregateRisk={aggregate_risk:.2f}"
        )

        if score_analysis.get("creator_resolved") is False:
            reasoning += " | creator_resolved=False"

        if adjustments:
            reasoning += f" | Adjustments: {', '.join(adjustments)}"

        if notes:
            reasoning += f" | Notes: {', '.join(notes)}"

        return reasoning

    def _apply_signal_early_guards(self, payload: Dict[str, Any]) -> List[str]:
        adjustments: List[str] = []

        final_score = self._safe_float(payload.get("final_score", 0))
        confidence = self._safe_float(payload.get("confidence", 0))
        aggregate_risk = self._safe_float(payload.get("aggregate_risk_score", 50))
        creator_risk = self._safe_float(payload.get("creator_risk", 0))
        wallet_cluster_risk = self._safe_float(payload.get("wallet_cluster_risk", 0))
        honeypot_risk = self._safe_float(payload.get("honeypot_risk", 0))

        breakdown = self._get_breakdown(payload)
        semantic_risk = self._safe_float(
            breakdown.get("semantic_risk", payload.get("semantic_risk", 0)),
        )
        metadata_score = self._safe_float(
            breakdown.get("metadata_score", payload.get("metadata_score", 0)),
        )
        semantic_gate_applied = self._safe_bool(
            breakdown.get("semantic_early_gate_applied", False)
        )
        semantic_flags = self._get_semantic_flags(payload)

        strict_high_threshold = max(float(self.settings.score_threshold_high_potential), 63.0)
        strict_min_confidence = max(float(self.settings.signal_early_min_confidence), 0.67)
        strict_max_aggregate_risk = min(float(self.settings.signal_early_max_aggregate_risk), 30.0)

        if final_score < strict_high_threshold:
            adjustments.append(f"signal_early_score_floor<{strict_high_threshold:.0f}")
        if confidence < strict_min_confidence:
            adjustments.append(f"signal_early_confidence_floor<{strict_min_confidence:.2f}")
        if aggregate_risk > strict_max_aggregate_risk:
            adjustments.append(f"signal_early_risk_cap>{strict_max_aggregate_risk:.0f}")
        if semantic_gate_applied:
            adjustments.append("semantic_early_gate_applied")
        if semantic_risk >= 15.0:
            adjustments.append(f"semantic_risk={semantic_risk:.1f}")
        if semantic_flags & self._STRICT_SIGNAL_EARLY_FLAGS:
            adjustments.append(
                "strict_semantic_flags=" + ",".join(sorted(semantic_flags & self._STRICT_SIGNAL_EARLY_FLAGS))
            )
        elif semantic_flags & self._REVIEW_SIGNAL_EARLY_FLAGS and semantic_risk >= 12.0:
            adjustments.append(
                "review_semantic_flags=" + ",".join(sorted(semantic_flags & self._REVIEW_SIGNAL_EARLY_FLAGS))
            )
        if metadata_score < 65.0:
            adjustments.append(f"metadata_score={metadata_score:.0f}")
        if wallet_cluster_risk >= 45.0:
            adjustments.append(f"wallet_cluster_risk={wallet_cluster_risk:.0f}")
        if creator_risk >= 50.0:
            adjustments.append(f"creator_risk={creator_risk:.0f}")
        if honeypot_risk >= 40.0:
            adjustments.append(f"honeypot_risk={honeypot_risk:.0f}")

        return adjustments

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

        decision_adjustments: List[str] = []

        if decision == "SIGNAL_EARLY":
            decision_adjustments.extend(self._apply_signal_early_guards(score_analysis))
            if decision_adjustments:
                decision = "MONITOR"
                logger.debug(
                    f"Downgraded {symbol} SIGNAL_EARLY → MONITOR: {'; '.join(decision_adjustments)}"
                )

        if score_analysis.get("creator_resolved") is False and decision == "SIGNAL_EARLY":
            decision = "MONITOR"
            decision_adjustments.append("creator_resolved=False")
            logger.debug(
                f"Downgraded {symbol} SIGNAL_EARLY → MONITOR: creator_resolved=False"
            )

        meta = DECISION_METADATA[decision]
        decision_payload = {
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
            "decision_adjustments": decision_adjustments,
            "decision_gates": {
                "signal_early_min_score": high_threshold,
                "signal_early_min_confidence": signal_early_min_confidence,
                "signal_early_max_aggregate_risk": signal_early_max_aggregate_risk,
                "signal_early_strict_min_score": max(high_threshold, 63.0),
                "signal_early_strict_min_confidence": max(signal_early_min_confidence, 0.67),
                "signal_early_strict_max_aggregate_risk": min(signal_early_max_aggregate_risk, 30.0),
                "monitor_min_score": medium_threshold,
                "monitor_min_confidence": monitor_min_confidence,
                "monitor_max_aggregate_risk": monitor_max_aggregate_risk,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        decision_payload["reasoning"] = self._make_reasoning(decision_payload, decision)
        return decision_payload

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
