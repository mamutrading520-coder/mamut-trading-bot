"""Database models for Mamut"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Token(Base):
    """Token information"""

    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    mint = Column(String(255), unique=True, nullable=False, index=True)

    # Identity / discovery
    name = Column(String(255))
    symbol = Column(String(50))
    creator = Column(String(255), index=True)
    uri = Column(Text)
    tx_signature = Column(String(255))

    # On-chain base data
    initial_sol = Column(Float, default=0.0)
    initial_buy = Column(Integer, default=0)
    bonding_curve = Column(String(255))
    v_tokens_in_bonding_curve = Column(Integer, default=0)
    v_sol_in_bonding_curve = Column(Float, default=0.0)
    market_cap_sol = Column(Float, default=0.0)

    # Enrichment / metadata
    mint_authority = Column(String(255))
    freeze_authority = Column(String(255))
    owner = Column(String(255))
    total_supply = Column(Float, default=0.0)
    holder_count = Column(Integer, default=0)
    creator_balance = Column(Float, default=0.0)
    metadata_retrieved = Column(Boolean, default=False)
    metadata_json = Column(Text)

    # Scoring / risk summary
    authority_risk = Column(Float, default=0.0)
    creator_risk = Column(Float, default=0.0)
    concentration_risk = Column(Float, default=0.0)
    flow_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String(50), default="UNKNOWN")

    # Filtering
    passed_filters = Column(Boolean, default=False)
    rejection_reason = Column(String(255))

    # Raydium / market confirmation
    raydium_pool_found = Column(Boolean, default=False)
    raydium_pool_id = Column(String(255))
    raydium_liquidity_sol = Column(Float, default=0.0)
    raydium_pool_age_minutes = Column(Integer)
    validation_score = Column(Float, default=0.0)

    # Lifecycle status: discovered, analyzed, signaled, closed
    lifecycle_status = Column(String(50), default="discovered", index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_mint_symbol", "mint", "symbol"),
        Index("idx_risk_level_created", "risk_level", "created_at"),
        Index("idx_creator_created", "creator", "created_at"),
        Index("idx_token_status_created", "lifecycle_status", "created_at"),
        Index("idx_mint_creator_risk", "mint", "creator", "risk_level"),
    )


class TokenScore(Base):
    """Token scoring results"""

    __tablename__ = "token_scores"

    id = Column(Integer, primary_key=True, index=True)
    mint = Column(String(255), nullable=False, index=True)

    # Component values aligned with current store contract
    market_cap_score = Column(Float, default=0.0)
    authority_risk = Column(Float, default=0.0)
    creator_risk = Column(Float, default=0.0)
    concentration_risk = Column(Float, default=0.0)
    flow_score = Column(Float, default=0.0)
    holder_quality = Column(Float, default=0.0)
    metadata_score = Column(Float, default=0.0)

    # Final score summary
    bonus_points = Column(Float, default=0.0)
    penalty_points = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    risk_level = Column(String(50))
    confidence = Column(Float, default=0.0)

    # Full breakdown
    score_breakdown_json = Column(Text)

    # Decision
    decision = Column(String(50))  # SIGNAL_EARLY, MONITOR, REJECT, etc

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_mint_score", "mint", "final_score"),
        Index("idx_risk_level", "risk_level"),
    )


class Signal(Base):
    """Generated trading signals"""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String(255), unique=True, nullable=False, index=True)
    mint = Column(String(255), nullable=False, index=True)
    symbol = Column(String(50))
    signal_type = Column(String(50), nullable=False, index=True)  # EARLY, CONFIRMATION, ABANDON

    score = Column(Float, nullable=False)
    confidence = Column(Float, default=0.0)
    reason = Column(Text)

    # Raydium validation
    raydium_pool_found = Column(Boolean, default=False)
    raydium_pool_id = Column(String(255))
    raydium_liquidity_sol = Column(Float, default=0.0)
    raydium_pool_age_minutes = Column(Integer)

    # Metadata (JSON string)
    metadata_json = Column(Text)

    # Alert status
    webhook_sent = Column(Boolean, default=False)
    webhook_sent_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Extended validation fields
    current_state = Column(String(50), default="created")  # created, active, closed, expired
    processing_time_ms = Column(Float)
    validation_score = Column(Float, default=0.0)

    __table_args__ = (
        Index("idx_mint_signal_type", "mint", "signal_type"),
        Index("idx_signal_type_created", "signal_type", "created_at"),
        Index("idx_signal_id_timestamp", "signal_id", "created_at"),
    )


class SignalHistory(Base):
    """Signal state transition history"""

    __tablename__ = "signal_history"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(String(255), nullable=False, index=True)
    mint = Column(String(255), nullable=False, index=True)
    old_state = Column(String(50))
    new_state = Column(String(50), nullable=False)
    reason = Column(Text)
    details_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_sh_signal_id_ts", "signal_id", "created_at"),
        Index("idx_sh_mint_ts", "mint", "created_at"),
    )


class TokenLifecycle(Base):
    """Token status transition lifecycle tracking"""

    __tablename__ = "token_lifecycle"

    id = Column(Integer, primary_key=True, index=True)
    mint = Column(String(255), nullable=False, index=True)
    old_status = Column(String(50))
    new_status = Column(String(50), nullable=False, index=True)
    event = Column(String(100))
    reason = Column(Text)
    details_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_tl_mint_ts", "mint", "created_at"),
        Index("idx_token_id_lifecycle_status", "mint", "new_status"),
    )


class PerformanceMetrics(Base):
    """Processing time and system efficiency metrics"""

    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    operation = Column(String(100), nullable=False, index=True)
    mint = Column(String(255), index=True)
    signal_id = Column(String(255), index=True)
    duration_ms = Column(Float, nullable=False)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_pm_operation_ts", "operation", "created_at"),
        Index("idx_pm_mint_op", "mint", "operation"),
    )



class CreatorProfile(Base):
    """Creator reputation and history"""

    __tablename__ = "creator_profiles"

    id = Column(Integer, primary_key=True, index=True)
    creator = Column(String(255), unique=True, nullable=False, index=True)

    # Statistics
    total_tokens = Column(Integer, default=0)
    successful_tokens = Column(Integer, default=0)
    failed_tokens = Column(Integer, default=0)
    average_score = Column(Float, default=0.0)

    # Risk
    is_trusted = Column(Boolean, default=False)
    is_blacklisted = Column(Boolean, default=False)

    # Risk level
    risk_level = Column(String(50))

    # Timing
    wallet_age_days = Column(Integer, default=0)
    first_token_date = Column(DateTime)
    last_token_date = Column(DateTime)

    # Metadata
    notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_creator_trusted", "creator", "is_trusted"),
        Index("idx_creator_blacklisted", "creator", "is_blacklisted"),
    )


class AuditLog(Base):
    """System audit log"""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    mint = Column(String(255), index=True)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_action_created", "action", "created_at"),
        Index("idx_mint_action", "mint", "action"),
    )


class SystemState(Base):
    """System state tracking"""

    __tablename__ = "system_state"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
