"""Main orchestrator that coordinates all Mamut components"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus
from core.token_lock_manager import TokenLockManager
from core.signal_deduper import SignalDeduper
from core.state_manager import StateManager
from storage.sqlite_store import SQLiteStore

logger = setup_logger("Orchestrator")


class Orchestrator:
    """Orchestrates all Mamut components and the full token lifecycle."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        self.store = SQLiteStore(settings)
        self.lock_manager = TokenLockManager()
        self.signal_deduper = SignalDeduper()
        self.state_manager = StateManager(self.store)

        self.pump_listener = None
        self.raydium_listener = None
        self.raydium_pool_validator = None
        self.market_confirmation_engine = None

        self.token_enricher = None
        self.creator_profiler = None
        self.trash_filter = None
        self.score_engine = None
        self.decision_mapper = None

        self.signal_engine = None
        self.signal_formatter = None
        self.alert_dispatcher = None

        self.running = False
        self.start_time: Optional[datetime] = None
        self.tokens_processed = 0

        self.token_context: Dict[str, Dict[str, Any]] = {}
        self.initial_signals: Dict[str, Dict[str, Any]] = {}
        self.pool_validations: Dict[str, Dict[str, Any]] = {}
        self.market_confirmations: Dict[str, Dict[str, Any]] = {}

    async def initialize(self) -> bool:
        """Initialize all components and register event handlers."""
        try:
            logger.info("Initializing Mamut orchestrator...")

            await self.event_bus.start()
            logger.info("Event bus started")

            from discovery.pump_listener import PumpListener
            from validation.raydium_listener import RaydiumListener
            from validation.raydium_pool_validator import RaydiumPoolValidator
            from validation.market_confirmation_engine import MarketConfirmationEngine
            from enrich.token_enricher import TokenEnricher
            from enrich.creator_profiler import CreatorProfiler
            from filters.trash_filter_engine import TrashFilterEngine
            from scoring.score_engine import ScoreEngine
            from scoring.decision_mapper import DecisionMapper
            from signals.signal_engine import SignalEngine
            from signals.signal_formatter import SignalFormatter
            from signals.alert_dispatcher import AlertDispatcher

            self.pump_listener = PumpListener(self.settings)
            self.raydium_listener = RaydiumListener(self.settings)
            self.raydium_pool_validator = RaydiumPoolValidator(self.settings)
            self.market_confirmation_engine = MarketConfirmationEngine(self.settings)

            self.token_enricher = TokenEnricher(self.settings)
            self.creator_profiler = CreatorProfiler(self.store, self.settings)
            self.trash_filter = TrashFilterEngine(self.store, self.settings)
            self.score_engine = ScoreEngine()
            self.decision_mapper = DecisionMapper(self.settings)

            self.signal_engine = SignalEngine(self.store, self.settings)
            self.signal_formatter = SignalFormatter()
            self.alert_dispatcher = AlertDispatcher(self.store, self.settings)

            await self._register_handlers()

            logger.info("All components initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Error initializing orchestrator: {e}")
            return False

    async def _register_handlers(self) -> None:
        self.event_bus.subscribe("TokenDiscovered", self._handle_token_discovered)
        self.event_bus.subscribe("TokenParsed", self._handle_token_parsed)
        self.event_bus.subscribe("TokenEnriched", self._handle_token_enriched)
        self.event_bus.subscribe("CreatorProfiled", self._handle_creator_profiled)
        self.event_bus.subscribe("TokenPassed", self._handle_token_passed)
        self.event_bus.subscribe("TokenRejected", self._handle_token_rejected)
        self.event_bus.subscribe("ScoreCalculated", self._handle_score_calculated)
        self.event_bus.subscribe("DecisionMade", self._handle_decision_made)
        self.event_bus.subscribe("SignalGenerated", self._handle_signal_generated)
        self.event_bus.subscribe("AlertDispatched", self._handle_alert_dispatched)
        self.event_bus.subscribe("PoolFound", self._handle_pool_found)
        self.event_bus.subscribe("PoolSearchTimeout", self._handle_pool_timeout)
        self.event_bus.subscribe("MarketConfirmed", self._handle_market_confirmed)

        logger.info("Event handlers registered successfully")

    async def _handle_token_discovered(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                logger.warning("TokenDiscovered without mint")
                return

            symbol = event.data.get("symbol", "UNKNOWN")

            if not self.lock_manager.lock_token(mint):
                logger.debug(f"Token already being processed: {mint[:8]}...")
                return

            initialized = await self.state_manager.initialize_token(
                mint=mint,
                name=event.data.get("name"),
                symbol=symbol,
            )
            if not initialized:
                self.lock_manager.unlock_token(mint)
                return

            self._merge_token_context(mint, event.data)
            logger.info(f"TokenDiscovered: {symbol} ({mint[:8]}...)")

            if self.token_enricher:
                await self.token_enricher.enrich_and_emit(event)

        except Exception as e:
            logger.error(f"Error handling TokenDiscovered: {e}")

    async def _handle_token_parsed(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(
                mint=mint,
                state="PARSED",
                event="TokenParsed",
                details=event.data,
            )

        except Exception as e:
            logger.error(f"Error handling TokenParsed: {e}")

    async def _handle_token_enriched(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="ENRICHED",
                event="TokenEnriched",
                details=event.data,
            )

            if self.creator_profiler:
                await self.creator_profiler.profile_and_emit(event)

        except Exception as e:
            logger.error(f"Error handling TokenEnriched: {e}")

    async def _handle_creator_profiled(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="PROFILED",
                event="CreatorProfiled",
                details=event.data,
            )

            if self.trash_filter:
                await self.trash_filter.filter_and_emit(event)

        except Exception as e:
            logger.error(f"Error handling CreatorProfiled: {e}")

    async def _handle_token_passed(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="PASSED_FILTERS",
                event="TokenPassed",
                details=event.data,
            )

            if self.score_engine:
                await self.score_engine.score_and_emit(event)

        except Exception as e:
            logger.error(f"Error handling TokenPassed: {e}")

    async def _handle_token_rejected(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            reason = event.data.get("reason", "Unknown")
            self._merge_token_context(mint, event.data)

            await self.state_manager.mark_abandoned(mint, reason)
            await self._stop_raydium_watch(mint)
            self.lock_manager.unlock_token(mint)

        except Exception as e:
            logger.error(f"Error handling TokenRejected: {e}")

    async def _handle_score_calculated(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="SCORED",
                event="ScoreCalculated",
                details=event.data,
            )

            if self.decision_mapper:
                await self.decision_mapper.map_and_emit(event)

        except Exception as e:
            logger.error(f"Error handling ScoreCalculated: {e}")

    async def _handle_decision_made(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            decision = event.data.get("decision", "UNKNOWN")
            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="DECISION_MADE",
                event="DecisionMade",
                details=event.data,
            )

            if decision == "SIGNAL_EARLY":
                if self.signal_engine:
                    await self.signal_engine.generate_early_and_emit(event)
                await self._start_raydium_watch(mint)

            elif decision == "MONITOR":
                await self._start_raydium_watch(mint)

            elif decision in {"REJECT", "IGNORE", "NO_SIGNAL"}:
                self.lock_manager.unlock_token(mint)

        except Exception as e:
            logger.error(f"Error handling DecisionMade: {e}")

    async def _handle_signal_generated(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            signal_type = event.data.get("signal_type", "UNKNOWN")

            score = float(event.data.get("score", event.data.get("final_score", 0)) or 0)

            if self.signal_deduper.is_duplicate(
                mint=mint,
                signal_type=signal_type,
                score=score,
            ):
                logger.debug(f"Duplicate signal skipped for {mint[:8]}... ({signal_type})")
                return

            self._merge_token_context(mint, event.data)

            if signal_type == "EARLY":
                self.initial_signals[mint] = dict(event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="SIGNAL_GENERATED",
                event="SignalGenerated",
                details=event.data,
            )

            if self.alert_dispatcher:
                await self.alert_dispatcher.dispatch_and_emit(event)

        except Exception as e:
            logger.error(f"Error handling SignalGenerated: {e}")

    async def _handle_alert_dispatched(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            signal_type = event.data.get("signal_type", "UNKNOWN")
            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="ALERT_DISPATCHED",
                event="AlertDispatched",
                details=event.data,
            )

            if signal_type == "EARLY":
                await self.state_manager.mark_early_signal_sent(mint)

        except Exception as e:
            logger.error(f"Error handling AlertDispatched: {e}")

    async def _handle_pool_found(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            pool_data = event.data.get("pool", {}) or {}
            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="POOL_FOUND",
                event="PoolFound",
                details=event.data,
            )

            if not self.raydium_pool_validator:
                logger.warning("RaydiumPoolValidator not initialized")
                return

            validation_result = await self.raydium_pool_validator.validate_pool(pool_data)
            self.pool_validations[mint] = validation_result or {}

            if not validation_result or not validation_result.get("is_valid", False):
                await self.state_manager.update_token_state(
                    mint=mint,
                    state="POOL_INVALID",
                    event="PoolValidationFailed",
                    details=validation_result or {"pool": pool_data},
                    reason="Pool validation failed",
                )
                await self._stop_raydium_watch(mint)
                self.lock_manager.unlock_token(mint)
                return

            await self.state_manager.update_token_state(
                mint=mint,
                state="POOL_VALIDATED",
                event="PoolValidated",
                details=validation_result,
            )

            token_context = self.token_context.get(mint, {}).copy()
            token_context.setdefault("mint", mint)
            token_context.setdefault("symbol", self._get_symbol(mint, event.data))

            initial_signal = self.initial_signals.get(mint, {})
            if not initial_signal:
                initial_signal = {
                    "mint": mint,
                    "symbol": token_context.get("symbol", "UNKNOWN"),
                    "score": token_context.get("final_score", 0),
                    "confidence": token_context.get("confidence", 0.0),
                    "decision": token_context.get("decision", "MONITOR"),
                }

            confirmation = await self.market_confirmation_engine.confirm_market(
                token_context,
                initial_signal,
                validation_result,
            )
            self.market_confirmations[mint] = confirmation or {}

            if not confirmation or not confirmation.get("is_confirmed", False):
                self.lock_manager.unlock_token(mint)
                return

            market_event = Event(
                event_type="MarketConfirmed",
                data=confirmation,
                source="Orchestrator",
                timestamp=datetime.utcnow(),
            )
            await self.event_bus.emit(market_event)

        except Exception as e:
            logger.error(f"Error handling PoolFound: {e}")

    async def _handle_pool_timeout(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="POOL_TIMEOUT",
                event="PoolSearchTimeout",
                details=event.data,
                reason="Raydium pool not found before timeout",
            )

            await self._stop_raydium_watch(mint)
            self.lock_manager.unlock_token(mint)

        except Exception as e:
            logger.error(f"Error handling PoolSearchTimeout: {e}")

    async def _handle_market_confirmed(self, event: Event) -> None:
        try:
            mint = event.data.get("mint")
            if not mint:
                return

            self._merge_token_context(mint, event.data)

            await self.state_manager.update_token_state(
                mint=mint,
                state="MARKET_CONFIRMED",
                event="MarketConfirmed",
                details=event.data,
            )

            if self.signal_engine:
                await self.signal_engine.generate_confirmed_and_emit(
                    event=event,
                    token_context=self.token_context.get(mint, {}),
                )

            await self._stop_raydium_watch(mint)
            self.lock_manager.unlock_token(mint)

        except Exception as e:
            logger.error(f"Error handling MarketConfirmed: {e}")

    async def _start_raydium_watch(self, mint: str) -> None:
        try:
            if not self.raydium_listener:
                logger.warning("RaydiumListener not initialized")
                return

            await self.raydium_listener.start_monitoring(
                mint,
                context=self.token_context.get(mint, {}),
            )

            await self.state_manager.update_token_state(
                mint=mint,
                state="RAYDIUM_WATCH_STARTED",
                event="RaydiumWatchStarted",
                details=self.token_context.get(mint, {"mint": mint}),
            )

        except Exception as e:
            logger.error(f"Error starting Raydium watch for {mint[:8]}...: {e}")

    async def _stop_raydium_watch(self, mint: str) -> None:
        try:
            if self.raydium_listener:
                await self.raydium_listener.stop_monitoring(mint)
        except Exception as e:
            logger.error(f"Error stopping Raydium watch for {mint[:8]}...: {e}")

    def _merge_token_context(self, mint: str, new_data: Dict[str, Any]) -> None:
        if mint not in self.token_context:
            self.token_context[mint] = {}
        self.token_context[mint].update(new_data)

    def _get_symbol(self, mint: str, fallback_data: Optional[Dict[str, Any]] = None) -> str:
        if fallback_data and fallback_data.get("symbol"):
            return fallback_data["symbol"]
        return self.token_context.get(mint, {}).get("symbol", "UNKNOWN")

    async def run(self) -> None:
        try:
            self.running = True
            self.start_time = datetime.utcnow()

            tasks = [
                asyncio.create_task(self.pump_listener.start()),
                asyncio.create_task(self.raydium_listener.monitor_pools()),
                asyncio.create_task(self._process_tokens()),
            ]

            await asyncio.gather(*tasks)

        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled")
        except Exception as e:
            logger.error(f"Error in orchestrator run: {e}")
        finally:
            await self.cleanup()

    async def _process_tokens(self) -> None:
        while self.running:
            try:
                self.lock_manager.cleanup_expired_locks()
                self.signal_deduper.cleanup_old_signals()
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in token processor: {e}")

    def get_stats(self) -> dict:
        return {
            "running": self.running,
            "uptime_seconds": (
                (datetime.utcnow() - self.start_time).total_seconds()
                if self.start_time
                else 0
            ),
            "tokens_processed": self.tokens_processed,
            "event_bus": self.event_bus.get_listener_count(),
            "lock_manager": self.lock_manager.get_stats(),
            "signal_deduper": self.signal_deduper.get_stats(),
            "storage": self.state_manager.get_stats(),
            "token_context_cache": len(self.token_context),
            "cached_initial_signals": len(self.initial_signals),
            "cached_pool_validations": len(self.pool_validations),
            "cached_market_confirmations": len(self.market_confirmations),
        }

    async def cleanup(self) -> None:
        try:
            logger.info("Cleaning up resources...")

            if self.token_enricher:
                await self.token_enricher.close()

            if self.raydium_listener:
                await self.raydium_listener.close()

            if self.alert_dispatcher:
                await self.alert_dispatcher.close()

            await self.event_bus.stop()
            logger.info("Cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def shutdown(self) -> None:
        logger.info("Shutdown requested")
        self.running = False
        await self.cleanup()
