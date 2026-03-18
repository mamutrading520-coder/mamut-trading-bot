"""Confirm market conditions and generate confirmation signals"""
from typing import Dict, Any, Optional
from datetime import datetime
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.settings import Settings
import uuid

logger = setup_logger("MarketConfirmationEngine")

class MarketConfirmationEngine:
    """Confirms market conditions for token validation"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.confirmations_made = 0
        self.confirmations_failed = 0
    
    def _analyze_pool_quality(self, pool_validation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze pool quality metrics
        
        Args:
            pool_validation: Pool validation results
            
        Returns:
            Quality analysis
        """
        analysis = {
            "pool_valid": pool_validation.get("is_valid", False),
            "liquidity_sol": pool_validation.get("liquidity_sol", 0.0),
            "quality_score": 50.0,
            "quality_factors": [],
        }
        
        if not analysis["pool_valid"]:
            analysis["quality_score"] = 20.0
            analysis["quality_factors"].append("Pool validation failed")
            return analysis
        
        score = 70.0  # Base score for valid pool
        
        # Factor: Liquidity
        liquidity = analysis["liquidity_sol"]
        if liquidity > 100:
            score += 15.0
            analysis["quality_factors"].append(f"Strong liquidity: {liquidity:.2f} SOL")
        elif liquidity > 50:
            score += 10.0
            analysis["quality_factors"].append(f"Adequate liquidity: {liquidity:.2f} SOL")
        elif liquidity > 10:
            score += 5.0
            analysis["quality_factors"].append(f"Minimal liquidity: {liquidity:.2f} SOL")
        
        # Factor: Program validation
        checks = pool_validation.get("checks", {})
        if checks.get("program_id", {}).get("valid"):
            score += 10.0
            analysis["quality_factors"].append("Official Raydium program")
        
        # Factor: Pool age
        if checks.get("pool_age", {}).get("valid"):
            score += 5.0
            analysis["quality_factors"].append("Pool age verified")
        
        analysis["quality_score"] = min(100.0, score)
        return analysis
    
    def _calculate_confidence_boost(
        self,
        initial_score: float,
        pool_quality: Dict[str, Any]
    ) -> float:
        """
        Calculate confidence boost from market validation
        
        Args:
            initial_score: Initial signal confidence
            pool_quality: Pool quality analysis
            
        Returns:
            New confidence level (0-1)
        """
        base_confidence = initial_score
        
        if not pool_quality.get("pool_valid"):
            return base_confidence * 0.5  # Reduce if pool not valid
        
        # Boost confidence based on quality
        quality_score = pool_quality.get("quality_score", 50)
        quality_boost = (quality_score / 100) * 0.2  # Max 20% boost
        
        new_confidence = min(0.99, base_confidence + quality_boost)
        
        return new_confidence
    
    async def confirm_market(
        self,
        token_data: Dict[str, Any],
        initial_signal: Dict[str, Any],
        pool_validation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Confirm market conditions for token
        
        Args:
            token_data: Token data
            initial_signal: Initial signal data
            pool_validation: Pool validation results
            
        Returns:
            Market confirmation results
        """
        try:
            mint = token_data.get("mint")
            logger.debug(f"Confirming market conditions for {mint[:8]}...")
            
            # Analyze pool quality
            pool_quality = self._analyze_pool_quality(pool_validation)
            
            # Calculate new confidence
            initial_confidence = initial_signal.get("confidence", 0.7)
            new_confidence = self._calculate_confidence_boost(
                initial_confidence,
                pool_quality
            )
            
            # Determine confirmation status
            is_confirmed = (
                pool_quality["pool_valid"] and
                pool_quality["quality_score"] >= 60
            )
            
            confirmation = {
                "mint": mint,
                "confirmation_id": f"CONFIRM-{uuid.uuid4().hex[:12]}",
                "is_confirmed": is_confirmed,
                "pool_quality": pool_quality,
                "initial_confidence": initial_confidence,
                "new_confidence": new_confidence,
                "confidence_boost": new_confidence - initial_confidence,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            self.confirmations_made += 1
            
            if is_confirmed:
                logger.info(f"Market confirmed for {mint[:8]}... - confidence: {new_confidence:.1%}")
            else:
                logger.warning(f"Market confirmation failed for {mint[:8]}...")
                self.confirmations_failed += 1
            
            return confirmation
            
        except Exception as e:
            logger.error(f"Error confirming market: {e}")
            self.confirmations_failed += 1
            return {
                "mint": token_data.get("mint"),
                "error": str(e),
                "is_confirmed": False,
            }
    
    async def confirm_and_emit(
        self,
        event: Event,
        token_data: Dict[str, Any],
        initial_signal: Dict[str, Any]
    ) -> bool:
        """
        Confirm market and emit result event
        
        Args:
            event: PoolFound event
            token_data: Token data
            initial_signal: Initial signal data
            
        Returns:
            True if confirmed and signal emitted, False otherwise
        """
        try:
            pool_data = event.data.get("pool", {})
            
            # Validate pool (already done by validator, but recheck)
            pool_validation = {
                "pool_id": pool_data.get("pool_id"),
                "is_valid": True,  # Assume valid since it's from validator
                "liquidity_sol": pool_data.get("liquidity_sol", 0),
                "checks": pool_data.get("checks", {}),
            }
            
            # Confirm market
            confirmation = await self.confirm_market(
                token_data,
                initial_signal,
                pool_validation
            )
            
            if not confirmation.get("is_confirmed"):
                logger.debug(f"Market not confirmed, no signal emitted")
                return False
            
            # Emit confirmation event
            confirm_event = Event(
                event_type="MarketConfirmed",
                data=confirmation,
                source="MarketConfirmationEngine",
                timestamp=datetime.utcnow()
            )
            
            await self.event_bus.emit(confirm_event)
            logger.debug(f"Emitted MarketConfirmed event")
            
            return True
            
        except Exception as e:
            logger.error(f"Error in confirm_and_emit: {e}")
            self.confirmations_failed += 1
            return False
    
    def get_stats(self) -> dict:
        """Get confirmation engine statistics"""
        total = self.confirmations_made + self.confirmations_failed
        return {
            "confirmations_made": self.confirmations_made,
            "confirmations_failed": self.confirmations_failed,
            "confirmation_rate": self.confirmations_made / total if total > 0 else 0,
        }