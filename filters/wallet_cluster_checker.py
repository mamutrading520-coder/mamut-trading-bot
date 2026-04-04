from typing import Any, Dict, List
from loguru import logger


class WalletClusterChecker:
    """
    Heuristic wallet clustering risk checker.

    This module does not perform on-chain graph clustering. It estimates
    concentration and coordination risk using early holder-distribution
    signals available during discovery/enrichment.
    """

    def __init__(self) -> None:
        self.analyzed_count = 0
        self.high_risk_count = 0
        logger.debug("WalletClusterChecker initialized")

    async def analyze(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze holder distribution and return cluster-risk heuristics."""
        try:
            holder_count = self._as_int(token_data.get("holder_count"))
            top_holder_percentage = self._as_float(token_data.get("top_holder_percentage"))
            top_5_holders_percentage = self._as_float(token_data.get("top_5_holders_percentage"))
            top_10_holders_percentage = self._as_float(token_data.get("top_10_holders_percentage"))
            creator_hold_percentage = self._as_float(token_data.get("creator_hold_percentage"))

            sniper_wallets_detected_raw = token_data.get("sniper_wallets_detected")
            fresh_wallet_ratio_raw = token_data.get("fresh_wallet_ratio")
            sniper_wallets_detected = self._as_int(sniper_wallets_detected_raw)
            fresh_wallet_ratio = self._as_float(fresh_wallet_ratio_raw)
            sniper_signal_present = sniper_wallets_detected_raw is not None
            fresh_wallet_signal_present = fresh_wallet_ratio_raw is not None

            concentration_score = self._resolve_concentration_score(
                token_data=token_data,
                top_holder_percentage=top_holder_percentage,
                top_5_holders_percentage=top_5_holders_percentage,
                top_10_holders_percentage=top_10_holders_percentage,
                creator_hold_percentage=creator_hold_percentage,
            )
            distribution_score = self._resolve_distribution_score(token_data=token_data)

            risk_score = 8.0
            risk_flags: List[str] = []

            if concentration_score >= 70:
                risk_score += 22.0
                risk_flags.append("holder_cluster_extreme_concentration")
            elif concentration_score >= 50:
                risk_score += 14.0
                risk_flags.append("holder_cluster_high_concentration")
            elif concentration_score >= 35:
                risk_score += 7.0
                risk_flags.append("holder_cluster_elevated_concentration")

            if holder_count > 0:
                if holder_count <= 10:
                    risk_score += 8.0
                    risk_flags.append("very_few_holders")
                elif holder_count <= 20:
                    risk_score += 5.0
                    risk_flags.append("few_holders")
                elif holder_count >= 60:
                    risk_score -= 6.0
                elif holder_count >= 30:
                    risk_score -= 3.0

            if top_holder_percentage >= 35:
                risk_score += 10.0
                risk_flags.append("top_holder_concentrated")
            elif top_holder_percentage >= 20:
                risk_score += 5.0
                risk_flags.append("top_holder_elevated")

            if top_5_holders_percentage >= 70:
                risk_score += 8.0
                risk_flags.append("top5_highly_concentrated")
            elif top_5_holders_percentage >= 55:
                risk_score += 4.0
                risk_flags.append("top5_concentrated")

            if creator_hold_percentage >= 20:
                risk_score += 8.0
                risk_flags.append("creator_large_allocation")
            elif creator_hold_percentage >= 10:
                risk_score += 4.0
                risk_flags.append("creator_elevated_allocation")

            if sniper_signal_present:
                if sniper_wallets_detected >= 5:
                    risk_score += 8.0
                    risk_flags.append("multiple_sniper_wallets")
                elif sniper_wallets_detected >= 2:
                    risk_score += 4.0
                    risk_flags.append("some_sniper_wallets")

            if fresh_wallet_signal_present:
                if fresh_wallet_ratio >= 0.80:
                    risk_score += 6.0
                    risk_flags.append("fresh_wallet_clustering")
                elif fresh_wallet_ratio >= 0.55:
                    risk_score += 3.0
                    risk_flags.append("fresh_wallet_bias")

            if distribution_score >= 70:
                risk_score -= 10.0
            elif distribution_score >= 50:
                risk_score -= 5.0
            elif distribution_score <= 20 and holder_count > 0:
                risk_score += 4.0
                risk_flags.append("weak_distribution_quality")

            if holder_count == 0 and concentration_score == 0 and not fresh_wallet_signal_present and not sniper_signal_present:
                risk_score = 12.0
                risk_flags.append("insufficient_cluster_data")

            cluster_risk_score = max(0.0, min(100.0, round(risk_score, 2)))

            result = {
                "score": cluster_risk_score,
                "wallet_cluster_risk_score": cluster_risk_score,
                "wallet_cluster_risk_level": self._classify_risk(cluster_risk_score),
                "wallet_cluster_flags": self._dedupe_flags(risk_flags),
                "is_wallet_cluster_high_risk": cluster_risk_score >= 65,
                "is_wallet_cluster_medium_risk": 40 <= cluster_risk_score < 65,
                "wallet_cluster_summary": self._build_summary(
                    risk_score=cluster_risk_score,
                    concentration_score=concentration_score,
                    distribution_score=distribution_score,
                    flags=risk_flags,
                ),
                "wallet_cluster_inputs": {
                    "holder_count": holder_count,
                    "top_holder_percentage": top_holder_percentage,
                    "top_5_holders_percentage": top_5_holders_percentage,
                    "top_10_holders_percentage": top_10_holders_percentage,
                    "creator_hold_percentage": creator_hold_percentage,
                    "sniper_wallets_detected": sniper_wallets_detected,
                    "fresh_wallet_ratio": fresh_wallet_ratio,
                    "holder_concentration_score": concentration_score,
                    "holder_distribution_score": distribution_score,
                },
            }

            self.analyzed_count += 1
            if cluster_risk_score >= 65:
                self.high_risk_count += 1

            logger.debug(
                "Wallet cluster analysis complete | risk=%s | concentration=%s | distribution=%s | flags=%s",
                cluster_risk_score,
                concentration_score,
                distribution_score,
                result["wallet_cluster_flags"],
            )
            return result

        except Exception as e:
            logger.error(f"Wallet cluster analysis failed: {e}")
            return {
                "score": 35.0,
                "wallet_cluster_risk_score": 35.0,
                "wallet_cluster_risk_level": "MEDIUM",
                "wallet_cluster_flags": ["wallet_cluster_analysis_error"],
                "is_wallet_cluster_high_risk": False,
                "is_wallet_cluster_medium_risk": True,
                "wallet_cluster_summary": "wallet cluster analysis failed",
            }

    def _resolve_concentration_score(
        self,
        token_data: Dict[str, Any],
        top_holder_percentage: float,
        top_5_holders_percentage: float,
        top_10_holders_percentage: float,
        creator_hold_percentage: float,
    ) -> float:
        holder_concentration_score = token_data.get("holder_concentration_score")
        if holder_concentration_score is not None:
            return max(0.0, min(100.0, self._as_float(holder_concentration_score)))

        score = 0.0
        if top_holder_percentage >= 35:
            score += 30.0
        elif top_holder_percentage >= 20:
            score += 18.0
        elif top_holder_percentage >= 10:
            score += 8.0

        if top_5_holders_percentage >= 70:
            score += 25.0
        elif top_5_holders_percentage >= 50:
            score += 15.0
        elif top_5_holders_percentage >= 35:
            score += 8.0

        if top_10_holders_percentage >= 85:
            score += 20.0
        elif top_10_holders_percentage >= 70:
            score += 12.0
        elif top_10_holders_percentage >= 55:
            score += 6.0

        if creator_hold_percentage >= 20:
            score += 25.0
        elif creator_hold_percentage >= 10:
            score += 12.0
        elif creator_hold_percentage >= 5:
            score += 5.0

        return max(0.0, min(100.0, score))

    def _resolve_distribution_score(self, token_data: Dict[str, Any]) -> float:
        distribution_score = token_data.get("holder_distribution_score")
        if distribution_score is None:
            return 0.0
        return max(0.0, min(100.0, self._as_float(distribution_score)))

    def _classify_risk(self, risk_score: float) -> str:
        if risk_score >= 65:
            return "HIGH"
        if risk_score >= 40:
            return "MEDIUM"
        return "LOW"

    def _build_summary(
        self,
        risk_score: float,
        concentration_score: float,
        distribution_score: float,
        flags: List[str],
    ) -> str:
        parts = [
            f"wallet_cluster_risk={int(risk_score)}",
            f"concentration={int(concentration_score)}",
            f"distribution={int(distribution_score)}",
        ]
        if flags:
            parts.append(f"flags={','.join(self._dedupe_flags(flags)[:4])}")
        return " | ".join(parts)

    def _dedupe_flags(self, flags: List[str]) -> List[str]:
        seen = set()
        deduped: List[str] = []
        for flag in flags:
            if flag in seen:
                continue
            seen.add(flag)
            deduped.append(flag)
        return deduped

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

    def get_stats(self) -> dict:
        """Get checker statistics."""
        return {
            "analyzed_count": self.analyzed_count,
            "high_risk_count": self.high_risk_count,
            "high_risk_rate": self.high_risk_count / self.analyzed_count if self.analyzed_count > 0 else 0,
        }
