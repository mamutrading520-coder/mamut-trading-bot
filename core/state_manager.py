from typing import Dict, Optional
from loguru import logger


class StateManager:
    """
    Tracks token processing state across the pipeline.
    """

    def __init__(self, store):
        self.store = store
        self.token_states: Dict[str, str] = {}
        self.early_signals_sent: int = 0

    async def initialize_token(
        self,
        mint: str,
        name: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> bool:
        """
        Initialize token in state tracking and persistent storage.
        """
        try:
            self.token_states[mint] = "DISCOVERED"

            token_data = {
                "mint": mint,
                "name": name or "",
                "symbol": symbol or "",
            }

            try:
                existing = self.store.get_token(mint)
            except Exception:
                existing = None

            if not existing:
                try:
                    self.store.create_token(token_data)
                except Exception as db_error:
                    logger.warning(f"Could not create token {mint[:8]}...: {db_error}")

            logger.debug(f"Token {mint[:8]}... initialized")
            return True

        except Exception as e:
            logger.error(f"Error initializing token {mint[:8]}...: {e}")
            return False

    async def set_state(self, mint: str, state: str) -> None:
        """
        Set current token state.
        """
        try:
            self.token_states[mint] = state
            logger.debug(f"Token {mint[:8]}... state -> {state}")
        except Exception as e:
            logger.error(f"Error setting state for {mint[:8]}...: {e}")

    async def update_token_state(self, mint: str, state: str) -> bool:
        """
        Update token state in memory.
        """
        try:
            self.token_states[mint] = state
            logger.debug(f"Token {mint[:8]}... updated state -> {state}")
            return True
        except Exception as e:
            logger.error(f"Error updating state for {mint[:8]}...: {e}")
            return False

    async def get_state(self, mint: str) -> Optional[str]:
        """
        Get current token state.
        """
        return self.token_states.get(mint)

    async def mark_discovered(self, mint: str) -> bool:
        """
        Mark token as discovered.
        """
        try:
            self.token_states[mint] = "DISCOVERED"
            logger.debug(f"Token {mint[:8]}... marked as DISCOVERED")
            return True
        except Exception as e:
            logger.error(f"Error marking discovered: {e}")
            return False

    async def mark_enriched(self, mint: str) -> bool:
        """
        Mark token as enriched.
        """
        try:
            self.token_states[mint] = "ENRICHED"
            logger.debug(f"Token {mint[:8]}... marked as ENRICHED")
            return True
        except Exception as e:
            logger.error(f"Error marking enriched: {e}")
            return False

    async def mark_filtered(self, mint: str, passed: bool) -> bool:
        """
        Mark token after filter stage.
        """
        try:
            self.token_states[mint] = "FILTERED" if passed else "REJECTED"
            logger.debug(
                f"Token {mint[:8]}... marked as {'FILTERED' if passed else 'REJECTED'}"
            )
            return True
        except Exception as e:
            logger.error(f"Error marking filtered: {e}")
            return False

    async def mark_scored(self, mint: str) -> bool:
        """
        Mark token as scored.
        """
        try:
            self.token_states[mint] = "SCORED"
            logger.debug(f"Token {mint[:8]}... marked as SCORED")
            return True
        except Exception as e:
            logger.error(f"Error marking scored: {e}")
            return False

    async def mark_signaled(self, mint: str) -> bool:
        """
        Mark token as signaled.
        """
        try:
            self.token_states[mint] = "SIGNALED"
            logger.debug(f"Token {mint[:8]}... marked as SIGNALED")
            return True
        except Exception as e:
            logger.error(f"Error marking signaled: {e}")
            return False

    async def mark_early_signal_sent(self, mint: str) -> bool:
        """
        Mark that an early signal alert was sent.
        """
        try:
            self.token_states[mint] = "EARLY_SIGNAL_SENT"
            self.early_signals_sent += 1
            logger.debug(f"Token {mint[:8]}... marked as EARLY_SIGNAL_SENT")
            return True
        except Exception as e:
            logger.error(f"Error marking early signal sent: {e}")
            return False

    async def mark_abandoned(self, mint: str, reason: str) -> bool:
        """
        Mark token as abandoned and persist rejection reason.
        """
        try:
            self.token_states[mint] = "ABANDONED"

            self.store.update_token(
                mint,
                {
                    "rejection_reason": reason,
                    "passed_filters": False,
                    "risk_level": "REJECTED",
                },
            )

            logger.debug(f"Token {mint[:8]}... abandoned: {reason}")
            return True
        except Exception as e:
            logger.error(f"Error marking token abandoned: {e}")
            return False

    def get_stats(self) -> dict:
        """
        Get state manager statistics.
        """
        return {
            "tracked_tokens": len(self.token_states),
            "early_signals_sent": self.early_signals_sent,
            "states": dict(self.token_states),
        }
