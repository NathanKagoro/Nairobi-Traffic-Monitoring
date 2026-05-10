"""
Time utilities for traffic monitoring system.
Handles timestamp formatting and interval calculations.
"""
from datetime import datetime, timezone


# Render UTC time in a human-friendly format for logs and status messages.
def get_utc_now_string() -> str:
    """
    Get current UTC time as readable string.
    
    Returns:
        Formatted timestamp string (YYYY-MM-DD HH:MM:SS UTC)
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
