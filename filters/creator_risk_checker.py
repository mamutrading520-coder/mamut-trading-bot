"""Creator risk pattern detection"""
from typing import Dict, Any, Tuple
from monitoring.logger import setup_logger
from config.thresholds import CREATOR_RISK_PATTERNS, CREATOR_RISK_THRESHOLDS

logger = setup_logger("CreatorRiskChecker")


class CreatorRiskChecker:
    """Detects risky creator patterns with evidence-aware scoring."""

    def __init__(self):
        self.checked_count = 0
        self.suspicious_count = 0

    def _resolved_outcomes(self, analysis: Dict[str, Any]) -> int:
        failed = int(analysis.get("failed_tokens", 0) or 0)
        successful = int(analysis.get("successful_tokens", 0) or 0)
        return max(0, failed + successful)

    def _analyze_failure_rate(self, analysis: Dict[str, Any]) -> Tuple[float, str]:
        failed = int(analysis.get("failed_tokens", 0) or 0)
        resolved = self._resolved_outcomes(analysis)
        min_history = int(
            CREATOR_RISK_THRESHOLDS.get("min_outcome_history_for_failure_penalty", 3)
        )

        if resolved < min_history or failed == 0:
            return 0.0, ""

        failure_rate = failed / resolved

        if resolved >= 6 and failure_rate >= 0.85:
            return 35.0, f"Very poor resolved history: {failed}/{resolved} failures ({failure_rate:.1%})"
        if resolved >= 4 and failure_rate >= 0.70:
            return 22.0, f"Poor resolved history: {failed}/{resolved} failures ({failure_rate:.1%})"
        if failure_rate >= 0.50:
            return 10.0, f"Elevated failure rate: {failed}/{resolved} failures ({failure_rate:.1%})"

        return 0.0, ""

    def _analyze_wallet_age(self, wallet_age_days: int) -> Tuple[float, str]:
        min_age = CREATOR_RISK_PATTERNS.get("wallet_age_min_days", 7)

        if wallet_age_days < 1:
            return 18.0, "Brand new wallet (< 1 day)"
        if wallet_age_days < min_age:
            return 10.0, f"Very new wallet ({wallet_age_days} days old)"
        if wallet_age_days < 30:
            return 4.0, f"Recent wallet ({wallet_age_days} days old)"

        return 0.0, ""

    def _analyze_token_velocity(self, total_tokens: int, wallet_age_days: int) -> Tuple[float, str]:
        if wallet_age_days < 1 or total_tokens < 6:
            return 0.0, ""

        tokens_per_day = total_tokens / max(wallet_age_days, 1)

        if tokens_per_day >= 3.0:
            return 12.0, f"Aggressive launch velocity: {tokens_per_day:.1f} tokens/day"
        if tokens_per_day >= 1.5:
            return 6.0, f"Elevated launch velocity: {tokens_per_day:.1f} tokens/day"

        return 0.0, ""

    def _analyze_average_score(self, avg_score: float, resolved_outcomes: int) -> Tuple[float, str]:
        if avg_score == 0 or resolved_outcomes < 3:
            return 0.0, ""

        if avg_score < 30:
            return 12.0, f"Very low avg successful signal score: {avg_score:.1f}"
        if avg_score < 50:
            return 6.0, f"Low avg successful signal score: {avg_score:.1f}"

        return 0.0, ""

    def check_creator_risk(self, creator_analysis: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """Check creator patterns for risk."""
        try:
            analysis = {
                "creator": creator_analysis.get("creator"),
                "is_trusted": creator_analysis.get("is_trusted", False),
                "is_blacklisted": creator_analysis.get("is_blacklisted", False),
                "risk_factors": [],
            }

            risk_score = 18.0
            resolved_outcomes = self._resolved_outcomes(creator_analysis)
            min_history = int(
                CREATOR_RISK_THRESHOLDS.get("min_outcome_history_for_failure_penalty", 3)
            )

            if analysis["is_blacklisted"]:
                risk_score = 100.0
                analysis["risk_factors"].append("CRITICAL: Creator is blacklisted")
                self.checked_count += 1
                self.suspicious_count += 1
                return risk_score, analysis

            if analysis["is_trusted"]:
                risk_score = max(0.0, risk_score - 10.0)
                analysis["risk_factors"].append("POSITIVE: Trusted creator")

            failure_score, failure_msg = self._analyze_failure_rate(creator_analysis)
            if failure_msg:
                risk_score += failure_score
                analysis["risk_factors"].append(failure_msg)
            elif resolved_outcomes < min_history:
                analysis["risk_factors"].append("INFO: Insufficient resolved creator history")

            wallet_age = int(creator_analysis.get("wallet_age_days", 0) or 0)
            age_score, age_msg = self._analyze_wallet_age(wallet_age)
            if age_msg:
                risk_score += age_score
                analysis["risk_factors"].append(age_msg)

            total_tokens = int(creator_analysis.get("total_tokens", 0) or 0)
            velocity_score, velocity_msg = self._analyze_token_velocity(total_tokens, wallet_age)
            if velocity_msg:
                risk_score += velocity_score
                analysis["risk_factors"].append(velocity_msg)

            avg_score = float(creator_analysis.get("average_score", 0.0) or 0.0)
            score_rating, score_msg = self._analyze_average_score(avg_score, resolved_outcomes)
            if score_msg:
                risk_score += score_rating
                analysis["risk_factors"].append(score_msg)

            risk_score = max(0.0, min(100.0, risk_score))

            self.checked_count += 1
            if risk_score >= 70:
                self.suspicious_count += 1

            return risk_score, analysis

        except Exception as e:
            logger.error(f"Error checking creator risk: {e}")
            return 50.0, {"error": str(e)}

    def get_stats(self) -> dict:
        """Get checker statistics"""
        return {
            "checked_count": self.checked_count,
            "suspicious_count": self.suspicious_count,
            "suspicious_rate": self.suspicious_count / self.checked_count
                             if self.checked_count > 0 else 0,
        }
