"""Main entry point for Mamut engine"""
import asyncio
import signal
import sys
from typing import Optional

from monitoring.logger import setup_logger
from config.settings import Settings
from core.orchestrator import Orchestrator

logger = setup_logger("Main")


class MamutApp:
    """Main Mamut application"""

    def __init__(self):
        self.settings = Settings()
        self.orchestrator = Orchestrator(self.settings)
        self.running = False
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_complete = False
        self._main_task: Optional[asyncio.Task] = None

    async def start(self) -> int:
        """Start the application."""
        try:
            logger.info("Starting Mamut application...")
            self.running = True
            self._main_task = asyncio.current_task()

            initialized = await self.orchestrator.initialize()
            if not initialized:
                logger.error("Orchestrator initialization failed")
                return 1

            await self.orchestrator.run()
            return 0

        except asyncio.CancelledError:
            logger.info("Application task cancelled")
            return 0
        except Exception as e:
            logger.error(f"Error starting application: {e}")
            return 1
        finally:
            self.running = False
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the application safely and only once."""
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return

            try:
                logger.info("Shutting down Mamut application...")
                self.running = False
                await self.orchestrator.shutdown()

                stats = self.orchestrator.get_stats()
                logger.info("Final statistics:")
                logger.info(f"  Lock Manager: {stats.get('lock_manager')}")
                logger.info(f"  Signal Deduper: {stats.get('signal_deduper')}")
                logger.info(f"  Storage: {stats.get('storage')}")

            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
            finally:
                self._shutdown_complete = True

    def handle_signal(self, signum, frame):
        """Handle system signals."""
        logger.info(f"Received signal {signum}")
        self.running = False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        loop.call_soon_threadsafe(lambda: asyncio.create_task(self.shutdown()))


async def main() -> int:
    """Main entry point."""
    app = MamutApp()

    try:
        signal.signal(signal.SIGINT, app.handle_signal)
        signal.signal(signal.SIGTERM, app.handle_signal)
        return await app.start()

    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        await app.shutdown()
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        await app.shutdown()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
