"""Token enrichment with on-chain metadata and metadata heuristics"""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

import httpx

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.settings import Settings
from config.thresholds import TIMEOUTS
from enrich.metadata_analyzer import MetadataAnalyzer
from enrich.holder_analyzer import HolderAnalyzer

logger = setup_logger("TokenEnricher")


@dataclass
class EnrichedTokenData:
    """Token data enriched with on-chain metadata and metadata analysis."""

    mint: str
    name: str
    symbol: str
    creator: str
    timestamp: int
    initial_sol: float
    initial_buy: int
    bonding_curve: str
    v_tokens_in_bonding_curve: int
    v_sol_in_bonding_curve: float
    market_cap_sol: float
    uri: str
    tx_signature: str

    # On-chain enrichment
    decimals: int = 6
    total_supply: int = 0
    mint_authority: Optional[str] = None
    freeze_authority: Optional[str] = None
    owner: Optional[str] = None
    owner_renounced: bool = False
    metadata_retrieved: bool = False
    uri_metadata: Optional[Dict[str, Any]] = None

    # Metadata analysis
    metadata_analysis: Dict[str, Any] = field(default_factory=dict)
    metadata_score: float = 0.0
    metadata_risk_flags: list[str] = field(default_factory=list)
    has_website: bool = False
    has_twitter: bool = False
    has_telegram: bool = False
    has_discord: bool = False
    social_count: int = 0

    # Holder analysis
    holder_analysis: Dict[str, Any] = field(default_factory=dict)
    holder_concentration_score: float = 0.0
    holder_distribution_score: float = 0.0
    holder_risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mint": self.mint,
            "name": self.name,
            "symbol": self.symbol,
            "creator": self.creator,
            "timestamp": self.timestamp,
            "initial_sol": self.initial_sol,
            "initial_buy": self.initial_buy,
            "bonding_curve": self.bonding_curve,
            "v_tokens_in_bonding_curve": self.v_tokens_in_bonding_curve,
            "v_sol_in_bonding_curve": self.v_sol_in_bonding_curve,
            "market_cap_sol": self.market_cap_sol,
            "uri": self.uri,
            "tx_signature": self.tx_signature,
            "decimals": self.decimals,
            "total_supply": self.total_supply,
            "mint_authority": self.mint_authority,
            "freeze_authority": self.freeze_authority,
            "owner": self.owner,
            "owner_renounced": self.owner_renounced,
            "metadata_retrieved": self.metadata_retrieved,
            "uri_metadata": self.uri_metadata,
            # Expose under the canonical key used by TrashFilterEngine and
            # SQLiteStore.update_token_enrichment so both can detect that
            # off-chain metadata has been retrieved.
            "metadata_json": self.uri_metadata,
            "metadata_analysis": self.metadata_analysis,
            "metadata_score": self.metadata_score,
            "metadata_risk_flags": self.metadata_risk_flags,
            "has_website": self.has_website,
            "has_twitter": self.has_twitter,
            "has_telegram": self.has_telegram,
            "has_discord": self.has_discord,
            "social_count": self.social_count,
            "holder_analysis": self.holder_analysis,
            "holder_concentration_score": self.holder_concentration_score,
            "holder_distribution_score": self.holder_distribution_score,
            "holder_risk_flags": self.holder_risk_flags,
        }


class TokenEnricher:
    """Enriches token with on-chain metadata from Solana RPC and URI metadata analysis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.rpc_url = settings.solana_rpc_url
        self.event_bus = get_event_bus()
        self.timeout = TIMEOUTS.get("token_enrichment", 20)

        self.enriched_count = 0
        self.failed_count = 0

        self.http_client: Optional[httpx.AsyncClient] = None
        self.metadata_analyzer = MetadataAnalyzer()
        self.holder_analyzer = HolderAnalyzer()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=self.timeout)
        return self.http_client

    async def _fetch_token_metadata(self, mint: str) -> Optional[Dict[str, Any]]:
        """Fetch token metadata from Solana RPC."""
        try:
            client = await self._get_http_client()

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenSupply",
                "params": [mint],
            }

            response = await client.post(self.rpc_url, json=payload)
            response.raise_for_status()
            result = response.json()

            if "result" in result and "value" in result["result"]:
                data = result["result"]["value"]
                return {
                    "decimals": data.get("decimals", 6),
                    "amount": int(data.get("amount", 0)),
                    "uiAmount": float(data.get("uiAmount", 0)),
                }

            logger.debug(f"No token supply data for {mint}")
            return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching token metadata for {mint}")
            return None
        except Exception as e:
            logger.debug(f"Error fetching token metadata for {mint}: {e}")
            return None

    async def _fetch_token_account(self, mint: str) -> Optional[Dict[str, Any]]:
        """Fetch token account info from Solana RPC."""
        try:
            client = await self._get_http_client()

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [mint, {"encoding": "jsonParsed"}],
            }

            response = await client.post(self.rpc_url, json=payload)
            response.raise_for_status()
            result = response.json()

            if "result" in result and result["result"] is not None:
                data = result["result"]["data"]
                if "parsed" in data and "info" in data["parsed"]:
                    info = data["parsed"]["info"]
                    return {
                        "mint_authority": info.get("mintAuthority"),
                        "freeze_authority": info.get("freezeAuthority"),
                        "owner": info.get("owner"),
                        "decimals": info.get("decimals", 6),
                    }

            return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching account info for {mint}")
            return None
        except Exception as e:
            logger.debug(f"Error fetching account info for {mint}: {e}")
            return None

    async def _fetch_uri_metadata(self, uri: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata from URI (IPFS/Arweave/HTTP)."""
        if not uri or not uri.startswith(("http", "ipfs://", "ar://")):
            return None

        try:
            client = await self._get_http_client()

            if uri.startswith("ipfs://"):
                http_url = f"https://ipfs.io/ipfs/{uri.replace('ipfs://', '')}"
            elif uri.startswith("ar://"):
                http_url = f"https://arweave.net/{uri.replace('ar://', '')}"
            else:
                http_url = uri

            response = await client.get(http_url, follow_redirects=True)
            response.raise_for_status()
            metadata = response.json()

            return {
                "name": metadata.get("name"),
                "symbol": metadata.get("symbol"),
                "description": metadata.get("description"),
                "image": metadata.get("image"),
                "website": metadata.get("website"),
                "external_url": metadata.get("external_url"),
                "twitter": metadata.get("twitter"),
                "x": metadata.get("x"),
                "telegram": metadata.get("telegram"),
                "discord": metadata.get("discord"),
                "links": metadata.get("links"),
            }

        except asyncio.TimeoutError:
            logger.debug(f"Timeout fetching URI metadata: {uri}")
            return None
        except Exception as e:
            logger.debug(f"Error fetching URI metadata from {uri}: {e}")
            return None

    def _build_metadata_input(
        self,
        token_data: Dict[str, Any],
        uri_metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build normalized metadata input for MetadataAnalyzer."""
        uri_metadata = uri_metadata or {}

        return {
            "name": uri_metadata.get("name") or token_data.get("name"),
            "symbol": uri_metadata.get("symbol") or token_data.get("symbol"),
            "description": uri_metadata.get("description"),
            "website": uri_metadata.get("website"),
            "external_url": uri_metadata.get("external_url"),
            "twitter": uri_metadata.get("twitter"),
            "x": uri_metadata.get("x"),
            "telegram": uri_metadata.get("telegram"),
            "discord": uri_metadata.get("discord"),
            "links": uri_metadata.get("links"),
        }

    async def enrich(self, token_data: Dict[str, Any]) -> Optional[EnrichedTokenData]:
        """Enrich token with on-chain metadata and metadata heuristics."""
        try:
            mint = token_data.get("mint")

            enriched = EnrichedTokenData(
                mint=mint,
                name=token_data.get("name"),
                symbol=token_data.get("symbol"),
                creator=token_data.get("creator"),
                timestamp=token_data.get("timestamp"),
                initial_sol=token_data.get("initial_sol"),
                initial_buy=token_data.get("initial_buy"),
                bonding_curve=token_data.get("bonding_curve"),
                v_tokens_in_bonding_curve=token_data.get("v_tokens_in_bonding_curve"),
                v_sol_in_bonding_curve=token_data.get("v_sol_in_bonding_curve"),
                market_cap_sol=token_data.get("market_cap_sol"),
                uri=token_data.get("uri"),
                tx_signature=token_data.get("tx_signature"),
            )

            token_metadata, account_info, uri_metadata = await asyncio.gather(
                self._fetch_token_metadata(mint),
                self._fetch_token_account(mint),
                self._fetch_uri_metadata(enriched.uri),
                return_exceptions=False,
            )

            if token_metadata:
                enriched.decimals = token_metadata.get("decimals", 6)
                enriched.total_supply = token_metadata.get("amount", 0)
                enriched.metadata_retrieved = True

            if account_info:
                enriched.mint_authority = account_info.get("mint_authority")
                enriched.freeze_authority = account_info.get("freeze_authority")
                enriched.owner = account_info.get("owner")
                enriched.owner_renounced = account_info.get("mint_authority") is None

            if uri_metadata:
                enriched.uri_metadata = uri_metadata

            metadata_input = self._build_metadata_input(token_data, uri_metadata)
            metadata_analysis = await self.metadata_analyzer.analyze(metadata_input)

            enriched.metadata_analysis = metadata_analysis
            enriched.metadata_score = float(metadata_analysis.get("metadata_score", 0.0) or 0.0)
            enriched.metadata_risk_flags = list(metadata_analysis.get("risk_flags", []) or [])
            enriched.has_website = bool(metadata_analysis.get("has_website", False))
            enriched.has_twitter = bool(metadata_analysis.get("has_twitter", False))
            enriched.has_telegram = bool(metadata_analysis.get("has_telegram", False))
            enriched.has_discord = bool(metadata_analysis.get("has_discord", False))
            enriched.social_count = int(metadata_analysis.get("social_count", 0) or 0)

            holder_analysis = await self.holder_analyzer.analyze(enriched.to_dict())
            enriched.holder_analysis = holder_analysis
            enriched.holder_concentration_score = float(
                holder_analysis.get("holder_concentration_score", 0.0) or 0.0
            )
            enriched.holder_distribution_score = float(
                holder_analysis.get("holder_distribution_score", 0.0) or 0.0
            )
            enriched.holder_risk_flags = list(holder_analysis.get("holder_risk_flags", []) or [])

            self.enriched_count += 1
            logger.debug(
                f"Enriched token: {enriched.symbol} ({mint[:8]}...) | "
                f"metadata_score={enriched.metadata_score} | "
                f"holder_distribution={enriched.holder_distribution_score}"
            )
            return enriched

        except Exception as e:
            logger.error(f"Error enriching token: {e}")
            self.failed_count += 1
            return None

    async def enrich_and_emit(self, event: Event) -> bool:
        """Enrich token from event and emit TokenEnriched event."""
        try:
            enriched = await self.enrich(event.data)
            if not enriched:
                logger.debug("Failed to enrich token from event")
                return False

            enriched_event = Event(
                event_type="TokenEnriched",
                data=enriched.to_dict(),
                source="TokenEnricher",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(enriched_event)
            logger.debug(f"Emitted TokenEnriched event for {enriched.symbol}")
            return True

        except Exception as e:
            logger.error(f"Error in enrich_and_emit: {e}")
            self.failed_count += 1
            return False

    async def close(self) -> None:
        """Close HTTP client."""
        if self.http_client:
            await self.http_client.aclose()

    def get_stats(self) -> dict:
        """Get enricher statistics."""
        total = self.enriched_count + self.failed_count
        return {
            "enriched_count": self.enriched_count,
            "failed_count": self.failed_count,
            "success_rate": self.enriched_count / total if total > 0 else 0,
        }
