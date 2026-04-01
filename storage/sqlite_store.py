"""SQLite database operations for Mamut"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import and_, create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from monitoring.logger import setup_logger
from storage.models import (
    AuditLog,
    Base,
    CreatorProfile,
    PerformanceMetrics,
    Signal,
    SignalHistory,
    SystemState,
    Token,
    TokenLifecycle,
    TokenScore,
)
from config.settings import Settings

logger = setup_logger("SQLiteStore")


class SQLiteStore:
    """SQLite database store for Mamut."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            connect_args={"check_same_thread": False},
        )
        self._init_db()
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

    def _init_db(self) -> None:
        """Initialize database."""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info(f"Database initialized: {self.settings.database_url}")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def _get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()

    def _json(self, value: Any) -> Optional[str]:
        """Safely serialize JSON payloads for DB columns."""
        if value is None:
            return None
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"Could not serialize JSON payload: {e}")
            return None

    def _filter_model_payload(self, model: Type[Base], payload: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only columns that belong to the SQLAlchemy model."""
        if not payload:
            return {}
        model_fields = set(model.__table__.columns.keys())
        return {key: value for key, value in payload.items() if key in model_fields}

    def _extract_component_score(
        self,
        payload: Dict[str, Any],
        direct_key: str,
        component_key: str,
    ) -> Optional[float]:
        """Extract component score either from flat payload or nested component_results."""
        if payload.get(direct_key) is not None:
            return payload.get(direct_key)

        component_results = payload.get("component_results", {}) or {}
        component_data = component_results.get(component_key, {}) or {}
        return component_data.get("score")

    # -------------------------------------------------------------------------
    # TOKEN OPERATIONS
    # -------------------------------------------------------------------------
    def create_token(self, token_data: Dict[str, Any]) -> Token:
        """Create token record."""
        session = self._get_session()
        try:
            payload = self._filter_model_payload(Token, token_data)
            token = Token(**payload)
            session.add(token)
            session.commit()
            session.refresh(token)
            return token
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating token: {e}")
            raise
        finally:
            session.close()

    def get_token(self, mint: str) -> Optional[Token]:
        """Get token by mint."""
        session = self._get_session()
        try:
            return session.query(Token).filter(Token.mint == mint).first()
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            return None
        finally:
            session.close()

    def token_exists(self, mint: str) -> bool:
        """Check if token exists."""
        session = self._get_session()
        try:
            return session.query(Token).filter(Token.mint == mint).first() is not None
        except Exception as e:
            logger.error(f"Error checking token existence: {e}")
            return False
        finally:
            session.close()

    def update_token(self, mint: str, updates: Dict[str, Any]) -> Optional[Token]:
        """Update token."""
        session = self._get_session()
        try:
            token = session.query(Token).filter(Token.mint == mint).first()
            if not token:
                return None

            payload = self._filter_model_payload(Token, updates)
            ignored_fields = sorted(set(updates.keys()) - set(payload.keys()))
            if ignored_fields:
                logger.warning(
                    f"Ignored unknown Token fields for {mint[:8]}...: {', '.join(ignored_fields)}"
                )

            for key, value in payload.items():
                setattr(token, key, value)

            token.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(token)
            return token
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating token: {e}")
            raise
        finally:
            session.close()

    def upsert_token_base(self, token_data: Dict[str, Any]) -> Token:
        """
        Create token if missing, otherwise update the discovery/base identity fields.
        """
        mint = token_data["mint"]
        session = self._get_session()

        try:
            token = session.query(Token).filter(Token.mint == mint).first()

            payload = self._filter_model_payload(
                Token,
                {
                    "mint": mint,
                    "name": token_data.get("name"),
                    "symbol": token_data.get("symbol"),
                    "creator": token_data.get("creator"),
                    "uri": token_data.get("uri"),
                    "tx_signature": token_data.get("tx_signature") or token_data.get("signature"),
                    "initial_sol": token_data.get("initial_sol"),
                    "initial_buy": token_data.get("initial_buy"),
                    "bonding_curve": token_data.get("bonding_curve"),
                    "v_tokens_in_bonding_curve": token_data.get("v_tokens_in_bonding_curve"),
                    "v_sol_in_bonding_curve": token_data.get("v_sol_in_bonding_curve"),
                    "market_cap_sol": token_data.get("market_cap_sol"),
                },
            )

            if not token:
                token = Token(**payload)
                session.add(token)
            else:
                for key, value in payload.items():
                    if key == "mint":
                        continue
                    if value is not None:
                        setattr(token, key, value)
                token.updated_at = datetime.utcnow()

            session.commit()
            session.refresh(token)
            return token

        except Exception as e:
            session.rollback()
            logger.error(f"Error upserting base token {mint}: {e}")
            raise
        finally:
            session.close()

    def update_token_enrichment(self, mint: str, enriched_data: Dict[str, Any]) -> Optional[Token]:
        """
        Persist enrichment-stage fields on Token.
        """
        updates = {
            "name": enriched_data.get("name"),
            "symbol": enriched_data.get("symbol"),
            "creator": enriched_data.get("creator"),
            "uri": enriched_data.get("uri"),
            "tx_signature": enriched_data.get("tx_signature") or enriched_data.get("signature"),
            "initial_sol": enriched_data.get("initial_sol"),
            "initial_buy": enriched_data.get("initial_buy"),
            "bonding_curve": enriched_data.get("bonding_curve"),
            "v_tokens_in_bonding_curve": enriched_data.get("v_tokens_in_bonding_curve"),
            "v_sol_in_bonding_curve": enriched_data.get("v_sol_in_bonding_curve"),
            "mint_authority": enriched_data.get("mint_authority"),
            "freeze_authority": enriched_data.get("freeze_authority"),
            "owner": enriched_data.get("owner"),
            "total_supply": enriched_data.get("total_supply"),
            "holder_count": enriched_data.get("holder_count"),
            "creator_balance": enriched_data.get("creator_balance"),
            "market_cap_sol": enriched_data.get("market_cap_sol"),
            "metadata_retrieved": bool(enriched_data.get("metadata_retrieved", False)),
            "metadata_json": self._json(
                enriched_data.get("metadata_json")
                or enriched_data.get("uri_metadata")
                or enriched_data.get("metadata")
            ),
        }
        updates = {k: v for k, v in updates.items() if v is not None}
        return self.update_token(mint, updates)

    def update_token_filter_result(self, mint: str, filter_data: Dict[str, Any]) -> Optional[Token]:
        """
        Persist filter-stage summary on Token.
        """
        passed_filters = filter_data.get("passed_filters")
        if passed_filters is None:
            passed_filters = True

        authority_risk = self._extract_component_score(
            filter_data,
            direct_key="authority_risk",
            component_key="authority_risk",
        )
        creator_risk = self._extract_component_score(
            filter_data,
            direct_key="creator_risk",
            component_key="creator_risk",
        )
        concentration_risk = self._extract_component_score(
            filter_data,
            direct_key="concentration_risk",
            component_key="concentration_risk",
        )

        updates = {
            "passed_filters": bool(passed_filters),
            "risk_level": filter_data.get("aggregate_risk_level") or filter_data.get("risk_level"),
            "risk_score": filter_data.get("aggregate_risk_score") or filter_data.get("risk_score"),
            "rejection_reason": (
                filter_data.get("rejection_reason")
                or filter_data.get("reason")
                or ""
            ) if not passed_filters else "",
            "authority_risk": authority_risk,
            "creator_risk": creator_risk,
            "concentration_risk": concentration_risk,
        }
        updates = {k: v for k, v in updates.items() if v is not None}
        return self.update_token(mint, updates)

    def update_token_scoring(self, mint: str, score_data: Dict[str, Any]) -> Optional[Token]:
        """
        Persist score-stage summary on Token.
        """
        breakdown = score_data.get("score_breakdown") or {}

        updates = {
            "final_score": score_data.get("final_score"),
            "confidence": score_data.get("confidence"),
            "risk_score": score_data.get("aggregate_risk_score"),
            "risk_level": score_data.get("aggregate_risk_level") or score_data.get("risk_level"),
            "authority_risk": breakdown.get("authority_risk"),
            "creator_risk": breakdown.get("creator_risk"),
            "concentration_risk": breakdown.get("concentration_risk"),
            "flow_score": breakdown.get("flow_score"),
            "market_cap_sol": breakdown.get("market_cap_sol"),
        }
        updates = {k: v for k, v in updates.items() if v is not None}
        return self.update_token(mint, updates)

    def update_token_raydium_status(self, mint: str, raydium_data: Dict[str, Any]) -> Optional[Token]:
        """
        Persist Raydium/market confirmation fields on Token.
        """
        pool = raydium_data.get("pool", {}) or {}
        pool_validation = raydium_data.get("pool_validation", {}) or {}
        checks = raydium_data.get("checks", {}) or pool_validation.get("checks", {}) or {}
        pool_age_info = checks.get("pool_age", {}) or {}

        liquidity_sol = (
            raydium_data.get("liquidity_sol")
            if raydium_data.get("liquidity_sol") is not None
            else pool.get("liquidity_sol")
        )
        if liquidity_sol is None:
            liquidity_sol = raydium_data.get("raydium_liquidity_sol")
        if liquidity_sol is None:
            liquidity_sol = pool_validation.get("liquidity_sol")

        pool_age_minutes = pool_age_info.get("pool_age_minutes")
        if pool_age_minutes is None and raydium_data.get("elapsed_seconds") is not None:
            try:
                pool_age_minutes = round(float(raydium_data["elapsed_seconds"]) / 60.0, 4)
            except (TypeError, ValueError):
                pool_age_minutes = None

        validation_score = (
            raydium_data.get("validation_score")
            if raydium_data.get("validation_score") is not None
            else pool_validation.get("validation_score")
        )

        updates = {
            "raydium_pool_found": bool(
                pool.get("pool_id")
                or pool.get("id")
                or raydium_data.get("pool_id")
                or raydium_data.get("raydium_pool_id")
                or pool_validation.get("pool_id")
            ),
            "raydium_pool_id": (
                pool.get("pool_id")
                or pool.get("id")
                or raydium_data.get("pool_id")
                or pool_validation.get("pool_id")
            ),
            "raydium_liquidity_sol": liquidity_sol,
            "raydium_pool_age_minutes": pool_age_minutes,
            "validation_score": validation_score,
            "market_cap_sol": raydium_data.get("market_cap_sol"),
            "confidence": raydium_data.get("new_confidence") or raydium_data.get("confidence"),
            "final_score": raydium_data.get("score") or raydium_data.get("final_score"),
        }
        updates = {k: v for k, v in updates.items() if v is not None}
        return self.update_token(mint, updates)

    # -------------------------------------------------------------------------
    # SCORE OPERATIONS
    # -------------------------------------------------------------------------
    def create_score(self, score_data: Dict[str, Any]) -> TokenScore:
        """Create score record."""
        session = self._get_session()
        try:
            payload = self._filter_model_payload(TokenScore, score_data)
            score = TokenScore(**payload)
            session.add(score)
            session.commit()
            session.refresh(score)
            return score
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating score: {e}")
            raise
        finally:
            session.close()

    def get_latest_score(self, mint: str) -> Optional[TokenScore]:
        """Get latest score for token."""
        session = self._get_session()
        try:
            return (
                session.query(TokenScore)
                .filter(TokenScore.mint == mint)
                .order_by(TokenScore.created_at.desc())
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting score: {e}")
            return None
        finally:
            session.close()

    def record_score_analysis(self, mint: str, score_data: Dict[str, Any]) -> TokenScore:
        """
        Persist a normalized score-analysis record.
        """
        breakdown = score_data.get("score_breakdown") or {}

        payload = {
            "mint": mint,
            "final_score": score_data.get("final_score"),
            "confidence": score_data.get("confidence"),
            "risk_level": score_data.get("aggregate_risk_level") or score_data.get("risk_level"),
            "market_cap_score": breakdown.get("market_cap_score")
            if breakdown.get("market_cap_score") is not None
            else breakdown.get("market_cap_sol"),
            "creator_risk": breakdown.get("creator_risk"),
            "authority_risk": breakdown.get("authority_risk"),
            "concentration_risk": breakdown.get("concentration_risk"),
            "flow_score": breakdown.get("flow_score"),
            "holder_quality": breakdown.get("holder_quality"),
            "metadata_score": breakdown.get("metadata_score"),
            "bonus_points": breakdown.get("bonus_points"),
            "penalty_points": breakdown.get("penalty_points"),
            "score_breakdown_json": self._json(breakdown),
            "decision": score_data.get("decision"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return self.create_score(payload)

    # -------------------------------------------------------------------------
    # SIGNAL OPERATIONS
    # -------------------------------------------------------------------------
    def create_signal(self, signal_data: Dict[str, Any]) -> Signal:
        """Create signal record."""
        session = self._get_session()
        try:
            payload = self._filter_model_payload(Signal, signal_data)
            signal = Signal(**payload)
            session.add(signal)
            session.commit()
            session.refresh(signal)
            return signal
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating signal: {e}")
            raise
        finally:
            session.close()

    def update_signal(self, signal_id: str, updates: Dict[str, Any]) -> Optional[Signal]:
        """Update signal."""
        session = self._get_session()
        try:
            signal = session.query(Signal).filter(Signal.signal_id == signal_id).first()
            if not signal:
                return None

            payload = self._filter_model_payload(Signal, updates)
            for key, value in payload.items():
                setattr(signal, key, value)

            session.commit()
            session.refresh(signal)
            return signal
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating signal: {e}")
            raise
        finally:
            session.close()

    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get signal by ID."""
        session = self._get_session()
        try:
            return session.query(Signal).filter(Signal.signal_id == signal_id).first()
        except Exception as e:
            logger.error(f"Error getting signal: {e}")
            return None
        finally:
            session.close()

    def get_signals_by_mint(self, mint: str) -> List[Signal]:
        """Get all signals for a token."""
        session = self._get_session()
        try:
            return session.query(Signal).filter(Signal.mint == mint).all()
        except Exception as e:
            logger.error(f"Error getting signals: {e}")
            return []
        finally:
            session.close()

    def create_structured_signal(self, signal_data: Dict[str, Any]) -> Signal:
        """
        Create signal using the richer pipeline payload.
        """
        metadata = signal_data.get("metadata", {}) or {}
        payload = {
            "signal_id": signal_data["signal_id"],
            "mint": signal_data["mint"],
            "symbol": signal_data.get("symbol", "UNKNOWN"),
            "signal_type": signal_data.get("signal_type"),
            "score": signal_data.get("score"),
            "confidence": signal_data.get("confidence"),
            "reason": signal_data.get("reason"),
            "metadata_json": self._json(metadata),
            "validation_score": metadata.get("validation_score"),
            "raydium_pool_id": metadata.get("pool_id") or metadata.get("pool_address"),
            "raydium_liquidity_sol": metadata.get("liquidity_sol"),
            "current_state": "CREATED",
            "processing_time_ms": signal_data.get("processing_time_ms"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return self.create_signal(payload)

    # -------------------------------------------------------------------------
    # CREATOR OPERATIONS
    # -------------------------------------------------------------------------
    def create_creator_profile(self, creator_data: Dict[str, Any]) -> CreatorProfile:
        """Create creator profile."""
        session = self._get_session()
        try:
            payload = self._filter_model_payload(CreatorProfile, creator_data)
            profile = CreatorProfile(**payload)
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating creator profile: {e}")
            raise
        finally:
            session.close()

    def get_creator_profile(self, creator: str) -> Optional[CreatorProfile]:
        """Get creator profile."""
        session = self._get_session()
        try:
            return (
                session.query(CreatorProfile)
                .filter(CreatorProfile.creator == creator)
                .first()
            )
        except Exception as e:
            logger.error(f"Error getting creator profile: {e}")
            return None
        finally:
            session.close()

    def update_creator_profile(self, creator: str, updates: Dict[str, Any]) -> CreatorProfile:
        """Update creator profile, creating it if it does not exist (upsert)."""
        if "total_tokens_created" in updates and "total_tokens" not in updates:
            updates = updates.copy()
            updates["total_tokens"] = updates.pop("total_tokens_created")

        session = self._get_session()
        try:
            profile = (
                session.query(CreatorProfile)
                .filter(CreatorProfile.creator == creator)
                .first()
            )
            payload = self._filter_model_payload(CreatorProfile, updates)
            if not profile:
                profile = CreatorProfile(creator=creator, **payload)
                session.add(profile)
            else:
                for key, value in payload.items():
                    setattr(profile, key, value)
            profile.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(profile)
            return profile
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating creator profile: {e}")
            raise
        finally:
            session.close()

    def upsert_creator_profile(self, creator: str, updates: Dict[str, Any]) -> CreatorProfile:
        """Create or update creator profile."""
        if "total_tokens_created" in updates and "total_tokens" not in updates:
            updates = updates.copy()
            updates["total_tokens"] = updates.pop("total_tokens_created")

        session = self._get_session()
        try:
            profile = (
                session.query(CreatorProfile)
                .filter(CreatorProfile.creator == creator)
                .first()
            )
            payload = self._filter_model_payload(CreatorProfile, updates)
            if not profile:
                profile = CreatorProfile(creator=creator)
                session.add(profile)
            for key, value in payload.items():
                setattr(profile, key, value)
            profile.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(profile)
            return profile
        except Exception as e:
            session.rollback()
            logger.error(f"Error upserting creator profile: {e}")
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # AUDIT OPERATIONS
    # -------------------------------------------------------------------------
    def log_audit(
        self,
        action: str,
        mint: Optional[str] = None,
        details: Optional[str] = None,
    ) -> AuditLog:
        """Log audit entry."""
        session = self._get_session()
        try:
            log = AuditLog(action=action, mint=mint, details=details)
            session.add(log)
            session.commit()
            session.refresh(log)
            return log
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging audit: {e}")
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # SIGNAL HISTORY OPERATIONS
    # -------------------------------------------------------------------------
    def create_signal_history(
        self,
        signal_id: str,
        mint: str,
        old_state: Optional[str],
        new_state: str,
        reason: Optional[str] = None,
        details_json: Optional[str] = None,
    ) -> SignalHistory:
        """Record a signal state transition."""
        session = self._get_session()
        try:
            entry = SignalHistory(
                signal_id=signal_id,
                mint=mint,
                old_state=old_state,
                new_state=new_state,
                reason=reason,
                details_json=details_json,
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating signal history: {e}")
            raise
        finally:
            session.close()

    def get_signal_history(self, mint: str, signal_id: str) -> List[SignalHistory]:
        """Get full state evolution for a specific signal."""
        session = self._get_session()
        try:
            return (
                session.query(SignalHistory)
                .filter(and_(SignalHistory.signal_id == signal_id, SignalHistory.mint == mint))
                .order_by(SignalHistory.created_at.asc())
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting signal history: {e}")
            return []
        finally:
            session.close()

    def get_signal_state_timeline(self, mint: str) -> List[SignalHistory]:
        """Get all signal state transitions for a token."""
        session = self._get_session()
        try:
            return (
                session.query(SignalHistory)
                .filter(SignalHistory.mint == mint)
                .order_by(SignalHistory.created_at.asc())
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting signal state timeline: {e}")
            return []
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # TOKEN LIFECYCLE OPERATIONS
    # -------------------------------------------------------------------------
    def update_token_lifecycle(
        self,
        mint: str,
        status: str,
        event: Optional[str] = None,
        reason: Optional[str] = None,
        details_json: Optional[str] = None,
    ) -> TokenLifecycle:
        """
        Record a token lifecycle transition and update Token.lifecycle_status.
        """
        session = self._get_session()
        try:
            token = session.query(Token).filter(Token.mint == mint).first()
            old_status = token.lifecycle_status if token else None

            if token:
                token.lifecycle_status = status
                token.updated_at = datetime.utcnow()

            entry = TokenLifecycle(
                mint=mint,
                old_status=old_status,
                new_status=status,
                event=event,
                reason=reason,
                details_json=details_json,
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating token lifecycle: {e}")
            raise
        finally:
            session.close()

    def get_token_lifecycle(self, mint: str) -> List[TokenLifecycle]:
        """Get token lifecycle history."""
        session = self._get_session()
        try:
            return (
                session.query(TokenLifecycle)
                .filter(TokenLifecycle.mint == mint)
                .order_by(TokenLifecycle.created_at.asc())
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting token lifecycle: {e}")
            return []
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # PERFORMANCE METRICS OPERATIONS
    # -------------------------------------------------------------------------
    def create_performance_metric(
        self,
        operation: str,
        duration_ms: float,
        mint: Optional[str] = None,
        signal_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PerformanceMetrics:
        """Persist a performance metric."""
        session = self._get_session()
        try:
            metric = PerformanceMetrics(
                operation=operation,
                mint=mint,
                signal_id=signal_id,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
                metadata_json=self._json(metadata),
            )
            session.add(metric)
            session.commit()
            session.refresh(metric)
            return metric
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating performance metric: {e}")
            raise
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # SYSTEM STATE OPERATIONS
    # -------------------------------------------------------------------------
    def set_system_state(self, key: str, value: Any) -> SystemState:
        """Set system state key/value."""
        session = self._get_session()
        try:
            state = session.query(SystemState).filter(SystemState.key == key).first()
            serialized = value if isinstance(value, str) else self._json(value)

            if not state:
                state = SystemState(key=key, value=serialized)
                session.add(state)
            else:
                state.value = serialized
                state.updated_at = datetime.utcnow()

            session.commit()
            session.refresh(state)
            return state
        except Exception as e:
            session.rollback()
            logger.error(f"Error setting system state: {e}")
            raise
        finally:
            session.close()

    def get_system_state(self, key: str) -> Optional[SystemState]:
        """Get system state by key."""
        session = self._get_session()
        try:
            return session.query(SystemState).filter(SystemState.key == key).first()
        except Exception as e:
            logger.error(f"Error getting system state: {e}")
            return None
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # ANALYTICS / QUERIES
    # -------------------------------------------------------------------------
    def get_recent_signals(self, limit: int = 50) -> List[Signal]:
        """Get most recent signals."""
        session = self._get_session()
        try:
            return (
                session.query(Signal)
                .order_by(Signal.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting recent signals: {e}")
            return []
        finally:
            session.close()

    def get_recent_tokens(self, limit: int = 50) -> List[Token]:
        """Get most recent tokens."""
        session = self._get_session()
        try:
            return (
                session.query(Token)
                .order_by(Token.created_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting recent tokens: {e}")
            return []
        finally:
            session.close()

    def get_tokens_created_since(self, minutes: int) -> List[Token]:
        """Get tokens created within the last N minutes."""
        session = self._get_session()
        try:
            threshold = datetime.utcnow() - timedelta(minutes=minutes)
            return (
                session.query(Token)
                .filter(Token.created_at >= threshold)
                .order_by(Token.created_at.desc())
                .all()
            )
        except Exception as e:
            logger.error(f"Error getting tokens created since: {e}")
            return []
        finally:
            session.close()

    def get_signal_count_since(self, minutes: int) -> int:
        """Count signals created within the last N minutes."""
        session = self._get_session()
        try:
            threshold = datetime.utcnow() - timedelta(minutes=minutes)
            return (
                session.query(func.count(Signal.id))
                .filter(Signal.created_at >= threshold)
                .scalar()
                or 0
            )
        except Exception as e:
            logger.error(f"Error counting recent signals: {e}")
            return 0
        finally:
            session.close()
