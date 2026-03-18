"""Configuration settings for Mamut engine - loads from .env"""
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Application settings with environment variable support"""

    # Pump.fun Configuration
    pump_ws_url: str = "wss://pumpportal.fun/api/data"
    pump_reconnect_delay: int = 5
    pump_max_retries: int = 10

    # Raydium Configuration
    raydium_ws_url: str = "wss://api.raydium.io/ws"
    raydium_api_url: str = "https://api.raydium.io/v2/sdk/liquidity/mainnet.json"
    raydium_pool_timeout: int = 30
    raydium_pool_min_liquidity: float = 10.0

    # Solana RPC Configuration
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_commitment: str = "finalized"

    # Database Configuration
    database_url: str = "sqlite:///./mamut.db"
    database_pool_size: int = 10
    database_echo: bool = False

    # Scoring Thresholds (Lowered for testing - adjust based on actual score distribution)
    score_threshold_high_potential: float = 50.0  # Changed from 70.0
    score_threshold_medium_potential: float = 40.0  # Changed from 50.0
    score_threshold_low_potential: float = 20.0  # Changed from 30.0

    # Risk Thresholds
    authority_risk_max: float = 80.0
    creator_risk_max: float = 80.0
    concentration_max: float = 80.0

    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = "logs/mamut.log"
    log_rotation: str = "500 MB"
    log_retention: str = "7 days"

    # Alert Configuration
    webhook_url: Optional[str] = None
    alert_enabled: bool = True
    alert_retry_count: int = 3

    # System Configuration
    max_concurrent_tokens: int = 1000
    token_lock_timeout: int = 3600
    signal_dedup_window: int = 60

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False