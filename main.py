"""
Main entry point for Dar Traffic Monitoring system.
Provides collect() and init() functions for GitHub Actions and local testing.
"""
import os
import sys
import logging
from typing import Callable

from config.settings import (
    TOMTOM_API_KEY,
    SUPABASE_URL,
    SUPABASE_KEY,
    COLLECTION_INTERVAL_MINUTES,
)
from utils.logger import setup_logger
from utils.time_helpers import get_utc_now_string
from database.init_db import init_database
from database.database_manager import DatabaseManager
from collectors.tomtom_collector import TomTomCollector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = setup_logger(__name__)


def validate_config() -> bool:
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


def main():
    """
    CLI entry point.
    Usage:
        python main.py init     - Initialize database
        python main.py collect  - Run collection cycle
    """
    if len(sys.argv) < 2:
        print("Usage: python main.py [init|collect]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'init':
        success = init()
    elif command == 'collect':
        success = collect()
    else:
        print(f"Unknown command: {command}")
        print("Usage: python main.py [init|collect]")
        sys.exit(1)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
