"""SQLite database operations for Mamut"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy import create_engine, func, and_
from sqlalchemy.orm import sessionmaker, Session
from monitoring.logger import setup_logger
from storage.models import Base, Token, TokenScore, Signal, CreatorProfile, AuditLog, SystemState
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