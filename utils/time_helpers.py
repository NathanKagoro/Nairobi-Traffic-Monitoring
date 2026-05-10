"""
Time utilities for traffic monitoring system.
Handles timestamp formatting and interval calculations.
"""
from datetime import datetime, timezone
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


def get_utc_now_iso() -> str:
    """
    Get current UTC time in ISO 8601 format.
    
    Returns:
        ISO 8601 formatted timestamp string
    """
    return datetime.now(timezone.utc).isoformat()


def get_utc_now_string() -> str:
    """
    Get current UTC time as readable string.
    
    Returns:
        Formatted timestamp string (YYYY-MM-DD HH:MM:SS UTC)
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def seconds_until_next_interval(interval_minutes: int) -> int:
    """
    Calculate seconds until next interval boundary.
    
    Args:
        interval_minutes: Interval in minutes (e.g., 30)
        
    Returns:
        Seconds to wait
    """
    now = datetime.now(timezone.utc)
    
    # Calculate next interval
    total_seconds = now.hour * 3600 + now.minute * 60 + now.second
    interval_seconds = interval_minutes * 60
    
    seconds_into_interval = total_seconds % interval_seconds
    seconds_until_next = interval_seconds - seconds_into_interval
    
    logger.debug(f"Seconds until next interval: {seconds_until_next}")
    return seconds_until_next


def parse_timestamp(timestamp_str: str) -> datetime:
    """
    Parse ISO 8601 timestamp string.
    
    Args:
        timestamp_str: ISO 8601 format timestamp
        
    Returns:
        datetime object
    """
    try:
        # Handle with or without timezone info
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        return datetime.fromisoformat(timestamp_str)
    except Exception as e:
        logger.error(f"Failed to parse timestamp {timestamp_str}: {e}")
        return None
