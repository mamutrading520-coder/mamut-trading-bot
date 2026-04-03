"""Manage token locks to prevent duplicate processing"""
from __future__ import annotations

from typing import Dict

from monitoring.logger import setup_logger
from config.thresholds import TOKEN_LOCK_CONFIG
from utils.time_utils import get_timestamp, seconds_since

logger = setup_logger("TokenLockManager")


class TokenLockManager:
    """Manages token locks to prevent concurrent processing."""

    def __init__(self):
        self.locks: Dict[str, float] = {}  # mint -> lock_time
        self.timeout = TOKEN_LOCK_CONFIG.get("lock_timeout_seconds", 300)
        self.locked_count = 0
        self.released_count = 0
        self.expired_count = 0
        self.duplicate_lock_attempts = 0
        self.failed_release_attempts = 0

    def lock_token(self, mint: str) -> bool:
        """Attempt to lock token."""
        try:
            if mint in self.locks:
                lock_time = self.locks[mint]
                elapsed = seconds_since(lock_time)

                if elapsed < self.timeout:
                    self.duplicate_lock_attempts += 1
                    logger.debug(f"Token already locked: {mint[:8]}... ({elapsed:.0f}s ago)")
                    return False

                logger.debug(f"Expired lock removed for {mint[:8]}...")
                self._drop_lock(mint, reason="expired")

            self.locks[mint] = get_timestamp()
            self.locked_count += 1
            logger.debug(f"Token locked: {mint[:8]}...")
            return True

        except Exception as e:
            logger.error(f"Error locking token: {e}")
            return False

    def unlock_token(self, mint: str, reason: str = "manual") -> bool:
        """Unlock token."""
        try:
            if mint not in self.locks:
                self.failed_release_attempts += 1
                logger.debug(f"Token not locked: {mint[:8]}...")
                return False

            self._drop_lock(mint, reason=reason)
            logger.debug(f"Token unlocked: {mint[:8]}... | reason={reason}")
            return True

        except Exception as e:
            logger.error(f"Error unlocking token: {e}")
            return False

    def release_token(self, mint: str, reason: str = "manual") -> bool:
        """Alias for unlock_token to support clearer terminal-release semantics."""
        return self.unlock_token(mint, reason=reason)

    def is_locked(self, mint: str) -> bool:
        """Check if token is locked and not expired."""
        try:
            if mint not in self.locks:
                return False

            lock_time = self.locks[mint]
            elapsed = seconds_since(lock_time)

            if elapsed >= self.timeout:
                self._drop_lock(mint, reason="expired")
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking lock: {e}")
            return False

    def cleanup_expired_locks(self) -> int:
        """Remove expired locks."""
        try:
            expired = []

            for mint, lock_time in list(self.locks.items()):
                elapsed = seconds_since(lock_time)
                if elapsed >= self.timeout:
                    expired.append(mint)

            for mint in expired:
                self._drop_lock(mint, reason="expired")

            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired locks")

            return len(expired)

        except Exception as e:
            logger.error(f"Error cleaning up locks: {e}")
            return 0

    def _drop_lock(self, mint: str, reason: str) -> None:
        """Internal lock removal with accounting."""
        if mint not in self.locks:
            return

        del self.locks[mint]
        self.released_count += 1
        if reason == "expired":
            self.expired_count += 1

    def get_stats(self) -> dict:
        """Get lock manager statistics."""
        return {
            "locked_tokens": len(self.locks),
            "total_locked": self.locked_count,
            "total_released": self.released_count,
            "expired_releases": self.expired_count,
            "duplicate_lock_attempts": self.duplicate_lock_attempts,
            "failed_release_attempts": self.failed_release_attempts,
            "active_locks": list(self.locks.keys()),
        }
