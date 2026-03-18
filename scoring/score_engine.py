"""Comprehensive score calculation engine"""
from typing import Dict, Any, Optional
from datetime import datetime
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.thresholds import (
    FLOW_ANALYSIS_THRESHOLDS,
    HOLDER_QUALITY_THRESHOLDS,
)
from scoring.score_weights import (
    SCORE_WEIGHTS,
    combine_scores,
    get_risk_level,
    get_confidence,
)

logger = setup_logger("ScoreEngine")

class ScoreEngine:
    """Calculates comprehensive risk and quality scores"""

    def __init__(self):
        self.event_bus = get_event_bus()
        self.scored_count = 0
        self.failed_count = 0

    def _calculate_flow_score(self, token_data: Dict[str, Any]) -> float:
        """Calculate flow quality score"""
        try:
            initial_buy = token_data.get("initial_buy", 0)
            initial_sol = token_data.get("initial_sol", 0)
            v_tokens_in_bonding = token_data.get("v_tokens_in_bonding_curve", 0)
            v_sol_in_bonding = token_data.get("v_sol_in_bonding_curve", 0)

            score = 50.0

            min_initial_sol = FLOW_ANALYSIS_THRESHOLDS.get("min_volume_threshold", 0.5)
            if initial_sol >= min_initial_sol:
                score += 15.0

            min_initial_buyers = FLOW_ANALYSIS_THRESHOLDS.get("min_initial_buyers", 5)
            if initial_buy >= min_initial_buyers:
                score += 15.0

            if v_tokens_in_bonding > 0 and v_sol_in_bonding > 0:
                curve_ratio = v_sol_in_bonding / v_tokens_in_bonding
                if 0.000001 <= curve_ratio <= 0.01:
                    score += 10.0

            if initial_sol < 0.01:
                score -= 20.0

            return max(0.0, min(100.0, score))

        except Exception as e:
            logger.debug(f"Error calculating flow score: {e}")
            return 50.0

    def _calculate_holder_quality_score(self, token_data: Dict[str, Any]) -> float:
        """Calculate buyer/holder quality score"""
        try:
            score = 60.0

            concentration_analysis = token_data.get("concentration_analysis", {})
            holder_count = concentration_analysis.get("total_holders", 0)

            min_holders = HOLDER_QUALITY_THRESHOLDS.get("min_unique_buyers", 10)

            if holder_count >= min_holders * 2:
                score += 20.0
            elif holder_count >= min_holders:
                score += 10.0
            elif holder_count > 0:
                score -= 10.0

            return max(0.0, min(100.0, score))

        except Exception as e:
            logger.debug(f"Error calculating holder quality: {e}")
            return 60.0

    def _extract_risk_scores(self, filter_results: Dict[str, Any]) -> Dict[str, float]:
        """Extract individual risk scores from filter results"""
        checks = filter_results.get("checks", {})

        return {
            "authority": checks.get("authority", {}).get("score", 50.0),
            "creator": checks.get("creator_risk", {}).get("score", 50.0),
            "concentration": checks.get("concentration", {}).get("score", 50.0),
        }

    def calculate_score(
        self,
        token_data: Dict[str, Any],
        filter_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate comprehensive token score"""
        try:
            mint = token_data.get("mint")
            symbol = token_data.get("symbol", "UNKNOWN")

            risk_scores = self._extract_risk_scores(filter_results)
            flow_score = self._calculate_flow_score(token_data)
            holder_quality = self._calculate_holder_quality_score(token_data)

            final_score = combine_scores(
                authority_risk=risk_scores["authority"],
                creator_risk=risk_scores["creator"],
                holder_quality=holder_quality,
                concentration=risk_scores["concentration"],
                flow_score=flow_score,
            )

            risk_level = get_risk_level(final_score)
            confidence = get_confidence(final_score)

            analysis = {
                "mint": mint,
                "symbol": symbol,
                "final_score": final_score,
                "confidence": confidence,
                "risk_level": risk_level,
                "component_scores": {
                    "authority_risk": risk_scores["authority"],
                    "creator_risk": risk_scores["creator"],
                    "concentration": risk_scores["concentration"],
                    "flow": flow_score,
                    "holder_quality": holder_quality,
                },
                "weights": SCORE_WEIGHTS,
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.scored_count += 1
            logger.debug(f"Scored {mint[:8]}...: {final_score:.1f} ({risk_level})")

            return analysis

        except Exception as e:
            logger.error(f"Error calculating score: {e}")
            self.failed_count += 1
            return {
                "mint": token_data.get("mint"),
                "error": str(e),
                "final_score": 0.0,
            }

    async def score_and_emit(self, event: Event) -> bool:
        """Score token and emit ScoreCalculated event"""
        try:
            score_analysis = self.calculate_score(event.data, event.data)

            if "error" in score_analysis:
                return False

            score_event = Event(
                event_type="ScoreCalculated",
                data=score_analysis,
                source="ScoreEngine",
                timestamp=datetime.utcnow()
            )

            await self.event_bus.emit(score_event)
            return True

        except Exception as e:
            logger.error(f"Error in score_and_emit: {e}")
            self.failed_count += 1
            return False

    def get_stats(self) -> dict:
        """Get score engine statistics"""
        total = self.scored_count + self.failed_count
        return {
            "scored_count": self.scored_count,
            "failed_count": self.failed_count,
            "success_rate": self.scored_count / total if total > 0 else 0,
        }