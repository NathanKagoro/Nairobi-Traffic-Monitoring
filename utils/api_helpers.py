"""
API helper utilities for TomTom requests.
Handles retries, rate limiting, and request formatting.
"""
import requests
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def make_request(
    url: str,
    params: Dict[str, Any],
    api_key: str,
    timeout: int = 10,
    max_retries: int = 3,
    retry_delay: int = 2
) -> Optional[Dict[str, Any]]:
    """
    Make API request with retry logic.
    
    Args:
        url: API endpoint URL
        params: Query parameters
        api_key: TomTom API key
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        
    Returns:
        JSON response or None if all retries fail
    """
    params['key'] = api_key
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            
            logger.debug(f"Request successful: {url}")
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.warning(f"Request timeout (attempt {attempt + 1}/{max_retries})")
            
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error (attempt {attempt + 1}/{max_retries})")
            
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:  # Rate limit
                logger.warning(f"Rate limited. Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
                continue
            else:
                logger.error(f"HTTP error {response.status_code}: {e} | Response: {response.text[:500]}")
                return None
                
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None
        
        # Wait before retry
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
    
    logger.error(f"Request failed after {max_retries} retries: {url}")
    return None


def parse_traffic_response(
    response: Dict[str, Any],
    point_name: str,
    latitude: float,
    longitude: float
) -> Optional[Dict[str, Any]]:
    """
    Parse TomTom Traffic Flow API response.
    
    Args:
        response: API response JSON
        point_name: Name of monitoring point
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        
    Returns:
        Normalized snapshot dictionary or None if parsing fails
    """
    try:
        # TomTom Traffic Flow API returns data in flowSegmentData array
        logger.debug(f"Full response for {point_name}: {response}")
        
        if 'flowSegmentData' not in response or not response['flowSegmentData']:
            logger.warning(f"No flow segment data for {point_name}. Response: {response}")
            return None
        
        segment = response['flowSegmentData'][0]
        
        current_speed = segment.get('currentSpeed')
        free_flow_speed = segment.get('freeFlowSpeed')
        confidence = segment.get('confidence')
        
        # Calculate congestion ratio
        congestion_ratio = None
        if free_flow_speed and current_speed:
            congestion_ratio = 1.0 - (current_speed / free_flow_speed)
            congestion_ratio = max(0, min(1, congestion_ratio))  # Clamp to 0-1
        
        # Check for road closure
        road_closure = 0
        if segment.get('roadClosure'):
            road_closure = 1
        
        snapshot = {
            'timestamp': response.get('processedTime'),
            'point_name': point_name,
            'latitude': latitude,
            'longitude': longitude,
            'current_speed': current_speed,
            'free_flow_speed': free_flow_speed,
            'congestion_ratio': congestion_ratio,
            'road_closure': road_closure,
            'confidence': confidence
        }
        
        logger.debug(f"Parsed snapshot for {point_name}: speed={current_speed}, congestion={congestion_ratio}")
        return snapshot
        
    except KeyError as e:
        logger.error(f"Missing expected field in response for {point_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing response for {point_name}: {e}")
        return None
