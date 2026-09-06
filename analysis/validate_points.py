"""
Monitoring point validation.

contributions.md asks contributors to "confirm coordinates map to real roads".
This makes that checkable instead of a matter of trust.

For each point in monitored_points.json it reverse-geocodes the coordinate
against OpenStreetMap and compares what is actually there against what the
point claims to be. Verdicts:

  MATCH     - the coordinate sits on a road whose name matches the point name.
  AREA_ONLY - right neighbourhood, but not the road the point claims. Usually
              means the coordinate drifted onto a nearby side street.
  MISMATCH  - the coordinate is nowhere near anything matching the point name.
              The series will be labelled as one road while measuring another.
  OFF_AREA  - the coordinate falls outside the target city bounding box.

Both are silent in the collected data: TomTom snaps any coordinate to its
nearest road segment and returns a perfectly valid-looking reading for it.

Run with:  python main.py validate-points
"""
import json
import logging
import re
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# Nominatim's usage policy requires an identifying User-Agent and at most one
# request per second. This runs over ~50 points, so it is a slow, one-off check.
USER_AGENT = "dar-traffic-monitoring/1.0 (point validation; github.com/NathanKagoro)"
REQUEST_DELAY_SECONDS = 1.1

# Rough Nairobi bounding box (min_lat, max_lat, min_lon, max_lon).
NAIROBI_BBOX = (-1.45, -1.15, 36.65, 37.05)

# Words that carry no location information when matching a name against OSM.
STOPWORDS = {
    "rd", "road", "st", "street", "ave", "avenue", "way", "lane", "dr", "drive",
    "junction", "approach", "access", "corridor", "roundabout", "interchange",
    "bypass", "estate", "area", "edge", "main", "gate", "terminal", "the",
    "of", "and", "north", "south", "east", "west", "outer", "ring", "upper",
    "lower", "stage", "centre", "center", "hill", "hills", "park", "grove",
    # Administrative filler that appears in every Nominatim display_name for
    # the city. Without these, any point anywhere in Nairobi "matches" any
    # point name containing the word Nairobi.
    "nairobi", "kenya", "county", "ward", "division", "sublocation", "location",
}


def _tokens(text: str) -> set:
    """Lowercase word tokens with routing/road-type noise removed."""
    if not text:
        return set()
    words = re.split(r"[^a-z0-9]+", text.lower())
    return {w for w in words if w and len(w) > 2 and w not in STOPWORDS}


def _normalise(text: str) -> str:
    """Lowercase, punctuation-free form for whole-name comparison."""
    if not text:
        return ""
    return " ".join(re.split(r"[^a-z0-9]+", text.lower())).strip()


def road_matches(claimed: str, osm_road: str) -> bool:
    """
    Does a point name refer to the road OSM reports at that coordinate?

    Whole-name comparison comes first, because some road names consist
    entirely of generic words - every token of "Outer Ring Road" and "Park
    Road" is a stopword, so token overlap alone would reject a perfect match.
    """
    if not claimed or not osm_road:
        return False

    claimed_norm = _normalise(claimed)
    road_norm = _normalise(osm_road)
    if not claimed_norm or not road_norm:
        return False

    # The point name may carry a disambiguating suffix: "Thika Road - Kasarani".
    claimed_head = _normalise(claimed.split(" - ")[0])

    if road_norm in (claimed_norm, claimed_head):
        return True
    if road_norm in claimed_norm or claimed_head in road_norm:
        return True
    return bool(_tokens(claimed) & _tokens(osm_road))


def reverse_geocode(lat: float, lon: float) -> Optional[Dict]:
    """Look up what OpenStreetMap has at a coordinate, at road-level zoom."""
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 17},
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
    except Exception as e:
        logger.warning(f"Reverse geocode failed for {lat},{lon}: {e}")
        return None

    if response.status_code != 200:
        logger.warning(f"Reverse geocode HTTP {response.status_code} for {lat},{lon}")
        return None

    return response.json()


def validate_point(point: Dict, bbox=NAIROBI_BBOX) -> Dict:
    """Check one point's coordinate against OSM and against the city bounds."""
    name = point.get("name", "")
    lat = point.get("lat")
    lon = point.get("lon")

    result = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "osm_road": None,
        "osm_area": None,
        "verdict": "UNKNOWN",
        "detail": "",
    }

    min_lat, max_lat, min_lon, max_lon = bbox
    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
        result["verdict"] = "OFF_AREA"
        result["detail"] = "coordinate falls outside the city bounding box"
        return result

    data = reverse_geocode(lat, lon)
    if data is None:
        result["detail"] = "reverse geocode failed"
        return result

    address = data.get("address", {}) or {}
    road = address.get("road")
    area = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("quarter")
        or address.get("city_district")
        or address.get("residential")
    )
    result["osm_road"] = road
    result["osm_area"] = area
    result["osm_display"] = data.get("display_name")

    # Compare the claimed name against what OSM knows about the spot. A match on
    # the road name itself is strong evidence; a match only on the surrounding
    # neighbourhood means the point is in roughly the right district but not
    # necessarily on the road it claims, so it is reported separately.
    claimed = _tokens(name)
    area_tokens = _tokens(" ".join(filter(None, [area, data.get("display_name")])))

    if road_matches(name, road):
        result["verdict"] = "MATCH"
        result["detail"] = f"on {road}"
    elif not claimed:
        result["verdict"] = "UNKNOWN"
        result["detail"] = "point name carries no distinguishing words"
    elif claimed & area_tokens:
        result["verdict"] = "AREA_ONLY"
        result["detail"] = (
            f"right district ({', '.join(sorted(claimed & area_tokens))}) but OSM "
            f"road here is {road or '(unnamed)'}"
        )
    else:
        result["verdict"] = "MISMATCH"
        result["detail"] = f"OSM says: {road or '(unnamed road)'}" + (
            f", {area}" if area else ""
        )

    return result


def validate_points(points: List[Dict], bbox=NAIROBI_BBOX) -> List[Dict]:
    """Validate every point, respecting the Nominatim rate limit."""
    results = []
    for index, point in enumerate(points, start=1):
        logger.info(f"[{index}/{len(points)}] {point.get('name')}")
        results.append(validate_point(point, bbox=bbox))
        if index < len(points):
            time.sleep(REQUEST_DELAY_SECONDS)
    return results


def render_validation(results: List[Dict]) -> str:
    """Render validation results as Markdown, worst first."""
    order = {"OFF_AREA": 0, "MISMATCH": 1, "AREA_ONLY": 2, "UNKNOWN": 3, "MATCH": 4}
    ranked = sorted(results, key=lambda r: (order.get(r["verdict"], 9), r["name"]))

    counts: Dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    lines = ["# Monitoring point validation", ""]
    lines.append("Each configured coordinate reverse-geocoded against OpenStreetMap.")
    lines.append("")
    for verdict in ("MATCH", "AREA_ONLY", "MISMATCH", "OFF_AREA", "UNKNOWN"):
        if verdict in counts:
            lines.append(f"- **{verdict}**: {counts[verdict]}")
    lines.append("")
    lines.append("| Verdict | Point name | Lat | Lon | OSM road | OSM area | Detail |")
    lines.append("|---|---|---:|---:|---|---|---|")
    for r in ranked:
        lines.append(
            f"| {r['verdict']} | {r['name']} | {r['lat']} | {r['lon']} "
            f"| {r.get('osm_road') or '-'} | {r.get('osm_area') or '-'} "
            f"| {r.get('detail', '')} |"
        )
    return "\n".join(lines)


def load_points(path) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
