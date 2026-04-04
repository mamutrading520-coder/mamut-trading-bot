"""Configuration settings for Mamut engine - loads from .env"""
from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings

from config.thresholds import (
    AUTHORITY_RISK_MAX,
    CONCENTRATION_RISK_MAX,
    CREATOR_RISK_MAX,
    HIGH_POTENTIAL_SCORE,
    LOW_POTENTIAL_SCORE,
    MEDIUM_POTENTIAL_SCORE,
    MONITOR_MAX_AGGREGATE_RISK,
    MONITOR_MIN_CONFIDENCE,
    RAYDIUM_MIN_LIQUIDITY_SOL,
    RAYDIUM_POOL_TIMEOUT_SECONDS,
    SIGNAL_DEDUP_WINDOW_SECONDS,
    SIGNAL_EARLY_MAX_AGGREGATE_RISK,
    SIGNAL_EARLY_MIN_CONFIDENCE,
    TOKEN_LOCK_TIMEOUT_SECONDS,
)


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    pump_ws_url: str = "wss://pumpportal.fun/api/data"
    pump_reconnect_delay: int = 5
    pump_max_retries: int = 10

    discovery_dedup_window: int = 180
    discovery_dedup_max_tracked: int = 5000
    discovery_dedup_initial_sol_tolerance: float = 0.002

    raydium_ws_url: str = "wss://api.raydium.io/ws"
    raydium_api_url: str = "https://api.raydium.io/v2/sdk/liquidity/mainnet.json"
    raydium_pool_timeout: int = RAYDIUM_POOL_TIMEOUT_SECONDS
    raydium_pool_min_liquidity: float = RAYDIUM_MIN_LIQUIDITY_SOL
    raydium_fetch_timeout: int = 10
    raydium_refresh_interval: int = 5
    raydium_stale_cache_ttl: int = 60
    raydium_fetch_failure_backoff_max: int = 20

    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_commitment: str = "finalized"

    database_url: str = "sqlite:///./mamut.db"
    database_pool_size: int = 10
    database_echo: bool = False

    score_threshold_high_potential: float = HIGH_POTENTIAL_SCORE
    score_threshold_medium_potential: float = MEDIUM_POTENTIAL_SCORE
    score_threshold_low_potential: float = LOW_POTENTIAL_SCORE

    signal_early_min_confidence: float = SIGNAL_EARLY_MIN_CONFIDENCE
    signal_early_max_aggregate_risk: float = SIGNAL_EARLY_MAX_AGGREGATE_RISK
    monitor_min_confidence: float = MONITOR_MIN_CONFIDENCE
    monitor_max_aggregate_risk: float = MONITOR_MAX_AGGREGATE_RISK

    authority_risk_max: float = AUTHORITY_RISK_MAX
    creator_risk_max: float = CREATOR_RISK_MAX
    concentration_max: float = CONCENTRATION_RISK_MAX

    log_level: str = "INFO"
    log_file: str = "logs/mamut.log"
    log_rotation: str = "500 MB"
    log_retention: str = "7 days"

    webhook_url: Optional[str] = None
    alert_enabled: bool = True
    alert_retry_count: int = 3

    max_concurrent_tokens: int = 1000
    token_lock_timeout: int = TOKEN_LOCK_TIMEOUT_SECONDS
    signal_dedup_window: int = SIGNAL_DEDUP_WINDOW_SECONDS

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
