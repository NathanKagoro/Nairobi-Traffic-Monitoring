"""
Central configuration for Dar Traffic Monitoring system.
Loads settings from environment variables and defaults.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env when present so local runs (and the audit tool) pick up
# credentials without exporting them by hand. GitHub Actions supplies these as
# real environment variables, where load_dotenv() is a harmless no-op.
load_dotenv()

# API Configuration
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "your_tomtom_api_key_here")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "your_supabase_url_here")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your_supabase_key_here")

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CITIES_DIR = CONFIG_DIR / "cities"

# Which city to collect for. Each city has its own point list under
# config/cities/, so switching target is a one-line change rather than an
# overwrite - and the previous city's points stay available for comparison.
CITY = os.getenv("CITY", "dar_es_salaam")

_city_points = CITIES_DIR / f"{CITY}.json"
# Fall back to the legacy single-city path so older checkouts keep working.
MONITORED_POINTS_FILE = (
    _city_points if _city_points.exists() else CONFIG_DIR / "monitored_points.json"
)

# Collection cadence, in minutes. Used by the audit tool to work out how many
# collection cycles *should* exist between the first and last snapshot.
COLLECTION_INTERVAL_MINUTES = int(os.getenv("COLLECTION_INTERVAL_MINUTES", "30"))

# Local timezone offset (hours from UTC) used only for human-readable
# hour-of-day breakdowns in reports. Nairobi/Dar es Salaam are both UTC+3.
LOCAL_UTC_OFFSET_HOURS = int(os.getenv("LOCAL_UTC_OFFSET_HOURS", "3"))

# Logging
LOG_LEVEL = "INFO"
