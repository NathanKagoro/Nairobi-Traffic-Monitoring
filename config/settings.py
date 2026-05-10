"""
Central configuration for Dar Traffic Monitoring system.
Loads settings from environment variables and defaults.
"""
import os
from pathlib import Path

# API Configuration
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "your_tomtom_api_key_here")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "your_supabase_url_here")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your_supabase_key_here")

# Collection Configuration
COLLECTION_INTERVAL_MINUTES = 30
REQUEST_TIMEOUT = 10  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Database Configuration
DB_TABLE_NAME = "traffic_snapshots"

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
MONITORED_POINTS_FILE = CONFIG_DIR / "monitored_points.json"

# Logging
LOG_LEVEL = "INFO"
