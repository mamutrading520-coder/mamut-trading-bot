"""Creator wallet analysis and profiling"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from storage.sqlite_store import SQLiteStore
from config.settings import Settings
from utils.time_utils import get_timestamp, days_since
from filters.creator_risk_checker import CreatorRiskChecker

logger = setup_logger("CreatorProfiler")

class CreatorProfiler:
    """Analyzes creator wallet history and patterns"""
    
    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()
        self.risk_checker = CreatorRiskChecker()
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
            
            analysis["total_tokens"] = profile.total_tokens or 0
            analysis["failed_tokens"] = profile.failed_tokens or 0
            analysis["successful_tokens"] = profile.successful_tokens or 0
            analysis["average_score"] = profile.average_score or 0.0
            analysis["wallet_age_days"] = self._calculate_wallet_age_days(profile.first_token_date)
            analysis["is_trusted"] = profile.is_trusted or False
            analysis["is_blacklisted"] = profile.is_blacklisted or False
            
            if analysis["total_tokens"] > 0:
                analysis["failure_rate"] = analysis["failed_tokens"] / analysis["total_tokens"]
            
            # Delegate to CreatorRiskChecker for consistent scoring
            risk_score, checker_result = self.risk_checker.check_creator_risk(analysis)
            analysis["risk_factors"] = checker_result.get("risk_factors", [])
            
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
            
            normalized_creator = (creator or "").strip()
            creator_resolved = normalized_creator not in {"", "UNKNOWN", "unknown"}

            risk_score, analysis = self._get_creator_risk_score(creator)
            
            # Store or update creator profile only when creator is genuinely known
            if creator_resolved:
                profile_updates = {
                    "total_tokens": analysis["total_tokens"] + 1,
                    "wallet_age_days": analysis["wallet_age_days"],
                    "risk_level": self._get_risk_level(risk_score),
                    "last_token_date": datetime.utcnow(),
                }
                # Record first_token_date when creating a new profile
                if analysis["total_tokens"] == 0:
                    profile_updates["first_token_date"] = datetime.utcnow()
                self.store.upsert_creator_profile(creator, profile_updates)
            
            self.analyzed_count += 1
            logger.debug(f"Profiled creator {normalized_creator[:8] if creator_resolved else '?'}... risk={risk_score:.1f}")
            
            return {
                "creator": creator,
                "mint": mint,
                "risk_score": risk_score,
                "risk_level": self._get_risk_level(risk_score),
                "analysis": analysis,
                "creator_resolved": creator_resolved,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Error profiling creator: {e}")
            self.failed_count += 1
            return {
                "creator": token_data.get("creator"),
                "error": str(e),
                "creator_resolved": False,
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
            
            # Merge enriched token data with creator profile so downstream
            # consumers (e.g. TrashFilterEngine) receive all required fields.
            # Creator profile keys override only their own keys; all enriched
            # fields (mint_authority, freeze_authority, metadata_score, …) are
            # preserved as-is.
            merged_data = {**event.data, **profile}

            # Create and emit profile event
            profile_event = Event(
                event_type="CreatorProfiled",
                data=merged_data,
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