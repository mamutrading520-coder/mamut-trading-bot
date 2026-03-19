"""Generate trading signals from token analysis"""
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from config.settings import Settings
from storage.sqlite_store import SQLiteStore
import json
import uuid

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

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.store = SQLiteStore(settings)
        self.score_threshold = settings.score_threshold_high_potential

        self.signals_generated = 0
        self.early_signals = 0
        self.confirmation_signals = 0
        self.abandon_signals = 0

    async def generate_early_and_emit(self, event: Event) -> bool:
        """Generate signal and emit to event bus"""
        try:
            start_time = datetime.utcnow()
            decision_str = event.data.get("decision", "UNKNOWN")
            decision_data = event.data

            # Create signal
            signal = SignalData(
                signal_id=f"SIGNAL-{uuid.uuid4().hex[:12]}",
                signal_type="EARLY",
                mint=decision_data.get("mint"),
                symbol=decision_data.get("symbol", "UNKNOWN"),
                score=decision_data.get("final_score", 0),
                confidence=decision_data.get("confidence", 0.5),
                risk_level=decision_str,
                reason=f"Decision: {decision_str}",
                metadata={"decision": decision_str},
                timestamp=start_time,
            )

            self.signals_generated += 1
            logger.info(f"Generated signal: {signal.signal_id} - {decision_str}")

            # Persist signal to database
            try:
                signal_db_data = {
                    "signal_id": signal.signal_id,
                    "mint": signal.mint,
                    "symbol": signal.symbol,
                    "signal_type": signal.signal_type,
                    "score": signal.score,
                    "confidence": signal.confidence,
                    "reason": signal.reason,
                    "metadata_json": json.dumps(signal.metadata),
                }
                self.store.create_signal(signal_db_data)
                logger.info(f"✓ Signal saved to DB: {signal.signal_id}")

                self.store.create_signal_history(
                    signal_id=signal.signal_id,
                    mint=signal.mint,
                    old_state=None,
                    new_state="CREATED",
                    reason=signal.reason,
                )

                duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                self.store.record_performance_metric(
                    operation="signal_generation",
                    duration_ms=duration_ms,
                    mint=signal.mint,
                    signal_id=signal.signal_id,
                    success=True,
                )
            except Exception as db_err:
                logger.error(f"Error persisting signal to DB: {db_err}")

            # Emit signal
            signal_event = Event(
                event_type="SignalGenerated",
                data=signal.to_dict(),
                source="SignalEngine",
                timestamp=datetime.utcnow()
            )

            await self.event_bus.emit(signal_event)
            logger.info(f"✓ SignalGenerated: {signal.signal_id}")

            return True

        except Exception as e:
            logger.error(f"Error in generate_early_and_emit: {e}")
            return False

    def get_stats(self) -> dict:
        """Get signal engine statistics"""
        return {
            "signals_generated": self.signals_generated,
            "early_signals": self.early_signals,
            "confirmation_signals": self.confirmation_signals,
            "abandon_signals": self.abandon_signals,
        }