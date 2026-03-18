"""Analyze token velocity and rate of change"""
from typing import Dict, Any, Optional
from datetime import datetime
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus

logger = setup_logger("VelocityAnalyzer")

class VelocityAnalyzer:
    """Analyzes token velocity metrics"""
    
    def __init__(self):
        self.event_bus = get_event_bus()
        self.analyzed_count = 0
    
    def _calculate_price_velocity(self, flow_analysis: Dict[str, Any]) -> float:
        """Calculate price velocity (rate of price change)"""
        try:
            price_change = flow_analysis.get("price_change_1h", 0)
            
            if price_change > 50:
                return 90.0
            elif price_change > 30:
                return 80.0
            elif price_change > 10:
                return 70.0
            elif price_change > 0:
                return 60.0
            else:
                return 40.0
            
        except Exception as e:
            logger.debug(f"Error calculating price velocity: {e}")
            return 50.0
    
    def _calculate_volume_velocity(self, flow_analysis: Dict[str, Any]) -> float:
        """Calculate volume velocity (rate of volume change)"""
        try:
            volume_1h = flow_analysis.get("volume_1h", 0)
            volume_5m = flow_analysis.get("volume_5m", 0)
            
            if volume_1h == 0:
                return 50.0
            
            # Calculate acceleration
            acceleration = volume_5m / (volume_1h / 12)
            
            if acceleration > 2.0:
                return 85.0
            elif acceleration > 1.5:
                return 75.0
            elif acceleration > 1.0:
                return 65.0
            elif acceleration > 0.5:
                return 55.0
            else:
                return 45.0
            
        except Exception as e:
            logger.debug(f"Error calculating volume velocity: {e}")
            return 50.0
    
    def _calculate_buyer_velocity(self, buyer_analysis: Dict[str, Any]) -> float:
        """Calculate buyer velocity (rate of buyer acquisition)"""
        try:
            unique_buyers = buyer_analysis.get("unique_buyers", 0)
            total_trades = buyer_analysis.get("total_trades", 0)
            
            if total_trades == 0:
                return 50.0
            
            # Average trades per buyer
            trades_per_buyer = total_trades / unique_buyers if unique_buyers > 0 else 0
            
            if unique_buyers > 50:
                return 80.0
            elif unique_buyers > 30:
                return 70.0
            elif unique_buyers > 10:
                return 60.0
            elif unique_buyers > 5:
                return 50.0
            else:
                return 40.0
            
        except Exception as e:
            logger.debug(f"Error calculating buyer velocity: {e}")
            return 50.0
    
    async def analyze_velocity(
        self,
        token_data: Dict[str, Any],
        flow_analysis: Dict[str, Any],
        buyer_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze token velocity across dimensions
        
        Args:
            token_data: Token data
            flow_analysis: Flow analysis results
            buyer_analysis: Buyer quality analysis results
            
        Returns:
            Velocity analysis
        """
        try:
            mint = token_data.get("mint")
            
            price_velocity = self._calculate_price_velocity(flow_analysis)
            volume_velocity = self._calculate_volume_velocity(flow_analysis)
            buyer_velocity = self._calculate_buyer_velocity(buyer_analysis)
            
            # Overall velocity score
            overall_velocity = (price_velocity + volume_velocity + buyer_velocity) / 3
            
            analysis = {
                "mint": mint,
                "overall_velocity": overall_velocity,
                "price_velocity": price_velocity,
                "volume_velocity": volume_velocity,
                "buyer_velocity": buyer_velocity,
                "velocity_level": self._get_velocity_level(overall_velocity),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            self.analyzed_count += 1
            logger.debug(f"Velocity for {mint[:8]}...: {overall_velocity:.1f}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing velocity: {e}")
            return {
                "mint": token_data.get("mint"),
                "error": str(e),
                "overall_velocity": 50.0,
            }
    
    @staticmethod
    def _get_velocity_level(score: float) -> str:
        """Get velocity level from score"""
        if score >= 80:
            return "EXTREME"
        elif score >= 65:
            return "HIGH"
        elif score >= 50:
            return "MODERATE"
        else:
            return "LOW"
    
    def get_stats(self) -> dict:
        """Get analyzer statistics"""
        return {
            "analyzed_count": self.analyzed_count,
        }