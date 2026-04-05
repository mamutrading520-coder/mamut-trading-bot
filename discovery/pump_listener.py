"""Pump.fun WebSocket listener for token discovery"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any

import websockets
from websockets.legacy.client import WebSocketClientProtocol

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus
from discovery.pump_event_parser import PumpEventParser, ParsedTokenEvent

logger = setup_logger("PumpListener")


class PumpListener:
    """Listens to Pump.fun for new token launches."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.parser = PumpEventParser()

        self.ws_url = settings.pump_ws_url
        self.reconnect_delay = settings.pump_reconnect_delay
        self.initial_reconnect_delay = settings.pump_reconnect_delay
        self.max_retries = settings.pump_max_retries
        self.receive_timeout = max(10, int(getattr(settings, "pump_receive_timeout", 60) or 60))
        self.parse_timeout = float(getattr(settings, "pump_parse_timeout", 5.0) or 5.0)
        self.emit_timeout = float(getattr(settings, "pump_emit_timeout", 5.0) or 5.0)
        self.processing_warn_threshold = float(
            getattr(settings, "pump_processing_warn_threshold", 3.0) or 3.0
        )
        self.stall_timeout = float(getattr(settings, "pump_stall_timeout", 20.0) or 20.0)
        self.watchdog_interval = float(getattr(settings, "pump_watchdog_interval", 5.0) or 5.0)

        self.ws: Optional[WebSocketClientProtocol] = None
        self.running = False
        self.ws_connected = False

        self.tokens_received = 0
        self.tokens_failed = 0
        self.last_received_at: Optional[datetime] = None
        self.reconnect_attempts = 0

        self.last_progress_at: Optional[datetime] = None
        self.last_stage: str = "idle"
        self.last_message_preview: str = ""
        self._watchdog_task: Optional[asyncio.Task] = None
        self._reconnect_requested = False

    def _mark_progress(self, stage: str, message_preview: Optional[str] = None) -> None:
        self.last_progress_at = datetime.utcnow()
        self.last_stage = stage
        if message_preview is not None:
            self.last_message_preview = self._short_preview(message_preview)

    @staticmethod
    def _short_preview(message: str, limit: int = 180) -> str:
        preview = str(message).replace("\n", " ").replace("\r", " ").strip()
        return preview[:limit]

    async def connect(self) -> bool:
        """Connect to Pump.fun WebSocket."""
        try:
            logger.info(f"Connecting to Pump.fun WebSocket: {self.ws_url}")
            self._mark_progress("connecting")

            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ),
                timeout=10.0,
            )

            self.ws_connected = True
            self._reconnect_requested = False
            self.reconnect_attempts = 0
            self.reconnect_delay = self.initial_reconnect_delay
            self._mark_progress("connected")
            logger.info("✓ Connected to Pump.fun WebSocket")
            return True

        except asyncio.TimeoutError:
            logger.warning("Connection timeout")
            self.ws_connected = False
            self._mark_progress("connect_timeout")
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.ws_connected = False
            self._mark_progress("connect_error")
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        try:
            self._mark_progress("disconnecting")
            if self.ws:
                try:
                    await asyncio.wait_for(self.ws.close(), timeout=5.0)
                except Exception:
                    pass
            self.ws = None
            self.ws_connected = False
            self._mark_progress("disconnected")
            logger.info("Disconnected from Pump.fun WebSocket")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")

    async def subscribe_new_token(self) -> bool:
        """Subscribe to new token events."""
        try:
            if not self.ws:
                logger.error("WebSocket not connected")
                return False

            subscribe_msg = {"method": "subscribeNewToken"}
            logger.info(f"Attempting subscription with: {subscribe_msg}")
            self._mark_progress("subscribing")

            await asyncio.wait_for(self.ws.send(json.dumps(subscribe_msg)), timeout=5.0)
            logger.info("✓ Subscription sent")

            try:
                response = await asyncio.wait_for(self.ws.recv(), timeout=2.0)
                self._mark_progress("subscribed", response)
                logger.info(f"Subscription response: {response[:200]}")
                return True
            except asyncio.TimeoutError:
                self._mark_progress("subscribed_no_ack")
                logger.warning("No subscription response, continuing anyway...")
                return True

        except Exception as e:
            logger.error(f"Subscribe error: {e}")
            self._mark_progress("subscribe_error")
            return False

    def _parse_event(self, message: str) -> Optional[ParsedTokenEvent]:
        """Parse WebSocket message."""
        try:
            data = json.loads(message)
            logger.debug(f"Raw message: {str(message)[:200]}")

            if isinstance(data, dict):
                if data.get("method") or data.get("result"):
                    logger.debug(f"Skipping non-token message: {data}")
                    return None

                if not data.get("mint") or not data.get("signature"):
                    logger.debug(f"Missing mint or signature in: {str(data)[:100]}")
                    return None

                parsed = self.parser.parse(data)
                if parsed:
                    logger.info(f"✓ Parsed token: {parsed.symbol} ({parsed.mint[:8]}...)")
                    return parsed

                logger.warning(f"Parser returned None for: {str(data)[:100]}")
                return None

            return None

        except json.JSONDecodeError:
            logger.debug(f"Invalid JSON: {str(message)[:100]}")
            return None
        except Exception as e:
            logger.debug(f"Parse error: {e}")
            self.tokens_failed += 1
            return None

    async def _handle_message(self, message: str, message_count: int) -> None:
        preview = self._short_preview(message)
        started_at = asyncio.get_running_loop().time()
        self._mark_progress("message_received", preview)

        try:
            self._mark_progress("message_parsing", preview)
            event = await asyncio.wait_for(
                asyncio.to_thread(self._parse_event, message),
                timeout=self.parse_timeout,
            )
            self._mark_progress("message_parsed", preview)
        except asyncio.TimeoutError:
            self.tokens_failed += 1
            logger.warning(
                f"Pump parse timeout after {self.parse_timeout:.1f}s | message=#{message_count} | preview={preview}"
            )
            self._mark_progress("parse_timeout", preview)
            self._reconnect_requested = True
            raise
        except Exception as e:
            self.tokens_failed += 1
            logger.error(f"Pump message processing error before emit: {e}")
            self._mark_progress("parse_error", preview)
            return

        if not event:
            return

        self.tokens_received += 1
        self.last_received_at = datetime.utcnow()
        logger.info(f"[{self.tokens_received}] Emitting: {event.symbol}")

        token_event = Event(
            event_type="TokenDiscovered",
            data=event.to_dict(),
            source="PumpListener",
            timestamp=datetime.utcnow(),
        )

        try:
            self._mark_progress("event_emitting", preview)
            await asyncio.wait_for(self.event_bus.emit(token_event), timeout=self.emit_timeout)
            self._mark_progress("event_emitted", preview)
        except asyncio.TimeoutError:
            self.tokens_failed += 1
            logger.warning(
                f"Pump event emit timeout after {self.emit_timeout:.1f}s | message=#{message_count} | symbol={event.symbol}"
            )
            self._mark_progress("emit_timeout", preview)
            self._reconnect_requested = True
            raise
        except Exception as e:
            self.tokens_failed += 1
            logger.error(f"Error emitting token event {event.symbol}: {e}")
            self._mark_progress("emit_error", preview)
            raise
        finally:
            elapsed = asyncio.get_running_loop().time() - started_at
            if elapsed >= self.processing_warn_threshold:
                logger.warning(
                    f"Pump message processing was slow | elapsed={elapsed:.2f}s | stage={self.last_stage} | preview={preview}"
                )

    async def _watchdog_loop(self) -> None:
        """Detect stalls and force reconnects when progress stops."""
        try:
            while self.running:
                await asyncio.sleep(self.watchdog_interval)
                if not self.running or not self.ws_connected or not self.last_progress_at:
                    continue

                stalled_for = (datetime.utcnow() - self.last_progress_at).total_seconds()
                threshold = self.stall_timeout
                if self.last_stage == "waiting_for_message":
                    threshold = max(float(self.receive_timeout) + 10.0, self.stall_timeout)

                if stalled_for < threshold:
                    continue

                logger.warning(
                    "Pump listener stall detected | stalled_for=%.1fs | stage=%s | preview=%s"
                    % (stalled_for, self.last_stage, self.last_message_preview)
                )
                self._reconnect_requested = True
                await self.disconnect()
        except asyncio.CancelledError:
            logger.info("Pump listener watchdog cancelled")
        except Exception as e:
            logger.error(f"Pump listener watchdog error: {e}")

    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        logger.info("Starting receive loop")
        message_count = 0

        try:
            while self.running and self.ws and self.ws_connected:
                try:
                    self._mark_progress("waiting_for_message")
                    message = await asyncio.wait_for(self.ws.recv(), timeout=float(self.receive_timeout))

                    if not message:
                        continue

                    message_count += 1
                    logger.debug(f"Received message #{message_count}: {str(message)[:100]}")
                    await self._handle_message(message, message_count)

                except asyncio.TimeoutError:
                    logger.warning(
                        f"WebSocket receive timeout after {message_count} messages, reconnecting..."
                    )
                    self._reconnect_requested = True
                    break
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"WebSocket connection closed: {e}")
                    break
                except Exception as e:
                    logger.error(f"Receive error: {e}")
                    self._reconnect_requested = True
                    break

        except asyncio.CancelledError:
            logger.info("Receive loop cancelled")
        finally:
            self.ws_connected = False
            logger.info(
                f"Receive loop ended. Received {message_count} messages | last_stage={self.last_stage} | reconnect_requested={self._reconnect_requested}"
            )

    async def _reconnect_loop(self) -> None:
        """Reconnect loop with exponential backoff."""
        while self.running:
            try:
                if not self.ws_connected and self.reconnect_attempts < self.max_retries:
                    self.reconnect_attempts += 1
                    logger.info(f"Reconnect attempt {self.reconnect_attempts}/{self.max_retries}")

                    if await self.connect():
                        await asyncio.sleep(1)
                        if await self.subscribe_new_token():
                            await self._receive_loop()
                        else:
                            await self.disconnect()

                    if self.running and not self.ws_connected:
                        logger.info(f"Reconnecting in {self.reconnect_delay}s...")
                        await asyncio.sleep(self.reconnect_delay)
                        self.reconnect_delay = min(self.reconnect_delay * 2, 60)

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info("Reconnect loop cancelled")
                break
            except Exception as e:
                logger.error(f"Reconnect loop error: {e}")
                await asyncio.sleep(5)

    async def start(self) -> None:
        """Start listening to Pump.fun."""
        logger.info("Starting Pump.fun listener")
        self.running = True
        self._mark_progress("starting")
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        try:
            await self._reconnect_loop()
        except asyncio.CancelledError:
            logger.info("Listener cancelled")
        finally:
            self.running = False
            if self._watchdog_task:
                self._watchdog_task.cancel()
                try:
                    await self._watchdog_task
                except asyncio.CancelledError:
                    pass
                self._watchdog_task = None
            await self.disconnect()

    async def stop(self) -> None:
        """Stop listening."""
        logger.info("Stopping Pump.fun listener")
        self.running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        await self.disconnect()
        logger.info(f"Listener stopped. Received: {self.tokens_received}, Failed: {self.tokens_failed}")

    def get_stats(self) -> Dict[str, Any]:
        """Get listener statistics."""
        return {
            "running": self.running,
            "tokens_received": self.tokens_received,
            "tokens_failed": self.tokens_failed,
            "last_received_at": self.last_received_at,
            "reconnect_attempts": self.reconnect_attempts,
            "ws_connected": self.ws_connected,
            "last_progress_at": self.last_progress_at,
            "last_stage": self.last_stage,
            "last_message_preview": self.last_message_preview,
            "reconnect_requested": self._reconnect_requested,
        }
