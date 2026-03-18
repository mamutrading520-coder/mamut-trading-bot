"""Track token migration to Raydium"""
from typing import Dict, Any, Optional
from datetime import datetime
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus

logger = setup_logger("MigrationTracker")

class MigrationTracker:
    """Tracks token migration from Pump.fun to Raydium"""
    
    def __init__(self):
        self.event_bus = get_event_bus()
        self.tracked_count = 0
        self.migrated_count = 0
    
    async def track_migration(
        self,
        token_data: Dict[str, Any],
        raydium_validation: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Track token migration status
        
        Args:
            token_data: Token data
            raydium_validation: Raydium pool validation results (if available)
            
        Returns:
            Migration tracking data
        """
        try:
            mint = token_data.get("mint")
            
            tracking = {
                "mint": mint,
                "migration_status": "PUMP_FUN_ONLY",
                "pool_found": False,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            if raydium_validation:
                tracking["raydium_data"] = raydium_validation
                
                if raydium_validation.get("pool_found"):
                    tracking["migration_status"] = "MIGRATED_TO_RAYDIUM"
                    tracking["pool_found"] = True
                    self.migrated_count += 1
                    logger.debug(f"Token migrated to Raydium: {mint[:8]}...")
            
            self.tracked_count += 1
            return tracking
            
        except Exception as e:
            logger.error(f"Error tracking migration: {e}")
            return {
                "mint": token_data.get("mint"),
                "error": str(e),
            }
    
    def get_stats(self) -> dict:
        """Get migration tracker statistics"""
        return {
            "tracked_count": self.tracked_count,
            "migrated_count": self.migrated_count,
            "migration_rate": self.migrated_count / self.tracked_count 
                            if self.tracked_count > 0 else 0,
        }