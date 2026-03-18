"""Check token holder concentration for distribution issues"""
from typing import Dict, Any, Tuple, Optional
from monitoring.logger import setup_logger
from config.thresholds import CONCENTRATION_RISK_WEIGHTS, HONEYPOT_THRESHOLDS
import httpx
import asyncio

logger = setup_logger("ConcentrationChecker")

class ConcentrationChecker:
    """Analyzes token holder distribution and concentration"""
    
    def __init__(self, settings=None):
        self.checked_count = 0
        self.concentrated_count = 0
        self.settings = settings
        self.http_client = None
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=5)
        return self.http_client
    
    async def _fetch_holder_data(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Fetch holder distribution from public API
        
        Args:
            mint: Token mint address
            
        Returns:
            Holder data dictionary or None
        """
        try:
            client = await self._get_http_client()
            
            # Try multiple holder data sources
            urls = [
                f"https://api.solscan.io/token/holders?token={mint}&limit=100",
                f"https://api.helius.xyz/v0/token/metadata?token={mint}",
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
                            return self._parse_solscan_holders(data["result"])
                        elif "token" in data:
                            return self._parse_helius_data(data)
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.debug(f"Error fetching from {url}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching holder data for {mint}: {e}")
            return None
    
    @staticmethod
    def _parse_solscan_holders(data: list) -> Dict[str, Any]:
        """Parse Solscan holder response"""
        try:
            if not data or len(data) < 2:
                return None
            
            total_supply = 0
            top_holders = []
            
            for i, holder in enumerate(data[:100]):
                amount = float(holder.get("tokenAmount", {}).get("uiAmount", 0))
                total_supply += amount
                if i < 100:
                    top_holders.append(amount)
            
            if not total_supply:
                return None
            
            # Calculate concentration ratios
            top_10_amount = sum(top_holders[:10])
            top_100_amount = sum(top_holders[:100])
            
            return {
                "total_supply": total_supply,
                "holder_count": len(data),
                "top_10_ratio": top_10_amount / total_supply if total_supply > 0 else 0,
                "top_100_ratio": top_100_amount / total_supply if total_supply > 0 else 0,
                "top_holder_amount": top_holders[0] if top_holders else 0,
            }
        except Exception as e:
            logger.debug(f"Error parsing Solscan data: {e}")
            return None
    
    @staticmethod
    def _parse_helius_data(data: dict) -> Optional[Dict[str, Any]]:
        """Parse Helius metadata response"""
        try:
            token_info = data.get("token", {})
            return {
                "total_supply": int(token_info.get("supply", 0)),
                "holder_count": token_info.get("holder_count", 0),
            }
        except Exception as e:
            logger.debug(f"Error parsing Helius data: {e}")
            return None
    
    def _analyze_concentration(self, holder_data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """
        Analyze holder concentration
        
        Args:
            holder_data: Holder distribution data
            
        Returns:
            Tuple of (risk_score, analysis)
        """
        analysis = {
            "total_holders": holder_data.get("holder_count", 0),
            "top_10_ratio": holder_data.get("top_10_ratio", 0),
            "top_100_ratio": holder_data.get("top_100_ratio", 0),
            "risk_factors": [],
        }
        
        risk_score = 0.0
        
        # Check holder count
        min_holders = HONEYPOT_THRESHOLDS.get("min_holder_count_safe", 100)
        if analysis["total_holders"] < min_holders:
            risk_score += CONCENTRATION_RISK_WEIGHTS.get("holder_count", 30)
            analysis["risk_factors"].append(f"Too few holders: {analysis['total_holders']} (min: {min_holders})")
        
        # Check top 10 concentration
        top_10_threshold = 0.5  # 50% threshold
        if analysis["top_10_ratio"] > top_10_threshold:
            risk_score += CONCENTRATION_RISK_WEIGHTS.get("top_10_ratio", 40)
            analysis["risk_factors"].append(f"Top 10 concentration: {analysis['top_10_ratio']:.1%}")
        
        # Check top 100 concentration
        top_100_threshold = 0.8  # 80% threshold
        if analysis["top_100_ratio"] > top_100_threshold:
            risk_score += CONCENTRATION_RISK_WEIGHTS.get("top_100_ratio", 30)
            analysis["risk_factors"].append(f"Top 100 concentration: {analysis['top_100_ratio']:.1%}")
        
        # Check max concentration limit
        max_ratio = HONEYPOT_THRESHOLDS.get("max_concentration_ratio", 0.8)
        if analysis["top_10_ratio"] > max_ratio:
            analysis["risk_factors"].append(f"CRITICAL: Exceeds max concentration {max_ratio:.1%}")
        
        # Clamp to 0-100
        risk_score = max(0.0, min(100.0, risk_score))
        
        return risk_score, analysis
    
    async def check_concentration(self, token_data: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
        """
        Check token holder concentration
        
        Args:
            token_data: Token data
            
        Returns:
            Tuple of (risk_score, analysis)
        """
        try:
            mint = token_data.get("mint")
            
            # Try to fetch holder data
            holder_data = await self._fetch_holder_data(mint)
            
            if not holder_data:
                logger.debug(f"Could not fetch holder data for {mint}, using conservative estimate")
                # Conservative estimate if data unavailable
                return 25.0, {
                    "mint": mint,
                    "status": "data_unavailable",
                    "risk_factors": ["Could not fetch holder data - conservative estimate"],
                }
            
            risk_score, analysis = self._analyze_concentration(holder_data)
            analysis["mint"] = mint
            
            self.checked_count += 1
            if risk_score >= 60:
                self.concentrated_count += 1
            
            return risk_score, analysis
            
        except Exception as e:
            logger.error(f"Error checking concentration: {e}")
            return 50.0, {"error": str(e)}
    
    async def close(self) -> None:
        """Close HTTP client"""
        if self.http_client:
            await self.http_client.aclose()
    
    def get_stats(self) -> dict:
        """Get checker statistics"""
        return {
            "checked_count": self.checked_count,
            "concentrated_count": self.concentrated_count,
            "concentration_rate": self.concentrated_count / self.checked_count 
                                if self.checked_count > 0 else 0,
        }