"""Analyze token trading flow and momentum"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.thresholds import FLOW_ANALYSIS_THRESHOLDS
from utils.time_utils import get_timestamp, minutes_since
import httpx
import asyncio

logger = setup_logger("FlowAnalyzer")

class FlowAnalyzer:
    """Analyzes token trading flow and initial momentum"""
    
    def __init__(self):
        self.event_bus = get_event_bus()
        self.analyzed_count = 0
        self.failed_count = 0
        self.http_client = None
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=5)
        return self.http_client
    
    async def _fetch_trading_data(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Fetch trading volume and momentum data
        
        Args:
            mint: Token mint address
            
        Returns:
            Trading data or None
        """
        try:
            client = await self._get_http_client()
            
            # Try multiple data sources
            urls = [
                f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
                f"https://api.solscan.io/token/meta?token={mint}",
            ]
            
            for url in urls:
                try:
                    response = await asyncio.wait_for(
                        client.get(url),
                        timeout=2.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if "pairs" in data:
                            return self._parse_dexscreener_trading(data["pairs"])
                        elif "result" in data:
                            return self._parse_solscan_trading(data["result"])
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.debug(f"Error fetching from {url}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching trading data for {mint}: {e}")
            return None
    
    @staticmethod
    def _parse_dexscreener_trading(pairs: List[Dict]) -> Optional[Dict[str, Any]]:
        """Parse DexScreener trading data"""
        try:
            if not pairs:
                return None
            
            pair = pairs[0]
            
            return {
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "volume_1h": float(pair.get("volume", {}).get("h1", 0)),
                "volume_5m": float(pair.get("volume", {}).get("m5", 0)),
                "trades_24h": int(pair.get("txns", {}).get("h24", {}).get("buys", 0)),
                "trades_1h": int(pair.get("txns", {}).get("h1", {}).get("buys", 0)),
                "trades_5m": int(pair.get("txns", {}).get("m5", {}).get("buys", 0)),
                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0)),
                "liquidity": float(pair.get("liquidity", {}).get("usd", 0)),
                "market_cap": float(pair.get("marketCap", 0)),
            }
            
        except Exception as e:
            logger.debug(f"Error parsing DexScreener trading: {e}")
            return None
    
    @staticmethod
    def _parse_solscan_trading(data: Dict) -> Optional[Dict[str, Any]]:
        """Parse Solscan trading data"""
        try:
            return {
                "volume_24h": float(data.get("volume24hSOL", 0)),
                "trades_24h": int(data.get("trades24h", 0)),
                "price_change_24h": float(data.get("priceChange24h", 0)),
            }
        except Exception as e:
            logger.debug(f"Error parsing Solscan trading: {e}")
            return None
    
    def _calculate_velocity(self, trading_data: Dict[str, Any]) -> float:
        """
        Calculate trading velocity (volume acceleration)
        
        Args:
            trading_data: Trading data
            
        Returns:
            Velocity score (0-100)
        """
        try:
            volume_1h = trading_data.get("volume_1h", 0)
            volume_5m = trading_data.get("volume_5m", 0)
            
            if volume_1h == 0:
                return 50.0
            
            # Calculate volume acceleration (5m is typically smaller)
            velocity_ratio = volume_5m / (volume_1h / 12) if volume_1h > 0 else 0
            
            # Score based on acceleration
            if velocity_ratio > 2.0:  # Accelerating fast
                return 85.0
            elif velocity_ratio > 1.5:
                return 75.0
            elif velocity_ratio > 1.0:
                return 65.0
            elif velocity_ratio > 0.5:
                return 55.0
            else:
                return 45.0
            
        except Exception as e:
            logger.debug(f"Error calculating velocity: {e}")
            return 50.0
    
    def _calculate_momentum(self, trading_data: Dict[str, Any]) -> float:
        """
        Calculate trading momentum (price + volume)
        
        Args:
            trading_data: Trading data
            
        Returns:
            Momentum score (0-100)
        """
        try:
            score = 50.0  # Base score
            
            # Positive: Price increase
            price_change = trading_data.get("price_change_1h", 0)
            if price_change > 50:
                score += 25.0
            elif price_change > 20:
                score += 15.0
            elif price_change > 5:
                score += 10.0
            elif price_change < -20:
                score -= 20.0
            
            # Positive: High volume
            volume_1h = trading_data.get("volume_1h", 0)
            if volume_1h > 100:
                score += 15.0
            elif volume_1h > 10:
                score += 10.0
            
            # Positive: Many trades
            trades_1h = trading_data.get("trades_1h", 0)
            if trades_1h > 100:
                score += 10.0
            elif trades_1h > 50:
                score += 5.0
            
            # Clamp to 0-100
            return max(0.0, min(100.0, score))
            
        except Exception as e:
            logger.error(f"Error calculating momentum: {e}")
            return 50.0
    
    def _analyze_flow_patterns(self, token_data: Dict[str, Any], trading_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze token flow patterns
        
        Args:
            token_data: Token data
            trading_data: Trading data
            
        Returns:
            Flow analysis
        """
        analysis = {
            "initial_sol": token_data.get("initial_sol", 0),
            "initial_buy": token_data.get("initial_buy", 0),
            "bonding_curve_liquidity": token_data.get("v_sol_in_bonding_curve", 0),
            "flow_patterns": [],
        }
        
        if not trading_data:
            return analysis
        
        # Add trading data
        analysis.update({
            "volume_1h": trading_data.get("volume_1h", 0),
            "trades_1h": trading_data.get("trades_1h", 0),
            "price_change_1h": trading_data.get("price_change_1h", 0),
        })
        
        # Detect flow patterns
        min_initial_sol = FLOW_ANALYSIS_THRESHOLDS.get("min_volume_threshold", 0.5)
        min_initial_buyers = FLOW_ANALYSIS_THRESHOLDS.get("min_initial_buyers", 5)
        
        if analysis["initial_sol"] >= min_initial_sol:
            analysis["flow_patterns"].append("GOOD_INITIAL_LIQUIDITY")
        
        if analysis["initial_buy"] >= min_initial_buyers:
            analysis["flow_patterns"].append("MULTIPLE_INITIAL_BUYERS")
        
        if analysis["volume_1h"] > 10:
            analysis["flow_patterns"].append("SUSTAINED_VOLUME")
        
        if analysis["price_change_1h"] > 10:
            analysis["flow_patterns"].append("POSITIVE_MOMENTUM")
        
        if analysis["trades_1h"] > 50:
            analysis["flow_patterns"].append("ACTIVE_TRADING")
        
        return analysis
    
    async def analyze_flow(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze token trading flow
        
        Args:
            token_data: Token data
            
        Returns:
            Flow analysis
        """
        try:
            mint = token_data.get("mint")
            logger.debug(f"Analyzing flow for {mint[:8]}...")
            
            # Fetch trading data
            trading_data = await self._fetch_trading_data(mint)
            
            # Calculate metrics
            velocity_score = self._calculate_velocity(trading_data or {})
            momentum_score = self._calculate_momentum(trading_data or {})
            
            # Average of velocity and momentum
            flow_score = (velocity_score + momentum_score) / 2
            
            # Analyze patterns
            patterns = self._analyze_flow_patterns(token_data, trading_data)
            
            analysis = {
                "mint": mint,
                "flow_score": flow_score,
                "velocity_score": velocity_score,
                "momentum_score": momentum_score,
                "flow_quality": self._get_flow_quality(flow_score),
                "patterns": patterns,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            self.analyzed_count += 1
            logger.debug(f"Flow analysis for {mint[:8]}...: {flow_score:.1f}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing flow: {e}")
            self.failed_count += 1
            return {
                "mint": token_data.get("mint"),
                "error": str(e),
                "flow_score": 50.0,
            }
    
    @staticmethod
    def _get_flow_quality(score: float) -> str:
        """Get flow quality level from score"""
        if score >= 75:
            return "STRONG"
        elif score >= 60:
            return "MODERATE"
        elif score >= 45:
            return "WEAK"
        else:
            return "POOR"
    
    async def close(self) -> None:
        """Close HTTP client"""
        if self.http_client:
            await self.http_client.aclose()
    
    def get_stats(self) -> dict:
        """Get analyzer statistics"""
        return {
            "analyzed_count": self.analyzed_count,
            "failed_count": self.failed_count,
            "success_rate": self.analyzed_count / (self.analyzed_count + self.failed_count)
                           if (self.analyzed_count + self.failed_count) > 0 else 0,
        }