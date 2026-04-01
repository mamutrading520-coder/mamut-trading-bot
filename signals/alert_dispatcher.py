"""Dispatch alerts through multiple channels"""
from typing import Dict, Any, Optional

from datetime import datetime
import asyncio

import httpx

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus
from storage.sqlite_store import SQLiteStore
from config.settings import Settings
from signals.signal_formatter import SignalFormatter

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

    async def _dispatch_to_webhook(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch alert to webhook.

        Returns:
            Structured result with attempted/success flags.
        """
        if not self.webhook_url:
            return {
                "attempted": False,
                "success": True,
                "status_code": None,
                "message": "No webhook configured",
            }

        try:
            client = await self._get_http_client()

            payload = self.formatter.format(signal, format_type="webhook")
            if not payload:
                logger.warning("Failed to format signal for webhook")
                return {
                    "attempted": True,
                    "success": False,
                    "status_code": None,
                    "message": "Webhook payload formatting failed",
                }

            response = await client.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code in [200, 201, 202, 204]:
                logger.debug("Webhook dispatch successful")
                return {
                    "attempted": True,
                    "success": True,
                    "status_code": response.status_code,
                    "message": "Webhook dispatched successfully",
                }

            logger.warning(f"Webhook returned status {response.status_code}")
            return {
                "attempted": True,
                "success": False,
                "status_code": response.status_code,
                "message": f"Unexpected webhook status: {response.status_code}",
            }

        except asyncio.TimeoutError:
            logger.warning("Webhook dispatch timeout")
            return {
                "attempted": True,
                "success": False,
                "status_code": None,
                "message": "Webhook dispatch timeout",
            }
        except Exception as e:
            logger.error(f"Error dispatching to webhook: {e}")
            return {
                "attempted": True,
                "success": False,
                "status_code": None,
                "message": str(e),
            }

    async def _update_signal_dispatch_state(
        self,
        signal: Dict[str, Any],
        webhook_result: Dict[str, Any],
        file_result: bool,
    ) -> bool:
        """
        Update existing signal record with dispatch outcome.
        """
        if not self.store:
            return True

        signal_id = signal.get("signal_id")
        if not signal_id:
            logger.warning("Cannot update signal dispatch state without signal_id")
            return False

        webhook_attempted = bool(webhook_result.get("attempted", False))
        webhook_success = bool(webhook_result.get("success", False))
        dispatch_success = file_result and (webhook_success if webhook_attempted else True)

        current_state = "DISPATCHED"
        if not dispatch_success and (file_result or webhook_success):
            current_state = "DISPATCH_PARTIAL"
        elif not dispatch_success:
            current_state = "DISPATCH_FAILED"

        updates = {
            "current_state": current_state,
        }

        if webhook_attempted:
            updates["webhook_sent"] = webhook_success
            if webhook_success:
                updates["webhook_sent_at"] = datetime.utcnow()

        try:
            updated_signal = self.store.update_signal(signal_id, updates)
            if not updated_signal:
                logger.warning(f"Signal not found while updating dispatch state: {signal_id}")
                return False

            logger.debug(f"Signal dispatch state updated: {signal_id} -> {current_state}")
            return True

        except Exception as e:
            logger.error(f"Error updating signal dispatch state: {e}")
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

    async def dispatch_alert(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch alert through all configured channels.

        Returns:
            Structured dispatch result with per-channel status.
        """
        if not self.alert_enabled:
            logger.debug("Alerts disabled, skipping dispatch")
            return {
                "success": True,
                "channels": {
                    "webhook": {
                        "attempted": False,
                        "success": True,
                        "status_code": None,
                        "message": "Alerts disabled",
                    },
                    "file_log": True,
                    "signal_state_updated": True,
                },
            }

        try:
            signal_id = signal.get("signal_id")
            logger.info(f"Dispatching alert for signal {signal_id}")

            webhook_result, file_result = await asyncio.gather(
                self._dispatch_to_webhook(signal),
                self._log_to_file(signal),
                return_exceptions=False,
            )

            state_result = await self._update_signal_dispatch_state(
                signal=signal,
                webhook_result=webhook_result,
                file_result=file_result,
            )

            webhook_required_success = (
                bool(webhook_result.get("success", False))
                if webhook_result.get("attempted", False)
                else True
            )
            success = bool(file_result) and bool(state_result) and webhook_required_success

            if success:
                self.alerts_dispatched += 1
                logger.info(f"Alert dispatched successfully: {signal_id}")
            else:
                self.alerts_failed += 1
                logger.warning(f"Alert dispatch failed or partial: {signal_id}")

            return {
                "success": success,
                "channels": {
                    "webhook": webhook_result,
                    "file_log": file_result,
                    "signal_state_updated": state_result,
                },
            }

        except Exception as e:
            logger.error(f"Error dispatching alert: {e}")
            self.alerts_failed += 1
            return {
                "success": False,
                "channels": {
                    "webhook": {
                        "attempted": False,
                        "success": False,
                        "status_code": None,
                        "message": str(e),
                    },
                    "file_log": False,
                    "signal_state_updated": False,
                },
            }

    async def dispatch_and_emit(self, event: Event) -> bool:
        """
        Dispatch alert and emit AlertDispatched event

        Args:
            event: SignalGenerated event

        Returns:
            True if dispatched successfully, False otherwise
        """
        try:
            signal = event.data or {}

            dispatch_result = await self.dispatch_alert(signal)
            success = bool(dispatch_result.get("success", False))

            dispatch_event = Event(
                event_type="AlertDispatched",
                data={
                    **signal,
                    "success": success,
                    "dispatch_results": dispatch_result.get("channels", {}),
                    "dispatched_at": datetime.utcnow().isoformat(),
                },
                source="AlertDispatcher",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(dispatch_event)
            logger.debug("Emitted AlertDispatched event")

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
