"""Pump.fun WebSocket listener for token discovery"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

import websockets
from websockets.legacy.client import WebSocketClientProtocol

from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus
from discovery.pump_event_parser import PumpEventParser, ParsedTokenEvent

logger = setup_logger("PumpListener")

QueueItem = Optional[Tuple[int, str]]


class PumpListener:
    """Listens to Pump.fun for new token launches without blocking the receive loop."""

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
        self.queue_maxsize = max(100, int(getattr(settings, "pump_queue_maxsize", 1000) or 1000))
        self.parser_workers = max(1, int(getattr(settings, "pump_parser_workers", 3) or 3))

        self.ws: Optional[WebSocketClientProtocol] = None
        self.running = False
        self.ws_connected = False

        self.tokens_received = 0
        self.tokens_failed = 0
        self.messages_dropped = 0
        self.last_received_at: Optional[datetime] = None
        self.reconnect_attempts = 0

        self.last_progress_at: Optional[datetime] = None
        self.last_stage: str = "idle"
        self.last_message_preview: str = ""
        self.last_ws_recv_at: Optional[datetime] = None
        self.last_queue_put_at: Optional[datetime] = None
        self.last_queue_get_at: Optional[datetime] = None
        self.last_emit_at: Optional[datetime] = None
        self._inflight_messages: int = 0

        self._watchdog_task: Optional[asyncio.Task] = None
        self._worker_tasks: List[asyncio.Task] = []
        self._reconnect_requested = False
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=self.queue_maxsize)

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
                self.last_ws_recv_at = datetime.utcnow()
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
        """Parse a WebSocket message synchronously in a worker thread."""
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

    def _enqueue_message(self, message: str, message_count: int) -> None:
        preview = self._short_preview(message)
        try:
            self._queue.put_nowait((message_count, message))
            self.last_queue_put_at = datetime.utcnow()
            self._mark_progress("message_queued", preview)
        except asyncio.QueueFull:
            self.messages_dropped += 1
            self.tokens_failed += 1
            self._mark_progress("queue_full_drop", preview)
            logger.warning(
                f"Pump queue full, dropping message #{message_count} | queue_size={self._queue.qsize()} | preview={preview}"
            )

    async def _process_queued_message(self, worker_id: int, item: Tuple[int, str]) -> None:
        message_count, message = item
        preview = self._short_preview(message)
        started_at = asyncio.get_running_loop().time()
        self._mark_progress(f"worker_{worker_id}_parsing", preview)

        try:
            event = await asyncio.to_thread(self._parse_event, message)
        except Exception as e:
            self.tokens_failed += 1
            self._mark_progress(f"worker_{worker_id}_parse_error", preview)
            logger.error(f"Pump parser worker {worker_id} failed: {e}")
            return

        elapsed = asyncio.get_running_loop().time() - started_at
        soft_threshold = max(self.processing_warn_threshold, self.parse_timeout)
        if elapsed >= soft_threshold:
            logger.warning(
                f"Pump parser worker slow | worker={worker_id} | elapsed={elapsed:.2f}s | message=#{message_count} | preview={preview}"
            )

        if not event:
            self._mark_progress(f"worker_{worker_id}_parsed_none", preview)
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
            self._mark_progress(f"worker_{worker_id}_emitting", preview)
            await asyncio.wait_for(self.event_bus.emit(token_event), timeout=self.emit_timeout)
            self.last_emit_at = datetime.utcnow()
            self._mark_progress(f"worker_{worker_id}_emitted", preview)
        except asyncio.TimeoutError:
            self.tokens_failed += 1
            self._mark_progress(f"worker_{worker_id}_emit_timeout", preview)
            logger.warning(
                f"Pump emit timeout after {self.emit_timeout:.1f}s | worker={worker_id} | message=#{message_count} | symbol={event.symbol}"
            )
        except Exception as e:
            self.tokens_failed += 1
            self._mark_progress(f"worker_{worker_id}_emit_error", preview)
            logger.error(f"Error emitting token event {event.symbol}: {e}")

    async def _parser_worker_loop(self, worker_id: int) -> None:
        """Consume queued messages without blocking the websocket receive loop."""
        logger.info(f"Starting pump parser worker {worker_id}")
        try:
            while self.running:
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if item is None:
                    self._queue.task_done()
                    logger.info(f"Pump parser worker {worker_id} received stop signal")
                    break

                self.last_queue_get_at = datetime.utcnow()
                self._inflight_messages += 1
                try:
                    await self._process_queued_message(worker_id, item)
                finally:
                    self._inflight_messages = max(0, self._inflight_messages - 1)
                    self._queue.task_done()
        except asyncio.CancelledError:
            logger.info(f"Pump parser worker {worker_id} cancelled")
        except Exception as e:
            logger.error(f"Pump parser worker {worker_id} error: {e}")

    async def _start_workers(self) -> None:
        if self._worker_tasks:
            return
        self._worker_tasks = [
            asyncio.create_task(self._parser_worker_loop(worker_id))
            for worker_id in range(1, self.parser_workers + 1)
        ]

    async def _stop_workers(self) -> None:
        if not self._worker_tasks:
            return
        for _ in self._worker_tasks:
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                break
        for task in self._worker_tasks:
            task.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks = []

    async def _watchdog_loop(self) -> None:
        """Watch backlog health only. Idle sockets are handled by receive_timeout."""
        try:
            while self.running:
                await asyncio.sleep(self.watchdog_interval)
                if not self.running or not self.ws_connected:
                    continue

                queue_size = self._queue.qsize()
                inflight = self._inflight_messages

                if queue_size == 0:
                    continue

                now = datetime.utcnow()
                consumer_markers = [marker for marker in [self.last_queue_get_at, self.last_emit_at] if marker]
                producer_markers = [marker for marker in [self.last_ws_recv_at, self.last_queue_put_at] if marker]
                last_consumer_progress = max(consumer_markers) if consumer_markers else None
                last_producer_progress = max(producer_markers) if producer_markers else None

                if last_consumer_progress is None:
                    stalled_for = (now - (last_producer_progress or now)).total_seconds()
                else:
                    stalled_for = (now - last_consumer_progress).total_seconds()

                threshold = max(self.stall_timeout, 15.0)
                if stalled_for < threshold:
                    continue

                logger.warning(
                    "Pump listener backlog stall detected | stalled_for=%.1fs | queue=%s | inflight=%s | stage=%s | preview=%s"
                    % (stalled_for, queue_size, inflight, self.last_stage, self.last_message_preview)
                )
                self._reconnect_requested = True
                await self.disconnect()
        except asyncio.CancelledError:
            logger.info("Pump listener watchdog cancelled")
        except Exception as e:
            logger.error(f"Pump listener watchdog error: {e}")

    async def _receive_loop(self) -> None:
        """Receive websocket messages and enqueue them immediately."""
        logger.info("Starting receive loop")
        message_count = 0

        try:
            while self.running and self.ws and self.ws_connected:
                try:
                    self._mark_progress("waiting_for_message")
                    message = await asyncio.wait_for(self.ws.recv(), timeout=float(self.receive_timeout))

                    if not message:
                        continue

                    self.last_ws_recv_at = datetime.utcnow()
                    message_count += 1
                    logger.debug(f"Received message #{message_count}: {str(message)[:100]}")
                    self._enqueue_message(message, message_count)

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
                f"Receive loop ended. Received {message_count} messages | queue={self._queue.qsize()} | inflight={self._inflight_messages} | last_stage={self.last_stage} | reconnect_requested={self._reconnect_requested}"
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
        await self._start_workers()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        try:
            await self._reconnect_loop()
        except asyncio.CancelledError:
            logger.info("Listener cancelled")
        finally:
            self.running = False
            if self._watchdog_task:
                self._watchdog_task.cancel()
                await asyncio.gather(self._watchdog_task, return_exceptions=True)
                self._watchdog_task = None
            await self.disconnect()
            await self._stop_workers()

    async def stop(self) -> None:
        """Stop listening."""
        logger.info("Stopping Pump.fun listener")
        self.running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()
            await asyncio.gather(self._watchdog_task, return_exceptions=True)
            self._watchdog_task = None
        await self.disconnect()
        await self._stop_workers()
        logger.info(
            f"Listener stopped. Received: {self.tokens_received}, Failed: {self.tokens_failed}, Dropped: {self.messages_dropped}"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get listener statistics."""
        return {
            "running": self.running,
            "tokens_received": self.tokens_received,
            "tokens_failed": self.tokens_failed,
            "messages_dropped": self.messages_dropped,
            "last_received_at": self.last_received_at,
            "reconnect_attempts": self.reconnect_attempts,
            "ws_connected": self.ws_connected,
            "last_progress_at": self.last_progress_at,
            "last_stage": self.last_stage,
            "last_message_preview": self.last_message_preview,
            "last_ws_recv_at": self.last_ws_recv_at,
            "last_queue_put_at": self.last_queue_put_at,
            "last_queue_get_at": self.last_queue_get_at,
            "last_emit_at": self.last_emit_at,
            "reconnect_requested": self._reconnect_requested,
            "queue_size": self._queue.qsize(),
            "queue_maxsize": self.queue_maxsize,
            "parser_workers": self.parser_workers,
            "inflight_messages": self._inflight_messages,
        }
