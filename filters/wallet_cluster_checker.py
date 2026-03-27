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
        """
        Analyze holder distribution and return cluster-risk heuristics.
        """
        try:
            risk_score = 0
            risk_flags: List[str] = []

            holder_count = self._as_int(token_data.get("holder_count"))
            top_holder_percentage = self._as_float(token_data.get("top_holder_percentage"))
            top_5_holders_percentage = self._as_float(token_data.get("top_5_holders_percentage"))
            top_10_holders_percentage = self._as_float(token_data.get("top_10_holders_percentage"))
            creator_hold_percentage = self._as_float(token_data.get("creator_hold_percentage"))
            sniper_wallets_detected = self._as_int(token_data.get("sniper_wallets_detected"))
            fresh_wallet_ratio = self._as_float(token_data.get("fresh_wallet_ratio"))

            if holder_count <= 15:
                risk_score += 18
                risk_flags.append("very_few_holders")
            elif holder_count <= 30:
                risk_score += 10
                risk_flags.append("few_holders")

            if top_holder_percentage >= 35:
                risk_score += 20
                risk_flags.append("top_holder_concentrated")
            elif top_holder_percentage >= 20:
                risk_score += 10
                risk_flags.append("top_holder_elevated")

            if top_5_holders_percentage >= 70:
                risk_score += 20
                risk_flags.append("top5_highly_concentrated")
            elif top_5_holders_percentage >= 50:
                risk_score += 12
                risk_flags.append("top5_concentrated")

            if top_10_holders_percentage >= 85:
                risk_score += 15
                risk_flags.append("top10_extreme_concentration")
            elif top_10_holders_percentage >= 70:
                risk_score += 8
                risk_flags.append("top10_high_concentration")

            if creator_hold_percentage >= 20:
                risk_score += 15
                risk_flags.append("creator_large_allocation")
            elif creator_hold_percentage >= 10:
                risk_score += 8
                risk_flags.append("creator_elevated_allocation")

            if sniper_wallets_detected >= 5:
                risk_score += 12
                risk_flags.append("multiple_sniper_wallets")
            elif sniper_wallets_detected >= 2:
                risk_score += 6
                risk_flags.append("some_sniper_wallets")

            if fresh_wallet_ratio >= 0.8:
                risk_score += 10
                risk_flags.append("fresh_wallet_clustering")
            elif fresh_wallet_ratio >= 0.5:
                risk_score += 5
                risk_flags.append("fresh_wallet_bias")

            cluster_risk_score = min(100.0, float(risk_score))

            result = {
                "score": cluster_risk_score,
                "wallet_cluster_risk_score": cluster_risk_score,
                "wallet_cluster_risk_level": self._classify_risk(cluster_risk_score),
                "wallet_cluster_flags": risk_flags,
                "is_wallet_cluster_high_risk": cluster_risk_score >= 60,
                "is_wallet_cluster_medium_risk": 35 <= cluster_risk_score < 60,
                "wallet_cluster_summary": self._build_summary(cluster_risk_score, risk_flags),
            }

            self.analyzed_count += 1
            if cluster_risk_score >= 60:
                self.high_risk_count += 1

            logger.debug(
                f"Wallet cluster analysis complete | risk={cluster_risk_score} | flags={risk_flags}"
            )
            return result

        except Exception as e:
            logger.error(f"Wallet cluster analysis failed: {e}")
            return {
                "wallet_cluster_risk_score": 100.0,
                "wallet_cluster_risk_level": "UNKNOWN",
                "wallet_cluster_flags": ["wallet_cluster_analysis_error"],
                "is_wallet_cluster_high_risk": True,
                "is_wallet_cluster_medium_risk": False,
                "wallet_cluster_summary": "wallet cluster analysis failed",
            }

    def _classify_risk(self, risk_score: float) -> str:
        if risk_score >= 60:
            return "HIGH"
        if risk_score >= 35:
            return "MEDIUM"
        return "LOW"

    def _build_summary(self, risk_score: float, flags: List[str]) -> str:
        if not flags:
            return f"wallet_cluster_risk={int(risk_score)} | no major flags"
        return f"wallet_cluster_risk={int(risk_score)} | flags={','.join(flags[:4])}"

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
