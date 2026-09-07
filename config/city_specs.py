"""
Geographic definitions for each monitored city.

Kept in its own module so both the point generator and the point validator can
import it without importing each other.

Every bounding box in this project is (south, west, north, east), the order
Overpass uses - that is, (min_lat, min_lon, max_lat, max_lon). Do not reorder:
a silently transposed box passes every type check and rejects every point.
"""

CITIES = {
    "dar_es_salaam": {
        # OSM administrative boundary, preferred over a bounding box: a
        # rectangle over a city also catches roads in neighbouring districts
        # that the project does not monitor.
        "area": {"name": "Dar es Salaam", "admin_level": "4"},
        # Dar es Salaam Region, per OSM relation 7202037.
        "bbox": (-7.19, 39.00, -6.56, 39.93),
        # Kisutu / Kivukoni / Posta - the historic centre.
        "cbd": (-6.830, 39.265, -6.800, 39.300),
        "centre": (-6.8161, 39.2803),
    },
    "nairobi": {
        "area": {"name": "Nairobi", "admin_level": "4"},
        # Nairobi County, per OSM relation 3492709.
        "bbox": (-1.45, 36.66, -1.15, 37.11),
        "cbd": (-1.298, 36.812, -1.272, 36.840),
        "centre": (-1.2864, 36.8172),
    },
}

# The city collected by default.
#
# This project exists to monitor Dar es Salaam, and that remains the goal. It
# is set to Nairobi because TomTom returned NO_COVERAGE for all 52 Dar es
# Salaam points on 2026-09-07 - see docs/provider-coverage.md - so pointing the
# collector at Dar es Salaam produces nothing but failed runs.
#
# Change this back to "dar_es_salaam" the moment a provider that covers
# Tanzania is wired up. Overridable per-run with the CITY environment variable,
# or repo-wide with an Actions variable named CITY.
DEFAULT_CITY = "nairobi"


def city_spec(name: str) -> dict:
    """Look up a city, with an error that lists the valid options."""
    if name not in CITIES:
        raise ValueError(
            f"Unknown city {name!r}. Known cities: {', '.join(sorted(CITIES))}"
        )
    return CITIES[name]
