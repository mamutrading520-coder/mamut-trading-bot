"""Validate Raydium pools for legitimacy and quality"""
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from monitoring.logger import setup_logger
from config.thresholds import RAYDIUM_VALIDATION_CONFIG
from utils.time_utils import get_timestamp, minutes_since
import httpx
import asyncio

logger = setup_logger("RaydiumPoolValidator")

class RaydiumPoolValidator:
    """Validates Raydium pool legitimacy and quality"""
    
    def __init__(self):
        self.validated_count = 0
        self.failed_count = 0
        self.http_client = None
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=5)
        return self.http_client
    
    def _validate_program_id(self, program_id: str) -> bool:
        """
        Validate that pool uses official Raydium program
        
        Args:
            program_id: Program ID from pool
            
        Returns:
            True if official program
        """
        official_programs = RAYDIUM_VALIDATION_CONFIG.get("official_program_ids", [])
        
        if program_id in official_programs:
            return True
        
        # Also accept common Raydium program IDs
        raydium_programs = [
            "675kPX9MHTjS2zt1qLCcV32qxPMoVvmT9nDpFoUGmJ7",  # Main AMM
            "9W959DqBbTRAu7fkCuJicPSC8kSrWznqXX8XcXLEKSJ",  # AcceleRaytor
        ]
        
        return program_id in raydium_programs
    
    async def _fetch_pool_liquidity(self, pool_id: str) -> Optional[float]:
        """
        Fetch pool liquidity from blockchain
        
        Args:
            pool_id: Pool ID
            
        Returns:
            Liquidity in SOL or None
        """
        try:
            client = await self._get_http_client()
            
            # Try to fetch pool info from public APIs
            urls = [
                f"https://api.dexscreener.com/latest/dex/raydium/{pool_id}",
                f"https://api.raydium.io/v2/main/info",
            ]
            
            for url in urls:
                try:
                    response = await asyncio.wait_for(
                        client.get(url),
                        timeout=2.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # Parse liquidity based on source
                        if "pairs" in data and len(data["pairs"]) > 0:
                            liquidity_usd = data["pairs"][0].get("liquidity", {}).get("usd", 0)
                            # Convert to approximate SOL (rough estimate)
                            return float(liquidity_usd) / 150  # Approximate SOL price
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.debug(f"Error fetching from {url}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching pool liquidity: {e}")
            return None
    
    def _validate_open_time(self, open_time: Optional[int]) -> Tuple[bool, str]:
        """
        Validate pool open time (age)
        
        Args:
            open_time: Pool open time (Unix timestamp)
            
        Returns:
            Tuple of (is_valid, reason)
        """
        if not open_time:
            return False, "No open time provided"
        
        try:
            current_time = get_timestamp()
            pool_age_seconds = current_time - open_time
            pool_age_minutes = pool_age_seconds / 60
            
            min_age = RAYDIUM_VALIDATION_CONFIG.get("min_pool_age_minutes", 5)
            
            if pool_age_minutes < min_age:
                return False, f"Pool too new ({pool_age_minutes:.1f} minutes)"
            
            return True, f"Pool age: {pool_age_minutes:.1f} minutes"
            
        except Exception as e:
            logger.debug(f"Error validating open time: {e}")
            return False, f"Error validating time: {e}"
    
    async def validate_pool(self, pool_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate Raydium pool
        
        Args:
            pool_data: Pool data from listener
            
        Returns:
            Validation results
        """
        try:
            pool_id = pool_data.get("pool_id")
            mint_a = pool_data.get("mint_a")
            mint_b = pool_data.get("mint_b")
            program_id = pool_data.get("program_id")
            open_time = pool_data.get("open_time")
            
            validation = {
                "pool_id": pool_id,
                "is_valid": False,
                "checks": {},
                "warnings": [],
                "liquidity_sol": 0.0,
            }
            
            # Check 1: Program ID validation
            program_valid = self._validate_program_id(program_id or "")
            validation["checks"]["program_id"] = {
                "valid": program_valid,
                "program_id": program_id,
            }
            
            if not program_valid:
                validation["warnings"].append("Non-official program ID")
            
            # Check 2: Pool age validation
            age_valid, age_msg = self._validate_open_time(open_time)
            validation["checks"]["pool_age"] = {
                "valid": age_valid,
                "message": age_msg,
            }
            
            if not age_valid:
                validation["warnings"].append(age_msg)
            
            # Check 3: Liquidity validation
            liquidity = await self._fetch_pool_liquidity(pool_id)
            min_liquidity = RAYDIUM_VALIDATION_CONFIG.get("min_liquidity_sol", 10.0)
            
            if liquidity:
                validation["liquidity_sol"] = liquidity
                liquidity_valid = liquidity >= min_liquidity
                validation["checks"]["liquidity"] = {
                    "valid": liquidity_valid,
                    "liquidity_sol": liquidity,
                    "min_required": min_liquidity,
                }
                
                if not liquidity_valid:
                    validation["warnings"].append(f"Low liquidity: {liquidity:.2f} SOL")
            else:
                validation["checks"]["liquidity"] = {
                    "valid": False,
                    "message": "Could not fetch liquidity data",
                }
                validation["warnings"].append("Could not verify liquidity")
            
            # Overall validation: program + age must be valid
            is_valid = program_valid and age_valid
            validation["is_valid"] = is_valid
            
            self.validated_count += 1
            
            if is_valid:
                logger.info(f"Pool validated: {pool_id} with {validation['liquidity_sol']:.2f} SOL")
            else:
                logger.warning(f"Pool validation failed: {pool_id}")
                self.failed_count += 1
            
            return validation
            
        except Exception as e:
            logger.error(f"Error validating pool: {e}")
            self.failed_count += 1
            return {
                "pool_id": pool_data.get("pool_id"),
                "is_valid": False,
                "error": str(e),
            }
    
    def get_stats(self) -> dict:
        """Get validator statistics"""
        total = self.validated_count + self.failed_count
        return {
            "validated_count": self.validated_count,
            "failed_count": self.failed_count,
            "validation_rate": self.validated_count / total if total > 0 else 0,
        }
    
    async def close(self) -> None:
        """Close HTTP client"""
        if self.http_client:
            await self.http_client.aclose()