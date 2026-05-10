"""
Initialize Supabase PostgreSQL database schema for traffic monitoring.
"""
import psycopg2
from psycopg2 import sql
import logging

logger = logging.getLogger(__name__)


def init_database(supabase_url: str, supabase_key: str) -> bool:
    """
    Initialize the database schema.
    Creates the traffic_snapshots table if it doesn't exist.
    
    Args:
        supabase_url: Supabase project URL (https://xxxxx.supabase.co)
        supabase_key: Supabase service_role key
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Extract project ID from URL (https://uvplijpdnimjhjtlvklk.supabase.co -> uvplijpdnimjhjtlvklk)
        if "supabase.co" in supabase_url:
            # Handle both https://xxx.supabase.co and xxx.supabase.co formats
            project_id = supabase_url.replace("https://", "").replace(".supabase.co", "")
        else:
            logger.error("Invalid SUPABASE_URL format")
            return False
        
        # Build connection string for Supabase
        # Format: postgresql://postgres:[service_role_key]@db.[project-id].supabase.co:5432/postgres
        conn_string = f"postgresql://postgres:{supabase_key}@db.{project_id}.supabase.co:5432/postgres?sslmode=require"
        
        logger.info(f"Connecting to Supabase project: {project_id}")
        conn = psycopg2.connect(conn_string)
        cursor = conn.cursor()
        
        # Create traffic_snapshots table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS traffic_snapshots (
            id SERIAL PRIMARY KEY,
            timestamp TEXT NOT NULL,
            point_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            current_speed REAL,
            free_flow_speed REAL,
            congestion_ratio REAL,
            road_closure INTEGER DEFAULT 0,
            confidence REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        cursor.execute(create_table_sql)
        
        # Create index on timestamp for faster queries
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_traffic_timestamp 
        ON traffic_snapshots(timestamp);
        """)
        
        # Create index on point_name for queries by location
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_traffic_point_name 
        ON traffic_snapshots(point_name);
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info("Database schema initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return False


if __name__ == "__main__":
    # For testing: python -m database.init_db
    import os
    from config.settings import SUPABASE_URL, SUPABASE_KEY
    
    logging.basicConfig(level=logging.INFO)
    
    url = os.getenv("SUPABASE_URL") or SUPABASE_URL
    key = os.getenv("SUPABASE_KEY") or SUPABASE_KEY
    
    if "your_" in url or "your_" in key:
        print("Error: Please set SUPABASE_URL and SUPABASE_KEY environment variables")
        exit(1)
    
    success = init_database(url, key)
    exit(0 if success else 1)
