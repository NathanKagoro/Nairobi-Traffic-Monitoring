"""
Database schema initialization helper.

The table must be created manually in Supabase SQL Editor (one-time setup).
This module provides the SQL and verifies the table exists via REST API.
"""
import logging
import requests

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS traffic_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    point_name  TEXT NOT NULL,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    current_speed    REAL,
    free_flow_speed  REAL,
    congestion_ratio REAL,
    road_closure     INTEGER DEFAULT 0,
    confidence       REAL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traffic_timestamp  ON traffic_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_traffic_point_name ON traffic_snapshots(point_name);
"""


def init_database(supabase_url: str, supabase_key: str) -> bool:
    """
    Verify the traffic_snapshots table exists via Supabase REST API.
    If it doesn't exist, print the SQL needed to create it.

    Args:
        supabase_url: Supabase project URL (https://xxxxx.supabase.co)
        supabase_key: Supabase service_role key

    Returns:
        bool: True if table exists and is reachable
    """
    base_url = supabase_url.rstrip("/")
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }

    try:
        url = f"{base_url}/rest/v1/traffic_snapshots?limit=1"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info("traffic_snapshots table exists and is accessible")
            return True

        if response.status_code == 404:
            logger.error(
                "Table 'traffic_snapshots' does not exist in Supabase.\n"
                "Please run the following SQL in your Supabase SQL Editor "
                "(https://app.supabase.com → SQL Editor):\n\n"
                + CREATE_TABLE_SQL
            )
            return False

        logger.error(f"Unexpected response [{response.status_code}]: {response.text}")
        return False

    except Exception as e:
        logger.error(f"Failed to reach Supabase API: {e}")
        return False
