"""Trash filter engine for token quality assessment"""
from typing import Dict, Any, Optional
from datetime import datetime
from monitoring.logger import setup_logger
from config.settings import Settings
from config.thresholds import (
    TRASH_FILTER_THRESHOLDS,
    CREATOR_RISK_THRESHOLDS,
    CONCENTRATION_THRESHOLDS,
    AUTHORITY_RISK_THRESHOLDS,
)
from storage.sqlite_store import SQLiteStore
from core.event_bus import Event, get_event_bus

logger = setup_logger("TrashFilterEngine")

class TrashFilterEngine:
    """Filters out low-quality and scam tokens"""
    
    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()
        self.passed = 0
        self.rejected = 0
    
    def _calculate_authority_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate authority/permission risk score"""
        try:
            risk_score = 50.0  # Base risk
            
            # Check if mint authority is renounced (good sign)
            mint_authority = token_data.get("mint_authority")
            if mint_authority and mint_authority.lower() == "renounced":
                risk_score -= 30.0
            elif not mint_authority:
                risk_score -= 15.0  # Unknown is slightly better than having authority
            else:
                risk_score += 20.0  # Has authority = higher risk
            
            # Check if freeze authority is renounced
            freeze_authority = token_data.get("freeze_authority")
            if freeze_authority and freeze_authority.lower() == "renounced":
                risk_score -= 20.0
            elif freeze_authority:
                risk_score += 15.0
            
            # Clamp to 0-100
            risk_score = max(0.0, min(100.0, risk_score))
            
            return {
                "score": risk_score,
                "has_mint_authority": mint_authority is not None and mint_authority.lower() != "renounced",
                "has_freeze_authority": freeze_authority is not None and freeze_authority.lower() != "renounced",
            }
        
        except Exception as e:
            logger.debug(f"Error calculating authority risk: {e}")
            return {"score": 50.0}
    
    def _calculate_creator_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate creator reputation risk score"""
        try:
            creator = token_data.get("creator", "unknown")
            risk_score = 50.0  # Base risk for unknown creator
            
            # Get creator profile from DB
            creator_profile = self.store.get_creator_profile(creator)
            
            if creator_profile:
                # Creator with history
                total_tokens = creator_profile.total_tokens
                successful_tokens = creator_profile.successful_tokens
                
                # Check if blacklisted
                if creator_profile.is_blacklisted:
                    risk_score = 95.0
                # Check if trusted
                elif creator_profile.is_trusted:
                    risk_score = 20.0
                else:
                    # Calculate success rate
                    if total_tokens > 0:
                        success_rate = successful_tokens / total_tokens
                        # Higher success rate = lower risk
                        risk_score = 50.0 - (success_rate * 40.0)
                    
                    # Newer creators = higher risk
                    if creator_profile.wallet_age_days is not None:
                        if creator_profile.wallet_age_days < 7:
                            risk_score += 20.0
                        elif creator_profile.wallet_age_days < 30:
                            risk_score += 10.0
            else:
                # New creator with no history = medium-high risk
                risk_score = 60.0
            
            # Clamp to 0-100
            risk_score = max(0.0, min(100.0, risk_score))
            
            return {
                "score": risk_score,
                "creator": creator,
                "is_new": creator_profile is None,
                "is_blacklisted": creator_profile and creator_profile.is_blacklisted,
                "is_trusted": creator_profile and creator_profile.is_trusted,
            }
        
        except Exception as e:
            logger.debug(f"Error calculating creator risk: {e}")
            return {"score": 50.0}
    
    def _calculate_concentration_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate token holder concentration risk"""
        try:
            risk_score = 50.0  # Base risk
            
            # Check if creator holds all tokens (rug pull indicator)
            creator_balance = token_data.get("creator_balance", 0)
            total_supply = token_data.get("total_supply", 1)
            
            if total_supply > 0:
                creator_percentage = (creator_balance / total_supply) * 100
                
                # Creator holds >90% = VERY HIGH RISK
                if creator_percentage > 90:
                    risk_score = 95.0
                # Creator holds >70% = HIGH RISK
                elif creator_percentage > 70:
                    risk_score = 80.0
                # Creator holds >50% = MEDIUM-HIGH RISK
                elif creator_percentage > 50:
                    risk_score = 65.0
                # Creator holds <20% = GOOD (lower risk)
                elif creator_percentage < 20:
                    risk_score = 30.0
            
            # Check holder count (if available)
            holder_count = token_data.get("holder_count", 0)
            if holder_count > 0:
                # More holders = lower concentration risk
                if holder_count > 100:
                    risk_score -= 15.0
                elif holder_count > 50:
                    risk_score -= 10.0
                elif holder_count > 20:
                    risk_score -= 5.0
            
            # Clamp to 0-100
            risk_score = max(0.0, min(100.0, risk_score))
            
            return {
                "score": risk_score,
                "creator_percentage": (creator_balance / total_supply * 100) if total_supply > 0 else 0,
                "holder_count": holder_count,
            }
        
        except Exception as e:
            logger.debug(f"Error calculating concentration risk: {e}")
            return {"score": 50.0}
    
    async def filter_and_emit(self, event: Event) -> Optional[str]:
        """
        Filter token and emit pass/reject event
        
        Args:
            event: TokenEnriched or CreatorProfiled event
        
        Returns:
            "PASSED" or "REJECTED" or None
        """
        try:
            token_data = event.data
            mint = token_data.get("mint")
            
            # Calculate individual risk scores
            authority_risk = self._calculate_authority_risk(token_data)
            creator_risk = self._calculate_creator_risk(token_data)
            concentration_risk = self._calculate_concentration_risk(token_data)
            
            # Hard filters - automatic reject
            hard_reject_reasons = []
            
            # Check authority risk threshold
            if authority_risk["score"] > AUTHORITY_RISK_THRESHOLDS.get("max_authority_risk", 80):
                hard_reject_reasons.append("Exceeds authority risk threshold")
            
            # Check creator risk threshold
            if creator_risk["score"] > CREATOR_RISK_THRESHOLDS.get("max_creator_risk", 85):
                hard_reject_reasons.append("Exceeds creator risk threshold")
            
            # Check concentration threshold
            if concentration_risk["score"] > CONCENTRATION_THRESHOLDS.get("max_concentration_risk", 80):
                hard_reject_reasons.append("Exceeds concentration risk threshold")
            
            # Reject if any hard filter triggered
            if hard_reject_reasons:
                self.rejected += 1
                rejection_event = Event(
                    event_type="TokenRejected",
                    data={
                        "mint": mint,
                        "rejection_reason": " | ".join(hard_reject_reasons),
                        "authority_risk": authority_risk["score"],
                        "creator_risk": creator_risk["score"],
                        "concentration_risk": concentration_risk["score"],
                    },
                    source="TrashFilterEngine",
                    timestamp=datetime.utcnow()
                )
                await self.event_bus.emit(rejection_event)
                logger.warning(f"[REJECTED] {mint[:8]}... - {hard_reject_reasons[0]}")
                return "REJECTED"
            
            # Token passed filters
            self.passed += 1
            
            # Create passed event with risk scores
            passed_event = Event(
                event_type="TokenPassed",
                data={
                    **token_data,
                    "authority_risk": authority_risk["score"],
                    "creator_risk": creator_risk["score"],
                    "concentration_risk": concentration_risk["score"],
                },
                source="TrashFilterEngine",
                timestamp=datetime.utcnow()
            )
            
            await self.event_bus.emit(passed_event)
            logger.info(f"[PASSED FILTERS] {mint[:8]}... - Authority:{authority_risk['score']:.0f} Creator:{creator_risk['score']:.0f}")
            return "PASSED"
        
        except Exception as e:
            logger.error(f"Error filtering token: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get filter statistics"""
        total = self.passed + self.rejected
        return {
            "passed": self.passed,
            "rejected": self.rejected,
            "pass_rate": (self.passed / total * 100) if total > 0 else 0,
        }