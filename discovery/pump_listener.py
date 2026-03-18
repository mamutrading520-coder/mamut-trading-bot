"""Pump.fun WebSocket listener for token discovery"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
from monitoring.logger import setup_logger
from config.settings import Settings
from core.event_bus import Event, get_event_bus
from discovery.pump_event_parser import PumpEventParser, ParsedTokenEvent
import websockets

logger = setup_logger("PumpListener")

class PumpListener:
    """Listens to Pump.fun for new token launches"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.parser = PumpEventParser()
        
        self.ws_url = settings.pump_ws_url
        self.reconnect_delay = settings.pump_reconnect_delay
        self.initial_reconnect_delay = settings.pump_reconnect_delay
        self.max_retries = settings.pump_max_retries
        
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.ws_connected = False
        
        self.tokens_received = 0
        self.tokens_failed = 0
        self.last_received_at: Optional[datetime] = None
        self.reconnect_attempts = 0
    
    async def connect(self) -> bool:
        """Connect to Pump.fun WebSocket"""
        try:
            logger.info(f"Connecting to Pump.fun WebSocket: {self.ws_url}")
            
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10
                ),
                timeout=10.0
            )
            
            self.ws_connected = True
            self.reconnect_attempts = 0
            self.reconnect_delay = self.initial_reconnect_delay
            logger.info("✓ Connected to Pump.fun WebSocket")
            return True
            
        except asyncio.TimeoutError:
            logger.warning("Connection timeout")
            self.ws_connected = False
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.ws_connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket"""
        try:
            if self.ws:
                try:
                    await asyncio.wait_for(self.ws.close(), timeout=5.0)
                except:
                    pass
            self.ws_connected = False
            logger.info("Disconnected from Pump.fun WebSocket")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
    
    async def subscribe_new_token(self) -> bool:
        """Subscribe to new token events"""
        try:
            if not self.ws:
                logger.error("WebSocket not connected")
                return False
        
            # Correct subscription format for pumpportal
            subscribe_msg = {
                "method": "subscribeNewToken"
            }
        
            logger.info(f"Attempting subscription with: {subscribe_msg}")
            await asyncio.wait_for(
                self.ws.send(json.dumps(subscribe_msg)),
                timeout=5.0
            )
            logger.info("✓ Subscription sent")
        
            # Wait for confirmation
            try:
                response = await asyncio.wait_for(self.ws.recv(), timeout=2.0)
                logger.info(f"Subscription response: {response[:200]}")
                return True
            except asyncio.TimeoutError:
                logger.warning("No subscription response, continuing anyway...")
                return True
        
        except Exception as e:
            logger.error(f"Subscribe error: {e}")
            return False
    
    def _parse_event(self, message: str) -> Optional[ParsedTokenEvent]:
        """Parse WebSocket message"""
        try:
            data = json.loads(message)
            
            # Log raw message for debugging
            logger.debug(f"Raw message: {str(message)[:200]}")
            
            # Skip subscription confirmations and non-dict messages
            if isinstance(data, dict):
                # Skip subscription responses
                if data.get("method") or data.get("result"):
                    logger.debug(f"Skipping non-token message: {data}")
                    return None
                
                # Check if it has token data
                if not data.get("mint") or not data.get("signature"):
                    logger.debug(f"Missing mint or signature in: {str(data)[:100]}")
                    return None
                
                # Parse token
                parsed = self.parser.parse(data)
                if parsed:
                    logger.info(f"✓ Parsed token: {parsed.symbol} ({parsed.mint[:8]}...)")
                    return parsed
                else:
                    logger.warning(f"Parser returned None for: {str(data)[:100]}")
                    return None
            
            return None
            
        except json.JSONDecodeError as e:
            logger.debug(f"Invalid JSON: {str(message)[:100]}")
            return None
        except Exception as e:
            logger.debug(f"Parse error: {e}")
            self.tokens_failed += 1
            return None
    
    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket"""
        logger.info("Starting receive loop")
        message_count = 0
        
        try:
            while self.running and self.ws and self.ws_connected:
                try:
                    # Timeout para detectar conexión muerta
                    message = await asyncio.wait_for(self.ws.recv(), timeout=60.0)
                    
                    if message:
                        message_count += 1
                        logger.debug(f"Received message #{message_count}: {str(message)[:100]}")
                        
                        event = self._parse_event(message)
                        if event:
                            self.tokens_received += 1
                            self.last_received_at = datetime.utcnow()
                            logger.info(f"[{self.tokens_received}] Emitting: {event.symbol}")
                            
                            # Emit event
                            token_event = Event(
                                event_type="TokenDiscovered",
                                data=event.to_dict(),
                                source="PumpListener",
                                timestamp=datetime.utcnow()
                            )
                            await self.event_bus.emit(token_event)
                        
                except asyncio.TimeoutError:
                    logger.warning(f"WebSocket receive timeout after {message_count} messages, reconnecting...")
                    break
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"WebSocket connection closed: {e}")
                    break
                except Exception as e:
                    logger.error(f"Receive error: {e}")
                    break
                    
        except asyncio.CancelledError:
            logger.info("Receive loop cancelled")
        finally:
            self.ws_connected = False
            logger.info(f"Receive loop ended. Received {message_count} messages")
    
    async def _reconnect_loop(self) -> None:
        """Reconnect loop with exponential backoff"""
        while self.running:
            try:
                if not self.ws_connected and self.reconnect_attempts < self.max_retries:
                    self.reconnect_attempts += 1
                    logger.info(f"Reconnect attempt {self.reconnect_attempts}/{self.max_retries}")
                    
                    if await self.connect():
                        await asyncio.sleep(1)  # Brief pause after connect
                        if await self.subscribe_new_token():
                            await self._receive_loop()
                        else:
                            await self.disconnect()
                    
                    if self.running and not self.ws_connected:
                        logger.info(f"Reconnecting in {self.reconnect_delay}s...")
                        await asyncio.sleep(self.reconnect_delay)
                        # Exponential backoff: 5s -> 10s -> 20s -> 40s... max 60s
                        self.reconnect_delay = min(self.reconnect_delay * 2, 60)
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logger.info("Reconnect loop cancelled")
                break
            except Exception as e:
                logger.error(f"Reconnect loop error: {e}")
                await asyncio.sleep(5)
    
    async def start(self) -> None:
        """Start listening to Pump.fun"""
        logger.info("Starting Pump.fun listener")
        self.running = True
        
        try:
            await self._reconnect_loop()
        except asyncio.CancelledError:
            logger.info("Listener cancelled")
        finally:
            self.running = False
            await self.disconnect()
    
    async def stop(self) -> None:
        """Stop listening"""
        logger.info("Stopping Pump.fun listener")
        self.running = False
        await self.disconnect()
        logger.info(f"Listener stopped. Received: {self.tokens_received}, Failed: {self.tokens_failed}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get listener statistics"""
        return {
            "running": self.running,
            "tokens_received": self.tokens_received,
            "tokens_failed": self.tokens_failed,
            "last_received_at": self.last_received_at,
            "reconnect_attempts": self.reconnect_attempts,
            "ws_connected": self.ws_connected,
        }