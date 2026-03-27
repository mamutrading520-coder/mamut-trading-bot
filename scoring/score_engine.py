"""Score engine for passed tokens"""

from __future__ import annotations

from typing import Dict, Any
from datetime import datetime

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus

logger = setup_logger("ScoreEngine")


class ScoreEngine:
    """Computes final token score after trash filtering."""

    def __init__(self):
        self.event_bus = get_event_bus()
        self.scored_count = 0
        self.failed_count = 0

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _compute_quality_score(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build final score from early-stage quality signals and residual risk.
        Returns:
        - final_score: 0..100
        - confidence: 0..1
        - breakdown
        """
        market_cap_sol = self._safe_float(token_data.get("market_cap_sol", 0))
        metadata_score = max(0.0, min(100.0, self._safe_float(token_data.get("metadata_score", 0))))
        social_count = int(token_data.get("social_count", 0) or 0)

        aggregate_risk = self._safe_float(token_data.get("aggregate_risk_score", 35))
        authority_risk = self._safe_float(token_data.get("authority_risk", 40))
        creator_risk = self._safe_float(token_data.get("creator_risk", 45))
        concentration_risk = self._safe_float(token_data.get("concentration_risk", 35))
        metadata_risk = self._safe_float(token_data.get("metadata_risk", 40))
        honeypot_risk = self._safe_float(token_data.get("honeypot_risk", 30))

        metadata_retrieved = bool(token_data.get("metadata_retrieved", False))
        metadata_present = bool(token_data.get("metadata_json") or token_data.get("uri_metadata"))

        score = 62.0
        notes = []

        # Metadata quality: no castigar fuerte si aún no llegó metadata real
        if not metadata_retrieved and not metadata_present:
            notes.append("Metadata pending")
        else:
            if metadata_score >= 80:
                score += 10
                notes.append("Strong metadata quality")
            elif metadata_score >= 60:
                score += 7
                notes.append("Good metadata quality")
            elif metadata_score >= 40:
                score += 3
                notes.append("Acceptable metadata quality")
            elif metadata_score > 0:
                score -= 4
                notes.append("Weak metadata quality")

        # Social presence: señal positiva, pero ausencia no debe matar early tokens
        if social_count >= 3:
            score += 7
            notes.append("Strong social presence")
        elif social_count == 2:
            score += 4
        elif social_count == 1:
            score += 2
        else:
            score -= 1
            notes.append("No socials detected")

        # Early market-cap sanity
        if 15 <= market_cap_sol <= 250:
            score += 6
            notes.append("Healthy early market cap range")
        elif 5 <= market_cap_sol < 15:
            score += 3
        elif market_cap_sol > 500:
            score -= 3
            notes.append("Late/extended market cap profile")

        # Main residual-risk penalty: usar aggregate como castigo principal
        score -= aggregate_risk * 0.38

        # Secondary fine-tuning only for extreme risks
        if authority_risk >= 80:
            score -= 6
            notes.append("High authority risk")
        elif authority_risk >= 60:
            score -= 3

        if creator_risk >= 80:
            score -= 5
            notes.append("High creator risk")
        elif creator_risk >= 60:
            score -= 2

        if concentration_risk >= 85:
            score -= 5
            notes.append("High concentration risk")
        elif concentration_risk >= 65:
            score -= 2

        if metadata_risk >= 85 and metadata_retrieved:
            score -= 5
            notes.append("High metadata risk")
        elif metadata_risk >= 65 and metadata_retrieved:
            score -= 2

        if honeypot_risk >= 80:
            score -= 8
            notes.append("High honeypot risk")
        elif honeypot_risk >= 60:
            score -= 4

        final_score = round(max(0.0, min(100.0, score)), 2)

        # Confidence: mezcla de score, limpieza y completitud de datos
        data_completeness = 0.0
        if metadata_retrieved or metadata_present:
            data_completeness += 0.2
        if social_count > 0:
            data_completeness += 0.1
        if market_cap_sol > 0:
            data_completeness += 0.1

        cleanliness = max(0.0, 100.0 - aggregate_risk)
        confidence = (
            (final_score / 100.0) * 0.5
            + (cleanliness / 100.0) * 0.3
            + data_completeness * 0.2
        )
        confidence = round(max(0.0, min(0.99, confidence)), 4)

        return {
            "final_score": final_score,
            "confidence": confidence,
            "breakdown": {
                "market_cap_sol": market_cap_sol,
                "metadata_score": metadata_score,
                "social_count": social_count,
                "aggregate_risk": aggregate_risk,
                "authority_risk": authority_risk,
                "creator_risk": creator_risk,
                "concentration_risk": concentration_risk,
                "metadata_risk": metadata_risk,
                "honeypot_risk": honeypot_risk,
                "metadata_retrieved": metadata_retrieved,
                "metadata_present": metadata_present,
                "notes": notes,
            },
        }
       
       
        

    async def score_and_emit(self, event: Event) -> bool:
        """Score token and emit ScoreCalculated."""
        try:
            token_data = event.data or {}
            mint = token_data.get("mint")
            if not mint:
                logger.warning("score_and_emit called without mint")
                return False

            result = self._compute_quality_score(token_data)

            score_event = Event(
                event_type="ScoreCalculated",
                data={
                    **token_data,
                    "final_score": result["final_score"],
                    "confidence": result["confidence"],
                    "score_breakdown": result["breakdown"],
                },
                source="ScoreEngine",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(score_event)

            self.scored_count += 1
            logger.info(
                f"ScoreCalculated: {mint[:8]}... | "
                f"score={result['final_score']:.2f} | conf={result['confidence']:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Error scoring token: {e}")
            self.failed_count += 1
            return False

    def get_stats(self) -> Dict[str, Any]:
        total = self.scored_count + self.failed_count
        return {
            "scored_count": self.scored_count,
            "failed_count": self.failed_count,
            "success_rate": self.scored_count / total if total > 0 else 0,
        }
