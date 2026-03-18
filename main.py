"""Main entry point for Mamut engine"""
import asyncio
import signal
import sys
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
    
    async def start(self) -> None:
        """Start the application"""
        try:
            logger.info("Starting Mamut application...")
            self.running = True
            
            # Initialize and run orchestrator
            await self.orchestrator.initialize()
            await self.orchestrator.run()
            
        except Exception as e:
            logger.error(f"Error starting application: {e}")
            self.running = False
        finally:
            await self.shutdown()
    
    async def shutdown(self) -> None:
        """Shutdown the application"""
        try:
            logger.info("Shutting down Mamut application...")
            self.running = False
            await self.orchestrator.shutdown()
            
            # Print final statistics
            stats = self.orchestrator.get_stats()
            logger.info("Final statistics:")
            logger.info(f"  Lock Manager: {stats.get('lock_manager')}")
            logger.info(f"  Signal Deduper: {stats.get('signal_deduper')}")
            logger.info(f"  Storage: {stats.get('storage')}")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    def handle_signal(self, signum, frame):
        """Handle system signals"""
        logger.info(f"Received signal {signum}")
        asyncio.create_task(self.shutdown())

async def main():
    """Main entry point"""
    try:
        app = MamutApp()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, app.handle_signal)
        signal.signal(signal.SIGTERM, app.handle_signal)
        
        # Start application
        await app.start()
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
