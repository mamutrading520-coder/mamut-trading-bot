"""Configuration thresholds for Mamut.

This module is the single source of truth for runtime thresholds and tunable
pipeline constants. Values can be overridden through environment variables so
that modules importing this file directly remain aligned with ``Settings``.
"""

from __future__ import annotations

import os
from typing import List


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return default


def _env_csv(name: str, default: List[str]) -> List[str]:
    value = os.getenv(name)
    if value is None:
        return default

    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or default


# Canonical shared defaults
HIGH_POTENTIAL_SCORE = _env_float("SCORE_THRESHOLD_HIGH_POTENTIAL", 70.0)
MEDIUM_POTENTIAL_SCORE = _env_float("SCORE_THRESHOLD_MEDIUM_POTENTIAL", 50.0)
LOW_POTENTIAL_SCORE = _env_float("SCORE_THRESHOLD_LOW_POTENTIAL", 30.0)

AUTHORITY_RISK_MAX = _env_float("AUTHORITY_RISK_MAX", 80.0)
CREATOR_RISK_MAX = _env_float("CREATOR_RISK_MAX", 85.0)
CONCENTRATION_RISK_MAX = _env_float("CONCENTRATION_MAX", 80.0)
MAX_TOTAL_RISK = _env_float("MAX_TOTAL_RISK", 75.0)
MAX_METADATA_RISK = _env_float("MAX_METADATA_RISK", 90.0)
MAX_WALLET_CLUSTER_RISK = _env_float("MAX_WALLET_CLUSTER_RISK", 80.0)

RAYDIUM_POOL_TIMEOUT_SECONDS = _env_int("RAYDIUM_POOL_TIMEOUT", 30)
RAYDIUM_MIN_LIQUIDITY_SOL = _env_float("RAYDIUM_POOL_MIN_LIQUIDITY", 10.0)
TOKEN_LOCK_TIMEOUT_SECONDS = _env_int("TOKEN_LOCK_TIMEOUT", 300)
SIGNAL_DEDUP_WINDOW_SECONDS = _env_int("SIGNAL_DEDUP_WINDOW", 60)

RAYDIUM_ALLOWED_QUOTE_MINTS = _env_csv(
    "RAYDIUM_ALLOWED_QUOTE_MINTS",
    ["So11111111111111111111111111111111111111112"],
)
RAYDIUM_OFFICIAL_PROGRAM_IDS = _env_csv(
    "RAYDIUM_OFFICIAL_PROGRAM_IDS",
    [
        "675kPX9MHTjS2zt1qLCcV32qxPMoVvmT9nDpFoUGmJ7",
        "9W959DqBbTRAu7fkCuJicPSC8kSrWznqXX8XcXLEKSJ",
    ],
)

# Request Timeouts
TIMEOUTS = {
    "http_request": _env_int("HTTP_REQUEST_TIMEOUT", 10),
    "helius_request": _env_int("HELIUS_REQUEST_TIMEOUT", 15),
    "token_enrichment": _env_int("TOKEN_ENRICHMENT_TIMEOUT", 20),
    "pool_search": RAYDIUM_POOL_TIMEOUT_SECONDS,
}

# Authority Risk Weights
AUTHORITY_RISK_WEIGHTS = {
    "mint_authority_exists": 25,
    "freeze_authority_exists": 20,
    "update_authority_exists": 15,
}

# Concentration Risk Weights
CONCENTRATION_RISK_WEIGHTS = {
    "creator_concentration": 40,
    "holder_concentration": 30,
    "top_10_holders": 20,
    "liquidity_pool_concentration": 10,
}

# Honeypot Thresholds
HONEYPOT_THRESHOLDS = {
    "max_transfer_fee_percent": 5,
    "max_sell_fee_percent": 10,
    "max_buy_fee_percent": 10,
}

# Creator Risk Patterns
CREATOR_RISK_PATTERNS = {
    "blacklist_patterns": [
        "rug", "scam", "honeypot", "fake", "exploit",
        "steal", "dump", "pump", "trash", "bad",
    ],
    "trusted_patterns": [
        "verified", "official", "team", "legit", "safe",
    ],
    "suspicious_patterns": [
        "test", "debug", "fake", "new", "temp",
    ],
}

# Trash Filter Thresholds
TRASH_FILTER_THRESHOLDS = {
    "min_liquidity_sol": 0.5,
    "min_initial_buyers": 5,
    "max_creator_concentration": 90,
    "min_unique_holders": 10,
    "max_total_risk": MAX_TOTAL_RISK,
    "max_metadata_risk": MAX_METADATA_RISK,
}

# Creator Risk Thresholds
CREATOR_RISK_THRESHOLDS = {
    "max_creator_risk": CREATOR_RISK_MAX,
    "new_creator_penalty": 20,
    "blacklist_score": 95,
    "trusted_score": 20,
}

# Authority Risk Thresholds
AUTHORITY_RISK_THRESHOLDS = {
    "max_authority_risk": AUTHORITY_RISK_MAX,
    "has_mint_authority_penalty": 20,
    "has_freeze_authority_penalty": 15,
}

# Concentration Risk Thresholds
CONCENTRATION_THRESHOLDS = {
    "max_concentration_risk": CONCENTRATION_RISK_MAX,
    "creator_holds_90_percent": 95,
    "creator_holds_70_percent": 80,
    "creator_holds_50_percent": 65,
}

# Flow Analysis Thresholds
FLOW_ANALYSIS_THRESHOLDS = {
    "min_volume_threshold": 0.5,
    "min_initial_buyers": 5,
    "good_bonding_curve_ratio_min": 0.000001,
    "good_bonding_curve_ratio_max": 0.01,
    "min_liquidity_for_good_flow": 2.0,
}

# Holder Quality Thresholds
HOLDER_QUALITY_THRESHOLDS = {
    "min_unique_buyers": 10,
    "min_holders_for_excellent": 100,
    "min_holders_for_good": 50,
}

# Scoring Thresholds
SCORING_THRESHOLDS = {
    "high_potential_score": HIGH_POTENTIAL_SCORE,
    "medium_potential_score": MEDIUM_POTENTIAL_SCORE,
    "low_potential_score": LOW_POTENTIAL_SCORE,
    "trash_score": 0,
}

# Decision Mapping Thresholds
DECISION_THRESHOLDS = {
    "signal_early_min_score": HIGH_POTENTIAL_SCORE,
    "monitor_min_score": MEDIUM_POTENTIAL_SCORE,
    "reject_max_score": LOW_POTENTIAL_SCORE,
}

# Raydium Pool Thresholds
RAYDIUM_THRESHOLDS = {
    "min_liquidity_sol": RAYDIUM_MIN_LIQUIDITY_SOL,
    "max_pool_search_timeout": RAYDIUM_POOL_TIMEOUT_SECONDS,
    "confirmation_pool_age_max": 300,
}

# Raydium Validation Config
RAYDIUM_VALIDATION_CONFIG = {
    "official_program_ids": RAYDIUM_OFFICIAL_PROGRAM_IDS,
    "min_liquidity_sol": RAYDIUM_MIN_LIQUIDITY_SOL,
    "min_pool_age_minutes": 0,
    "max_pool_age_minutes": 30,
    "allowed_quote_mints": RAYDIUM_ALLOWED_QUOTE_MINTS,
}

# Signal Generation Thresholds
SIGNAL_THRESHOLDS = {
    "min_early_score": HIGH_POTENTIAL_SCORE,
    "min_confirmation_score": _env_float("MIN_CONFIRMATION_SCORE", 65.0),
    "max_abandon_score": 40,
    "early_signal_confidence": _env_float("EARLY_SIGNAL_CONFIDENCE", 0.8),
}

# Market Confirmation Thresholds
MARKET_CONFIRMATION_THRESHOLDS = {
    "min_holder_increase_percent": 50,
    "min_volume_increase_percent": 200,
    "confirmation_check_interval": 60,
    "max_confirmation_attempts": 10,
}

# Bonding Curve Analysis
BONDING_CURVE_THRESHOLDS = {
    "min_tokens_in_bonding": 1000000,
    "max_tokens_in_bonding": 1000000000000,
    "min_sol_in_bonding": 0.1,
    "max_sol_in_bonding": 1000,
}

# Token Metadata Thresholds
TOKEN_METADATA_THRESHOLDS = {
    "min_symbol_length": 1,
    "max_symbol_length": 20,
    "min_name_length": 1,
    "max_name_length": 100,
}

# Wallet Age Thresholds (in days)
WALLET_AGE_THRESHOLDS = {
    "very_new": 1,
    "new": 7,
    "medium": 30,
    "old": 90,
}

# Risk Score Multipliers
RISK_SCORE_MULTIPLIERS = {
    "very_new_wallet": 1.5,
    "no_history": 1.3,
    "single_success": 1.2,
    "multiple_failures": 1.4,
}

# Wallet Cluster Risk Thresholds
WALLET_CLUSTER_THRESHOLDS = {
    "max_wallet_cluster_risk": MAX_WALLET_CLUSTER_RISK,
}

# Token Lock Manager Config
TOKEN_LOCK_CONFIG = {
    "max_concurrent_locks": 100,
    "lock_timeout_seconds": TOKEN_LOCK_TIMEOUT_SECONDS,
    "check_interval_seconds": 5,
}

# Signal Deduplication Config
SIGNAL_DEDUP_CONFIG = {
    "dedup_window_seconds": SIGNAL_DEDUP_WINDOW_SECONDS,
    "min_score_diff_for_new_signal": 5,
    "max_stored_signals": 1000,
}
