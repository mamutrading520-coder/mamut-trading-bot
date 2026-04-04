"""Main orchestrator that coordinates all Mamut components"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus
from core.token_lock_manager import TokenLockManager
from core.signal_deduper import SignalDeduper
from core.discovery_deduper import DiscoveryDeduper
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
        self.discovery_deduper = DiscoveryDeduper(settings)
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
        self.initialized = False
        self.start_time: Optional[datetime] = None
        self.tokens_processed = 0

        self.token_context: Dict[str, Dict[str, Any]] = {}
        self.initial_signals: Dict[str, Dict[str, Any]] = {}
        self.pool_validations: Dict[str, Dict[str, Any]] = {}
        self.market_confirmations: Dict[str, Dict[str, Any]] = {}

        self._background_tasks: Dict[str, asyncio.Task] = {}
        self._cleanup_lock = asyncio.Lock()
        self._cleanup_done = False
        self._shutting_down = False

    async def initialize(self) -> bool:
        if self.initialized:
            logger.info("Orchestrator already initialized")
            return True

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

            self.initialized = True
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

    def _safe_store_call(self, description: str, store_call: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        try:
            store_call(*args, **kwargs)
        except Exception as e:
            logger.error(f"Persistence error during {description}: {e}")

    def _record_pipeline_metric(self, operation: str, mint: Optional[str] = None, success: bool = True, error_message: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        self._safe_store_call(
            f"pipeline metric {operation}",
            self.store.create_performance_metric,
            operation=operation,
            mint=mint,
            duration_ms=0.0,
            success=success,
            error_message=error_message,
            metadata=metadata or {},
        )

    def _get_creator_identity(self, mint: str, event_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        creator = None
        if event_data:
            creator = event_data.get("creator")
        if not creator:
            creator = self.token_context.get(mint, {}).get("creator")
        if not creator or not isinstance(creator, str):
            return None
        normalized = creator.strip()
        if normalized.lower() in {"", "unknown"}:
            return None
        return normalized

    def _record_creator_outcome(self, mint: str, outcome: str, score: Optional[float] = None, event_data: Optional[Dict[str, Any]] = None) -> None:
        creator = self._get_creator_identity(mint, event_data)
        if not creator:
            return

        try:
            profile = self.store.get_creator_profile(creator)
            current_success = int(getattr(profile, "successful_tokens", 0) or 0) if profile else 0
            current_failed = int(getattr(profile, "failed_tokens", 0) or 0) if profile else 0
            current_total = int(getattr(profile, "total_tokens", 0) or 0) if profile else 0
            current_avg = float(getattr(profile, "average_score", 0.0) or 0.0) if profile else 0.0

            updates: Dict[str, Any] = {
                "last_token_date": datetime.utcnow(),
                "total_tokens": max(current_total, current_success + current_failed),
            }

            if profile is None:
                updates["first_token_date"] = datetime.utcnow()
                updates["total_tokens"] = max(1, updates["total_tokens"])

            if outcome == "success":
                new_success = current_success + 1
                updates["successful_tokens"] = new_success
                if score is not None:
                    updates["average_score"] = round(
                        ((current_avg * current_success) + float(score)) / new_success,
                        2,
                    )
            elif outcome == "failed":
                updates["failed_tokens"] = current_failed + 1
            else:
                return

            self.store.update_creator_profile(creator, updates)
        except Exception as e:
            logger.error(f"Error recording creator outcome for {mint[:8]}...: {e}")

    def _should_accept_new_work(self) -> bool:
        return self.running and not self._shutting_down and not self._cleanup_done

    def _clear_token_runtime(self, mint: str, keep_initial_signal: bool = False) -> None:
        cleared = []
        if self.token_context.pop(mint, None) is not None:
            cleared.append("token_context")
        if self.pool_validations.pop(mint, None) is not None:
            cleared.append("pool_validations")
        if self.market_confirmations.pop(mint, None) is not None:
            cleared.append("market_confirmations")
        if not keep_initial_signal and self.initial_signals.pop(mint, None) is not None:
            cleared.append("initial_signals")
        if cleared:
            logger.debug(f"Cleared runtime cache for {mint[:8]}...: {', '.join(cleared)}")

    async def _finalize_token_runtime(self, mint: str, stop_raydium: bool = False, keep_initial_signal: bool = False, release_reason: str = "terminal", evict_state: bool = False) -> None:
        if stop_raydium:
            await self._stop_raydium_watch(mint)
        self.lock_manager.unlock_token(mint, reason=release_reason)
        self._clear_token_runtime(mint, keep_initial_signal=keep_initial_signal)
        if evict_state:
            self.state_manager.evict_token_state(mint)

    async def _handle_stage_failure(self, stage: str, mint: Optional[str], error: Exception, details: Optional[Dict[str, Any]] = None, stop_raydium: bool = False, keep_initial_signal: bool = False) -> None:
        error_message = str(error)
        if mint:
            logger.error(f"Error handling {stage} for {mint[:8]}...: {error_message}")
        else:
            logger.error(f"Error handling {stage}: {error_message}")
        self._record_pipeline_metric(operation=f"stage_error_{stage.lower()}", mint=mint, success=False, error_message=error_message, metadata={"stage": stage, "has_details": bool(details)})
        if not mint:
            return
        await self.state_manager.mark_failed(mint=mint, stage=stage, reason=error_message, details=details)
        await self._finalize_token_runtime(mint=mint, stop_raydium=stop_raydium, keep_initial_signal=keep_initial_signal, release_reason=f"stage_failed:{stage}", evict_state=True)

    async def _handle_token_discovered(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint:
                logger.warning("TokenDiscovered without mint")
                return
            if not self._should_accept_new_work():
                logger.debug(f"Skipping TokenDiscovered during shutdown: {mint[:8]}...")
                return

            symbol = event.data.get("symbol", "UNKNOWN")
            is_duplicate, duplicate_reason = self.discovery_deduper.check_and_register(event.data or {})
            if is_duplicate:
                logger.info(
                    f"Discovery duplicate skipped: {symbol} ({mint[:8]}...) | reason={duplicate_reason}"
                )
                self._record_pipeline_metric(
                    operation="token_discovered_deduped",
                    mint=mint,
                    success=True,
                    metadata={
                        "reason": duplicate_reason,
                        "symbol": symbol,
                        "creator": event.data.get("creator"),
                    },
                )
                return

            if not self.lock_manager.lock_token(mint):
                logger.debug(f"Token already being processed: {mint[:8]}...")
                return

            initialized = await self.state_manager.initialize_token(mint=mint, name=event.data.get("name"), symbol=symbol)
            if not initialized:
                self.lock_manager.unlock_token(mint, reason="initialize_failed")
                return

            self.tokens_processed += 1
            self._safe_store_call(f"base token persistence for {mint[:8]}...", self.store.upsert_token_base, event.data)
            self._merge_token_context(mint, event.data)
            logger.info(f"TokenDiscovered: {symbol} ({mint[:8]}...)")
            if self.token_enricher and self._should_accept_new_work():
                await self.token_enricher.enrich_and_emit(event)
        except Exception as e:
            await self._handle_stage_failure("TokenDiscovered", mint, e, details=event.data, stop_raydium=False)

    async def _handle_token_parsed(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="PARSED", event="TokenParsed", details=event.data)
        except Exception as e:
            await self._handle_stage_failure("TokenParsed", mint, e, details=event.data)

    async def _handle_token_enriched(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="ENRICHED", event="TokenEnriched", details=event.data)
            self._safe_store_call(f"enrichment persistence for {mint[:8]}...", self.store.update_token_enrichment, mint, event.data)
            if self.creator_profiler and self._should_accept_new_work():
                await self.creator_profiler.profile_and_emit(event)
        except Exception as e:
            await self._handle_stage_failure("TokenEnriched", mint, e, details=event.data)

    async def _handle_creator_profiled(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="PROFILED", event="CreatorProfiled", details=event.data)
            if self.trash_filter and self._should_accept_new_work():
                await self.trash_filter.filter_and_emit(event)
        except Exception as e:
            await self._handle_stage_failure("CreatorProfiled", mint, e, details=event.data)

    async def _handle_token_passed(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="PASSED_FILTERS", event="TokenPassed", details=event.data)
            self._safe_store_call(f"filter-pass persistence for {mint[:8]}...", self.store.update_token_filter_result, mint, {**event.data, "passed_filters": True})
            if self.score_engine and self._should_accept_new_work():
                await self.score_engine.score_and_emit(event)
        except Exception as e:
            await self._handle_stage_failure("TokenPassed", mint, e, details=event.data)

    async def _handle_token_rejected(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint:
                return
            reason = event.data.get("reason", "Unknown")
            self._merge_token_context(mint, event.data)
            self._safe_store_call(f"filter-reject persistence for {mint[:8]}...", self.store.update_token_filter_result, mint, {**event.data, "passed_filters": False})
            self._record_creator_outcome(mint=mint, outcome="failed", event_data=event.data)
            await self.state_manager.mark_abandoned(mint, reason)
            self._record_pipeline_metric(operation="token_rejected", mint=mint, success=True, metadata={"reason": reason})
            await self._finalize_token_runtime(mint=mint, stop_raydium=True, release_reason="rejected", evict_state=True)
        except Exception as e:
            await self._handle_stage_failure("TokenRejected", mint, e, details=event.data, stop_raydium=True)

    async def _handle_score_calculated(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="SCORED", event="ScoreCalculated", details=event.data)
            self._safe_store_call(f"token scoring summary persistence for {mint[:8]}...", self.store.update_token_scoring, mint, event.data)
            self._safe_store_call(f"token score analysis persistence for {mint[:8]}...", self.store.record_score_analysis, mint, event.data)
            if self.decision_mapper and self._should_accept_new_work():
                await self.decision_mapper.map_and_emit(event)
        except Exception as e:
            await self._handle_stage_failure("ScoreCalculated", mint, e, details=event.data)

    async def _handle_decision_made(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint:
                return
            decision = event.data.get("decision", "UNKNOWN")
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="DECISION_MADE", event="DecisionMade", details=event.data)
            if self._shutting_down:
                return
            if decision == "SIGNAL_EARLY":
                if self.signal_engine:
                    await self.signal_engine.generate_early_and_emit(event=event, token_context=self.token_context.get(mint, {}))
                await self._start_raydium_watch(mint)
            elif decision == "MONITOR":
                await self._start_raydium_watch(mint)
            elif decision in {"REJECT", "IGNORE", "NO_SIGNAL"}:
                await self._finalize_token_runtime(mint=mint, stop_raydium=False, release_reason=f"decision:{decision.lower()}", evict_state=True)
        except Exception as e:
            await self._handle_stage_failure("DecisionMade", mint, e, details=event.data, stop_raydium=False, keep_initial_signal=True)

    async def _handle_signal_generated(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint:
                return
            signal_type = event.data.get("signal_type", "UNKNOWN")
            score = float(event.data.get("score", event.data.get("final_score", 0)) or 0)
            if self.signal_deduper.is_duplicate(mint=mint, signal_type=signal_type, score=score):
                logger.debug(f"Duplicate signal skipped for {mint[:8]}... ({signal_type})")
                return
            self._merge_token_context(mint, event.data)
            if signal_type == "EARLY":
                self.initial_signals[mint] = dict(event.data)
            await self.state_manager.update_token_state(mint=mint, state="SIGNAL_GENERATED", event="SignalGenerated", details=event.data)
            self._record_pipeline_metric(operation="signal_generated", mint=mint, success=True, metadata={"signal_type": signal_type, "score": event.data.get("score")})
            if self.alert_dispatcher and not self._shutting_down:
                await self.alert_dispatcher.dispatch_and_emit(event)
        except Exception as e:
            logger.error(f"Error handling SignalGenerated: {e}")
            self._record_pipeline_metric(operation="signal_generated", mint=mint, success=False, error_message=str(e), metadata={"stage": "SignalGenerated"})

    async def _handle_alert_dispatched(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint:
                return
            signal_type = event.data.get("signal_type", "UNKNOWN")
            dispatch_success = bool(event.data.get("success", False))
            self._merge_token_context(mint, event.data)
            self._record_pipeline_metric(operation="alert_dispatched", mint=mint, success=dispatch_success, error_message=None if dispatch_success else "dispatch_failed", metadata={"signal_type": signal_type, "success": dispatch_success})
            if not dispatch_success:
                logger.warning(f"Alert dispatch failed for {mint[:8]}... ({signal_type})")
                return
            await self.state_manager.update_token_state(mint=mint, state="ALERT_DISPATCHED", event="AlertDispatched", details=event.data)
            if signal_type == "EARLY":
                await self.state_manager.mark_early_signal_sent(mint)
                self._record_creator_outcome(
                    mint=mint,
                    outcome="success",
                    score=event.data.get("score"),
                    event_data=event.data,
                )
            elif signal_type == "CONFIRMED":
                await self._finalize_token_runtime(mint=mint, stop_raydium=False, release_reason="confirmed_dispatched", evict_state=True)
        except Exception as e:
            logger.error(f"Error handling AlertDispatched: {e}")
            self._record_pipeline_metric(operation="alert_dispatched", mint=mint, success=False, error_message=str(e), metadata={"stage": "AlertDispatched"})

    async def _handle_pool_found(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            pool_data = event.data.get("pool", {}) or {}
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="POOL_FOUND", event="PoolFound", details=event.data)
            self._safe_store_call(f"raydium pool-found persistence for {mint[:8]}...", self.store.update_token_raydium_status, mint, event.data)
            if not self.raydium_pool_validator:
                logger.warning("RaydiumPoolValidator not initialized")
                return
            validation_result = await self.raydium_pool_validator.validate_pool(pool_data)
            self.pool_validations[mint] = validation_result or {}
            self._safe_store_call(f"raydium validation persistence for {mint[:8]}...", self.store.update_token_raydium_status, mint, {**event.data, **(validation_result or {}), "pool": pool_data, "pool_validation": validation_result or {}})
            if not validation_result or not validation_result.get("is_valid", False):
                await self.state_manager.update_token_state(mint=mint, state="POOL_INVALID", event="PoolValidationFailed", details=validation_result or {"pool": pool_data}, reason="Pool validation failed")
                self._record_pipeline_metric(operation="pool_invalid", mint=mint, success=True, metadata={"has_validation_result": bool(validation_result)})
                await self._finalize_token_runtime(mint=mint, stop_raydium=True, release_reason="pool_invalid", evict_state=True)
                return
            await self.state_manager.update_token_state(mint=mint, state="POOL_VALIDATED", event="PoolValidated", details=validation_result)
            token_context = self.token_context.get(mint, {}).copy()
            token_context.setdefault("mint", mint)
            token_context.setdefault("symbol", self._get_symbol(mint, event.data))
            initial_signal = self.initial_signals.get(mint, {})
            if not initial_signal:
                initial_signal = {"mint": mint, "symbol": token_context.get("symbol", "UNKNOWN"), "score": token_context.get("final_score", 0), "confidence": token_context.get("confidence", 0.0), "decision": token_context.get("decision", "MONITOR")}
            confirmation = await self.market_confirmation_engine.confirm_market(token_context, initial_signal, validation_result)
            self.market_confirmations[mint] = confirmation or {}
            if not confirmation or not confirmation.get("is_confirmed", False):
                self._record_pipeline_metric(operation="market_not_confirmed", mint=mint, success=True, metadata={"decision": token_context.get("decision"), "had_confirmation_payload": bool(confirmation)})
                await self._finalize_token_runtime(mint=mint, stop_raydium=True, keep_initial_signal=False, release_reason="market_not_confirmed", evict_state=True)
                return
            market_event = Event(event_type="MarketConfirmed", data=confirmation, source="Orchestrator", timestamp=datetime.utcnow())
            await self.event_bus.emit(market_event)
        except Exception as e:
            await self._handle_stage_failure("PoolFound", mint, e, details=event.data, stop_raydium=True)

    async def _handle_pool_timeout(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="POOL_TIMEOUT", event="PoolSearchTimeout", details=event.data, reason="Raydium pool not found before timeout")
            self._safe_store_call(f"raydium timeout persistence for {mint[:8]}...", self.store.update_token_raydium_status, mint, event.data)
            self._record_pipeline_metric(operation="pool_timeout", mint=mint, success=True, metadata={"elapsed_seconds": event.data.get("elapsed_seconds")})
            await self._finalize_token_runtime(mint=mint, stop_raydium=True, release_reason="pool_timeout", evict_state=True)
        except Exception as e:
            await self._handle_stage_failure("PoolSearchTimeout", mint, e, details=event.data, stop_raydium=True)

    async def _handle_market_confirmed(self, event: Event) -> None:
        mint = (event.data or {}).get("mint")
        try:
            if not mint or self._shutting_down:
                return
            self._merge_token_context(mint, event.data)
            await self.state_manager.update_token_state(mint=mint, state="MARKET_CONFIRMED", event="MarketConfirmed", details=event.data)
            self._safe_store_call(f"market confirmation persistence for {mint[:8]}...", self.store.update_token_raydium_status, mint, event.data)
            self._record_pipeline_metric(operation="market_confirmed", mint=mint, success=True, metadata={"score": event.data.get("score"), "new_confidence": event.data.get("new_confidence")})
            if self.signal_engine and not self._shutting_down:
                await self.signal_engine.generate_confirmed_and_emit(event=event, token_context=self.token_context.get(mint, {}))
            await self._stop_raydium_watch(mint)
            self.lock_manager.unlock_token(mint, reason="market_confirmed")
        except Exception as e:
            await self._handle_stage_failure("MarketConfirmed", mint, e, details=event.data, stop_raydium=True)

    async def _start_raydium_watch(self, mint: str) -> None:
        try:
            if self._shutting_down:
                return
            if not self.raydium_listener:
                logger.warning("RaydiumListener not initialized")
                return
            await self.raydium_listener.start_monitoring(mint, context=self.token_context.get(mint, {}))
            await self.state_manager.update_token_state(mint=mint, state="RAYDIUM_WATCH_STARTED", event="RaydiumWatchStarted", details=self.token_context.get(mint, {"mint": mint}))
        except Exception as e:
            logger.error(f"Error starting Raydium watch for {mint[:8]}...: {e}")
            self._record_pipeline_metric(operation="raydium_watch_start", mint=mint, success=False, error_message=str(e))
            raise

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
        if not self.initialized:
            raise RuntimeError("Orchestrator must be initialized before run()")
        if self.running:
            logger.warning("Orchestrator already running")
            return
        try:
            self.running = True
            self._shutting_down = False
            self.start_time = datetime.utcnow()
            self._cleanup_done = False
            self._start_background_tasks()
            task_items = list(self._background_tasks.items())
            results = await asyncio.gather(*(task for _, task in task_items), return_exceptions=True)
            for (task_name, _), result in zip(task_items, results):
                if isinstance(result, asyncio.CancelledError):
                    logger.debug(f"Background task cancelled: {task_name}")
                elif isinstance(result, Exception):
                    logger.error(f"Background task failed ({task_name}): {result}")
        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled")
        except Exception as e:
            logger.error(f"Error in orchestrator run: {e}")
        finally:
            self.running = False
            await self.cleanup()

    def _start_background_tasks(self) -> None:
        if not self.pump_listener or not self.raydium_listener:
            raise RuntimeError("Listeners not initialized")
        if self._background_tasks:
            return
        self._background_tasks = {
            "pump_listener": asyncio.create_task(self.pump_listener.start()),
            "raydium_listener": asyncio.create_task(self.raydium_listener.monitor_pools()),
            "token_processor": asyncio.create_task(self._process_tokens()),
        }

    async def _cancel_background_tasks(self) -> None:
        task_items = list(self._background_tasks.items())
        self._background_tasks = {}
        if not task_items:
            return
        for _, task in task_items:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*(task for _, task in task_items), return_exceptions=True)
        for (task_name, _), result in zip(task_items, results):
            if isinstance(result, asyncio.CancelledError):
                logger.debug(f"Background task cancelled during cleanup: {task_name}")
            elif isinstance(result, Exception):
                logger.error(f"Background task errored during cleanup ({task_name}): {result}")

    async def _stop_runtime_components(self) -> None:
        if self.pump_listener:
            try:
                await self.pump_listener.stop()
            except Exception as e:
                logger.error(f"Error stopping PumpListener: {e}")
        if self.raydium_listener:
            try:
                await self.raydium_listener.stop()
            except Exception as e:
                logger.error(f"Error stopping RaydiumListener: {e}")

    async def _process_tokens(self) -> None:
        while self.running:
            try:
                expired_count = self.lock_manager.cleanup_expired_locks()
                dedup_cleanup = self.signal_deduper.cleanup_old_signals()
                discovery_cleanup = self.discovery_deduper.cleanup_old_entries()
                if expired_count:
                    logger.debug(f"Expired locks cleaned during maintenance: {expired_count}")
                if dedup_cleanup or discovery_cleanup:
                    logger.debug(
                        f"Dedup cleanup | signals={dedup_cleanup} discoveries={discovery_cleanup}"
                    )
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("Token processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in token processor: {e}")

    def get_stats(self) -> dict:
        return {
            "running": self.running,
            "uptime_seconds": ((datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0),
            "tokens_processed": self.tokens_processed,
            "event_bus": self.event_bus.get_listener_count(),
            "lock_manager": self.lock_manager.get_stats(),
            "signal_deduper": self.signal_deduper.get_stats(),
            "discovery_deduper": self.discovery_deduper.get_stats(),
            "storage": self.state_manager.get_stats(),
            "token_context_cache": len(self.token_context),
            "cached_initial_signals": len(self.initial_signals),
            "cached_pool_validations": len(self.pool_validations),
            "cached_market_confirmations": len(self.market_confirmations),
        }

    async def cleanup(self) -> None:
        async with self._cleanup_lock:
            if self._cleanup_done:
                return
            try:
                logger.info("Cleaning up resources...")
                self._shutting_down = True
                self.running = False
                await self._stop_runtime_components()
                await self._cancel_background_tasks()
                if self.token_enricher:
                    await self.token_enricher.close()
                if self.raydium_listener:
                    await self.raydium_listener.close()
                if self.raydium_pool_validator:
                    await self.raydium_pool_validator.close()
                if self.alert_dispatcher:
                    await self.alert_dispatcher.close()
                self.token_context.clear()
                self.initial_signals.clear()
                self.pool_validations.clear()
                self.market_confirmations.clear()
                await self.event_bus.stop()
                logger.info("Cleanup completed")
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
            finally:
                self._cleanup_done = True

    async def shutdown(self) -> None:
        logger.info("Shutdown requested")
        self._shutting_down = True
        self.running = False
        await self.cleanup()
