"""Real-time monitoring dashboard for live testing"""
import asyncio
from datetime import datetime
from monitoring.logger import setup_logger
from storage.sqlite_store import SQLiteStore
from config.settings import Settings

logger = setup_logger("MonitoringDashboard")

class MonitoringDashboard:
    """Real-time monitoring dashboard"""
    
    def __init__(self):
        self.settings = Settings()
        self.store = SQLiteStore(self.settings)
        self.running = False
    
    async def start(self) -> None:
        """Start monitoring dashboard"""
        self.running = True
        logger.info("Starting monitoring dashboard...")
        
        while self.running:
            try:
                await self.display_dashboard()
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Dashboard error: {e}")
                await asyncio.sleep(10)
    
    async def display_dashboard(self) -> None:
        """Display monitoring dashboard"""
        try:
            stats = self.store.get_statistics()
            
            print("\033[2J\033[H")
            
            print("=" * 100)
            print("MAMUT LIVE MONITORING DASHBOARD".center(100))
            print("=" * 100)
            print(f"Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}".center(100))
            print("=" * 100)
            print()
            
            print("OVERALL STATISTICS")
            print("-" * 100)
            print(f"Total Tokens Discovered:     {stats.get('total_tokens', 0):>10}")
            print(f"Total Signals Generated:     {stats.get('total_signals', 0):>10}")
            print()
            
            print("TOKENS BY RISK LEVEL")
            print("-" * 100)
            for level, count in stats.get('tokens_by_risk', {}).items():
                percentage = (count / stats.get('total_tokens', 1)) * 100
                bar = "█" * int(percentage / 2)
                print(f"{level:<25} {count:>6} ({percentage:>5.1f}%) {bar}")
            print()
            
            print("SIGNALS BY TYPE")
            print("-" * 100)
            for sig_type, count in stats.get('signals_by_type', {}).items():
                total_signals = stats.get('total_signals', 1)
                percentage = (count / total_signals) * 100
                bar = "█" * int(percentage / 5)
                print(f"{sig_type:<25} {count:>6} ({percentage:>5.1f}%) {bar}")
            print()
            
            print("=" * 100)
            
        except Exception as e:
            logger.error(f"Error displaying dashboard: {e}")
    
    async def stop(self) -> None:
        """Stop dashboard"""
        self.running = False


async def main():
    """Main entry point for dashboard"""
    dashboard = MonitoringDashboard()
    
    def signal_handler(signum, frame):
        asyncio.create_task(dashboard.stop())
    
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await dashboard.start()


if __name__ == "__main__":
    asyncio.run(main())