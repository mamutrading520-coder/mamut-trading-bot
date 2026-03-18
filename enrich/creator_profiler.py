"""Creator wallet analysis and profiling"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from storage.sqlite_store import SQLiteStore
from config.settings import Settings
from config.thresholds import CREATOR_RISK_PATTERNS
from utils.time_utils import get_timestamp, days_since

logger = setup_logger("CreatorProfiler")

class CreatorProfiler:
    """Analyzes creator wallet history and patterns"""
    
    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()
        self.analyzed_count = 0
        self.failed_count = 0
    
    def _calculate_wallet_age_days(self, first_token_date: Optional[datetime]) -> int:
        """Calculate wallet age in days"""
        if not first_token_date:
            return 0
        try:
            timestamp = int(first_token_date.timestamp())
            return int(days_since(timestamp))
        except Exception as e:
            logger.debug(f"Error calculating wallet age: {e}")
            return 0
    
    def _get_creator_risk_score(self, creator: str) -> tuple[float, Dict[str, Any]]:
        """
        Calculate creator risk score based on history
        
        Args:
            creator: Creator wallet address
            
        Returns:
            Tuple of (risk_score, analysis_details)
        """
        try:
            # Get creator profile from database
            profile = self.store.get_creator_profile(creator)
            
            analysis = {
                "creator": creator,
                "total_tokens": 0,
                "failed_tokens": 0,
                "successful_tokens": 0,
                "average_score": 0.0,
                "wallet_age_days": 0,
                "failure_rate": 0.0,
                "risk_factors": [],
                "is_trusted": False,
                "is_blacklisted": False,
            }
            
            if not profile:
                # New creator, lower risk initially
                analysis["wallet_age_days"] = 0
                return 30.0, analysis
            
            analysis["total_tokens"] = profile.total_tokens_created or 0
            analysis["failed_tokens"] = profile.failed_tokens or 0
            analysis["successful_tokens"] = profile.successful_tokens or 0
            analysis["average_score"] = profile.average_score or 0.0
            analysis["wallet_age_days"] = profile.wallet_age_days or 0
            analysis["is_trusted"] = profile.is_trusted or False
            analysis["is_blacklisted"] = profile.is_blacklisted or False
            
            risk_score = 0.0
            
            # Risk factor: Blacklisted creator
            if analysis["is_blacklisted"]:
                risk_score += 100.0
                analysis["risk_factors"].append("Creator is blacklisted")
                return risk_score, analysis
            
            # Risk factor: High failure rate
            if analysis["total_tokens"] > 0:
                failure_rate = analysis["failed_tokens"] / analysis["total_tokens"]
                analysis["failure_rate"] = failure_rate
                
                if failure_rate > 0.5:  # More than 50% failures
                    risk_score += 40.0
                    analysis["risk_factors"].append(f"High failure rate: {failure_rate:.1%}")
                elif failure_rate > 0.3:  # More than 30% failures
                    risk_score += 25.0
                    analysis["risk_factors"].append(f"Moderate failure rate: {failure_rate:.1%}")
            
            # Risk factor: Young wallet
            min_age_days = CREATOR_RISK_PATTERNS.get("wallet_age_min_days", 7)
            if analysis["wallet_age_days"] < min_age_days:
                risk_score += 30.0
                analysis["risk_factors"].append(f"Wallet too young: {analysis['wallet_age_days']} days")
            
            # Risk factor: Too many tokens launched
            if analysis["total_tokens"] > 10:
                risk_score += 15.0
                analysis["risk_factors"].append(f"High token count: {analysis['total_tokens']}")
            
            # Positive factor: Trusted creator
            if analysis["is_trusted"]:
                risk_score = max(0, risk_score - 20.0)
                analysis["risk_factors"].append("Trusted creator (reputation bonus)")
            
            # Clamp score to 0-100
            risk_score = max(0.0, min(100.0, risk_score))
            
            return risk_score, analysis
            
        except Exception as e:
            logger.error(f"Error calculating creator risk: {e}")
            self.failed_count += 1
            return 50.0, {"creator": creator, "error": str(e)}
    
    async def profile_creator(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Profile creator for a token
        
        Args:
            token_data: Enriched token data
            
        Returns:
            Creator profile analysis
        """
        try:
            creator = token_data.get("creator")
            mint = token_data.get("mint")
            
            risk_score, analysis = self._get_creator_risk_score(creator)
            
            # Store or update creator profile
            profile_updates = {
                "total_tokens_created": analysis["total_tokens"] + 1,
                "wallet_age_days": analysis["wallet_age_days"],
                "risk_level": self._get_risk_level(risk_score),
                "last_token_date": datetime.utcnow(),
            }
            
            self.store.update_creator_profile(creator, profile_updates)
            
            self.analyzed_count += 1
            logger.debug(f"Profiled creator {creator[:8]}... risk={risk_score:.1f}")
            
            return {
                "creator": creator,
                "mint": mint,
                "risk_score": risk_score,
                "risk_level": self._get_risk_level(risk_score),
                "analysis": analysis,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error profiling creator: {e}")
            self.failed_count += 1
            return {
                "creator": token_data.get("creator"),
                "error": str(e),
            }
    
    def _get_risk_level(self, risk_score: float) -> str:
        """Get risk level from score"""
        if risk_score >= 80:
            return "CRITICAL"
        elif risk_score >= 60:
            return "HIGH"
        elif risk_score >= 40:
            return "MEDIUM"
        else:
            return "LOW"
    
    async def profile_and_emit(self, event: Event) -> bool:
        """
        Profile creator and emit event
        
        Args:
            event: TokenEnriched event
            
        Returns:
            True if profiled successfully, False otherwise
        """
        try:
            # Profile the creator
            profile = await self.profile_creator(event.data)
            
            if "error" in profile:
                logger.debug(f"Failed to profile creator")
                return False
            
            # Create and emit profile event
            profile_event = Event(
                event_type="CreatorProfiled",
                data=profile,
                source="CreatorProfiler",
                timestamp=datetime.utcnow()
            )
            
            await self.event_bus.emit(profile_event)
            logger.debug(f"Emitted CreatorProfiled event for {profile['creator'][:8]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error in profile_and_emit: {e}")
            self.failed_count += 1
            return False
    
    def get_stats(self) -> dict:
        """Get profiler statistics"""
        return {
            "analyzed_count": self.analyzed_count,
            "failed_count": self.failed_count,
            "success_rate": self.analyzed_count / (self.analyzed_count + self.failed_count)
                           if (self.analyzed_count + self.failed_count) > 0 else 0,
        }