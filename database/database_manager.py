"""
Database manager for traffic snapshots.
Uses Supabase REST API (HTTPS) instead of direct PostgreSQL connection.
This avoids firewall/port issues with GitHub Actions runners.
"""
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages insert and query operations via Supabase REST API."""

    def __init__(self, supabase_url: str, supabase_key: str):
        """
        Initialize database manager.

        Args:
            supabase_url: Supabase project URL (https://xxxxx.supabase.co)
            supabase_key: Supabase service_role key
        """
        # Normalise URL — strip trailing slash
        self.base_url = supabase_url.rstrip("/")
        self.supabase_key = supabase_key
        self.headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def connect(self) -> bool:
        """
        Verify Supabase REST API is reachable by making a lightweight HEAD request.

        Returns:
            bool: True if reachable, False otherwise
        """
        try:
            url = f"{self.base_url}/rest/v1/traffic_snapshots?limit=1"
            response = requests.get(url, headers=self.headers, timeout=10)
            # 200 means table exists, 404 means table missing — both mean API is reachable
            if response.status_code in (200, 404):
                logger.info("Supabase REST API reachable")
                return True
            logger.error(f"Unexpected status {response.status_code}: {response.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to reach Supabase API: {e}")
            return False

    def close(self):
        """No-op — REST API has no persistent connection to close."""
        pass

    def bulk_insert(self, snapshots: List[Dict]) -> int:
        """
        Insert multiple traffic snapshots via Supabase REST API.

        Args:
            snapshots: List of snapshot dictionaries

        Returns:
            int: Number of snapshots sent (REST API returns no row count in minimal mode)
        """
        if not snapshots:
            return 0

        # Normalise each snapshot to match column names
        rows = [
            {
                "timestamp": s.get("timestamp"),
                "point_name": s.get("point_name"),
                "latitude": s.get("latitude"),
                "longitude": s.get("longitude"),
                "current_speed": s.get("current_speed"),
                "free_flow_speed": s.get("free_flow_speed"),
                "congestion_ratio": s.get("congestion_ratio"),
                "road_closure": s.get("road_closure", 0),
                "confidence": s.get("confidence"),
            }
            for s in snapshots
        ]

        try:
            url = f"{self.base_url}/rest/v1/traffic_snapshots"
            response = requests.post(url, headers=self.headers, json=rows, timeout=30)

            if response.status_code in (200, 201):
                logger.info(f"Inserted {len(rows)} snapshots via REST API")
                return len(rows)
            else:
                logger.error(f"Insert failed [{response.status_code}]: {response.text}")
                return 0

        except Exception as e:
            logger.error(f"Failed to bulk insert snapshots: {e}")
            return 0

    def insert_snapshot(self, snapshot: Dict) -> bool:
        """Insert a single snapshot."""
        return self.bulk_insert([snapshot]) == 1

    def query_recent(self, point_name: Optional[str] = None,
                     limit: int = 100) -> List[Dict]:
        """
        Query recent traffic snapshots via REST API.

        Args:
            point_name: Optional filter by point name
            limit: Maximum rows to return

        Returns:
            List of snapshot dictionaries
        """
        try:
            url = f"{self.base_url}/rest/v1/traffic_snapshots"
            params = {
                "order": "timestamp.desc",
                "limit": limit,
            }
            if point_name:
                params["point_name"] = f"eq.{point_name}"

            headers = {**self.headers, "Prefer": "return=representation"}
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()
            logger.error(f"Query failed [{response.status_code}]: {response.text}")
            return []

        except Exception as e:
            logger.error(f"Failed to query snapshots: {e}")
            return []
