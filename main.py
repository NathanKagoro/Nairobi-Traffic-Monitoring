"""
Main entry point for Dar Traffic Monitoring system.
Provides collect, init, audit, healthcheck and validate-points commands
for GitHub Actions and local testing.
"""
import json
import sys
import logging
from datetime import datetime, timezone

from config.settings import (
    TOMTOM_API_KEY,
    SUPABASE_URL,
    SUPABASE_KEY,
    MONITORED_POINTS_FILE,
    COLLECTION_INTERVAL_MINUTES,
    LOCAL_UTC_OFFSET_HOURS,
)
from utils.logger import setup_logger
from utils.time_helpers import get_utc_now_string
from database.init_db import init_database
from database.database_manager import DatabaseManager
from collectors.tomtom_collector import TomTomCollector
from analysis.audit import run_audit, render_report, latest_timestamp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = setup_logger(__name__)


def validate_config() -> bool:
    # Guardrail: fail fast when secrets are missing or still set to placeholders.
    """
    Validate that all required configuration is present.
    
    Returns:
        bool: True if valid, False otherwise
    """
    required_keys = {
        'TOMTOM_API_KEY': TOMTOM_API_KEY,
        'SUPABASE_URL': SUPABASE_URL,
        'SUPABASE_KEY': SUPABASE_KEY,
    }
    
    for key_name, key_value in required_keys.items():
        if not key_value or 'your_' in key_value:
            logger.error(f"Missing or invalid {key_name}. Set environment variable.")
            return False
    
    logger.info("Configuration validated")
    return True


def init() -> bool:
    # One-time setup helper for creating/verifying the storage table.
    """
    Initialize database schema.
    Run once before first collection.
    
    Returns:
        bool: True if successful
    """
    logger.info("Initializing database...")
    
    if not validate_config():
        return False
    
    success = init_database(SUPABASE_URL, SUPABASE_KEY)
    
    if success:
        logger.info("Database initialization complete")
    else:
        logger.error("Database initialization failed")
    
    return success


def collect() -> bool:
    # End-to-end collection cycle: fetch snapshots, then persist them.
    """
    Execute a single traffic collection cycle.
    Collects from all monitoring points and stores in database.
    
    Returns:
        bool: True if successful
    """
    logger.info(f"Starting collection cycle at {get_utc_now_string()}")
    
    if not validate_config():
        return False
    
    try:
        # Initialize collector
        logger.info("Initializing TomTom collector...")
        collector = TomTomCollector(TOMTOM_API_KEY)
        logger.info(f"Ready to collect from {collector.get_point_count()} points")
        
        # Collect data
        logger.info("Collecting traffic data from TomTom...")
        snapshots = collector.collect_all()
        
        if not snapshots:
            logger.error("No data collected")
            return False
        
        logger.info(f"Collected {len(snapshots)} snapshots")
        
        # Connect to database
        logger.info("Connecting to database...")
        db = DatabaseManager(SUPABASE_URL, SUPABASE_KEY)
        
        if not db.connect():
            logger.error("Failed to connect to database")
            return False
        
        # Insert data
        logger.info(f"Inserting {len(snapshots)} snapshots into database...")
        inserted = db.bulk_insert(snapshots)
        db.close()
        
        if inserted == len(snapshots):
            logger.info(f"Successfully inserted {inserted} snapshots")
            logger.info(f"Collection cycle complete at {get_utc_now_string()}")
            return True
        else:
            logger.warning(f"Inserted {inserted}/{len(snapshots)} snapshots")
            return False
            
    except Exception as e:
        logger.error(f"Collection cycle failed: {e}")
        return False


def audit(days: int = None, out_path: str = None) -> bool:
    # Read-only quality check over whatever is already in the database.
    """
    Audit the collected data for coverage, integrity and real-world signal.

    Args:
        days: Only audit snapshots from the last N days (default: everything)
        out_path: Optional path to write the Markdown report to

    Returns:
        bool: True if the audit ran (not a judgement on the data itself)
    """
    if not SUPABASE_URL or 'your_' in SUPABASE_URL:
        logger.error("SUPABASE_URL is not set. Put it in a .env file or export it.")
        return False
    if not SUPABASE_KEY or 'your_' in SUPABASE_KEY:
        logger.error("SUPABASE_KEY is not set. Put it in a .env file or export it.")
        return False

    # The configured point list is the yardstick for "should have reported".
    expected_points = None
    try:
        with open(MONITORED_POINTS_FILE, 'r') as f:
            expected_points = [p['name'] for p in json.load(f)]
    except Exception as e:
        logger.warning(f"Could not load monitored points, auditing without them: {e}")

    report = run_audit(
        SUPABASE_URL,
        SUPABASE_KEY,
        expected_points=expected_points,
        days=days,
        interval_minutes=COLLECTION_INTERVAL_MINUTES,
        local_offset_hours=LOCAL_UTC_OFFSET_HOURS,
    )

    if report is None:
        return False

    markdown = render_report(report)
    print()
    print(markdown)

    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(markdown + "\n")
        logger.info(f"Report written to {out_path}")

    return True


def validate_points_cmd(out_path: str = None) -> bool:
    # Offline-data check: do the configured coordinates match their labels?
    """
    Reverse-geocode every monitoring point and report label/coordinate mismatches.

    Slow by design - OpenStreetMap's Nominatim allows one request per second.

    Returns:
        bool: True if every point matched its claimed location
    """
    from analysis.validate_points import (
        load_points,
        validate_points,
        render_validation,
    )

    points = load_points(MONITORED_POINTS_FILE)
    logger.info(f"Validating {len(points)} points (about {len(points)} seconds)...")

    results = validate_points(points)
    markdown = render_validation(results)
    print()
    print(markdown)

    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(markdown + "\n")
        logger.info(f"Validation written to {out_path}")

    bad = [r for r in results if r["verdict"] in ("MISMATCH", "OFF_AREA")]
    if bad:
        logger.error(f"{len(bad)} of {len(results)} points do not match their labels")
        return False

    logger.info("All points match their labels")
    return True


def healthcheck(max_age_hours: int = 6) -> bool:
    # Cheap liveness probe: is anything still landing in the table?
    """
    Fail if the newest snapshot is older than max_age_hours.

    Run on a schedule so a silently dead pipeline produces a failed job (and
    therefore a notification) instead of months of missing data.

    Returns:
        bool: True if data is fresh
    """
    if not SUPABASE_URL or 'your_' in SUPABASE_URL:
        logger.error("SUPABASE_URL is not set")
        return False
    if not SUPABASE_KEY or 'your_' in SUPABASE_KEY:
        logger.error("SUPABASE_KEY is not set")
        return False

    latest = latest_timestamp(SUPABASE_URL.rstrip('/'), SUPABASE_KEY)

    if latest is None:
        logger.error("No snapshots found, or the table could not be read. "
                     "Check credentials and that the Supabase project is not paused.")
        return False

    age_hours = (datetime.now(timezone.utc) - latest).total_seconds() / 3600.0
    logger.info(f"Newest snapshot: {latest:%Y-%m-%d %H:%M} UTC ({age_hours:.1f}h old)")

    if age_hours > max_age_hours:
        logger.error(f"STALE: newest snapshot is {age_hours:.1f}h old, "
                     f"threshold is {max_age_hours}h. Collection has stopped.")
        return False

    logger.info("Collection is healthy")
    return True


def main():
    # Small CLI dispatcher used by both local runs and CI workflow commands.
    """
    CLI entry point.
    Usage:
        python main.py init     - Initialize database
        python main.py collect  - Run collection cycle
        python main.py audit [--days N] [--out FILE]
                                - Data quality report on stored snapshots
        python main.py healthcheck [--max-age-hours N]
                                - Exit non-zero if collection has stalled
        python main.py validate-points [--out FILE]
                                - Check point coordinates against OpenStreetMap
    """
    usage = (
        "Usage: python main.py [init|collect|audit|healthcheck|validate-points]\n"
        "  audit           [--days N] [--out FILE]\n"
        "  healthcheck     [--max-age-hours N]\n"
        "  validate-points [--out FILE]"
    )

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    def flag(name, cast=str, default=None):
        # Minimal flag parsing keeps the CLI dependency-free.
        if name not in args:
            return default
        try:
            return cast(args[args.index(name) + 1])
        except (IndexError, ValueError):
            print(usage)
            sys.exit(1)

    if command == 'init':
        success = init()
    elif command == 'collect':
        success = collect()
    elif command == 'audit':
        success = audit(days=flag('--days', int), out_path=flag('--out'))
    elif command == 'healthcheck':
        success = healthcheck(max_age_hours=flag('--max-age-hours', int, 6))
    elif command == 'validate-points':
        success = validate_points_cmd(out_path=flag('--out'))
    else:
        print(f"Unknown command: {command}")
        print(usage)
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
