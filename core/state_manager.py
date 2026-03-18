"""Manage token processing state and lifecycle"""
from typing import Dict, Optional
from datetime import datetime
from monitoring.logger import setup_logger
from storage.sqlite_store import SQLiteStore
from config.settings import Settings

logger = setup_logger("StateManager")

class StateManager:
    """Manages token state throughout processing pipeline"""

    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        # Track token processing state in memory
        self.token_states: Dict[str, str] = {}

    async def initialize_token(self, mint: str, name: str, symbol: str) -> bool:
        """
        Initialize token in system

        Args:
            mint: Token mint
            name: Token name
            symbol: Token symbol

        Returns:
            True if initialized, False otherwise
        """
        try:
            # Create token record with only valid fields
            token_data = {
                "mint": mint,
                "name": name,
                "symbol": symbol,
                "risk_level": "UNKNOWN",
                "passed_filters": False,
            }
            self.store.create_token(token_data)
            
            # Track state in memory
            self.token_states[mint] = "DISCOVERED"

            logger.debug(f"Initialized token: {symbol} ({mint[:8]}...)")
            return True

        except Exception as e:
            logger.error(f"Error initializing token: {e}")
            return False

    async def update_token_state(self, mint: str, state: str) -> bool:
        """
        Update token processing state

        Args:
            mint: Token mint
            state: New state (DISCOVERED, PARSED, ENRICHED, PROFILED, PASSED_FILTERS, SCORED, DECISION_MADE)

        Returns:
            True if updated, False otherwise
        """
        try:
            self.token_states[mint] = state
            logger.debug(f"Token {mint[:8]}... state: {state}")
            return True
        except Exception as e:
            logger.error(f"Error updating token state: {e}")
            return False

    async def mark_abandoned(self, mint: str, reason: str) -> bool:
        """
        Mark token as abandoned

        Args:
            mint: Token mint
            reason: Abandonment reason

        Returns:
            True if marked, False otherwise
        """
        try:
            self.token_states[mint] = "ABANDONED"
            
            # Update in database
            token = self.store.get_token(mint)
            if token:
                token.rejection_reason = reason
                self.store.update_token(token)
            
            logger.debug(f"Token {mint[:8]}... abandoned: {reason}")
            return True
        except Exception as e:
            logger.error(f"Error marking token abandoned: {e}")
            return False

    async def mark_early_signal_sent(self, mint: str) -> bool:
        """
        Mark early signal as sent

        Args:
            mint: Token mint

        Returns:
            True if marked, False otherwise
        """
        try:
            self.token_states[mint] = "EARLY_SIGNAL_SENT"
            logger.debug(f"Token {mint[:8]}... early signal marked as sent")
            return True
        except Exception as e:
            logger.error(f"Error marking early signal sent: {e}")
            return False

    async def mark_confirmation_signal_sent(self, mint: str) -> bool:
        """
        Mark confirmation signal as sent

        Args:
            mint: Token mint

        Returns:
            True if marked, False otherwise
        """
        try:
            self.token_states[mint] = "CONFIRMATION_SIGNAL_SENT"
            logger.debug(f"Token {mint[:8]}... confirmation signal marked as sent")
            return True
        except Exception as e:
            logger.error(f"Error marking confirmation signal sent: {e}")
            return False

    def get_token_state(self, mint: str) -> Optional[str]:
        """Get current token state"""
        return self.token_states.get(mint)

    def get_stats(self) -> dict:
        """Get state manager statistics"""
        states = {}
        for state in self.token_states.values():
            states[state] = states.get(state, 0) + 1
        
        return {
            "tracked_tokens": len(self.token_states),
            "states": states,
        }