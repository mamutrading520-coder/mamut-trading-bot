"""Analyze buyer quality and distribution patterns"""
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.thresholds import HOLDER_QUALITY_THRESHOLDS
import httpx
import asyncio

logger = setup_logger("BuyerQualityAnalyzer")

class BuyerQualityAnalyzer:
    """Analyzes initial buyer quality and patterns"""
    
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
    
    async def _fetch_initial_trades(self, mint: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch initial trades for token
        
        Args:
            mint: Token mint address
            
        Returns:
            List of initial trades or None
        """
        try:
            client = await self._get_http_client()
            
            # Try multiple trade data sources
            urls = [
                f"https://api.solscan.io/token/txlist?token={mint}&limit=100&offset=0",
                f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            ]
            
            for url in urls:
                try:
                    response = await asyncio.wait_for(
                        client.get(url),
                        timeout=2.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Parse based on source
                        if "result" in data:
                            return self._parse_solscan_trades(data["result"])
                        elif "pairs" in data:
                            return self._parse_dexscreener_trades(data["pairs"])
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.debug(f"Error fetching from {url}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching initial trades for {mint}: {e}")
            return None
    
    @staticmethod
    def _parse_solscan_trades(trades: List[Dict]) -> Optional[List[Dict[str, Any]]]:
        """Parse Solscan trade response"""
        try:
            parsed_trades = []
            
            for trade in trades[:100]:  # First 100 trades
                parsed_trades.append({
                    "buyer": trade.get("from_owner"),
                    "amount": float(trade.get("token_amount", 0)),
                    "sol_amount": float(trade.get("sol_amount", 0)),
                    "timestamp": int(trade.get("block_time", 0)),
                    "is_buy": trade.get("action") == "buy",
                })
            
            return parsed_trades if parsed_trades else None
            
        except Exception as e:
            logger.debug(f"Error parsing Solscan trades: {e}")
            return None
    
    @staticmethod
    def _parse_dexscreener_trades(pairs: List[Dict]) -> Optional[List[Dict[str, Any]]]:
        """Parse DexScreener trade response"""
        try:
            if not pairs or len(pairs) == 0:
                return None
            
            pair = pairs[0]
            trades = pair.get("txns", {})
            
            parsed_trades = []
            
            for trade in trades.get("buys", [])[:50]:
                parsed_trades.append({
                    "buyer": trade.get("maker"),
                    "amount": float(trade.get("tokenAmount", 0)),
                    "sol_amount": float(trade.get("nativeAmount", 0)),
                    "timestamp": int(trade.get("blockUnixTime", 0)),
                    "is_buy": True,
                })
            
            return parsed_trades if parsed_trades else None
            
        except Exception as e:
            logger.debug(f"Error parsing DexScreener trades: {e}")
            return None
    
    def _analyze_buyer_distribution(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze buyer distribution patterns
        
        Args:
            trades: List of initial trades
            
        Returns:
            Distribution analysis
        """
        if not trades:
            return {
                "unique_buyers": 0,
                "total_trades": 0,
                "average_buy_size": 0.0,
                "max_single_buyer_ratio": 0.0,
                "total_volume": 0.0,
            }
        
        try:
            buyer_amounts = {}
            total_volume = 0.0
            
            for trade in trades:
                if trade.get("is_buy"):
                    buyer = trade.get("buyer", "unknown")
                    amount = float(trade.get("sol_amount", 0))
                    
                    buyer_amounts[buyer] = buyer_amounts.get(buyer, 0.0) + amount
                    total_volume += amount
            
            unique_buyers = len(buyer_amounts)
            total_trades = len(trades)
            average_buy_size = total_volume / unique_buyers if unique_buyers > 0 else 0.0
            
            # Find largest single buyer ratio
            max_single_amount = max(buyer_amounts.values()) if buyer_amounts else 0.0
            max_single_buyer_ratio = max_single_amount / total_volume if total_volume > 0 else 0.0
            
            return {
                "unique_buyers": unique_buyers,
                "total_trades": total_trades,
                "average_buy_size": average_buy_size,
                "max_single_buyer_ratio": max_single_buyer_ratio,
                "total_volume": total_volume,
                "buyer_distribution": sorted(
                    [(b, a) for b, a in buyer_amounts.items()],
                    key=lambda x: x[1],
                    reverse=True
                )[:10],  # Top 10 buyers
            }
            
        except Exception as e:
            logger.error(f"Error analyzing buyer distribution: {e}")
            return {}
    
    def _calculate_quality_score(self, distribution: Dict[str, Any]) -> float:
        """
        Calculate buyer quality score
        
        Args:
            distribution: Distribution analysis
            
        Returns:
            Quality score (0-100)
        """
        try:
            score = 50.0  # Base score
            
            unique_buyers = distribution.get("unique_buyers", 0)
            avg_buy_size = distribution.get("average_buy_size", 0.0)
            max_ratio = distribution.get("max_single_buyer_ratio", 0.0)
            
            # Positive: Many unique buyers
            min_buyers = HOLDER_QUALITY_THRESHOLDS.get("min_unique_buyers", 10)
            if unique_buyers >= min_buyers * 3:
                score += 25.0
            elif unique_buyers >= min_buyers * 2:
                score += 15.0
            elif unique_buyers >= min_buyers:
                score += 10.0
            else:
                score -= 15.0
            
            # Positive: Good average buy size
            min_avg = HOLDER_QUALITY_THRESHOLDS.get("min_average_buy_size", 0.01)
            if avg_buy_size >= min_avg * 5:
                score += 15.0
            elif avg_buy_size >= min_avg:
                score += 10.0
            
            # Negative: Too concentrated (whale buying)
            max_ratio_threshold = HOLDER_QUALITY_THRESHOLDS.get("max_single_buyer_ratio", 0.30)
            if max_ratio > max_ratio_threshold * 2:
                score -= 25.0
            elif max_ratio > max_ratio_threshold:
                score -= 15.0
            
            # Clamp to 0-100
            return max(0.0, min(100.0, score))
            
        except Exception as e:
            logger.error(f"Error calculating quality score: {e}")
            return 50.0
    
    async def analyze_buyer_quality(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze buyer quality for token
        
        Args:
            token_data: Token data
            
        Returns:
            Buyer quality analysis
        """
        try:
            mint = token_data.get("mint")
            logger.debug(f"Analyzing buyer quality for {mint[:8]}...")
            
            # Fetch initial trades
            trades = await self._fetch_initial_trades(mint)
            
            if not trades:
                logger.debug(f"No trade data available for {mint}")
                self.analyzed_count += 1
                return {
                    "mint": mint,
                    "status": "data_unavailable",
                    "quality_score": 50.0,  # Conservative estimate
                    "reason": "No trade data available",
                }
            
            # Analyze distribution
            distribution = self._analyze_buyer_distribution(trades)
            
            # Calculate quality score
            quality_score = self._calculate_quality_score(distribution)
            
            analysis = {
                "mint": mint,
                "quality_score": quality_score,
                "distribution": distribution,
                "quality_level": self._get_quality_level(quality_score),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            self.analyzed_count += 1
            logger.debug(f"Buyer quality for {mint[:8]}...: {quality_score:.1f}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing buyer quality: {e}")
            self.failed_count += 1
            return {
                "mint": token_data.get("mint"),
                "error": str(e),
                "quality_score": 50.0,
            }
    
    @staticmethod
    def _get_quality_level(score: float) -> str:
        """Get quality level from score"""
        if score >= 75:
            return "EXCELLENT"
        elif score >= 60:
            return "GOOD"
        elif score >= 45:
            return "FAIR"
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