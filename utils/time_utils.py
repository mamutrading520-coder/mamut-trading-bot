"""Time utility functions for Mamut"""
from datetime import datetime, timedelta, timezone
from typing import Union

def get_timestamp() -> int:
    """Get current Unix timestamp (seconds)"""
    return int(datetime.now(timezone.utc).timestamp())

def get_timestamp_ms() -> int:
    """Get current Unix timestamp (milliseconds)"""
    return int(datetime.now(timezone.utc).timestamp() * 1000)

def timestamp_to_datetime(timestamp: Union[int, float]) -> datetime:
    """Convert Unix timestamp to datetime"""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)

def datetime_to_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp"""
    return int(dt.timestamp())

def get_time_ago(seconds: int) -> datetime:
    """Get datetime for N seconds ago"""
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)

def get_hours_ago(hours: int) -> datetime:
    """Get datetime for N hours ago"""
    return datetime.now(timezone.utc) - timedelta(hours=hours)

def get_days_ago(days: int) -> datetime:
    """Get datetime for N days ago"""
    return datetime.now(timezone.utc) - timedelta(days=days)

def seconds_since(timestamp: Union[int, float]) -> int:
    """Get seconds elapsed since timestamp"""
    return get_timestamp() - int(timestamp)

def minutes_since(timestamp: Union[int, float]) -> float:
    """Get minutes elapsed since timestamp"""
    return seconds_since(timestamp) / 60

def hours_since(timestamp: Union[int, float]) -> float:
    """Get hours elapsed since timestamp"""
    return seconds_since(timestamp) / 3600

def days_since(timestamp: Union[int, float]) -> float:
    """Get days elapsed since timestamp"""
    return seconds_since(timestamp) / 86400

def format_duration(seconds: int) -> str:
    """Format duration in seconds to readable string"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    elif seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    else:
        return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"

def is_within_window(timestamp: Union[int, float], window_seconds: int) -> bool:
    """Check if timestamp is within time window"""
    return seconds_since(timestamp) <= window_seconds