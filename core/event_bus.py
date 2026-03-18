"""Async event bus for decoupled event processing"""
import asyncio
from typing import Callable, Dict, List, Any, Awaitable, Optional
from dataclasses import dataclass
from datetime import datetime
from monitoring.logger import setup_logger

logger = setup_logger("EventBus")

@dataclass
class Event:
    """Base event class"""
    event_type: str
    data: Any
    timestamp: datetime
    source: str
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

class EventBus:
    """Async event bus for decoupled event processing"""
    
    def __init__(self, max_queue_size: int = 10000):
        self._listeners: Dict[str, List[Callable[[Event], Awaitable[None]]]] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._event_count: int = 0
    
    def subscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]) -> str:
        """
        Subscribe to event type
        
        Args:
            event_type: Type of event to subscribe to
            handler: Async handler function that receives Event
            
        Returns:
            Subscription ID
        """
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        
        self._listeners[event_type].append(handler)
        sub_id = f"{event_type}_{id(handler)}"
        logger.debug(f"Subscribed {handler.__name__} to {event_type} (ID: {sub_id})")
        return sub_id
    
    def unsubscribe(self, event_type: str, handler: Callable[[Event], Awaitable[None]]) -> bool:
        """
        Unsubscribe from event type
        
        Args:
            event_type: Type of event
            handler: Handler to remove
            
        Returns:
            True if removed, False if not found
        """
        if event_type in self._listeners and handler in self._listeners[event_type]:
            self._listeners[event_type].remove(handler)
            logger.debug(f"Unsubscribed {handler.__name__} from {event_type}")
            return True
        return False
    
    async def emit(self, event: Event) -> None:
        """
        Emit event to all listeners (non-blocking, queues event)
        
        Args:
            event: Event to emit
        """
        try:
            await self._event_queue.put(event)
            self._event_count += 1
            logger.debug(f"Queued event {event.event_type} from {event.source}")
        except asyncio.QueueFull:
            logger.error(f"Event queue full, dropping event {event.event_type}")
    
    async def emit_sync(self, event: Event) -> None:
        """
        Emit event synchronously (waits for all handlers to complete)
        
        Args:
            event: Event to emit
        """
        if event.event_type in self._listeners:
            handlers = self._listeners[event.event_type]
            logger.debug(f"Emitting event {event.event_type} to {len(handlers)} handlers")
            
            tasks = []
            for handler in handlers:
                try:
                    task = asyncio.create_task(handler(event))
                    tasks.append(task)
                except Exception as e:
                    logger.error(f"Error creating task for {handler.__name__}: {e}")
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _process_events(self) -> None:
        """Process queued events (internal worker)"""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                
                if event.event_type in self._listeners:
                    handlers = self._listeners[event.event_type]
                    tasks = []
                    
                    for handler in handlers:
                        try:
                            task = asyncio.create_task(self._safe_handler_call(handler, event))
                            tasks.append(task)
                        except Exception as e:
                            logger.error(f"Error creating handler task: {e}")
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                
                self._event_queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing event: {e}")
    
    @staticmethod
    async def _safe_handler_call(handler: Callable, event: Event) -> None:
        """Safely call handler with error handling"""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Error in handler {handler.__name__}: {e}")
    
    async def start(self) -> None:
        """Start event bus worker"""
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._process_events())
            logger.info("Event bus started")
    
    async def stop(self) -> None:
        """Stop event bus worker gracefully"""
        if self._running:
            self._running = False
            
            # Wait for queue to drain
            try:
                await asyncio.wait_for(self._event_queue.join(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Event queue did not drain within timeout")
            
            if self._worker_task:
                await self._worker_task
            
            logger.info(f"Event bus stopped. Processed {self._event_count} events")
    
    def get_listener_count(self, event_type: Optional[str] = None) -> Dict[str, int] | int:
        """Get number of listeners"""
        if event_type:
            return len(self._listeners.get(event_type, []))
        return {et: len(handlers) for et, handlers in self._listeners.items()}
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self._event_queue.qsize()
    
    async def wait_queue_empty(self, timeout: float = 5.0) -> bool:
        """Wait for event queue to become empty"""
        try:
            await asyncio.wait_for(self._event_queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

# Global event bus singleton
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    """Get or create global event bus"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus