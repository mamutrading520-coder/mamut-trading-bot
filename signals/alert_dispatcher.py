"""Dispatch alerts through multiple channels"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from storage.sqlite_store import SQLiteStore
from config.settings import Settings
from signals.signal_formatter import SignalFormatter
import httpx
import asyncio

logger = setup_logger("AlertDispatcher")

class AlertDispatcher:
    """Dispatches alerts through multiple channels"""
    
    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()
        self.formatter = SignalFormatter()
        
        self.alerts_dispatched = 0
        self.alerts_failed = 0
        self.http_client = None
        
        # Dispatch channels
        self.webhook_url = settings.webhook_url
        self.alert_enabled = settings.alert_enabled
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=5)
        return self.http_client
    
    async def _dispatch_to_webhook(self, signal: Dict[str, Any]) -> bool:
        """
        Dispatch alert to webhook
        
        Args:
            signal: Signal data
            
        Returns:
            True if successful, False otherwise
        """
        if not self.webhook_url:
            return True  # No webhook configured, skip
        
        try:
            client = await self._get_http_client()
            
            # Format signal for webhook
            payload = self.formatter.format(signal, format_type="webhook")
            
            if not payload:
                logger.warning(f"Failed to format signal for webhook")
                return False
            
            response = await client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201, 202, 204]:
                logger.debug(f"Webhook dispatch successful")
                return True
            else:
                logger.warning(f"Webhook returned status {response.status_code}")
                return False
            
        except asyncio.TimeoutError:
            logger.warning(f"Webhook dispatch timeout")
            return False
        except Exception as e:
            logger.error(f"Error dispatching to webhook: {e}")
            return False
    
    async def _save_to_database(self, signal: Dict[str, Any]) -> bool:
        """
        Save signal to database
        
        Args:
            signal: Signal data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            signal_data = {
                "signal_id": signal.get("signal_id"),
                "mint": signal.get("mint"),
                "signal_type": signal.get("signal_type"),
                "score": signal.get("score"),
                "confidence": signal.get("confidence"),
                "reason": signal.get("reason"),
                "metadata": self.formatter._format_json(signal.get("metadata", {})),
            }
            
            self.store.create_signal(signal_data)
            logger.debug(f"Signal saved to database: {signal.get('signal_id')}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving signal to database: {e}")
            return False
    
    async def _log_to_file(self, signal: Dict[str, Any]) -> bool:
        """
        Log signal to file
        
        Args:
            signal: Signal data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            formatted = self.formatter.format(signal, format_type="text")
            logger.info(f"Signal alert:\n{formatted}")
            return True
            
        except Exception as e:
            logger.error(f"Error logging signal: {e}")
            return False
    
    async def dispatch_alert(self, signal: Dict[str, Any]) -> bool:
        """
        Dispatch alert through all configured channels
        
        Args:
            signal: Signal data
            
        Returns:
            True if dispatched successfully, False otherwise
        """
        if not self.alert_enabled:
            logger.debug(f"Alerts disabled, skipping dispatch")
            return True
        
        try:
            mint = signal.get("mint")
            signal_id = signal.get("signal_id")
            
            logger.info(f"Dispatching alert for signal {signal_id}")
            
            # Dispatch to all channels in parallel
            webhook_result, db_result, file_result = await asyncio.gather(
                self._dispatch_to_webhook(signal),
                self._save_to_database(signal),
                self._log_to_file(signal),
                return_exceptions=False
            )
            
            # Consider success if at least database and file logging worked
            success = db_result and file_result
            
            if success:
                self.alerts_dispatched += 1
                logger.info(f"Alert dispatched successfully: {signal_id}")
            else:
                self.alerts_failed += 1
                logger.warning(f"Alert dispatch partially failed: {signal_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error dispatching alert: {e}")
            self.alerts_failed += 1
            return False
    
    async def dispatch_and_emit(self, event: Event) -> bool:
        """
        Dispatch alert and emit AlertDispatched event
        
        Args:
            event: SignalGenerated event
            
        Returns:
            True if dispatched successfully, False otherwise
        """
        try:
            signal = event.data
            
            # Dispatch alert
            success = await self.dispatch_alert(signal)
            
            # Emit dispatch result
            dispatch_event = Event(
                event_type="AlertDispatched",
                data={
                    "signal_id": signal.get("signal_id"),
                    "mint": signal.get("mint"),
                    "success": success,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                source="AlertDispatcher",
                timestamp=datetime.utcnow()
            )
            
            await self.event_bus.emit(dispatch_event)
            logger.debug(f"Emitted AlertDispatched event")
            
            return success
            
        except Exception as e:
            logger.error(f"Error in dispatch_and_emit: {e}")
            self.alerts_failed += 1
            return False
    
    async def close(self) -> None:
        """Close HTTP client"""
        if self.http_client:
            await self.http_client.aclose()
    
    def get_stats(self) -> dict:
        """Get dispatcher statistics"""
        total = self.alerts_dispatched + self.alerts_failed
        return {
            "alerts_dispatched": self.alerts_dispatched,
            "alerts_failed": self.alerts_failed,
            "success_rate": self.alerts_dispatched / total if total > 0 else 0,
        }