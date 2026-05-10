"""
TomTom traffic collector.
Queries TomTom Traffic Flow API and collects traffic data.
"""
import json
import logging
from typing import List, Dict, Optional
from pathlib import Path

from config.settings import MONITORED_POINTS_FILE
from utils.api_helpers import make_request, parse_traffic_response
from utils.time_helpers import get_utc_now_iso

logger = logging.getLogger(__name__)

# TomTom API endpoint
TOMTOM_TRAFFIC_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/20/json"


class TomTomCollector:
    """Collects traffic data from TomTom API."""
    
    def __init__(self, api_key: str, timeout: int = 10, max_retries: int = 3):
        """
        Initialize collector.
        
        Args:
            api_key: TomTom API key
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts per point
        """
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.monitored_points = self._load_points()
    
    def _load_points(self) -> List[Dict]:
        """
        Load monitoring points from JSON file.
        
        Returns:
            List of point dictionaries
        """
        try:
            with open(MONITORED_POINTS_FILE, 'r') as f:
                points = json.load(f)
            logger.info(f"Loaded {len(points)} monitoring points")
            return points
        except Exception as e:
            logger.error(f"Failed to load monitoring points: {e}")
            return []
    
    def collect_all(self) -> List[Dict]:
        """
        Collect traffic data for all monitoring points.
        
        Returns:
            List of traffic snapshots
        """
        snapshots = []
        successful = 0
        failed = 0
        
        logger.info(f"Starting collection for {len(self.monitored_points)} points")
        
        for point in self.monitored_points:
            snapshot = self._collect_point(point)
            if snapshot:
                snapshots.append(snapshot)
                successful += 1
            else:
                failed += 1
        
        logger.info(f"Collection complete: {successful} successful, {failed} failed")
        return snapshots
    
    def _collect_point(self, point: Dict) -> Optional[Dict]:
        """
        Collect traffic data for a single point.
        
        Args:
            point: Point dictionary with 'name', 'lat', 'lon'
            
        Returns:
            Traffic snapshot or None if failed
        """
        name = point.get('name')
        lat = point.get('lat')
        lon = point.get('lon')
        
        if not all([name, lat, lon]):
            logger.warning(f"Invalid point definition: {point}")
            return None
        
        try:
            # TomTom Traffic Flow API: zoom level is in the URL path, not a query param
            params = {
                'point': f'{lat},{lon}'
            }
            
            response = make_request(
                TOMTOM_TRAFFIC_FLOW_URL,
                params,
                self.api_key,
                timeout=self.timeout,
                max_retries=self.max_retries
            )
            
            if not response:
                logger.warning(f"No response for point {name}")
                return None
            
            snapshot = parse_traffic_response(response, name, lat, lon)
            
            if snapshot:
                logger.debug(f"Collected data for {name}")
                return snapshot
            else:
                logger.warning(f"Failed to parse response for {name}")
                return None
                
        except Exception as e:
            logger.error(f"Error collecting point {name}: {e}")
            return None
    
    def get_point_count(self) -> int:
        """Get total number of monitoring points."""
        return len(self.monitored_points)


if __name__ == "__main__":
    # For testing: python -m collectors.tomtom_collector
    import os
    from utils.logger import setup_logger
    
    logging.basicConfig(level=logging.INFO)
    setup_logger(__name__)
    
    api_key = os.getenv("TOMTOM_API_KEY", "test_key")
    if api_key == "test_key":
        print("Error: Please set TOMTOM_API_KEY environment variable")
        exit(1)
    
    collector = TomTomCollector(api_key)
    snapshots = collector.collect_all()
    
    print(f"\nCollected {len(snapshots)} snapshots")
    if snapshots:
        print(f"Sample: {snapshots[0]}")
