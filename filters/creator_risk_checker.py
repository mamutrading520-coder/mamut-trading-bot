"""Creator risk pattern detection"""
from typing import Dict, Any, Tuple
from monitoring.logger import setup_logger
from config.thresholds import CREATOR_RISK_PATTERNS

logger = setup_logger("CreatorRiskChecker")

class CreatorRiskChecker:
    """Detects risky creator patterns"""
    
    def __init__(self):
        self.checked_count = 0
        self.suspicious_count = 0
    
    def _analyze_failure_rate(self, analysis: Dict[str, Any]) -> Tuple[float, str]:
        """Analyze failure rate pattern"""
        total = analysis.get("total_tokens", 0)
        failed = analysis.get("failed_tokens", 0)
        
        if total == 0:
            return 0.0, ""
        
        failure_rate = failed / total
        threshold = CREATOR_RISK_PATTERNS.get("failed_tokens_threshold", 3)
        
        if failed >= threshold and failure_rate > 0.5:
            return 40.0, f"High failure rate: {failed}/{total} ({failure_rate:.1%})"
        elif failed >= 2:
            return 20.0, f"Multiple failures: {failed}/{total}"
        
        return 0.0, ""
    
    def _analyze_wallet_age(self, wallet_age_days: int) -> Tuple[float, str]:
        """Analyze wallet age pattern"""
        min_age = CREATOR_RISK_PATTERNS.get("wallet_age_min_days", 7)
        
        if wallet_age_days < 1:
            return 35.0, "Brand new wallet (< 1 day)"
        elif wallet_age_days < min_age:
            return 25.0, f"Very new wallet ({wallet_age_days} days old)"
        elif wallet_age_days < 30:
            return 10.0, f"New wallet ({wallet_age_days} days old)"
        
        return 0.0, ""
    
    def _analyze_token_velocity(self, total_tokens: int, wallet_age_days: int) -> Tuple[float, str]:
        """Analyze token launch velocity"""
        if wallet_age_days < 1 or total_tokens == 0:
            return 0.0, ""
        
        tokens_per_day = total_tokens / wallet_age_days
        min_interval_hours = CREATOR_RISK_PATTERNS.get("launch_min_interval_hours", 24)
        min_interval_days = min_interval_hours / 24
        
        if tokens_per_day > (1 / min_interval_days):
            return 20.0, f"Aggressive launch velocity: {tokens_per_day:.1f} tokens/day"
        
        return 0.0, ""
    
    def _analyze_average_score(self, avg_score: float) -> Tuple[float, str]:
        """Analyze average token score"""
        if avg_score == 0:
            return 0.0, ""
        
        if avg_score < 30:
            return 30.0, f"Very low avg token score: {avg_score:.1f}"
        elif avg_score < 50:
            return 15.0, f"Low avg token score: {avg_score:.1f}"
        
        return 0.0, ""
    
    def check_creator_risk(self, creator_analysis: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """
        Check creator patterns for risk
        
        Args:
            creator_analysis: Creator analysis from database
            
        Returns:
            Tuple of (risk_score, analysis_details)
        """
        try:
            analysis = {
                "creator": creator_analysis.get("creator"),
                "is_trusted": creator_analysis.get("is_trusted", False),
                "is_blacklisted": creator_analysis.get("is_blacklisted", False),
                "risk_factors": [],
            }
            
            risk_score = 0.0
            
            # CRITICAL: Blacklisted creator
            if analysis["is_blacklisted"]:
                risk_score = 100.0
                analysis["risk_factors"].append("CRITICAL: Creator is blacklisted")
                self.checked_count += 1
                self.suspicious_count += 1
                return risk_score, analysis
            
            # POSITIVE: Trusted creator
            if analysis["is_trusted"]:
                risk_score = max(0.0, risk_score - 15.0)
                analysis["risk_factors"].append("POSITIVE: Trusted creator (reputation bonus)")
            
            # Analyze failure rate
            failure_score, failure_msg = self._analyze_failure_rate(creator_analysis)
            if failure_msg:
                risk_score += failure_score
                analysis["risk_factors"].append(failure_msg)
            
            # Analyze wallet age
            wallet_age = creator_analysis.get("wallet_age_days", 0)
            age_score, age_msg = self._analyze_wallet_age(wallet_age)
            if age_msg:
                risk_score += age_score
                analysis["risk_factors"].append(age_msg)
            
            # Analyze token velocity
            total_tokens = creator_analysis.get("total_tokens", 0)
            velocity_score, velocity_msg = self._analyze_token_velocity(total_tokens, wallet_age)
            if velocity_msg:
                risk_score += velocity_score
                analysis["risk_factors"].append(velocity_msg)
            
            # Analyze average score
            avg_score = creator_analysis.get("average_score", 0.0)
            score_rating, score_msg = self._analyze_average_score(avg_score)
            if score_msg:
                risk_score += score_rating
                analysis["risk_factors"].append(score_msg)
            
            # Clamp to 0-100
            risk_score = max(0.0, min(100.0, risk_score))
            
            self.checked_count += 1
            if risk_score >= 60:
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