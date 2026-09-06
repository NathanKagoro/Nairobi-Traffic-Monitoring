"""
Monitoring point generator.

Builds monitored_points.json from real OpenStreetMap road geometry instead of
hand-entered coordinates. contributions.md lists a "city template generator for
monitored_points.json" as a wanted contribution; this is it.

Why it exists: coordinates typed from memory land in the wrong place, and the
failure is invisible. TomTom snaps any coordinate to its nearest road segment
and returns a plausible reading, so a point labelled "Ngong Road" can spend
months quietly measuring a residential side street. Generating points from OSM
geometry makes that impossible - every coordinate is a node on the named road.

Method:
  1. Ask Overpass for every named road of a significant class inside the city's
     administrative boundary.
  2. Group ways by name and measure each road's length inside the city.
  3. Rank by road class, then length, under a per-class quota so urban
     arterials are not crowded out by long peripheral trunk roads.
  4. Sample points along each corridor, centre-first and spaced apart. Long
     arterials get several, so one road is not reduced to a single reading.
  5. Name each point for its road, adding a neighbourhood only where one road
     carries several points and the suffix is needed to tell them apart.

Run with:  python -m analysis.generate_points
"""
import json
import logging
import math
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

import requests

from analysis.validate_points import (
    USER_AGENT,
    reverse_geocode,
    road_matches,
    REQUEST_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

# Overpass is a free shared service that rate-limits and sheds load readily.
# Rotating over mirrors with backoff is the difference between this tool
# working and it failing on every second run.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# The city's administrative boundary, used in preference to a bounding box. A
# rectangle over Nairobi also covers chunks of Kiambu and Kajiado counties, and
# selects roads in Ruiru, Kikuyu and Ongata Rongai that the project does not
# monitor. Querying the real polygon removes them exactly.
CITY_AREA = {"name": "Nairobi", "admin_level": "4"}

# Bounding box for the same area (min_lat, min_lon, max_lat, max_lon) in
# Overpass order. Used to clip way geometry that runs past the boundary, so a
# road is ranked on the length that lies inside the city.
CITY_BBOX = (-1.45, 36.66, -1.15, 37.11)

# Tight box over the central business district. CBD streets are short and
# tagged as tertiary or residential, so they never survive a city-wide ranking
# by length and have to be selected separately.
CBD_BBOX = (-1.298, 36.812, -1.272, 36.840)

# City centre, used to bias sampling inwards. The geometric midpoint of a long
# radial road is out in the countryside - the midpoint of Ngong Road is nearer
# Ngong town than Nairobi - so candidate positions are tried centre-first.
CITY_CENTRE = (-1.2864, 36.8172)

# OSM highway classes worth monitoring, most significant first. The index in
# this list is the ranking priority.
ARTERIAL_CLASSES = ["motorway", "trunk", "primary", "secondary"]
CBD_CLASSES = ["primary", "secondary", "tertiary", "residential"]

# How many points each road class may contribute. Without quotas the longest
# trunk roads take every slot and the city's primary arterials - Ngong Road,
# Jogoo Road, Outer Ring Road - are never sampled at all.
CLASS_QUOTAS = {
    "motorway": 4,
    "trunk": 10,
    "primary": 16,
    "secondary": 10,
}

# Two points closer together than this are effectively the same reading. The
# city centre uses a tighter figure because CBD blocks are barely 150 m apart
# and the 500 m rule would exclude most of the named streets in it.
MIN_SEPARATION_KM = 0.5
CBD_MIN_SEPARATION_KM = 0.3

# Positions to try along a road before giving up on it. A road whose midpoint
# happens to sit near an already-placed point should be sampled somewhere else,
# not dropped - the Nairobi Expressway is built directly above Mombasa Road and
# Uhuru Highway, and one candidate position each would lose two major roads.
CANDIDATE_POSITIONS = 5

# Map OSM highway class to this project's category vocabulary.
CLASS_TO_CATEGORY = {
    "motorway": "highway",
    "trunk": "highway",
    "primary": "main_road",
    "secondary": "main_road",
    "tertiary": "main_road",
    "residential": "residential",
}


def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) pairs, in kilometres."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def query_overpass(region, classes: List[str]) -> List[Dict]:
    """
    Fetch every named way of the given highway classes inside a region.

    `region` is either a (south, west, north, east) bounding box or a dict of
    OSM tags identifying an administrative area, e.g.
    {"name": "Nairobi", "admin_level": "4"}.
    """
    class_re = "|".join(classes)

    if isinstance(region, dict):
        tag_filter = "".join(f'["{k}"="{v}"]' for k, v in region.items())
        selector = f'area{tag_filter}->.searchArea;\n    way(area.searchArea)'
    else:
        south, west, north, east = region
        selector = f"way({south},{west},{north},{east})"

    query = f"""
    [out:json][timeout:180];
    {selector}
       ["highway"~"^({class_re})$"]
       ["name"];
    out geom;
    """
    logger.info(f"Querying Overpass for {class_re} in {region}...")

    last_error = None
    for attempt in range(1, len(OVERPASS_MIRRORS) * 2 + 1):
        mirror = OVERPASS_MIRRORS[(attempt - 1) % len(OVERPASS_MIRRORS)]
        try:
            response = requests.post(
                mirror,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=240,
            )
            # 429 (too many requests) and 504 (gateway timeout) are Overpass
            # shedding load, not a bad query. Both are worth retrying elsewhere.
            if response.status_code in (429, 504):
                raise requests.HTTPError(f"{response.status_code} from {mirror}")
            response.raise_for_status()
            elements = response.json().get("elements", [])
            logger.info(f"Overpass returned {len(elements)} ways from {mirror}")
            return elements
        except Exception as e:
            last_error = e
            backoff = min(60, 5 * attempt)
            logger.warning(f"Overpass attempt {attempt} failed ({e}); "
                           f"retrying in {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(f"All Overpass mirrors failed: {last_error}")


def _neighbourhood(lat: float, lon: float) -> Optional[str]:
    """The neighbourhood name OSM gives for a coordinate, suffixes stripped."""
    data = reverse_geocode(lat, lon)
    if not data:
        return None

    address = data.get("address", {}) or {}
    area = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("quarter")
        or address.get("city_district")
    )
    if not area:
        return None

    # "Kilimani division" -> "Kilimani"
    for suffix in (" ward", " division", " sublocation", " location"):
        if area.lower().endswith(suffix):
            return area[: -len(suffix)]
    return area


def _in_bbox(lat: float, lon: float, bbox: Tuple[float, float, float, float]) -> bool:
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east


def group_roads(elements: List[Dict], classes: List[str],
                bbox: Optional[Tuple[float, float, float, float]] = None
                ) -> Dict[str, Dict]:
    """
    Group ways by road name, pooling their nodes and total length.

    Ways are not stitched into a single ordered line - that is fiddly and not
    needed. Pooling the nodes and sorting along the road's dominant axis is
    accurate enough to spread sample points along a corridor.

    When bbox is given, nodes outside it are dropped before measuring length,
    so a road is ranked on how much of it is actually inside the city.
    """
    roads: Dict[str, Dict] = defaultdict(
        lambda: {"nodes": [], "length_km": 0.0, "classes": set()}
    )

    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name")
        highway = tags.get("highway")
        geometry = element.get("geometry") or []
        if not name or not highway or len(geometry) < 2:
            continue

        coords = [(g["lat"], g["lon"]) for g in geometry]
        if bbox is not None:
            coords = [c for c in coords if _in_bbox(c[0], c[1], bbox)]
        if len(coords) < 2:
            continue

        length = sum(
            _haversine_km(coords[i], coords[i + 1]) for i in range(len(coords) - 1)
        )

        entry = roads[name]
        entry["nodes"].extend(coords)
        entry["length_km"] += length
        entry["classes"].add(highway)

    # Rank each road by its most significant class.
    for name, entry in roads.items():
        entry["rank"] = min(
            (classes.index(c) for c in entry["classes"] if c in classes),
            default=len(classes),
        )
        entry["primary_class"] = sorted(
            entry["classes"], key=lambda c: classes.index(c) if c in classes else 99
        )[0]

    return dict(roads)


def sample_along(nodes: List[Tuple[float, float]], count: int) -> List[Tuple[float, float]]:
    """
    Pick `count` points spread along a road.

    Nodes are sorted by whichever axis the road actually runs along, then taken
    at even quantiles. For a corridor that is what "spread out" means; for a
    twisty road it still guarantees the samples are far apart rather than
    clustered at one junction.
    """
    if not nodes:
        return []
    if count <= 1 or len(nodes) < count:
        return [nodes[len(nodes) // 2]]

    lat_span = max(n[0] for n in nodes) - min(n[0] for n in nodes)
    lon_span = max(n[1] for n in nodes) - min(n[1] for n in nodes)
    axis = 0 if lat_span >= lon_span else 1
    ordered = sorted(nodes, key=lambda n: n[axis])

    picks = []
    for i in range(count):
        # Even quantiles, avoiding the extreme ends where a road tapers into a
        # junction with a different name.
        fraction = (i + 0.5) / count
        picks.append(ordered[int(fraction * (len(ordered) - 1))])
    return picks


def extra_samples_for_length(length_km: float) -> int:
    """
    How many points beyond the first a corridor deserves.

    Every selected road gets one point. A long arterial crosses several
    distinct traffic regimes, so it earns more - but only after every road in
    the quota has been given its first point, so breadth beats depth.
    """
    if length_km >= 14:
        return 2
    if length_km >= 6:
        return 1
    return 0


def _far_enough(candidate: Tuple[float, float],
                existing: List[Tuple[float, float]],
                min_km: float = MIN_SEPARATION_KM) -> bool:
    return all(_haversine_km(candidate, e) >= min_km for e in existing)


def _verify_and_repair(raw_points: List[Dict], *road_sources: Dict) -> List[Dict]:
    """
    Confirm every sampled coordinate really sits on the road it names.

    Overpass says a node belongs to a way, but a node at a junction resolves to
    the crossing road, and that is exactly the mislabelling this generator
    exists to prevent. Each point is checked against Nominatim; a point that
    fails is re-sampled elsewhere on the same road, and dropped if no position
    on it can be confirmed.
    """
    roads: Dict[str, Dict] = {}
    for source in road_sources:
        roads.update(source)

    verified: List[Dict] = []
    for index, raw in enumerate(raw_points, start=1):
        road_name = raw["road"]
        logger.info(f"[{index}/{len(raw_points)}] verifying {road_name}")

        data = reverse_geocode(raw["lat"], raw["lon"])
        time.sleep(REQUEST_DELAY_SECONDS)
        osm_road = (data or {}).get("address", {}).get("road")

        if road_matches(road_name, osm_road):
            verified.append(raw)
            continue

        logger.warning(f"{road_name} at {raw['lat']},{raw['lon']} resolves to "
                       f"{osm_road or 'an unnamed road'}; re-sampling")

        entry = roads.get(road_name)
        repaired = False
        if entry:
            # Try further along the road, skipping anything near the position
            # that already failed.
            for coord in sample_along(entry["nodes"], 9):
                if _haversine_km(coord, (raw["lat"], raw["lon"])) < 0.3:
                    continue
                probe = reverse_geocode(coord[0], coord[1])
                time.sleep(REQUEST_DELAY_SECONDS)
                if road_matches(road_name, (probe or {}).get("address", {}).get("road")):
                    raw = dict(raw, lat=round(coord[0], 5), lon=round(coord[1], 5))
                    verified.append(raw)
                    logger.info(f"  repaired to {raw['lat']},{raw['lon']}")
                    repaired = True
                    break

        if not repaired:
            logger.warning(f"  dropping {road_name}: no position could be confirmed")

    dropped = len(raw_points) - len(verified)
    logger.info(f"Verified {len(verified)} points ({dropped} dropped)")
    return verified


def build_points(target_count: int = 52,
                 city_area=CITY_AREA,
                 city_bbox=CITY_BBOX,
                 cbd_bbox=CBD_BBOX,
                 label_with_area: bool = True,
                 verify: bool = True) -> List[Dict]:
    """Generate a monitoring point list for the configured city."""
    arterials = group_roads(
        query_overpass(city_area, ARTERIAL_CLASSES), ARTERIAL_CLASSES, bbox=city_bbox
    )
    cbd = group_roads(
        query_overpass(cbd_bbox, CBD_CLASSES), CBD_CLASSES, bbox=cbd_bbox
    )

    # Reserve part of the budget for the city centre, which is where congestion
    # actually bites and where the short, unrankable streets live.
    cbd_budget = max(6, target_count // 4)

    raw_points: List[Dict] = []
    placed: List[Tuple[float, float]] = []

    def try_place(road: str, entry: Dict, category: str,
                  coord: Tuple[float, float], min_km: float) -> bool:
        if len(raw_points) >= target_count or not _far_enough(coord, placed, min_km):
            return False
        placed.append(coord)
        raw_points.append(
            {
                "road": road,
                "lat": round(coord[0], 5),
                "lon": round(coord[1], 5),
                "category": category,
                "length_km": round(entry["length_km"], 2),
            }
        )
        return True

    def place_somewhere(road: str, entry: Dict, category: str,
                        min_km: float) -> bool:
        """
        Try several positions along a road, keeping the first that fits.

        Positions are tried nearest-the-centre first, so a radial road is
        sampled on its congested urban stretch rather than at the rural end
        where its geometric midpoint often falls.
        """
        candidates = sample_along(entry["nodes"], CANDIDATE_POSITIONS)
        candidates.sort(key=lambda c: _haversine_km(c, CITY_CENTRE))
        for coord in candidates:
            if try_place(road, entry, category, coord, min_km):
                return True
        return False

    # --- city centre ------------------------------------------------------
    ranked_cbd = sorted(cbd.items(), key=lambda kv: (kv[1]["rank"], -kv[1]["length_km"]))
    cbd_placed = 0
    for name, entry in ranked_cbd:
        if cbd_placed >= cbd_budget:
            break
        if entry["length_km"] < 0.2:
            continue
        if place_somewhere(name, entry, "cbd_corridor", CBD_MIN_SEPARATION_KM):
            cbd_placed += 1

    # --- arterials, one point per road, quota'd by class ------------------
    # Grouping by class first is what guarantees primary urban arterials get
    # slots instead of losing every comparison to longer trunk roads.
    by_class: Dict[str, List[Tuple[str, Dict]]] = defaultdict(list)
    for name, entry in arterials.items():
        if name in {p["road"] for p in raw_points} or entry["length_km"] < 0.5:
            continue
        by_class[entry["primary_class"]].append((name, entry))

    selected: List[Tuple[str, Dict, str]] = []
    for road_class in ARTERIAL_CLASSES:
        quota = CLASS_QUOTAS.get(road_class, 0)
        candidates = sorted(by_class.get(road_class, []), key=lambda kv: -kv[1]["length_km"])
        taken = 0
        for name, entry in candidates:
            if taken >= quota or len(raw_points) >= target_count:
                break
            category = CLASS_TO_CATEGORY.get(road_class, "main_road")
            if place_somewhere(name, entry, category, MIN_SEPARATION_KM):
                selected.append((name, entry, category))
                taken += 1

    # --- second pass: extra points on the longest corridors ---------------
    for name, entry, category in sorted(selected, key=lambda s: -s[1]["length_km"]):
        if len(raw_points) >= target_count:
            break
        extra = extra_samples_for_length(entry["length_km"])
        if not extra:
            continue
        # Ask for more samples than needed; separation filtering discards the
        # ones that land too close to a point already placed.
        for coord in sample_along(entry["nodes"], extra + 3):
            if extra <= 0:
                break
            if try_place(name, entry, category, coord, MIN_SEPARATION_KM):
                extra -= 1

    road_count = len({p["road"] for p in raw_points})
    logger.info(f"Sampled {len(raw_points)} points across {road_count} roads")

    if verify:
        raw_points = _verify_and_repair(raw_points, arterials, cbd)

    # Name the points.
    #
    # A road sampled once is named for the road, full stop. Appending a
    # neighbourhood there is worse than useless: OSM ward names are coarse, so
    # it produces labels like "Kenyatta Avenue - Kilimani" that pair a road
    # with a district it is not in - reintroducing the exact mislabelling this
    # generator exists to prevent.
    #
    # Only roads sampled more than once need a suffix to tell their points
    # apart, and there the neighbourhood is genuinely informative
    # ("Thika Road - Roysambu" versus "Thika Road - Kasarani").
    road_counts = Counter(raw["road"] for raw in raw_points)
    needs_suffix = {road for road, n in road_counts.items() if n > 1}

    points: List[Dict] = []
    seen_names = set()
    to_label = [r for r in raw_points if r["road"] in needs_suffix]
    logger.info(f"Labelling {len(to_label)} points on multi-sample roads")

    labelled = 0
    for raw in raw_points:
        area: Optional[str] = None
        if label_with_area and raw["road"] in needs_suffix:
            labelled += 1
            logger.info(f"[{labelled}/{len(to_label)}] labelling {raw['road']}")
            area = _neighbourhood(raw["lat"], raw["lon"])
            time.sleep(REQUEST_DELAY_SECONDS)

        name = f"{raw['road']} - {area}" if area else raw["road"]
        # Guarantee uniqueness; two samples can land in the same ward.
        base = name
        suffix = 2
        while name in seen_names:
            name = f"{base} ({suffix})"
            suffix += 1
        seen_names.add(name)

        points.append(
            {
                "name": name,
                "lat": raw["lat"],
                "lon": raw["lon"],
                "category": raw["category"],
            }
        )

    return points


def write_points(points: List[Dict], path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(points, f, indent=2, ensure_ascii=False)
        f.write("\n")
    logger.info(f"Wrote {len(points)} points to {path}")


if __name__ == "__main__":
    import sys
    from config.settings import MONITORED_POINTS_FILE

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    target = int(sys.argv[1]) if len(sys.argv) > 1 else 52
    generated = build_points(target_count=target)
    write_points(generated, MONITORED_POINTS_FILE)
