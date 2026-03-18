"""SQLite database operations for Mamut"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from sqlalchemy import create_engine, func, and_
from sqlalchemy.orm import sessionmaker, Session
from monitoring.logger import setup_logger
from storage.models import (
    Base, Token, TokenScore, Signal, CreatorProfile, AuditLog, SystemState,
    SignalHistory, TokenLifecycle, PerformanceMetrics, SignalOutcome,
)
from config.settings import Settings

logger = setup_logger("SQLiteStore")

class SQLiteStore:
    """SQLite database store for Mamut"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(
            settings.database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            connect_args={"check_same_thread": False}
        )
        
        self._init_db()
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
    
    def _init_db(self) -> None:
        """Initialize database"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info(f"Database initialized: {self.settings.database_url}")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def _get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()
    
    # TOKEN OPERATIONS
    def create_token(self, token_data: Dict[str, Any]) -> Token:
        """Create token record"""
        try:
            session = self._get_session()
            token = Token(**token_data)
            session.add(token)
            session.commit()
            session.refresh(token)
            session.close()
            return token
        except Exception as e:
            logger.error(f"Error creating token: {e}")
            raise
    
    def get_token(self, mint: str) -> Optional[Token]:
        """Get token by mint"""
        try:
            session = self._get_session()
            token = session.query(Token).filter(Token.mint == mint).first()
            session.close()
            return token
        except Exception as e:
            logger.error(f"Error getting token: {e}")
            return None
    
    def token_exists(self, mint: str) -> bool:
        """Check if token exists"""
        try:
            session = self._get_session()
            exists = session.query(Token).filter(Token.mint == mint).first() is not None
            session.close()
            return exists
        except Exception as e:
            logger.error(f"Error checking token existence: {e}")
            return False
    
    def update_token(self, mint: str, updates: Dict[str, Any]) -> Optional[Token]:
        """Update token"""
        try:
            session = self._get_session()
            token = session.query(Token).filter(Token.mint == mint).first()
            if token:
                for key, value in updates.items():
                    setattr(token, key, value)
                token.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(token)
            session.close()
            return token
        except Exception as e:
            logger.error(f"Error updating token: {e}")
            raise
    
    # SCORE OPERATIONS
    def create_score(self, score_data: Dict[str, Any]) -> TokenScore:
        """Create score record"""
        try:
            session = self._get_session()
            score = TokenScore(**score_data)
            session.add(score)
            session.commit()
            session.refresh(score)
            session.close()
            return score
        except Exception as e:
            logger.error(f"Error creating score: {e}")
            raise
    
    def get_latest_score(self, mint: str) -> Optional[TokenScore]:
        """Get latest score for token"""
        try:
            session = self._get_session()
            score = session.query(TokenScore).filter(
                TokenScore.mint == mint
            ).order_by(TokenScore.created_at.desc()).first()
            session.close()
            return score
        except Exception as e:
            logger.error(f"Error getting score: {e}")
            return None
    
    # SIGNAL OPERATIONS
    def create_signal(self, signal_data: Dict[str, Any]) -> Signal:
        """Create signal record"""
        try:
            session = self._get_session()
            signal = Signal(**signal_data)
            session.add(signal)
            session.commit()
            session.refresh(signal)
            session.close()
            return signal
        except Exception as e:
            logger.error(f"Error creating signal: {e}")
            raise
    
    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get signal by ID"""
        try:
            session = self._get_session()
            signal = session.query(Signal).filter(Signal.signal_id == signal_id).first()
            session.close()
            return signal
        except Exception as e:
            logger.error(f"Error getting signal: {e}")
            return None
    
    def get_signals_by_mint(self, mint: str) -> List[Signal]:
        """Get all signals for a token"""
        try:
            session = self._get_session()
            signals = session.query(Signal).filter(Signal.mint == mint).all()
            session.close()
            return signals
        except Exception as e:
            logger.error(f"Error getting signals: {e}")
            return []
    
    # CREATOR OPERATIONS
    def create_creator_profile(self, creator_data: Dict[str, Any]) -> CreatorProfile:
        """Create creator profile"""
        try:
            session = self._get_session()
            profile = CreatorProfile(**creator_data)
            session.add(profile)
            session.commit()
            session.refresh(profile)
            session.close()
            return profile
        except Exception as e:
            logger.error(f"Error creating creator profile: {e}")
            raise
    
    def get_creator_profile(self, creator: str) -> Optional[CreatorProfile]:
        """Get creator profile"""
        try:
            session = self._get_session()
            profile = session.query(CreatorProfile).filter(
                CreatorProfile.creator == creator
            ).first()
            session.close()
            return profile
        except Exception as e:
            logger.error(f"Error getting creator profile: {e}")
            return None
    
    def update_creator_profile(self, creator: str, updates: Dict[str, Any]) -> Optional[CreatorProfile]:
        """Update creator profile"""
        try:
            session = self._get_session()
            profile = session.query(CreatorProfile).filter(
                CreatorProfile.creator == creator
            ).first()
            if profile:
                for key, value in updates.items():
                    setattr(profile, key, value)
                profile.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(profile)
            session.close()
            return profile
        except Exception as e:
            logger.error(f"Error updating creator profile: {e}")
            raise
    
    # AUDIT OPERATIONS
    def log_audit(self, action: str, mint: Optional[str] = None, details: Optional[str] = None) -> AuditLog:
        """Log audit entry"""
        try:
            session = self._get_session()
            log = AuditLog(action=action, mint=mint, details=details)
            session.add(log)
            session.commit()
            session.refresh(log)
            session.close()
            return log
        except Exception as e:
            logger.error(f"Error logging audit: {e}")
            raise
    
    # STATISTICS
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        try:
            session = self._get_session()
            
            # Count tokens
            total_tokens = session.query(func.count(Token.id)).scalar() or 0
            
            # Count signals
            total_signals = session.query(func.count(Signal.id)).scalar() or 0
            
            # Tokens by risk level
            risk_levels = session.query(
                Token.risk_level,
                func.count(Token.id)
            ).group_by(Token.risk_level).all()
            
            tokens_by_risk = {level: count for level, count in risk_levels}
            
            # Signals by type
            signal_types = session.query(
                Signal.signal_type,
                func.count(Signal.id)
            ).group_by(Signal.signal_type).all()
            
            signals_by_type = {sig_type: count for sig_type, count in signal_types}
            
            session.close()
            
            return {
                "total_tokens": total_tokens,
                "total_signals": total_signals,
                "tokens_by_risk": tokens_by_risk,
                "signals_by_type": signals_by_type,
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                "total_tokens": 0,
                "total_signals": 0,
                "tokens_by_risk": {},
                "signals_by_type": {},
            }
    
    def cleanup(self) -> None:
        """Cleanup database resources"""
        try:
            self.engine.dispose()
            logger.info("Database cleanup complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    # SIGNAL HISTORY OPERATIONS

    def create_signal_history(
        self,
        signal_id: str,
        mint: str,
        old_state: Optional[str],
        new_state: str,
        reason: Optional[str] = None,
        details_json: Optional[str] = None,
    ) -> SignalHistory:
        """Record a signal state transition.

        Complexity: O(1) insert.
        """
        try:
            session = self._get_session()
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
            session.close()
            return entry
        except Exception as e:
            logger.error(f"Error creating signal history: {e}")
            raise

    def get_signal_history(self, mint: str, signal_id: str) -> List[SignalHistory]:
        """Get full state evolution for a specific signal.

        Uses idx_sh_signal_id_ts index for O(log n) lookup.
        """
        try:
            session = self._get_session()
            rows = (
                session.query(SignalHistory)
                .filter(
                    and_(SignalHistory.signal_id == signal_id, SignalHistory.mint == mint)
                )
                .order_by(SignalHistory.created_at.asc())
                .all()
            )
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting signal history: {e}")
            return []

    def get_signal_state_timeline(self, mint: str) -> List[SignalHistory]:
        """Get all signal state transitions for a token.

        Uses idx_sh_mint_ts index for O(log n) lookup.
        """
        try:
            session = self._get_session()
            rows = (
                session.query(SignalHistory)
                .filter(SignalHistory.mint == mint)
                .order_by(SignalHistory.created_at.asc())
                .all()
            )
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting signal state timeline: {e}")
            return []

    # TOKEN LIFECYCLE OPERATIONS

    def update_token_lifecycle(
        self,
        mint: str,
        status: str,
        event: Optional[str] = None,
        reason: Optional[str] = None,
        details_json: Optional[str] = None,
    ) -> TokenLifecycle:
        """Record a token lifecycle status transition and update the token record.

        Writes a TokenLifecycle event and updates Token.lifecycle_status.
        Uses a single transaction for both writes.
        """
        try:
            session = self._get_session()
            token = session.query(Token).filter(Token.mint == mint).first()
            old_status = token.lifecycle_status if token else None
            if token:
                token.lifecycle_status = status
                token.updated_at = datetime.utcnow()
            else:
                logger.warning(
                    f"update_token_lifecycle: token '{mint}' not found; "
                    "recording lifecycle event without updating token record"
                )
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
            session.close()
            return entry
        except Exception as e:
            logger.error(f"Error updating token lifecycle: {e}")
            raise

    def get_token_lifecycle(self, mint: str) -> List[TokenLifecycle]:
        """Get the full lifecycle timeline for a token.

        Uses idx_tl_mint_ts index for O(log n) lookup.
        """
        try:
            session = self._get_session()
            rows = (
                session.query(TokenLifecycle)
                .filter(TokenLifecycle.mint == mint)
                .order_by(TokenLifecycle.created_at.asc())
                .all()
            )
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting token lifecycle: {e}")
            return []

    def get_tokens_by_status(self, status: str) -> List[Token]:
        """Get all tokens currently at a given lifecycle status.

        Uses idx_token_status_created index for efficient filtering.
        """
        try:
            session = self._get_session()
            tokens = (
                session.query(Token)
                .filter(Token.lifecycle_status == status)
                .order_by(Token.created_at.desc())
                .all()
            )
            session.close()
            return tokens
        except Exception as e:
            logger.error(f"Error getting tokens by status: {e}")
            return []

    # PERFORMANCE METRICS OPERATIONS

    def record_performance_metric(
        self,
        operation: str,
        duration_ms: float,
        mint: Optional[str] = None,
        signal_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> PerformanceMetrics:
        """Record a performance metric for an operation.

        Complexity: O(1) insert.
        """
        try:
            session = self._get_session()
            metric = PerformanceMetrics(
                operation=operation,
                mint=mint,
                signal_id=signal_id,
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
                metadata_json=metadata_json,
            )
            session.add(metric)
            session.commit()
            session.refresh(metric)
            session.close()
            return metric
        except Exception as e:
            logger.error(f"Error recording performance metric: {e}")
            raise

    def get_performance_metrics(
        self,
        time_range: Optional[Tuple[datetime, datetime]] = None,
        operation: Optional[str] = None,
    ) -> List[PerformanceMetrics]:
        """Get performance metrics, optionally filtered by time range and operation.

        Uses idx_pm_operation_ts index for efficient filtering.
        """
        try:
            session = self._get_session()
            q = session.query(PerformanceMetrics)
            if time_range:
                start, end = time_range
                q = q.filter(
                    and_(
                        PerformanceMetrics.created_at >= start,
                        PerformanceMetrics.created_at <= end,
                    )
                )
            if operation:
                q = q.filter(PerformanceMetrics.operation == operation)
            rows = q.order_by(PerformanceMetrics.created_at.asc()).all()
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            return []

    def get_slow_signals(self, threshold_ms: float = 1000.0) -> List[PerformanceMetrics]:
        """Identify slow signal processing operations exceeding a given threshold.

        Uses idx_pm_operation_ts index for O(log n) scan.
        """
        try:
            session = self._get_session()
            rows = (
                session.query(PerformanceMetrics)
                .filter(
                    and_(
                        PerformanceMetrics.operation.like("%signal%"),
                        PerformanceMetrics.duration_ms >= threshold_ms,
                    )
                )
                .order_by(PerformanceMetrics.duration_ms.desc())
                .all()
            )
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting slow signals: {e}")
            return []

    # SIGNAL OUTCOME OPERATIONS

    def create_signal_outcome(self, outcome_data: Dict[str, Any]) -> SignalOutcome:
        """Create or upsert a signal outcome record.

        Complexity: O(1) insert.
        """
        try:
            session = self._get_session()
            outcome = SignalOutcome(**outcome_data)
            session.add(outcome)
            session.commit()
            session.refresh(outcome)
            session.close()
            return outcome
        except Exception as e:
            logger.error(f"Error creating signal outcome: {e}")
            raise

    def get_signal_outcomes(
        self,
        date_range: Optional[Tuple[datetime, datetime]] = None,
    ) -> List[SignalOutcome]:
        """Get signal outcomes for performance analysis.

        Optionally filtered by date range. Uses idx_so_mint_ts index.
        """
        try:
            session = self._get_session()
            q = session.query(SignalOutcome)
            if date_range:
                start, end = date_range
                q = q.filter(
                    and_(
                        SignalOutcome.created_at >= start,
                        SignalOutcome.created_at <= end,
                    )
                )
            rows = q.order_by(SignalOutcome.created_at.desc()).all()
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting signal outcomes: {e}")
            return []

    def get_creator_signal_performance(self, creator: str) -> List[SignalOutcome]:
        """Get signal outcomes for a specific creator for accuracy analysis.

        Uses idx_so_creator_outcome index for O(log n) lookup.
        """
        try:
            session = self._get_session()
            rows = (
                session.query(SignalOutcome)
                .filter(SignalOutcome.creator == creator)
                .order_by(SignalOutcome.created_at.desc())
                .all()
            )
            session.close()
            return rows
        except Exception as e:
            logger.error(f"Error getting creator signal performance: {e}")
            return []

    # DATA RETENTION OPERATIONS

    def cleanup_old_records(self, days: int = 90) -> Dict[str, int]:
        """Delete records older than the specified number of days.

        Removes entries from audit_logs, signal_history, token_lifecycle,
        and performance_metrics to enforce data retention policy.
        Returns a dict with count of deleted rows per table.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted: Dict[str, int] = {}
        try:
            session = self._get_session()
            for model, label in [
                (AuditLog, "audit_logs"),
                (SignalHistory, "signal_history"),
                (TokenLifecycle, "token_lifecycle"),
                (PerformanceMetrics, "performance_metrics"),
            ]:
                count = (
                    session.query(model)
                    .filter(model.created_at < cutoff)
                    .delete(synchronize_session=False)
                )
                deleted[label] = count
            session.commit()
            session.close()
            logger.info(f"Cleaned up records older than {days} days: {deleted}")
            return deleted
        except Exception as e:
            logger.error(f"Error during cleanup_old_records: {e}")
            raise

    def archive_old_data(self, before_date: datetime) -> Dict[str, int]:
        """Delete signal outcome and token lifecycle records before a date.

        Intended for periodic archival to maintain query performance.
        Returns a dict with count of archived (deleted) rows per table.
        """
        archived: Dict[str, int] = {}
        try:
            session = self._get_session()
            for model, label in [
                (SignalOutcome, "signal_outcomes"),
                (TokenLifecycle, "token_lifecycle"),
                (SignalHistory, "signal_history"),
            ]:
                count = (
                    session.query(model)
                    .filter(model.created_at < before_date)
                    .delete(synchronize_session=False)
                )
                archived[label] = count
            session.commit()
            session.close()
            logger.info(f"Archived data before {before_date}: {archived}")
            return archived
        except Exception as e:
            logger.error(f"Error during archive_old_data: {e}")
            raise