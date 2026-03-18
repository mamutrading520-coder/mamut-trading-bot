"""Deduplicate signals to prevent duplicate alerts"""
from typing import Dict, Optional, Tuple
from datetime import datetime
from monitoring.logger import setup_logger
from config.thresholds import SIGNAL_DEDUP_CONFIG
from utils.time_utils import get_timestamp, seconds_since

logger = setup_logger("SignalDeduper")

class SignalDeduper:
    """Deduplicates signals within time window"""
    
    def __init__(self):
        self.window = SIGNAL_DEDUP_CONFIG.get("window_seconds", 60)
        self.min_score_diff = SIGNAL_DEDUP_CONFIG.get("min_score_diff", 5)
        
        # Track recent signals: (mint, signal_type) -> (score, timestamp)
        self.recent_signals: Dict[Tuple[str, str], Tuple[float, float]] = {}
        
        self.deduped_count = 0
        self.unique_count = 0
    
    def is_duplicate(self, mint: str, signal_type: str, score: float) -> bool:
        """
        Check if signal is a duplicate
        
        Args:
            mint: Token mint
            signal_type: Type of signal (EARLY, CONFIRMATION, etc)
            score: Signal score
            
        Returns:
            True if duplicate, False if unique
        """
        try:
            key = (mint, signal_type)
            current_time = get_timestamp()
            
            if key not in self.recent_signals:
                # New signal
                self.recent_signals[key] = (score, current_time)
                self.unique_count += 1
                logger.debug(f"New signal: {mint[:8]}... type={signal_type}")
                return False
            
            prev_score, prev_time = self.recent_signals[key]
            elapsed = current_time - prev_time
            
            # Check if within dedup window
            if elapsed > self.window:
                # Outside window, treat as new
                self.recent_signals[key] = (score, current_time)
                self.unique_count += 1
                logger.debug(f"New signal (window expired): {mint[:8]}... type={signal_type}")
                return False
            
            # Check if score difference is significant
            score_diff = abs(score - prev_score)
            if score_diff >= self.min_score_diff:
                # Significant score change, treat as new
                self.recent_signals[key] = (score, current_time)
                self.unique_count += 1
                logger.debug(f"New signal (score changed): {mint[:8]}... type={signal_type} (diff={score_diff:.1f})")
                return False
            
            # Duplicate
            self.deduped_count += 1
            logger.debug(f"Duplicate signal deduped: {mint[:8]}... type={signal_type} (age={elapsed}s)")
            return True
            
        except Exception as e:
            logger.error(f"Error checking duplicate: {e}")
            return False
    
    def cleanup_old_signals(self) -> int:
        """
        Remove signals outside dedup window
        
        Returns:
            Number of signals removed
        """
        try:
            current_time = get_timestamp()
            to_remove = []
            
            for key, (score, timestamp) in self.recent_signals.items():
                elapsed = current_time - timestamp
                if elapsed > self.window:
                    to_remove.append(key)
            
            for key in to_remove:
                del self.recent_signals[key]
            
            if to_remove:
                logger.debug(f"Cleaned up {len(to_remove)} old signals")
            
            return len(to_remove)
            
        except Exception as e:
            logger.error(f"Error cleaning up signals: {e}")
            return 0
    
    def get_stats(self) -> dict:
        """Get deduper statistics"""
        total = self.deduped_count + self.unique_count
        return {
            "unique_signals": self.unique_count,
            "deduped_signals": self.deduped_count,
            "dedup_rate": self.deduped_count / total if total > 0 else 0,
            "tracked_signals": len(self.recent_signals),
        }