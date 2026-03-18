"""Check token authorities for honeypot indicators"""
from typing import Dict, Any, Tuple
from monitoring.logger import setup_logger
from config.thresholds import AUTHORITY_RISK_WEIGHTS, HONEYPOT_THRESHOLDS

logger = setup_logger("AuthorityChecker")

class AuthorityChecker:
    """Validates token authorities and detects honeypot indicators"""
    
    def __init__(self):
        self.checked_count = 0
        self.honeypot_detected = 0
    
    def _is_null_authority(self, authority: str) -> bool:
        """
        Check if authority is null (renounced)
        
        Args:
            authority: Authority address string
            
        Returns:
            True if authority is null/renounced
        """
        if not authority:
            return True
        
        # Common null addresses in Solana
        null_addresses = [
            "11111111111111111111111111111111",
            "system",
            "SystemProgram",
            "",
        ]
        
        return authority.strip().lower() in [addr.lower() for addr in null_addresses]
    
    def check_authorities(self, token_data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """
        Check token authorities for honeypot indicators
        
        Args:
            token_data: Enriched token data
            
        Returns:
            Tuple of (risk_score, analysis_details)
        """
        try:
            mint_authority = token_data.get("mint_authority")
            freeze_authority = token_data.get("freeze_authority")
            owner = token_data.get("owner")
            
            analysis = {
                "mint_authority": mint_authority,
                "freeze_authority": freeze_authority,
                "owner": owner,
                "mint_authority_null": self._is_null_authority(mint_authority),
                "freeze_authority_null": self._is_null_authority(freeze_authority),
                "owner_renounced": self._is_null_authority(owner),
                "risk_factors": [],
                "is_honeypot": False,
            }
            
            risk_score = 0.0
            
            # CRITICAL: Freeze authority is not null (can freeze accounts)
            if not analysis["freeze_authority_null"]:
                is_critical = HONEYPOT_THRESHOLDS.get("freeze_authority_is_honeypot", True)
                if is_critical:
                    risk_score += AUTHORITY_RISK_WEIGHTS.get("freeze_authority_not_null", 40)
                    analysis["risk_factors"].append("CRITICAL: Freeze authority retained (can freeze accounts)")
                    analysis["is_honeypot"] = True
            
            # HIGH: Mint authority is not null (can mint infinite tokens)
            if not analysis["mint_authority_null"]:
                risk_score += AUTHORITY_RISK_WEIGHTS.get("mint_authority_not_null", 35)
                analysis["risk_factors"].append("HIGH: Mint authority retained (can mint infinite tokens)")
                if not analysis["freeze_authority_null"]:
                    analysis["is_honeypot"] = True
            
            # MEDIUM: Owner not renounced
            if not analysis["owner_renounced"]:
                risk_score += AUTHORITY_RISK_WEIGHTS.get("owner_not_renounced", 25)
                analysis["risk_factors"].append("MEDIUM: Owner not renounced")
            
            # Clamp to 0-100
            risk_score = max(0.0, min(100.0, risk_score))
            
            self.checked_count += 1
            if analysis["is_honeypot"]:
                self.honeypot_detected += 1
                logger.warning(f"Honeypot detected via authority check: {token_data.get('mint')[:8]}...")
            
            return risk_score, analysis
            
        except Exception as e:
            logger.error(f"Error checking authorities: {e}")
            return 50.0, {"error": str(e)}
    
    def get_stats(self) -> dict:
        """Get checker statistics"""
        return {
            "checked_count": self.checked_count,
            "honeypot_detected": self.honeypot_detected,
            "honeypot_rate": self.honeypot_detected / self.checked_count 
                           if self.checked_count > 0 else 0,
        }