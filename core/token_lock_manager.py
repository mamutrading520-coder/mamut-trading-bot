"""Manage token locks to prevent duplicate processing"""
from typing import Dict, Optional
from datetime import datetime, timedelta
from monitoring.logger import setup_logger
from config.thresholds import TOKEN_LOCK_CONFIG
from utils.time_utils import get_timestamp, seconds_since

logger = setup_logger("TokenLockManager")

class TokenLockManager:
    """Manages token locks to prevent concurrent processing"""
    
    def __init__(self):
        self.locks: Dict[str, float] = {}  # mint -> lock_time
        self.timeout = TOKEN_LOCK_CONFIG.get("timeout_seconds", 3600)
        self.locked_count = 0
        self.released_count = 0
    
    def lock_token(self, mint: str) -> bool:
        """
        Attempt to lock token
        
        Args:
            mint: Token mint address
            
        Returns:
            True if locked successfully, False if already locked
        """
        try:
            if mint in self.locks:
                # Check if lock has expired
                lock_time = self.locks[mint]
                elapsed = seconds_since(lock_time)
                
                if elapsed < self.timeout:
                    logger.debug(f"Token already locked: {mint[:8]}... ({elapsed:.0f}s ago)")
                    return False
                else:
                    # Lock expired, remove it
                    logger.debug(f"Expired lock removed for {mint[:8]}...")
                    del self.locks[mint]
            
            # Create new lock
            self.locks[mint] = get_timestamp()
            self.locked_count += 1
            logger.debug(f"Token locked: {mint[:8]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error locking token: {e}")
            return False
    
    def unlock_token(self, mint: str) -> bool:
        """
        Unlock token
        
        Args:
            mint: Token mint address
            
        Returns:
            True if unlocked, False if not locked
        """
        try:
            if mint not in self.locks:
                logger.debug(f"Token not locked: {mint[:8]}...")
                return False
            
            del self.locks[mint]
            self.released_count += 1
            logger.debug(f"Token unlocked: {mint[:8]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error unlocking token: {e}")
            return False
    
    def is_locked(self, mint: str) -> bool:
        """
        Check if token is locked
        
        Args:
            mint: Token mint address
            
        Returns:
            True if locked and not expired
        """
        try:
            if mint not in self.locks:
                return False
            
            lock_time = self.locks[mint]
            elapsed = seconds_since(lock_time)
            
            if elapsed >= self.timeout:
                # Lock expired
                del self.locks[mint]
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking lock: {e}")
            return False
    
    def cleanup_expired_locks(self) -> int:
        """
        Remove expired locks
        
        Returns:
            Number of locks removed
        """
        try:
            expired = []
            
            for mint, lock_time in self.locks.items():
                elapsed = seconds_since(lock_time)
                if elapsed >= self.timeout:
                    expired.append(mint)
            
            for mint in expired:
                del self.locks[mint]
            
            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired locks")
            
            return len(expired)
            
        except Exception as e:
            logger.error(f"Error cleaning up locks: {e}")
            return 0
    
    def get_stats(self) -> dict:
        """Get lock manager statistics"""
        return {
            "locked_tokens": len(self.locks),
            "total_locked": self.locked_count,
            "total_released": self.released_count,
            "active_locks": list(self.locks.keys()),
        }