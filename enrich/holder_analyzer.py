from typing import Any, Dict, List
from loguru import logger


class HolderAnalyzer:
    """
    Early holder-distribution analyzer.

    This module estimates concentration, distribution quality and
    participation breadth using the limited early holder data available
    during discovery/enrichment.
    """

    def __init__(self) -> None:
        logger.debug("HolderAnalyzer initialized")

    async def analyze(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze holder distribution and return normalized metrics.
        """
        try:
            holder_count = self._as_int(token_data.get("holder_count"))
            top_holder_percentage = self._as_float(token_data.get("top_holder_percentage"))
            top_5_holders_percentage = self._as_float(token_data.get("top_5_holders_percentage"))
            top_10_holders_percentage = self._as_float(token_data.get("top_10_holders_percentage"))
            creator_hold_percentage = self._as_float(token_data.get("creator_hold_percentage"))
            fresh_wallet_ratio = self._as_float(token_data.get("fresh_wallet_ratio"))
            sniper_wallets_detected = self._as_int(token_data.get("sniper_wallets_detected"))

            concentration_score = self._compute_concentration_score(
                top_holder_percentage=top_holder_percentage,
                top_5_holders_percentage=top_5_holders_percentage,
                top_10_holders_percentage=top_10_holders_percentage,
                creator_hold_percentage=creator_hold_percentage,
            )

            distribution_score = self._compute_distribution_score(
                holder_count=holder_count,
                concentration_score=concentration_score,
                fresh_wallet_ratio=fresh_wallet_ratio,
                sniper_wallets_detected=sniper_wallets_detected,
            )

            risk_flags: List[str] = []

            if holder_count <= 15:
                risk_flags.append("very_low_holder_count")
            elif holder_count <= 30:
                risk_flags.append("low_holder_count")

            if top_holder_percentage >= 35:
                risk_flags.append("top_holder_concentrated")
            elif top_holder_percentage >= 20:
                risk_flags.append("top_holder_elevated")

            if top_5_holders_percentage >= 70:
                risk_flags.append("top5_highly_concentrated")
            elif top_5_holders_percentage >= 50:
                risk_flags.append("top5_concentrated")

            if creator_hold_percentage >= 20:
                risk_flags.append("creator_large_allocation")
            elif creator_hold_percentage >= 10:
                risk_flags.append("creator_elevated_allocation")

            if fresh_wallet_ratio >= 0.8:
                risk_flags.append("fresh_wallets_dominant")
            elif fresh_wallet_ratio >= 0.5:
                risk_flags.append("fresh_wallets_elevated")

            if sniper_wallets_detected >= 5:
                risk_flags.append("multiple_sniper_wallets")
            elif sniper_wallets_detected >= 2:
                risk_flags.append("some_sniper_wallets")

            result = {
                "holder_count": holder_count,
                "top_holder_percentage": top_holder_percentage,
                "top_5_holders_percentage": top_5_holders_percentage,
                "top_10_holders_percentage": top_10_holders_percentage,
                "creator_hold_percentage": creator_hold_percentage,
                "fresh_wallet_ratio": fresh_wallet_ratio,
                "sniper_wallets_detected": sniper_wallets_detected,
                "holder_concentration_score": concentration_score,
                "holder_distribution_score": distribution_score,
                "holder_risk_flags": risk_flags,
                "holder_summary": self._build_summary(
                    holder_count=holder_count,
                    concentration_score=concentration_score,
                    distribution_score=distribution_score,
                    risk_flags=risk_flags,
                ),
            }

            logger.debug(
                f"Holder analysis complete | holders={holder_count} | "
                f"distribution={distribution_score} | concentration={concentration_score}"
            )
            return result

        except Exception as e:
            logger.error(f"Holder analysis failed: {e}")
            return {
                "holder_count": 0,
                "top_holder_percentage": 0.0,
                "top_5_holders_percentage": 0.0,
                "top_10_holders_percentage": 0.0,
                "creator_hold_percentage": 0.0,
                "fresh_wallet_ratio": 0.0,
                "sniper_wallets_detected": 0,
                "holder_concentration_score": 100.0,
                "holder_distribution_score": 0.0,
                "holder_risk_flags": ["holder_analysis_error"],
                "holder_summary": "holder analysis failed",
            }

    def _compute_concentration_score(
        self,
        top_holder_percentage: float,
        top_5_holders_percentage: float,
        top_10_holders_percentage: float,
        creator_hold_percentage: float,
    ) -> float:
        score = 0.0

        if top_holder_percentage >= 35:
            score += 30
        elif top_holder_percentage >= 20:
            score += 18
        elif top_holder_percentage >= 10:
            score += 8

        if top_5_holders_percentage >= 70:
            score += 25
        elif top_5_holders_percentage >= 50:
            score += 15
        elif top_5_holders_percentage >= 35:
            score += 8

        if top_10_holders_percentage >= 85:
            score += 20
        elif top_10_holders_percentage >= 70:
            score += 12
        elif top_10_holders_percentage >= 55:
            score += 6

        if creator_hold_percentage >= 20:
            score += 25
        elif creator_hold_percentage >= 10:
            score += 12
        elif creator_hold_percentage >= 5:
            score += 5

        return min(100.0, score)

    def _compute_distribution_score(
        self,
        holder_count: int,
        concentration_score: float,
        fresh_wallet_ratio: float,
        sniper_wallets_detected: int,
    ) -> float:
        score = 20.0

        if holder_count >= 150:
            score += 35
        elif holder_count >= 80:
            score += 25
        elif holder_count >= 40:
            score += 15
        elif holder_count >= 20:
            score += 8

        score += max(0.0, 30.0 - (concentration_score * 0.3))

        if fresh_wallet_ratio < 0.3:
            score += 10
        elif fresh_wallet_ratio < 0.5:
            score += 5
        elif fresh_wallet_ratio >= 0.8:
            score -= 10

        if sniper_wallets_detected == 0:
            score += 5
        elif sniper_wallets_detected >= 5:
            score -= 10
        elif sniper_wallets_detected >= 2:
            score -= 5

        return max(0.0, min(100.0, score))

    def _build_summary(
        self,
        holder_count: int,
        concentration_score: float,
        distribution_score: float,
        risk_flags: List[str],
    ) -> str:
        parts = [
            f"holders={holder_count}",
            f"distribution={int(distribution_score)}",
            f"concentration={int(concentration_score)}",
        ]
        if risk_flags:
            parts.append(f"flags={','.join(risk_flags[:4])}")
        return " | ".join(parts)

    def _as_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _as_float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0
