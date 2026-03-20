from __future__ import annotations

import json
from typing import Any, Dict, Optional

from loguru import logger


class StateManager:
    """
    Centraliza el estado de procesamiento de cada token.

    Responsabilidades:
    - Mantener estado actual en memoria para acceso rápido.
    - Persistir el token base si aún no existe.
    - Persistir transiciones de lifecycle en la base de datos.
    - Mantener métricas operativas simples del pipeline.
    """

    VALID_STATES = {
        "DISCOVERED",
        "PARSED",
        "ENRICHED",
        "PROFILED",
        "PASSED_FILTERS",
        "FILTER_REJECTED",
        "SCORED",
        "DECISION_MADE",
        "EARLY_SIGNAL_SENT",
        "SIGNAL_GENERATED",
        "ALERT_DISPATCHED",
        "RAYDIUM_WATCH_STARTED",
        "POOL_FOUND",
        "POOL_VALIDATED",
        "POOL_INVALID",
        "MARKET_CONFIRMED",
        "POOL_TIMEOUT",
        "ABANDONED",
        "FAILED",
    }

    def __init__(self, store):
        self.store = store
        self.token_states: Dict[str, str] = {}
        self.early_signals_sent: int = 0
        self.lifecycle_updates: int = 0
        self.abandoned_tokens: int = 0
        self.failed_updates: int = 0

    async def initialize_token(
        self,
        mint: str,
        name: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> bool:
        """
        Inicializa un token en memoria y en persistencia.
        Si el token ya existe, no lo duplica.
        """
        if not mint:
            logger.error("initialize_token called without mint")
            self.failed_updates += 1
            return False

        try:
            existing = None
            try:
                existing = self.store.get_token(mint)
            except Exception as db_error:
                logger.warning(f"Could not read token {mint[:8]}... from store: {db_error}")

            if not existing:
                token_data = {
                    "mint": mint,
                    "name": name or "",
                    "symbol": symbol or "",
                    "lifecycle_status": "DISCOVERED",
                }

                try:
                    self.store.create_token(token_data)
                except Exception as db_error:
                    logger.error(f"Could not create token {mint[:8]}...: {db_error}")
                    self.failed_updates += 1
                    return False

            self.token_states[mint] = "DISCOVERED"

            self._record_lifecycle(
                mint=mint,
                new_status="DISCOVERED",
                event="TokenDiscovered",
                reason=None,
                details={
                    "name": name or "",
                    "symbol": symbol or "",
                },
            )

            logger.debug(f"Token {mint[:8]}... initialized")
            return True

        except Exception as e:
            logger.error(f"Error initializing token {mint[:8]}...: {e}")
            self.failed_updates += 1
            return False

    async def update_token_state(
        self,
        mint: str,
        state: str,
        details: Optional[Dict[str, Any]] = None,
        event: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Actualiza el estado actual del token en memoria y persistencia.
        Registra primero la transición de lifecycle y después consolida
        el estado actual en memoria y en la tabla tokens.
        """
        if not mint:
            logger.error("update_token_state called without mint")
            self.failed_updates += 1
            return False

        normalized_state = self._normalize_state(state)
        current_state = self.token_states.get(mint)

        try:
            if current_state == normalized_state:
                logger.debug(f"Token {mint[:8]}... already in state {normalized_state}")
                return True

            self._record_lifecycle(
                mint=mint,
                new_status=normalized_state,
                event=event,
                reason=reason,
                details=details,
            )

            self.token_states[mint] = normalized_state

            try:
                self.store.update_token(
                    mint,
                    {
                        "lifecycle_status": normalized_state,
                    },
                )
            except Exception as db_error:
                logger.warning(
                    f"Could not update token lifecycle_status for {mint[:8]}...: {db_error}"
                )

            logger.debug(
                f"Token {mint[:8]}... state -> {normalized_state}"
                + (f" | reason={reason}" if reason else "")
            )
            return True

        except Exception as e:
            logger.error(f"Error updating state for {mint[:8]}...: {e}")
            self.failed_updates += 1
            return False

    async def mark_abandoned(self, mint: str, reason: str) -> bool:
        """
        Marca un token como abandonado/rechazado y persiste la razón.
        Registra primero la transición en token_lifecycle y después
        consolida el estado actual en memoria y en la tabla tokens.
        """
        if not mint:
            logger.error("mark_abandoned called without mint")
            self.failed_updates += 1
            return False

        try:
            self._record_lifecycle(
                mint=mint,
                new_status="ABANDONED",
                event="TokenRejected",
                reason=reason,
                details=None,
            )

            self.token_states[mint] = "ABANDONED"

            try:
                self.store.update_token(
                    mint,
                    {
                        "rejection_reason": reason,
                        "passed_filters": False,
                        "risk_level": "REJECTED",
                        "lifecycle_status": "ABANDONED",
                    },
                )
            except Exception as db_error:
                logger.warning(f"Could not persist abandoned state for {mint[:8]}...: {db_error}")

            self.abandoned_tokens += 1
            logger.debug(f"Token {mint[:8]}... abandoned: {reason}")
            return True

        except Exception as e:
            logger.error(f"Error marking token abandoned {mint[:8]}...: {e}")
            self.failed_updates += 1
            return False

    async def mark_early_signal_sent(self, mint: str) -> bool:
        """
        Marca que ya se despachó una señal temprana.
        """
        updated = await self.update_token_state(
            mint=mint,
            state="EARLY_SIGNAL_SENT",
            event="AlertDispatched",
        )
        if updated:
            self.early_signals_sent += 1
        return updated

    async def get_state(self, mint: str) -> Optional[str]:
        """
        Devuelve el estado actual del token desde memoria.
        """
        return self.token_states.get(mint)

    def get_stats(self) -> dict:
        """
        Devuelve estadísticas operativas del gestor de estados.
        """
        state_counts: Dict[str, int] = {}
        for state in self.token_states.values():
            state_counts[state] = state_counts.get(state, 0) + 1

        return {
            "tracked_tokens": len(self.token_states),
            "early_signals_sent": self.early_signals_sent,
            "lifecycle_updates": self.lifecycle_updates,
            "abandoned_tokens": self.abandoned_tokens,
            "failed_updates": self.failed_updates,
            "states": dict(self.token_states),
            "state_counts": state_counts,
        }

    def _normalize_state(self, state: str) -> str:
        """
        Normaliza estados para evitar basura tipográfica
        sin bloquear estados nuevos del pipeline.
        """
        normalized = (state or "").strip().upper()
        if not normalized:
            return "FAILED"

        if normalized not in self.VALID_STATES:
            logger.warning(f"Unknown token state received: {normalized}")

        return normalized

    def _record_lifecycle(
        self,
        mint: str,
        new_status: str,
        event: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Persiste la transición en token_lifecycle si el store lo soporta.
        """
        details_json = None

        if details:
            try:
                details_json = json.dumps(details, ensure_ascii=False, default=str)
            except Exception as json_error:
                logger.warning(
                    f"Could not serialize lifecycle details for {mint[:8]}...: {json_error}"
                )

        try:
            self.store.update_token_lifecycle(
                mint=mint,
                status=new_status,
                event=event,
                reason=reason,
                details_json=details_json,
            )
            self.lifecycle_updates += 1
        except Exception as db_error:
            logger.warning(
                f"Could not record lifecycle transition for {mint[:8]}... -> {new_status}: {db_error}"
            )
