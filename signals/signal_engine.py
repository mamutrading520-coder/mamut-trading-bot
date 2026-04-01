"""Generate trading signals from token analysis"""
from __future__ import annotations

import json
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

    async def generate_early_and_emit(
        self,
        event: Event,
        token_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        start_time = time.time()
        try:
            decision_data = event.data or {}
            token_context = token_context or {}
            merged_context = {**token_context, **decision_data}

            mint = merged_context.get("mint")
            if not mint:
                logger.error("generate_early_and_emit called without mint")
                return False

            decision_str = merged_context.get("decision", "UNKNOWN")
            classification = merged_context.get("classification", decision_str)

            metadata = self._build_common_metadata(
                source_data=merged_context,
                token_context=token_context,
            )
            metadata.update(
                {
                    "source_event": event.event_type,
                    "signal_stage": "EARLY",
                    "decision": decision_str,
                    "classification": classification,
                }
            )

            signal = SignalData(
                signal_id=f"SIGNAL-{uuid.uuid4().hex[:12]}",
                signal_type="EARLY",
                mint=mint,
                symbol=merged_context.get("symbol", "UNKNOWN"),
                score=self._safe_float(
                    merged_context.get("final_score", merged_context.get("score", 0))
                ),
                confidence=self._safe_float(merged_context.get("confidence", 0.5), 0.5),
                risk_level=merged_context.get("aggregate_risk_level", "UNKNOWN"),
                reason=merged_context.get("reasoning")
                or f"Early signal classified as {classification}",
                metadata=metadata,
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
        start_time = time.time()
        try:
            confirmation_data = event.data or {}
            token_context = token_context or {}
            merged_context = {**token_context, **confirmation_data}

            mint = merged_context.get("mint")
            symbol = merged_context.get("symbol", "UNKNOWN")

            if not mint:
                logger.error("generate_confirmed_and_emit called without mint")
                return False

            base_score = self._safe_float(
                merged_context.get("score", merged_context.get("final_score", 0))
            )
            confidence = self._safe_float(
                merged_context.get("new_confidence", merged_context.get("confidence", 0.5)),
                0.5,
            )

            pool_validation = confirmation_data.get("pool_validation", {}) or {}
            pool_info = confirmation_data.get("pool", {}) or {}

            validation_score = self._safe_float(pool_validation.get("validation_score", 0))
            liquidity_sol = self._safe_float(
                pool_validation.get("liquidity_sol", pool_info.get("liquidity_sol", 0))
            )

            metadata = self._build_common_metadata(
                source_data=merged_context,
                token_context=token_context,
            )
            metadata.update(
                {
                    "source_event": event.event_type,
                    "signal_stage": "CONFIRMED",
                    "pool_id": pool_info.get("id") or pool_info.get("pool_id"),
                    "pool_address": pool_info.get("address")
                    or pool_info.get("pool_address")
                    or pool_validation.get("pool_address"),
                    "liquidity_sol": liquidity_sol,
                    "validation_score": validation_score,
                    "pool_validation": pool_validation,
                    "confidence_boost": self._safe_float(
                        confirmation_data.get("confidence_boost", 0)
                    ),
                    "market_stage": confirmation_data.get("market_stage"),
                    "confirmation_checks": confirmation_data.get("checks", {}),
                    "confirmation_reasons": list(confirmation_data.get("reasons", []) or []),
                }
            )

            signal = SignalData(
                signal_id=f"SIGNAL-{uuid.uuid4().hex[:12]}",
                signal_type="CONFIRMED",
                mint=mint,
                symbol=symbol,
                score=base_score,
                confidence=confidence,
                risk_level=merged_context.get("aggregate_risk_level", "UNKNOWN"),
                reason=confirmation_data.get(
                    "reason",
                    "Market confirmed after Raydium pool validation",
                ),
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

    def _build_common_metadata(
        self,
        source_data: Dict[str, Any],
        token_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a rich signal payload usable for console output and manual follow-up."""
        token_context = token_context or {}
        merged = {**token_context, **source_data}
        score_breakdown = merged.get("score_breakdown", {}) or {}

        component_scores = {
            "aggregate_risk": self._safe_float(merged.get("aggregate_risk_score", 0)),
            "authority_risk": self._safe_float(merged.get("authority_risk", 0)),
            "creator_risk": self._safe_float(merged.get("creator_risk", 0)),
            "concentration_risk": self._safe_float(merged.get("concentration_risk", 0)),
            "metadata_risk": self._safe_float(merged.get("metadata_risk", 0)),
            "honeypot_risk": self._safe_float(merged.get("honeypot_risk", 0)),
            "wallet_cluster_risk": self._safe_float(merged.get("wallet_cluster_risk", 0)),
            "metadata_score": self._safe_float(
                merged.get("metadata_score", score_breakdown.get("metadata_score", 0))
            ),
        }

        return {
            "contract_address": merged.get("mint"),
            "token_name": merged.get("name") or merged.get("symbol") or "UNKNOWN",
            "creator": merged.get("creator") or "",
            "creator_resolved": bool(merged.get("creator_resolved", False)),
            "initial_sol": self._safe_float(merged.get("initial_sol", 0)),
            "initial_buy": int(merged.get("initial_buy", 0) or 0),
            "market_cap_sol": self._safe_float(merged.get("market_cap_sol", 0)),
            "aggregate_risk_score": self._safe_float(merged.get("aggregate_risk_score", 0)),
            "aggregate_risk_level": merged.get("aggregate_risk_level"),
            "metadata_score": component_scores["metadata_score"],
            "social_count": int(merged.get("social_count", 0) or 0),
            "holder_count": int(merged.get("holder_count", 0) or 0),
            "creator_hold_percentage": self._safe_float(
                merged.get("creator_hold_percentage", 0)
            ),
            "top_holder_percentage": self._safe_float(
                merged.get("top_holder_percentage", 0)
            ),
            "top_5_holders_percentage": self._safe_float(
                merged.get("top_5_holders_percentage", 0)
            ),
            "top_10_holders_percentage": self._safe_float(
                merged.get("top_10_holders_percentage", 0)
            ),
            "mint_authority": merged.get("mint_authority"),
            "freeze_authority": merged.get("freeze_authority"),
            "owner_renounced": bool(merged.get("owner_renounced", False)),
            "uri": merged.get("uri"),
            "description": merged.get("description"),
            "reasoning": merged.get("reasoning"),
            "warnings": list(merged.get("warnings", []) or []),
            "score_notes": list(score_breakdown.get("notes", []) or []),
            "component_scores": component_scores,
        }

    def _persist_signal(
        self,
        signal: SignalData,
        old_state: Optional[str] = None,
        new_state: str = "CREATED",
        history_reason: Optional[str] = None,
        operation_name: str = "signal_persistence",
        started_at: Optional[float] = None,
    ) -> None:
        if not self.store:
            return

        started_at = started_at or time.time()

        try:
            signal_db_data = {
                "signal_id": signal.signal_id,
                "mint": signal.mint,
                "symbol": signal.symbol,
                "signal_type": signal.signal_type,
                "score": signal.score,
                "confidence": signal.confidence,
                "reason": signal.reason,
                "metadata": signal.metadata or {},
                "processing_time_ms": (time.time() - started_at) * 1000,
            }

            self.store.create_structured_signal(signal_db_data)

            details_json = None
            try:
                details_json = json.dumps(signal.metadata or {}, ensure_ascii=False, default=str)
            except Exception as json_error:
                logger.warning(
                    f"Could not serialize signal history details for {signal.signal_id}: {json_error}"
                )

            self.store.create_signal_history(
                signal_id=signal.signal_id,
                mint=signal.mint,
                old_state=old_state,
                new_state=new_state,
                reason=history_reason,
                details_json=details_json,
            )

            self.store.create_performance_metric(
                operation=operation_name,
                mint=signal.mint,
                signal_id=signal.signal_id,
                duration_ms=(time.time() - started_at) * 1000,
                success=True,
                metadata={
                    "signal_type": signal.signal_type,
                    "score": signal.score,
                    "risk_level": signal.risk_level,
                },
            )

        except Exception as e:
            logger.error(f"Failed to persist signal {signal.signal_id}: {e}")
            try:
                self.store.create_performance_metric(
                    operation=operation_name,
                    mint=signal.mint,
                    signal_id=signal.signal_id,
                    duration_ms=(time.time() - started_at) * 1000,
                    success=False,
                    error_message=str(e),
                    metadata={
                        "signal_type": signal.signal_type,
                        "risk_level": signal.risk_level,
                    },
                )
            except Exception as perf_error:
                logger.error(f"Failed to persist performance metric: {perf_error}")

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_stats(self) -> dict:
        return {
            "signals_generated": self.signals_generated,
            "early_signals": self.early_signals,
            "confirmation_signals": self.confirmation_signals,
            "abandon_signals": self.abandon_signals,
        }
