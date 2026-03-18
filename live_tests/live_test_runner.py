"""Live testing runner for real-time token discovery and analysis"""
import asyncio
import signal
import json
from datetime import datetime
from monitoring.logger import setup_logger
from config.settings import Settings
from discovery.pump_listener import PumpListener
from discovery.pump_event_parser import PumpEventParser
from enrich.token_enricher import TokenEnricher
from enrich.creator_profiler import CreatorProfiler
from filters.trash_filter_engine import TrashFilterEngine
from scoring.score_engine import ScoreEngine
from scoring.decision_mapper import DecisionMapper
from signals.signal_engine import SignalEngine
from signals.alert_dispatcher import AlertDispatcher
from validation.raydium_listener import RaydiumListener
from validation.raydium_pool_validator import RaydiumPoolValidator
from validation.market_confirmation_engine import MarketConfirmationEngine
from storage.sqlite_store import SQLiteStore
from core.event_bus import Event, get_event_bus

logger = setup_logger("LiveTestRunner")


class LiveTestRunner:
    """Live testing runner for real-time system testing"""
    
    def __init__(self):
        self.settings = Settings()
        self.event_bus = get_event_bus()
        self.store = SQLiteStore(self.settings)
        
        self.pump_listener = PumpListener(self.settings)
        self.pump_parser = PumpEventParser()
        self.token_enricher = TokenEnricher(self.settings)
        self.creator_profiler = CreatorProfiler(self.store, self.settings)
        self.trash_filter = TrashFilterEngine(self.store, self.settings)
        self.score_engine = ScoreEngine()
        self.decision_mapper = DecisionMapper(self.settings)
        self.signal_engine = SignalEngine(self.settings)
        self.alert_dispatcher = AlertDispatcher(self.store, self.settings)
        self.raydium_listener = RaydiumListener(self.settings)
        self.pool_validator = RaydiumPoolValidator()
        self.market_confirmation = MarketConfirmationEngine(self.settings)
        
        self.running = False
        self.start_time = None
        self.tokens_discovered = 0
        self.tokens_signaled = 0
        self.signals_generated = 0
    
    async def setup(self) -> bool:
        """Setup live testing environment"""
        try:
            logger.info("=" * 80)
            logger.info("MAMUT LIVE TEST RUNNER - INITIALIZING")
            logger.info("=" * 80)
            
            await self.event_bus.start()
            logger.info("✓ Event bus started")
            
            await self._register_handlers()
            logger.info("✓ Event handlers registered")
            
            if self.store.get_statistics():
                logger.info("✓ Database connection verified")
            else:
                logger.error("✗ Database connection failed")
                return False
            
            logger.info("=" * 80)
            logger.info("READY FOR LIVE TESTING")
            logger.info("=" * 80)
            
            return True
            
        except Exception as e:
            logger.error(f"Setup failed: {e}", exc_info=True)
            return False
    
    async def _register_handlers(self) -> None:
        """Register all event handlers"""
        
        # ============================================================
        # HANDLER 1: Token Discovered
        # ============================================================
        async def on_token_discovered(event: Event):
            self.tokens_discovered += 1
            mint = event.data.get("mint")
            symbol = event.data.get("symbol", "UNKNOWN")
            logger.info(f"[DISCOVERED #{self.tokens_discovered}] {symbol} ({mint[:8]}...)")
            
            try:
                token_data = {
                    "mint": mint,
                    "name": event.data.get("name", ""),
                    "symbol": symbol,
                    "creator": event.data.get("creator", ""),
                    "initial_sol": float(event.data.get("initial_sol", 0)),
                    "market_cap_sol": float(event.data.get("market_cap_sol", 0)),
                    "uri": event.data.get("uri", ""),
                }
                self.store.create_token(token_data)
                logger.debug(f"Token saved to DB: {mint}")
            except Exception as e:
                logger.error(f"Error saving token: {e}")
            
            try:
                enriched = await self.token_enricher.enrich(event.data)
                if enriched:
                    enrich_event = Event(
                        event_type="TokenEnriched",
                        data=enriched.to_dict(),
                        source="LiveTestRunner",
                        timestamp=datetime.utcnow()
                    )
                    await self.event_bus.emit(enrich_event)
            except Exception as e:
                logger.error(f"Error enriching token: {e}")
        
        # ============================================================
        # HANDLER 2: Token Enriched
        # ============================================================
        async def on_token_enriched(event: Event):
            mint = event.data.get("mint")
            logger.debug(f"[ENRICHED] {mint[:8]}...")
            
            try:
                await self.creator_profiler.profile_and_emit(event)
            except Exception as e:
                logger.error(f"Error profiling creator: {e}")
        
        # ============================================================
        # HANDLER 3: Creator Profiled
        # ============================================================
        async def on_creator_profiled(event: Event):
            mint = event.data.get("mint")
            risk_level = event.data.get("analysis", {}).get("risk_level", "UNKNOWN")
            logger.debug(f"[PROFILED] {mint[:8]}... risk={risk_level}")
            
            try:
                combined_event = Event(
                    event_type="CreatorProfiled",
                    data=event.data,
                    source="LiveTestRunner",
                    timestamp=datetime.utcnow()
                )
                await self.trash_filter.filter_and_emit(combined_event)
            except Exception as e:
                logger.error(f"Error filtering token: {e}")
        
        # ============================================================
        # HANDLER 4: Token Rejected
        # ============================================================
        async def on_token_rejected(event: Event):
            mint = event.data.get("mint")
            reason = event.data.get("rejection_reason", "UNKNOWN")
            logger.warning(f"[REJECTED] {mint[:8]}... reason={reason}")
            
            try:
                self.store.update_token(mint, {
                    "passed_filters": False,
                    "rejection_reason": reason,
                    "risk_level": "TRASH"
                })
            except Exception as e:
                logger.error(f"Error updating rejected token: {e}")
        
        # ============================================================
        # HANDLER 5: Token Passed Filters
        # ============================================================
        async def on_token_passed(event: Event):
            mint = event.data.get("mint")
            logger.info(f"[PASSED FILTERS] {mint[:8]}...")
            
            try:
                self.store.update_token(mint, {"passed_filters": True})
                logger.debug(f"  ✓ Token updated in DB")
                
                # Create filter results from event data
                filter_results = {
                    "checks": {
                        "authority": {"score": event.data.get("authority_risk", 50.0)},
                        "creator_risk": {"score": event.data.get("creator_risk", 50.0)},
                        "concentration": {"score": event.data.get("concentration_risk", 50.0)},
                    }
                }
                logger.debug(f"  ✓ Filter results created")
                
                # Calculate score
                score_analysis = self.score_engine.calculate_score(event.data, filter_results)
                logger.info(f"  ✓ Score calculated: {score_analysis.get('final_score')} risk={score_analysis.get('risk_level')}")
                
                # Merge score data with event data
                score_event_data = {**event.data, **score_analysis}
                
                # Create and emit score event
                score_event = Event(
                    event_type="ScoreCalculated",
                    data=score_event_data,
                    source="LiveTestRunner",
                    timestamp=datetime.utcnow()
                )
                
                await self.event_bus.emit(score_event)
                logger.debug(f"  ✓ ScoreCalculated event EMITTED")
                
            except Exception as e:
                logger.error(f"Error scoring token: {e}", exc_info=True)
        
        # ============================================================
        # HANDLER 6: Score Calculated
        # ============================================================
        async def on_score_calculated(event: Event):
            mint = event.data.get("mint")
            final_score = event.data.get("final_score", 0)
            risk_level = event.data.get("risk_level", "UNKNOWN")
            logger.info(f"[SCORED] {mint[:8]}... score={final_score:.1f} risk={risk_level}")
            
            try:
                # Update token with score
                self.store.update_token(mint, {
                    "final_score": final_score,
                    "risk_level": risk_level,
                })
                logger.debug(f"  ✓ Score saved to DB")
                
                # Create decision event and let DecisionMapper handle it
                decision_event = Event(
                    event_type="DecisionMade",
                    data=event.data,
                    source="LiveTestRunner",
                    timestamp=datetime.utcnow()
                )
                
                # DecisionMapper.map_and_emit will handle the decision logic
                await self.decision_mapper.map_and_emit(decision_event)
                logger.debug(f"  ✓ Decision mapped and emitted")
                
            except Exception as e:
                logger.error(f"Error in score calculation: {e}", exc_info=True)
        
        # ============================================================
        # HANDLER 7: Decision Made
        # ============================================================
        async def on_decision_made(event: Event):
            mint = event.data.get("mint")
            decision = event.data.get("decision", "UNKNOWN")
            score = event.data.get("final_score", 0)
            
            if decision == "SIGNAL_EARLY":
                self.tokens_signaled += 1
                logger.info(f"[EARLY SIGNAL #{self.tokens_signaled}] {mint[:8]}... score={score:.1f}")
                
                try:
                    signal_data = {
                        "mint": mint,
                        "symbol": event.data.get("symbol", "UNKNOWN"),
                        "name": event.data.get("name", "UNKNOWN"),
                        "creator": event.data.get("creator", "UNKNOWN"),
                        "initial_sol": event.data.get("initial_sol", 0),
                        "market_cap_sol": event.data.get("market_cap_sol", 0),
                        "uri": event.data.get("uri", ""),
                    }
                    
                    signal = self.signal_engine.generate_early_signal(
                        token_data=signal_data,
                        decision=event.data,
                    )
                    
                    if signal:
                        self.signals_generated += 1
                        
                        try:
                            signal_db_data = {
                                "signal_id": signal.signal_id,
                                "mint": mint,
                                "symbol": signal_data.get("symbol"),
                                "signal_type": "EARLY",
                                "score": score,
                                "confidence": 0.8,
                                "reason": "High potential token detected",
                                "metadata_json": json.dumps(event.data)
                            }
                            self.store.create_signal(signal_db_data)
                            logger.info(f"  ✓ Signal saved to DB: {signal.signal_id}")
                        except Exception as e:
                            logger.error(f"Error saving signal to DB: {e}")
                        
                        signal_event = Event(
                            event_type="SignalGenerated",
                            data=signal.to_dict(),
                            source="LiveTestRunner",
                            timestamp=datetime.utcnow()
                        )
                        await self.alert_dispatcher.dispatch_and_emit(signal_event)
                        
                        await self.raydium_listener.start_monitoring(mint)
                        logger.info(f"[RAYDIUM MONITOR] Started for {mint[:8]}...")
                except Exception as e:
                    logger.error(f"Error generating signal: {e}", exc_info=True)
        
        # ============================================================
        # HANDLER 8: Pool Found
        # ============================================================
        async def on_pool_found(event: Event):
            mint = event.data.get("mint")
            pool_id = event.data.get("pool", {}).get("pool_id", "UNKNOWN")
            elapsed = event.data.get("elapsed_seconds", 0)
            logger.info(f"[POOL FOUND] {mint[:8]}... in {elapsed}s")
            
            try:
                pool_validation = await self.pool_validator.validate_pool(
                    event.data.get("pool", {})
                )
                
                if pool_validation.get("is_valid"):
                    logger.info(f"[POOL VALID] Liquidity: {pool_validation.get('liquidity_sol', 0):.2f} SOL")
                    
                    self.store.update_token(mint, {
                        "raydium_pool_found": True,
                        "raydium_pool_id": pool_id,
                        "raydium_liquidity_sol": pool_validation.get("liquidity_sol", 0),
                    })
            except Exception as e:
                logger.error(f"Error validating pool: {e}")
        
        # ============================================================
        # HANDLER 9: Pool Timeout
        # ============================================================
        async def on_pool_timeout(event: Event):
            mint = event.data.get("mint")
            elapsed = event.data.get("elapsed_seconds", 0)
            logger.warning(f"[POOL TIMEOUT] {mint[:8]}... after {elapsed}s")
        
        # ============================================================
        # HANDLER 10: Alert Dispatched
        # ============================================================
        async def on_alert_dispatched(event: Event):
            success = event.data.get("success", False)
            signal_id = event.data.get("signal_id", "UNKNOWN")
            
            if success:
                logger.info(f"[ALERT SENT] {signal_id}")
            else:
                logger.error(f"[ALERT FAILED] {signal_id}")
        
        # ============================================================
        # REGISTER ALL HANDLERS
        # ============================================================
        self.event_bus.subscribe("TokenDiscovered", on_token_discovered)
        self.event_bus.subscribe("TokenEnriched", on_token_enriched)
        self.event_bus.subscribe("CreatorProfiled", on_creator_profiled)
        self.event_bus.subscribe("TokenRejected", on_token_rejected)
        self.event_bus.subscribe("TokenPassed", on_token_passed)
        self.event_bus.subscribe("ScoreCalculated", on_score_calculated)
        self.event_bus.subscribe("DecisionMade", on_decision_made)
        self.event_bus.subscribe("PoolFound", on_pool_found)
        self.event_bus.subscribe("PoolSearchTimeout", on_pool_timeout)
        self.event_bus.subscribe("AlertDispatched", on_alert_dispatched)
    
    async def start_pump_listener(self) -> None:
        """Start Pump.fun listener"""
        logger.info("Starting Pump.fun listener...")
        try:
            await self.pump_listener.start()
        except Exception as e:
            logger.error(f"Pump listener error: {e}")
    
    async def start_raydium_monitor(self) -> None:
        """Start Raydium pool monitor"""
        logger.info("Starting Raydium pool monitor...")
        try:
            await self.raydium_listener.monitor_pools()
        except Exception as e:
            logger.error(f"Raydium monitor error: {e}")
    
    async def _print_stats_loop(self) -> None:
        """Print statistics periodically"""
        while self.running:
            try:
                await asyncio.sleep(30)
                await self.print_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error printing stats: {e}")
    
    async def print_stats(self) -> None:
        """Print current statistics"""
        try:
            uptime = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
            
            logger.info("=" * 80)
            logger.info("LIVE TEST STATISTICS")
            logger.info("=" * 80)
            logger.info(f"Uptime:              {uptime:.0f}s")
            logger.info(f"Tokens Discovered:   {self.tokens_discovered}")
            logger.info(f"Tokens Signaled:     {self.tokens_signaled}")
            logger.info(f"Signals Generated:   {self.signals_generated}")
            
            if self.tokens_discovered > 0:
                signal_rate = (self.tokens_signaled / self.tokens_discovered) * 100
                logger.info(f"Signal Rate:         {signal_rate:.1f}%")
            
            logger.info("")
            logger.info("Component Statistics:")
            logger.info(f"  Pump Listener:       {self.pump_listener.get_stats()}")
            logger.info(f"  Score Engine:        {self.score_engine.get_stats()}")
            logger.info(f"  Signal Engine:       {self.signal_engine.get_stats()}")
            logger.info(f"  Raydium Listener:    {self.raydium_listener.get_stats()}")
            
            db_stats = self.store.get_statistics()
            logger.info("")
            logger.info("Database Statistics:")
            logger.info(f"  Total Tokens:        {db_stats.get('total_tokens', 0)}")
            logger.info(f"  Total Signals:       {db_stats.get('total_signals', 0)}")
            logger.info(f"  By Risk Level:       {db_stats.get('tokens_by_risk', {})}")
            
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"Error printing stats: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        try:
            logger.info("Cleaning up resources...")
            self.running = False
            
            await self.pump_listener.stop()
            await self.token_enricher.close()
            await self.alert_dispatcher.close()
            await self.raydium_listener.close()
            await self.pool_validator.close()
            await self.event_bus.stop()
            
            await self.print_stats()
            
            logger.info("=" * 80)
            logger.info("LIVE TEST COMPLETED")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    async def shutdown(self) -> None:
        """Shutdown gracefully"""
        self.running = False
        await self.cleanup()
    
    async def run(self) -> None:
        """Run live testing"""
        try:
            if not await self.setup():
                logger.error("Setup failed")
                return
            
            self.running = True
            self.start_time = datetime.utcnow()
            
            pump_task = asyncio.create_task(self.start_pump_listener())
            raydium_task = asyncio.create_task(self.start_raydium_monitor())
            stats_task = asyncio.create_task(self._print_stats_loop())
            
            done, pending = await asyncio.wait(
                [pump_task, raydium_task, stats_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
            
        except asyncio.CancelledError:
            logger.info("Live testing cancelled")
        except Exception as e:
            logger.error(f"Error in run: {e}")
        finally:
            await self.cleanup()


async def main():
    """Main entry point for live testing"""
    runner = LiveTestRunner()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(runner.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())