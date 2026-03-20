"""Generate trading signals from token analysis"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.settings import Settings

logger = setup_logger("SignalEngine")


@dataclass
class SignalData:
    """Signal data structure"""

    signal_id: str
    signal_type: str
    mint: str
    symbol: str
    score: float
    confidence: float
    risk_level: str
    reason: str
    metadata: Dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "mint": self.mint,
            "symbol": self.symbol,
            "score": self.score,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class SignalEngine:
    """Generates trading signals from comprehensive analysis"""

    def __init__(self, store, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()

        self.score_threshold = settings.score_threshold_high_potential

        self.signals_generated = 0
        self.early_signals = 0
        self.confirmation_signals = 0
        self.abandon_signals = 0

    async def generate_early_and_emit(self, event: Event) -> bool:
        """Generate EARLY signal and emit to event bus with persistence to DB."""
        start_time = time.time()

        try:
            decision_data = event.data or {}
            decision_str = decision_data.get("decision", "UNKNOWN")

            signal = SignalData(
                signal_id=f"SIGNAL-{uuid.uuid4().hex[:12]}",
                signal_type="EARLY",
                mint=decision_data.get("mint"),
                symbol=decision_data.get("symbol", "UNKNOWN"),
                score=float(decision_data.get("final_score", 0) or 0),
                confidence=float(decision_data.get("confidence", 0.5) or 0.5),
                risk_level=decision_str,
                reason=f"Decision: {decision_str}",
                metadata={
                    "decision": decision_str,
                    "source_event": event.event_type,
                },
                timestamp=datetime.utcnow(),
            )

            self._persist_signal(
                signal=signal,
                old_state=None,
                new_state="CREATED",
                history_reason="Early signal generated from decision pipeline",
                operation_name="signal_generation_early",
                started_at=start_time,
            )

            self.signals_generated += 1
            self.early_signals += 1

            signal_event = Event(
                event_type="SignalGenerated",
                data=signal.to_dict(),
                source="SignalEngine",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(signal_event)
            logger.info(f"SignalGenerated EARLY: {signal.signal_id}")
            return True

        except Exception as e:
            logger.error(f"Error in generate_early_and_emit: {e}")
            return False

    async def generate_confirmed_and_emit(
        self,
        event: Event,
        token_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Generate CONFIRMED signal from market confirmation and emit it.

        Expected source:
        - event.event_type == "MarketConfirmed"
        - event.data includes market confirmation output
        """
        start_time = time.time()

        try:
            confirmation_data = event.data or {}
            token_context = token_context or {}

            mint = confirmation_data.get("mint") or token_context.get("mint")
            symbol = (
                confirmation_data.get("symbol")
                or token_context.get("symbol")
                or "UNKNOWN"
            )

            if not mint:
                logger.error("generate_confirmed_and_emit called without mint")
                return False

            base_score = self._safe_float(
                confirmation_data.get("score", token_context.get("final_score", 0))
            )
            confidence = self._safe_float(
                confirmation_data.get(
                    "new_confidence",
                    confirmation_data.get("confidence", token_context.get("confidence", 0.5)),
                )
            )

            pool_validation = confirmation_data.get("pool_validation", {}) or {}
            pool_info = confirmation_data.get("pool", {}) or {}

            validation_score = self._safe_float(
                pool_validation.get("validation_score", 0)
            )
            liquidity_sol = self._safe_float(
                pool_validation.get("liquidity_sol", pool_info.get("liquidity_sol", 0))
            )

            risk_level = confirmation_data.get(
                "risk_level",
                token_context.get("decision", "CONFIRMED"),
            )

            confirmation_reason = confirmation_data.get(
                "reason",
                "Market confirmed after Raydium pool validation",
            )

            metadata = {
                "source_event": event.event_type,
                "decision": token_context.get("decision"),
                "pool_id": pool_info.get("id") or pool_info.get("pool_id"),
                "pool_address": pool_info.get("address") or pool_info.get("pool_address"),
                "liquidity_sol": liquidity_sol,
                "validation_score": validation_score,
                "pool_validation": pool_validation,
                "confidence_boost": self._safe_float(
                    confirmation_data.get("confidence_boost", 0)
                ),
                "market_stage": confirmation_data.get("market_stage"),
                "confirmation_checks": confirmation_data.get("checks", {}),
            }

            signal = SignalData(
                signal_id=f"SIGNAL-{uuid.uuid4().hex[:12]}",
                signal_type="CONFIRMED",
                mint=mint,
                symbol=symbol,
                score=base_score,
                confidence=confidence,
                risk_level=risk_level,
                reason=confirmation_reason,
                metadata=metadata,
                timestamp=datetime.utcnow(),
            )

            self._persist_signal(
                signal=signal,
                old_state=None,
                new_state="CREATED",
                history_reason="Confirmed signal generated after market confirmation",
                operation_name="signal_generation_confirmed",
                started_at=start_time,
            )

            self.signals_generated += 1
            self.confirmation_signals += 1

            signal_event = Event(
                event_type="SignalGenerated",
                data=signal.to_dict(),
                source="SignalEngine",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(signal_event)
            logger.info(f"SignalGenerated CONFIRMED: {signal.signal_id}")
            return True

        except Exception as e:
            logger.error(f"Error in generate_confirmed_and_emit: {e}")
            return False

    def _persist_signal(
        self,
        signal: SignalData,
        old_state: Optional[str],
        new_state: str,
        history_reason: str,
        operation_name: str,
        started_at: float,
    ) -> None:
        """Persist signal, history and performance metrics."""
        try:
            signal_db_data = {
                "signal_id": signal.signal_id,
                "mint": signal.mint,
                "symbol": signal.symbol,
                "signal_type": signal.signal_type,
                "score": signal.score,
                "confidence": signal.confidence,
                "reason": signal.reason,
            }
            self.store.create_signal(signal_db_data)

            self.store.create_signal_history(
                signal_id=signal.signal_id,
                mint=signal.mint,
                old_state=old_state,
                new_state=new_state,
                reason=history_reason,
            )

            generation_time_ms = (time.time() - started_at) * 1000
            self.store.record_performance_metric(
                operation=operation_name,
                duration_ms=generation_time_ms,
                signal_id=signal.signal_id,
                success=True,
            )

            logger.info(f"Signal persisted to DB: {signal.signal_id}")

        except Exception as db_error:
            logger.error(f"Error persisting signal to DB: {db_error}")
            raise

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Convert values safely to float."""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_stats(self) -> dict:
        """Get signal engine statistics"""
        return {
            "signals_generated": self.signals_generated,
            "early_signals": self.early_signals,
            "confirmation_signals": self.confirmation_signals,
            "abandon_signals": self.abandon_signals,
        }
