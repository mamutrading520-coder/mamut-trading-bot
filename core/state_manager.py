from typing import Dict, Optional
from loguru import logger


class StateManager:
    """
    Tracks token processing state across the pipeline.
    """

    def __init__(self, store):
        self.store = store
        self.token_states: Dict[str, str] = {}

    async def set_state(self, mint: str, state: str) -> None:
        """
        Set current token state.
        """
        try:
            self.token_states[mint] = state
            logger.debug(f"Token {mint[:8]}... state -> {state}")
        except Exception as e:
            logger.error(f"Error setting state for {mint[:8]}...: {e}")

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
