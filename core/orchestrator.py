"""Main orchestrator that coordinates all Mamut components"""

import asyncio
from datetime import datetime

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus
from core.token_lock_manager import TokenLockManager
from core.signal_deduper import SignalDeduper
from core.state_manager import StateManager
from storage.sqlite_store import SQLiteStore

logger = setup_logger("Orchestrator")


class Orchestrator:
    """Orchestrates all Mamut components"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()

        # Core managers
        self.store = SQLiteStore(settings)
        self.lock_manager = TokenLockManager()
        self.signal_deduper = SignalDeduper()
        self.state_manager = StateManager(self.store)

        # Component placeholders
        self.pump_listener = None
        self.token_enricher = None
        self.creator_profiler = None
        self.trash_filter = None
        self.score_engine = None
        self.decision_mapper = None
        self.signal_engine = None
        self.signal_formatter = None
        self.alert_dispatcher = None
        self.raydium_listener = None

        self.running = False
        self.start_time = None
        self.tokens_processed = 0

    async def initialize(self) -> bool:
        """Initialize all components"""
        try:
            logger.info("Initializing Mamut orchestrator...")

            await self.event_bus.start()
            logger.info("Event bus started")

            from discovery.pump_listener import PumpListener
            from validation.raydium_listener import RaydiumListener
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
            self.token_enricher = TokenEnricher(self.settings)
            self.creator_profiler = CreatorProfiler(self.store, self.settings)
            self.trash_filter = TrashFilterEngine(self.store, self.settings)
            self.score_engine = ScoreEngine()
            self.decision_mapper = DecisionMapper(self.settings)
            self.signal_engine = SignalEngine(self.store, self.settings)
            self.signal_formatter = SignalFormatter()
            self.alert_dispatcher = AlertDispatcher(self.store, self.settings)

            logger.info("All components initialized")

            await self._register_handlers()
            logger.info("Event handlers registered")
            return True

        except Exception as e:
            logger.error(f"Error initializing orchestrator: {e}")
            return False

    async def _register_handlers(self) -> None:
        """Register event handlers"""
        try:
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

        except Exception as e:
            logger.error(f"Error registering handlers: {e}")

    async def _handle_token_discovered(self, event: Event) -> None:
        """Handle TokenDiscovered event - START OF PIPELINE"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")

            if not self.lock_manager.lock_token(mint):
                logger.debug(f"Token already being processed: {mint[:8]}...")
                return

            await self.state_manager.initialize_token(
                mint,
                event.data.get("name"),
                symbol,
            )

            logger.info(f"TokenDiscovered: {symbol} ({mint[:8]}...)")

            if self.token_enricher:
                await self.token_enricher.enrich_and_emit(event)
            else:
                logger.warning("TokenEnricher not initialized")

        except Exception as e:
            logger.error(f"Error handling TokenDiscovered: {e}")

    async def _handle_token_parsed(self, event: Event) -> None:
        """Handle TokenParsed event"""
        try:
            mint = event.data.get("mint")
            await self.state_manager.update_token_state(mint, "PARSED")
            logger.debug(f"Token parsed: {mint[:8]}...")
        except Exception as e:
            logger.error(f"Error handling TokenParsed: {e}")

    async def _handle_token_enriched(self, event: Event) -> None:
        """Handle TokenEnriched event - TRIGGER PROFILING"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            await self.state_manager.update_token_state(mint, "ENRICHED")
            logger.info(f"TokenEnriched: {symbol}")

            if self.creator_profiler:
                await self.creator_profiler.profile_and_emit(event)
            else:
                logger.warning("CreatorProfiler not initialized")

        except Exception as e:
            logger.error(f"Error handling TokenEnriched: {e}")

    async def _handle_creator_profiled(self, event: Event) -> None:
        """Handle CreatorProfiled event - TRIGGER FILTERING"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            await self.state_manager.update_token_state(mint, "PROFILED")
            logger.info(f"CreatorProfiled: {symbol}")

            if self.trash_filter:
                await self.trash_filter.filter_and_emit(event)
            else:
                logger.warning("TrashFilter not initialized")

        except Exception as e:
            logger.error(f"Error handling CreatorProfiled: {e}")

    async def _handle_token_passed(self, event: Event) -> None:
        """Handle TokenPassed event (passed filters) - TRIGGER SCORING"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            await self.state_manager.update_token_state(mint, "PASSED_FILTERS")
            logger.info(f"TokenPassed Filters: {symbol}")

            if self.score_engine:
                await self.score_engine.score_and_emit(event)
            else:
                logger.warning("ScoreEngine not initialized")

        except Exception as e:
            logger.error(f"Error handling TokenPassed: {e}")

    async def _handle_token_rejected(self, event: Event) -> None:
        """Handle TokenRejected event - CLEANUP"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            reason = event.data.get("reason", "Unknown")

            logger.warning(f"TokenRejected: {symbol} - {reason}")
            await self.state_manager.mark_abandoned(mint, reason)
            self.lock_manager.release_token(mint)

        except Exception as e:
            logger.error(f"Error handling TokenRejected: {e}")

    async def _handle_score_calculated(self, event: Event) -> None:
        """Handle ScoreCalculated event - TRIGGER DECISION"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            score = event.data.get("final_score", 0)

            logger.info(f"ScoreCalculated: {symbol} = {score:.2f}")
            await self.state_manager.update_token_state(mint, "SCORED")

            if self.decision_mapper:
                await self.decision_mapper.map_and_emit(event)
            else:
                logger.warning("DecisionMapper not initialized")

        except Exception as e:
            logger.error(f"Error handling ScoreCalculated: {e}")

    async def _handle_decision_made(self, event: Event) -> None:
        """Handle DecisionMade event - TRIGGER SIGNAL GENERATION"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            decision = event.data.get("decision", "UNKNOWN")

            logger.info(f"DecisionMade: {symbol} = {decision}")
            await self.state_manager.update_token_state(mint, "DECISION_MADE")

            if decision in ["SIGNAL_EARLY", "MONITOR"]:
                if self.signal_engine:
                    await self.signal_engine.generate_early_and_emit(event)
                else:
                    logger.warning("SignalEngine not initialized")

        except Exception as e:
            logger.error(f"Error handling DecisionMade: {e}")

    async def _handle_signal_generated(self, event: Event) -> None:
        """Handle SignalGenerated event - TRIGGER ALERT"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            signal_type = event.data.get("signal_type", "UNKNOWN")

            logger.info(f"SignalGenerated: {symbol} ({signal_type})")
            await self.state_manager.update_token_state(mint, "SIGNAL_GENERATED")

            if self.alert_dispatcher:
                await self.alert_dispatcher.dispatch_and_emit(event)
            else:
                logger.warning("AlertDispatcher not initialized")

        except Exception as e:
            logger.error(f"Error handling SignalGenerated: {e}")

    async def _handle_alert_dispatched(self, event: Event) -> None:
        """Handle AlertDispatched event"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            logger.info(f"AlertDispatched: {symbol}")
            await self.state_manager.mark_early_signal_sent(mint)
        except Exception as e:
            logger.error(f"Error handling AlertDispatched: {e}")

    async def _handle_pool_found(self, event: Event) -> None:
        """Handle PoolFound event"""
        try:
            symbol = event.data.get("symbol")
            logger.info(f"PoolFound: {symbol}")
        except Exception as e:
            logger.error(f"Error handling PoolFound: {e}")

    async def _handle_pool_timeout(self, event: Event) -> None:
        """Handle PoolSearchTimeout event"""
        try:
            mint = event.data.get("mint")
            symbol = event.data.get("symbol")
            logger.warning(f"PoolSearchTimeout: {symbol}")
            self.lock_manager.release_token(mint)
        except Exception as e:
            logger.error(f"Error handling PoolSearchTimeout: {e}")

    async def _handle_market_confirmed(self, event: Event) -> None:
        """Handle MarketConfirmed event"""
        try:
            symbol = event.data.get("symbol")
            logger.info(f"MarketConfirmed: {symbol}")
        except Exception as e:
            logger.error(f"Error handling MarketConfirmed: {e}")

    async def run(self) -> None:
        """Run the Mamut engine"""
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
        """Background processor for tokens"""
        while self.running:
            try:
                self.lock_manager.cleanup_expired_locks()
                self.signal_deduper.cleanup_old_signals()
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in token processor: {e}")

    def get_stats(self) -> dict:
        """Get comprehensive system statistics"""
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
        }

    async def cleanup(self) -> None:
        """Clean up all resources"""
        try:
            logger.info("Cleaning up resources...")

            if self.token_enricher:
                await self.token_enricher.close()
            if self.alert_dispatcher:
                await self.alert_dispatcher.close()

            await self.event_bus.stop()
            logger.info("Cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    async def shutdown(self) -> None:
        """Shutdown the engine"""
        logger.info("Shutdown requested")
        self.running = False
        await self.cleanup()
