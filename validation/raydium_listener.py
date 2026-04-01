"""Raydium WebSocket / HTTP listener for pool detection"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

import httpx

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus

logger = setup_logger("RaydiumListener")


class RaydiumListener:
    """Monitors Raydium for token pool launches."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.api_url = settings.raydium_api_url
        self.pool_timeout = settings.raydium_pool_timeout

        self.pools_found = 0
        self.pools_missed = 0
        self.running = False

        self.http_client: Optional[httpx.AsyncClient] = None

        # mint -> monitoring context
        self.monitored_tokens: Dict[str, Dict[str, Any]] = {}

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=10)
        return self.http_client

    async def _fetch_raydium_pools(self) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch all Raydium pools from the configured API.
        """
        try:
            client = await self._get_http_client()
            logger.debug(f"Fetching Raydium pools from {self.api_url}")

            response = await client.get(self.api_url)
            response.raise_for_status()
            data = response.json()

            official = data.get("official", [])
            unofficial = data.get("unOfficial", [])
            pools = official + unofficial

            logger.debug(f"Fetched {len(pools)} Raydium pools")
            return pools

        except asyncio.TimeoutError:
            logger.warning("Timeout fetching Raydium pools")
            return None
        except Exception as e:
            logger.error(f"Error fetching Raydium pools: {e}")
            return None

    @staticmethod
    def _build_pool_index(
        pools: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build an O(1) mint-address → pool-info lookup from the pools list.

        Each pool can appear under both its mintA and mintB addresses so that
        any monitored token can be found with a single dict lookup instead of
        an O(N) linear scan.
        """
        index: Dict[str, Dict[str, Any]] = {}
        for pool in pools:
            mint_a = pool.get("mintA", {}).get("address", "")
            mint_b = pool.get("mintB", {}).get("address", "")
            if mint_a:
                index[mint_a] = pool
            if mint_b:
                index[mint_b] = pool
        return index

    def _search_token_in_pools(
        self,
        mint: str,
        pools: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Search token mint in current Raydium pools.
        """
        try:
            for pool in pools:
                mint_a = pool.get("mintA", {}).get("address", "")
                mint_b = pool.get("mintB", {}).get("address", "")

                if mint_a == mint or mint_b == mint:
                    return {
                        "pool_id": pool.get("id"),
                        "amm_id": pool.get("ammId"),
                        "pool_address": pool.get("id"),
                        "mint_a": mint_a,
                        "mint_b": mint_b,
                        "base_mint": mint_a,
                        "quote_mint": mint_b if mint_a == mint else mint_a,
                        "program_id": pool.get("programId"),
                        "open_time": pool.get("openTime"),
                        "source": "raydium",
                    }

            return None

        except Exception as e:
            logger.debug(f"Error searching token in pools: {e}")
            return None

    def _lookup_token_in_index(
        self,
        mint: str,
        pool_index: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        O(1) pool lookup using a pre-built pool index.
        """
        try:
            pool = pool_index.get(mint)
            if pool is None:
                return None
            mint_a = pool.get("mintA", {}).get("address", "")
            mint_b = pool.get("mintB", {}).get("address", "")
            return {
                "pool_id": pool.get("id"),
                "amm_id": pool.get("ammId"),
                "pool_address": pool.get("id"),
                "mint_a": mint_a,
                "mint_b": mint_b,
                "base_mint": mint_a,
                "quote_mint": mint_b if mint_a == mint else mint_a,
                "program_id": pool.get("programId"),
                "open_time": pool.get("openTime"),
                "source": "raydium",
            }
        except Exception as e:
            logger.debug(f"Error looking up token in pool index: {e}")
            return None

    async def start_monitoring(
        self,
        mint: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Start monitoring token for Raydium pool.

        Context is stored so PoolFound / PoolSearchTimeout can emit richer data.
        """
        try:
            current_time = datetime.utcnow().timestamp()
            context = context or {}

            self.monitored_tokens[mint] = {
                "mint": mint,
                "watch_started_at": current_time,
                "symbol": context.get("symbol", "UNKNOWN"),
                "decision": context.get("decision"),
                "initial_score": context.get("final_score", context.get("score")),
                "initial_confidence": context.get("confidence"),
                "name": context.get("name"),
            }

            logger.debug(f"Started monitoring {mint[:8]}... for Raydium pool")

        except Exception as e:
            logger.error(f"Error starting monitoring: {e}")

    async def stop_monitoring(self, mint: str) -> None:
        """Stop monitoring token."""
        if mint in self.monitored_tokens:
            del self.monitored_tokens[mint]
            logger.debug(f"Stopped monitoring {mint[:8]}...")

    async def stop(self) -> None:
        """Stop the pool monitoring loop."""
        self.running = False
        logger.info("Stopping Raydium pool monitor")

    async def _handle_pool_found(self, mint: str, pool_data: Dict[str, Any]) -> None:
        """Update shared state when a Raydium pool is found for a monitored token."""
        self.pools_found += 1
        logger.info(f"Pool found for {mint[:8]}...: {pool_data['pool_id']}")
        await self.stop_monitoring(mint)

    async def check_token_pool(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Check if token has a Raydium pool.
        """
        try:
            pools = await self._fetch_raydium_pools()
            if not pools:
                logger.debug(f"Could not fetch pools for {mint[:8]}...")
                return None

            pool_data = self._search_token_in_pools(mint, pools)
            if pool_data:
                await self._handle_pool_found(mint, pool_data)
                return pool_data

        except Exception as e:
            logger.error(f"Error checking token pool: {e}")

        return None

    async def monitor_pools(self) -> None:
        """
        Monitor all tracked tokens for pool appearance.
        Emits PoolFound or PoolSearchTimeout.

        Pools are fetched once per cycle and indexed by mint address so that
        all monitored tokens can be checked with O(1) lookups instead of an
        O(N) linear scan per token.
        """
        if self.running:
            logger.warning("Raydium pool monitor already running")
            return

        logger.info("Starting Raydium pool monitor")
        self.running = True

        try:
            while self.running:
                try:
                    mints_to_check = list(self.monitored_tokens.keys())
                    if not mints_to_check:
                        await asyncio.sleep(5)
                        continue

                    pools = await self._fetch_raydium_pools()
                    pool_index: Dict[str, Dict[str, Any]] = (
                        self._build_pool_index(pools) if pools else {}
                    )

                    for mint in mints_to_check:
                        watch_context = self.monitored_tokens.get(mint, {})
                        start_time = watch_context.get(
                            "watch_started_at",
                            datetime.utcnow().timestamp(),
                        )
                        elapsed = datetime.utcnow().timestamp() - start_time

                        if elapsed > self.pool_timeout:
                            self.pools_missed += 1
                            logger.warning(
                                f"Pool search timeout for {mint[:8]}... (elapsed: {elapsed:.0f}s)"
                            )

                            timeout_event = Event(
                                event_type="PoolSearchTimeout",
                                data={
                                    "mint": mint,
                                    "symbol": watch_context.get("symbol", "UNKNOWN"),
                                    "decision": watch_context.get("decision"),
                                    "initial_score": watch_context.get("initial_score"),
                                    "initial_confidence": watch_context.get("initial_confidence"),
                                    "elapsed_seconds": int(elapsed),
                                    "timeout_seconds": self.pool_timeout,
                                    "watch_started_at": watch_context.get("watch_started_at"),
                                },
                                source="RaydiumListener",
                                timestamp=datetime.utcnow(),
                            )
                            await self.event_bus.emit(timeout_event)
                            await self.stop_monitoring(mint)
                            continue

                        pool_data = self._lookup_token_in_index(mint, pool_index)
                        if pool_data:
                            await self._handle_pool_found(mint, pool_data)

                            pool_event = Event(
                                event_type="PoolFound",
                                data={
                                    "mint": mint,
                                    "symbol": watch_context.get("symbol", "UNKNOWN"),
                                    "decision": watch_context.get("decision"),
                                    "initial_score": watch_context.get("initial_score"),
                                    "initial_confidence": watch_context.get("initial_confidence"),
                                    "watch_started_at": watch_context.get("watch_started_at"),
                                    "elapsed_seconds": int(elapsed),
                                    "pool_found_at": datetime.utcnow().isoformat(),
                                    "pool": pool_data,
                                },
                                source="RaydiumListener",
                                timestamp=datetime.utcnow(),
                            )
                            await self.event_bus.emit(pool_event)

                    await asyncio.sleep(5)

                except asyncio.CancelledError:
                    logger.info("Pool monitor cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error in pool monitor: {e}")
                    await asyncio.sleep(5)
        finally:
            self.running = False
            logger.info("Raydium pool monitor stopped")

    def get_stats(self) -> dict:
        """Get listener statistics."""
        return {
            "running": self.running,
            "pools_found": self.pools_found,
            "pools_missed": self.pools_missed,
            "currently_monitoring": len(self.monitored_tokens),
            "find_rate": (
                self.pools_found / (self.pools_found + self.pools_missed)
                if (self.pools_found + self.pools_missed) > 0
                else 0
            ),
        }

    async def close(self) -> None:
        """Close HTTP client."""
        await self.stop()
        self.monitored_tokens.clear()

        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None
