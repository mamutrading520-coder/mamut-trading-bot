"""Database models for Mamut"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, Index, ForeignKey
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Token(Base):
    """Token information"""
    __tablename__ = "tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    mint = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    symbol = Column(String(50))
    creator = Column(String(255), index=True)
    initial_sol = Column(Float, default=0.0)
    initial_buy = Column(Integer, default=0)
    bonding_curve = Column(String(255))
    v_tokens_in_bonding_curve = Column(Integer, default=0)
    v_sol_in_bonding_curve = Column(Float, default=0.0)
    market_cap_sol = Column(Float, default=0.0)
    uri = Column(Text)
    tx_signature = Column(String(255))
    
    # Scoring fields
    authority_risk = Column(Float, default=0.0)
    creator_risk = Column(Float, default=0.0)
    concentration_risk = Column(Float, default=0.0)
    flow_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    risk_level = Column(String(50), default="UNKNOWN")  # HIGH_POTENTIAL, MEDIUM_POTENTIAL, LOW_POTENTIAL, TRASH
    
    # Filtering
    passed_filters = Column(Boolean, default=False)
    rejection_reason = Column(String(255))
    
    # Raydium
    raydium_pool_found = Column(Boolean, default=False)
    raydium_pool_id = Column(String(255))
    raydium_liquidity_sol = Column(Float, default=0.0)
    raydium_pool_age_minutes = Column(Integer)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_mint_symbol', 'mint', 'symbol'),
        Index('idx_risk_level_created', 'risk_level', 'created_at'),
        Index('idx_creator_created', 'creator', 'created_at'),
    )


class TokenScore(Base):
    """Token scoring results"""
    __tablename__ = "token_scores"
    
    id = Column(Integer, primary_key=True, index=True)
    mint = Column(String(255), nullable=False, index=True)
    
    # Component scores
    authority_risk = Column(Float, default=0.0)
    creator_risk = Column(Float, default=0.0)
    concentration_risk = Column(Float, default=0.0)
    flow_score = Column(Float, default=0.0)
    holder_quality = Column(Float, default=0.0)
    
    # Final score
    final_score = Column(Float, default=0.0)
    risk_level = Column(String(50))
    confidence = Column(Float, default=0.0)
    
    # Decision
    decision = Column(String(50))  # SIGNAL_EARLY, MONITOR, REJECT, etc
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_mint_score', 'mint', 'final_score'),
        Index('idx_risk_level', 'risk_level'),
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
    
    __table_args__ = (
        Index('idx_mint_signal_type', 'mint', 'signal_type'),
        Index('idx_signal_type_created', 'signal_type', 'created_at'),
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
    
    # Timing
    wallet_age_days = Column(Integer, default=0)
    first_token_date = Column(DateTime)
    
    # Metadata
    notes = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_creator_trusted', 'creator', 'is_trusted'),
        Index('idx_creator_blacklisted', 'creator', 'is_blacklisted'),
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
        Index('idx_action_created', 'action', 'created_at'),
        Index('idx_mint_action', 'mint', 'action'),
    )


class SystemState(Base):
    """System state tracking"""
    __tablename__ = "system_state"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)