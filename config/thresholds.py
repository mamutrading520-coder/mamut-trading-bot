"""Configuration thresholds for Mamut"""

# Request Timeouts
TIMEOUTS = {
    "http_request": 10,
    "helius_request": 15,
    "token_enrichment": 20,
    "pool_search": 600,
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
        "steal", "dump", "pump", "trash", "bad"
    ],
    "trusted_patterns": [
        "verified", "official", "team", "legit", "safe"
    ],
    "suspicious_patterns": [
        "test", "debug", "fake", "new", "temp"
    ]
}

# Trash Filter Thresholds
TRASH_FILTER_THRESHOLDS = {
    "min_liquidity_sol": 0.5,
    "min_initial_buyers": 5,
    "max_creator_concentration": 90,
    "min_unique_holders": 10,
}

# Creator Risk Thresholds
CREATOR_RISK_THRESHOLDS = {
    "max_creator_risk": 85,
    "new_creator_penalty": 20,
    "blacklist_score": 95,
    "trusted_score": 20,
}

# Authority Risk Thresholds
AUTHORITY_RISK_THRESHOLDS = {
    "max_authority_risk": 80,
    "has_mint_authority_penalty": 20,
    "has_freeze_authority_penalty": 15,
}

# Concentration Risk Thresholds
CONCENTRATION_THRESHOLDS = {
    "max_concentration_risk": 80,
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
    "high_potential_score": 75,
    "medium_potential_score": 50,
    "low_potential_score": 30,
    "trash_score": 0,
}

# Decision Mapping Thresholds
DECISION_THRESHOLDS = {
    "signal_early_min_score": 70,
    "monitor_min_score": 50,
    "reject_max_score": 30,
}

# Raydium Pool Thresholds
RAYDIUM_THRESHOLDS = {
    "min_liquidity_sol": 5.0,
    "max_pool_search_timeout": 600,
    "confirmation_pool_age_max": 300,
}

# Raydium Validation Config
RAYDIUM_VALIDATION_CONFIG = {
    "min_liquidity_usd": 1000,
    "min_liquidity_sol": 5.0,
    "max_price_impact": 10,
    "min_pool_age_minutes": 1,
    "max_pool_age_hours": 24,
}

# Signal Generation Thresholds
SIGNAL_THRESHOLDS = {
    "min_early_score": 70,
    "min_confirmation_score": 65,
    "max_abandon_score": 40,
    "early_signal_confidence": 0.8,
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

# Token Lock Manager Config
TOKEN_LOCK_CONFIG = {
    "max_concurrent_locks": 100,
    "lock_timeout_seconds": 300,
    "check_interval_seconds": 5,
}

# Signal Deduplication Config
SIGNAL_DEDUP_CONFIG = {
    "dedup_window_seconds": 60,
    "min_score_diff_for_new_signal": 5,
    "max_stored_signals": 1000,
}