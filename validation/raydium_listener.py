"""Raydium WebSocket listener for pool detection"""
import asyncio
import json
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime
from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus

logger = setup_logger("RaydiumListener")

class RaydiumListener:
    """Monitors Raydium for token pool launches"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.api_url = settings.raydium_api_url
        self.pool_timeout = settings.raydium_pool_timeout
        
        self.pools_found = 0
        self.pools_missed = 0
        self.http_client = None
        self.monitored_tokens: Dict[str, float] = {}  # mint -> timestamp
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=10)
        return self.http_client
    
    async def _fetch_raydium_pools(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch all Raydium pools from official API
        
        Args:
            None
            
        Returns:
            List of pool data or None
        """
        try:
            client = await self._get_http_client()
            
            logger.debug(f"Fetching Raydium pools from {self.api_url}")
            
            response = await client.get(self.api_url)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse response based on API structure
            official = data.get("official", [])
            unOfficial = data.get("unOfficial", [])
            
            pools = official + unOfficial
            
            logger.debug(f"Fetched {len(pools)} Raydium pools")
            return pools
            
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching Raydium pools")
            return None
        except Exception as e:
            logger.error(f"Error fetching Raydium pools: {e}")
            return None
    
    def _search_token_in_pools(
        self,
        mint: str,
        pools: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Search for token in pool list
        
        Args:
            mint: Token mint address
            pools: List of pools
            
        Returns:
            Pool data if found, None otherwise
        """
        try:
            for pool in pools:
                # Check if token is in this pool
                mint_a = pool.get("mintA", {}).get("address", "")
                mint_b = pool.get("mintB", {}).get("address", "")
                
                if mint_a == mint or mint_b == mint:
                    return {
                        "pool_id": pool.get("id"),
                        "amm_id": pool.get("ammId"),
                        "mint_a": mint_a,
                        "mint_b": mint_b,
                        "program_id": pool.get("programId"),
                        "open_time": pool.get("openTime"),
                    }
            
            return None
            
        except Exception as e:
            logger.debug(f"Error searching token in pools: {e}")
            return None
    
    async def start_monitoring(self, mint: str) -> None:
        """
        Start monitoring token for Raydium pool
        
        Args:
            mint: Token mint to monitor
        """
        try:
            current_time = datetime.utcnow().timestamp()
            self.monitored_tokens[mint] = current_time
            logger.debug(f"Started monitoring {mint[:8]}... for Raydium pool")
        except Exception as e:
            logger.error(f"Error starting monitoring: {e}")
    
    async def stop_monitoring(self, mint: str) -> None:
        """
        Stop monitoring token
        
        Args:
            mint: Token mint to stop monitoring
        """
        if mint in self.monitored_tokens:
            del self.monitored_tokens[mint]
            logger.debug(f"Stopped monitoring {mint[:8]}...")
    
    async def check_token_pool(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Check if token has Raydium pool
        
        Args:
            mint: Token mint to check
            
        Returns:
            Pool data if found, None otherwise
        """
        try:
            # Fetch current pools
            pools = await self._fetch_raydium_pools()
            
            if not pools:
                logger.debug(f"Could not fetch pools for {mint[:8]}...")
                return None
            
            # Search for token in pools
            pool_data = self._search_token_in_pools(mint, pools)
            
            if pool_data:
                self.pools_found += 1
                logger.info(f"Pool found for {mint[:8]}...: {pool_data['pool_id']}")
                await self.stop_monitoring(mint)
            
            return pool_data
            
        except Exception as e:
            logger.error(f"Error checking token pool: {e}")
            return None
    
    async def monitor_pools(self) -> None:
        """
        Monitor all tracked tokens for pool appearance
        Checks periodically and emits events when pools are found
        """
        logger.info("Starting Raydium pool monitor")
        
        while True:
            try:
                # Get current list of monitored tokens
                mints_to_check = list(self.monitored_tokens.keys())
                
                if not mints_to_check:
                    await asyncio.sleep(5)
                    continue
                
                # Check each token
                for mint in mints_to_check:
                    start_time = self.monitored_tokens.get(mint, datetime.utcnow().timestamp())
                    elapsed = datetime.utcnow().timestamp() - start_time
                    
                    # Check if timeout exceeded
                    if elapsed > self.pool_timeout:
                        self.pools_missed += 1
                        logger.warning(f"Pool search timeout for {mint[:8]}... (elapsed: {elapsed:.0f}s)")
                        
                        # Emit timeout event
                        timeout_event = Event(
                            event_type="PoolSearchTimeout",
                            data={
                                "mint": mint,
                                "elapsed_seconds": int(elapsed),
                                "timeout_seconds": self.pool_timeout,
                            },
                            source="RaydiumListener",
                            timestamp=datetime.utcnow()
                        )
                        await self.event_bus.emit(timeout_event)
                        
                        await self.stop_monitoring(mint)
                        continue
                    
                    # Check for pool
                    pool_data = await self.check_token_pool(mint)
                    
                    if pool_data:
                        # Emit pool found event
                        pool_event = Event(
                            event_type="PoolFound",
                            data={
                                "mint": mint,
                                "pool": pool_data,
                                "elapsed_seconds": int(elapsed),
                            },
                            source="RaydiumListener",
                            timestamp=datetime.utcnow()
                        )
                        await self.event_bus.emit(pool_event)
                
                # Check less frequently to avoid rate limits
                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                logger.info("Pool monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in pool monitor: {e}")
                await asyncio.sleep(5)
    
    def get_stats(self) -> dict:
        """Get listener statistics"""
        return {
            "pools_found": self.pools_found,
            "pools_missed": self.pools_missed,
            "currently_monitoring": len(self.monitored_tokens),
            "find_rate": self.pools_found / (self.pools_found + self.pools_missed)
                        if (self.pools_found + self.pools_missed) > 0 else 0,
        }
    
    async def close(self) -> None:
        """Close HTTP client"""
        if self.http_client:
            await self.http_client.aclose()