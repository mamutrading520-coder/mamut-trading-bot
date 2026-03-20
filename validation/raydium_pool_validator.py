"""Validate Raydium pools for legitimacy and minimum tradability quality"""

from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional, Tuple

import httpx

from monitoring.logger import setup_logger
from config.thresholds import RAYDIUM_VALIDATION_CONFIG
from utils.time_utils import get_timestamp

logger = setup_logger("RaydiumPoolValidator")


class RaydiumPoolValidator:
    """Validates Raydium pool legitimacy and minimum quality."""

    def __init__(self, settings=None):
        self.settings = settings
        self.validated_count = 0
        self.failed_count = 0
        self.http_client: Optional[httpx.AsyncClient] = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=5)
        return self.http_client

    def _validate_program_id(self, program_id: str) -> Tuple[bool, str]:
        """
        Validate that the pool uses an accepted Raydium program ID.
        """
        official_programs = RAYDIUM_VALIDATION_CONFIG.get("official_program_ids", []) or []

        accepted_programs = set(official_programs)
        accepted_programs.update(
            {
                "675kPX9MHTjS2zt1qLCcV32qxPMoVvmT9nDpFoUGmJ7",  # Raydium AMM
                "9W959DqBbTRAu7fkCuJicPSC8kSrWznqXX8XcXLEKSJ",  # AcceleRaytor / legacy related
            }
        )

        if not program_id:
            return False, "Missing program_id"

        if program_id in accepted_programs:
            return True, "Accepted Raydium program_id"

        return False, f"Unrecognized program_id: {program_id}"

    def _validate_open_time(self, open_time: Optional[int]) -> Tuple[bool, str, float]:
        """
        Validate pool age.
        Returns: (is_valid, message, age_minutes)
        """
        if not open_time:
            return False, "No open time provided", 0.0

        try:
            current_time = get_timestamp()
            pool_age_seconds = current_time - int(open_time)
            pool_age_minutes = max(pool_age_seconds / 60, 0.0)

            min_age = float(RAYDIUM_VALIDATION_CONFIG.get("min_pool_age_minutes", 0))
            max_age = RAYDIUM_VALIDATION_CONFIG.get("max_pool_age_minutes")

            if pool_age_minutes < min_age:
                return False, f"Pool too new ({pool_age_minutes:.2f} min)", pool_age_minutes

            if max_age is not None and pool_age_minutes > float(max_age):
                return False, f"Pool too old ({pool_age_minutes:.2f} min)", pool_age_minutes

            return True, f"Pool age acceptable ({pool_age_minutes:.2f} min)", pool_age_minutes

        except Exception as e:
            logger.debug(f"Error validating open time: {e}")
            return False, f"Error validating time: {e}", 0.0

    def _validate_quote_asset(self, pool_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate that the quote asset is one of the allowed assets.
        """
        quote_mint = pool_data.get("quote_mint") or ""
        allowed_quote_mints = set(RAYDIUM_VALIDATION_CONFIG.get("allowed_quote_mints", []) or [])

        if not allowed_quote_mints:
            return True, "No quote asset restriction configured"

        if not quote_mint:
            return False, "Missing quote_mint"

        if quote_mint in allowed_quote_mints:
            return True, "Allowed quote asset"

        return False, f"Disallowed quote asset: {quote_mint}"

    async def _fetch_pool_liquidity(self, pool_id: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Fetch pool liquidity from public sources.
        Returns approximate liquidity in SOL plus source name.
        """
        if not pool_id:
            return None, None

        try:
            client = await self._get_http_client()

            urls = [
                ("dexscreener", f"https://api.dexscreener.com/latest/dex/pairs/solana/{pool_id}"),
                ("raydium", "https://api.raydium.io/v2/main/info"),
            ]

            for source_name, url in urls:
                try:
                    response = await asyncio.wait_for(client.get(url), timeout=2.0)
                    if response.status_code != 200:
                        continue

                    data = response.json()

                    if source_name == "dexscreener":
                        pairs = data.get("pairs") or []
                        if pairs:
                            liquidity_usd = (pairs[0].get("liquidity") or {}).get("usd", 0)
                            if liquidity_usd:
                                # Conversión aproximada a SOL solo para scoring mínimo interno.
                                return float(liquidity_usd) / 150.0, source_name

                    if source_name == "raydium":
                        # El endpoint puede variar; aquí mantenemos búsqueda tolerante.
                        if isinstance(data, dict):
                            for bucket in ("official", "unOfficial"):
                                for item in data.get(bucket, []) or []:
                                    if item.get("id") == pool_id:
                                        tvl = item.get("tvl") or item.get("liquidity") or 0
                                        if tvl:
                                            return float(tvl) / 150.0, source_name

                except asyncio.TimeoutError:
                    logger.debug(f"Timeout fetching liquidity from {source_name}")
                    continue
                except Exception as e:
                    logger.debug(f"Error fetching liquidity from {source_name}: {e}")
                    continue

            return None, None

        except Exception as e:
            logger.debug(f"Error fetching pool liquidity: {e}")
            return None, None

    def _score_validation(
        self,
        program_valid: bool,
        age_valid: bool,
        quote_valid: bool,
        liquidity_valid: bool,
        liquidity_known: bool,
    ) -> float:
        """
        Simple weighted validation score from 0 to 100.
        """
        score = 0.0

        if program_valid:
            score += 35.0
        if age_valid:
            score += 25.0
        if quote_valid:
            score += 20.0
        if liquidity_known and liquidity_valid:
            score += 20.0
        elif not liquidity_known:
            score += 5.0

        return round(score, 2)

    async def validate_pool(self, pool_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate Raydium pool.

        Returns a structured validation result usable by the orchestrator.
        """
        try:
            pool_id = pool_data.get("pool_id")
            program_id = pool_data.get("program_id")
            open_time = pool_data.get("open_time")

            validation: Dict[str, Any] = {
                "pool_id": pool_id,
                "pool_address": pool_data.get("pool_address") or pool_id,
                "is_valid": False,
                "validation_score": 0.0,
                "checks": {},
                "warnings": [],
                "reasons": [],
                "liquidity_sol": 0.0,
                "liquidity_source": None,
            }

            # 1) Program ID
            program_valid, program_msg = self._validate_program_id(program_id or "")
            validation["checks"]["program_id"] = {
                "valid": program_valid,
                "program_id": program_id,
                "message": program_msg,
            }
            if program_valid:
                validation["reasons"].append(program_msg)
            else:
                validation["warnings"].append(program_msg)

            # 2) Pool age
            age_valid, age_msg, pool_age_minutes = self._validate_open_time(open_time)
            validation["checks"]["pool_age"] = {
                "valid": age_valid,
                "message": age_msg,
                "pool_age_minutes": pool_age_minutes,
            }
            if age_valid:
                validation["reasons"].append(age_msg)
            else:
                validation["warnings"].append(age_msg)

            # 3) Quote asset
            quote_valid, quote_msg = self._validate_quote_asset(pool_data)
            validation["checks"]["quote_asset"] = {
                "valid": quote_valid,
                "quote_mint": pool_data.get("quote_mint"),
                "message": quote_msg,
            }
            if quote_valid:
                validation["reasons"].append(quote_msg)
            else:
                validation["warnings"].append(quote_msg)

            # 4) Liquidity
            liquidity_sol, liquidity_source = await self._fetch_pool_liquidity(pool_id)
            min_liquidity = float(RAYDIUM_VALIDATION_CONFIG.get("min_liquidity_sol", 10.0))

            liquidity_known = liquidity_sol is not None
            liquidity_valid = False

            if liquidity_known:
                validation["liquidity_sol"] = float(liquidity_sol or 0.0)
                validation["liquidity_source"] = liquidity_source
                liquidity_valid = validation["liquidity_sol"] >= min_liquidity

                validation["checks"]["liquidity"] = {
                    "valid": liquidity_valid,
                    "liquidity_sol": validation["liquidity_sol"],
                    "min_required": min_liquidity,
                    "source": liquidity_source,
                }

                if liquidity_valid:
                    validation["reasons"].append(
                        f"Liquidity acceptable ({validation['liquidity_sol']:.2f} SOL)"
                    )
                else:
                    validation["warnings"].append(
                        f"Low liquidity ({validation['liquidity_sol']:.2f} SOL)"
                    )
            else:
                validation["checks"]["liquidity"] = {
                    "valid": False,
                    "message": "Could not fetch liquidity data",
                    "min_required": min_liquidity,
                }
                validation["warnings"].append("Could not verify liquidity")

            validation["validation_score"] = self._score_validation(
                program_valid=program_valid,
                age_valid=age_valid,
                quote_valid=quote_valid,
                liquidity_valid=liquidity_valid,
                liquidity_known=liquidity_known,
            )

            # Regla final:
            # - programa y edad deben pasar
            # - quote asset debe pasar si está configurado
            # - liquidez debe pasar si fue obtenida
            # - si la liquidez no pudo obtenerse, no invalida automáticamente,
            #   pero baja el score y deja warning explícito
            is_valid = program_valid and age_valid and quote_valid and (
                liquidity_valid or not liquidity_known
            )

            validation["is_valid"] = is_valid

            self.validated_count += 1
            if is_valid:
                logger.info(
                    f"Pool validated: {pool_id} | score={validation['validation_score']}"
                )
            else:
                logger.warning(
                    f"Pool validation failed: {pool_id} | score={validation['validation_score']}"
                )
                self.failed_count += 1

            return validation

        except Exception as e:
            logger.error(f"Error validating pool: {e}")
            self.failed_count += 1
            return {
                "pool_id": pool_data.get("pool_id"),
                "pool_address": pool_data.get("pool_address"),
                "is_valid": False,
                "validation_score": 0.0,
                "checks": {},
                "warnings": [],
                "reasons": [],
                "liquidity_sol": 0.0,
                "error": str(e),
            }

    def get_stats(self) -> dict:
        """Get validator statistics."""
        total = self.validated_count + self.failed_count
        return {
            "validated_count": self.validated_count,
            "failed_count": self.failed_count,
            "validation_rate": self.validated_count / total if total > 0 else 0,
        }

    async def close(self) -> None:
        """Close HTTP client."""
        if self.http_client:
            await self.http_client.aclose()
