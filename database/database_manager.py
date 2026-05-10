"""
Database manager for traffic snapshots.
Handles all CRUD operations with Supabase PostgreSQL.
"""
import psycopg2
from psycopg2 import sql
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages connections and operations with Supabase PostgreSQL."""
    
    def __init__(self, supabase_url: str, supabase_key: str):
        """
        Initialize database manager.
        
        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase API key
        """
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.connection = None
        
    def connect(self) -> bool:
        """
        Establish connection to Supabase PostgreSQL.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Extract project ID from URL
            if "supabase.co" in self.supabase_url:
                project_id = self.supabase_url.replace("https://", "").replace(".supabase.co", "")
            else:
                logger.error("Invalid SUPABASE_URL format")
                return False
            
            # Build connection string with SSL requirement for Supabase
            conn_string = f"postgresql://postgres:{self.supabase_key}@db.{project_id}.supabase.co:5432/postgres?sslmode=require"
            
            self.connection = psycopg2.connect(conn_string)
            logger.info("Database connection established")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False
    
    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")
    
    def insert_snapshot(self, snapshot: Dict) -> bool:
        """
        Insert a single traffic snapshot.
        
        Args:
            snapshot: Dictionary with keys: timestamp, point_name, latitude, longitude,
                     current_speed, free_flow_speed, congestion_ratio, road_closure, confidence
                     
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            cursor = self.connection.cursor()
            
            insert_sql = """
            INSERT INTO traffic_snapshots 
            (timestamp, point_name, latitude, longitude, current_speed, 
             free_flow_speed, congestion_ratio, road_closure, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cursor.execute(insert_sql, (
                snapshot.get('timestamp'),
                snapshot.get('point_name'),
                snapshot.get('latitude'),
                snapshot.get('longitude'),
                snapshot.get('current_speed'),
                snapshot.get('free_flow_speed'),
                snapshot.get('congestion_ratio'),
                snapshot.get('road_closure', 0),
                snapshot.get('confidence')
            ))
            
            self.connection.commit()
            cursor.close()
            return True
            
        except Exception as e:
            logger.error(f"Failed to insert snapshot: {e}")
            if self.connection:
                self.connection.rollback()
            return False
    
    def bulk_insert(self, snapshots: List[Dict]) -> int:
        """
        Insert multiple traffic snapshots in batch.
        
        Args:
            snapshots: List of snapshot dictionaries
            
        Returns:
            int: Number of successfully inserted rows
        """
        if not snapshots:
            return 0
            
        try:
            cursor = self.connection.cursor()
            
            insert_sql = """
            INSERT INTO traffic_snapshots 
            (timestamp, point_name, latitude, longitude, current_speed, 
             free_flow_speed, congestion_ratio, road_closure, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            data = [
                (
                    s.get('timestamp'),
                    s.get('point_name'),
                    s.get('latitude'),
                    s.get('longitude'),
                    s.get('current_speed'),
                    s.get('free_flow_speed'),
                    s.get('congestion_ratio'),
                    s.get('road_closure', 0),
                    s.get('confidence')
                )
                for s in snapshots
            ]
            
            cursor.executemany(insert_sql, data)
            self.connection.commit()
            
            rows_inserted = cursor.rowcount
            cursor.close()
            
            logger.info(f"Inserted {rows_inserted} snapshots")
            return rows_inserted
            
        except Exception as e:
            logger.error(f"Failed to bulk insert snapshots: {e}")
            if self.connection:
                self.connection.rollback()
            return 0
    
    def query_recent(self, point_name: Optional[str] = None, 
                    limit: int = 100) -> List[Dict]:
        """
        Query recent traffic snapshots.
        
        Args:
            point_name: Optional filter by point name
            limit: Maximum number of rows to return
            
        Returns:
            List of snapshot dictionaries
        """
        try:
            cursor = self.connection.cursor()
            
            if point_name:
                query = """
                SELECT * FROM traffic_snapshots 
                WHERE point_name = %s 
                ORDER BY timestamp DESC 
                LIMIT %s
                """
                cursor.execute(query, (point_name, limit))
            else:
                query = """
                SELECT * FROM traffic_snapshots 
                ORDER BY timestamp DESC 
                LIMIT %s
                """
                cursor.execute(query, (limit,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            cursor.close()
            return results
            
        except Exception as e:
            logger.error(f"Failed to query recent snapshots: {e}")
            return []
    
    def get_latest_by_point(self) -> Dict[str, Dict]:
        """
        Get the latest snapshot for each monitoring point.
        
        Returns:
            Dictionary mapping point_name to latest snapshot
        """
        try:
            cursor = self.connection.cursor()
            
            query = """
            SELECT DISTINCT ON (point_name) *
            FROM traffic_snapshots
            ORDER BY point_name, timestamp DESC
            """
            
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]
            results = {}
            
            for row in cursor.fetchall():
                snapshot = dict(zip(columns, row))
                results[snapshot['point_name']] = snapshot
            
            cursor.close()
            return results
            
        except Exception as e:
            logger.error(f"Failed to get latest snapshots: {e}")
            return {}
