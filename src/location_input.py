"""
Location input helpers -- turns a drawn map polygon or GPS point into
usable numbers for the design/siting pipeline.

v0.1: pure geometry, no external data dependency yet. Population and
soil auto-lookup (from bundled datasets) plug in here in Checkpoint 3
once we pick the actual dataset -- kept separate so the geometry math
can be tested and trusted independently first.
"""

import math

EARTH_RADIUS_KM = 6371.0


def polygon_area_km2(coords: list) -> float:
    """
    Approximate area of a lat/lon polygon using an equirectangular
    projection centered on the polygon's mean latitude. Accurate enough
    for city/zone-scale polygons (few km across); not for continental
    scale, which is fine for our use case.

    coords: list of (lat, lon) tuples, in order, polygon need not be closed.
    """
    if len(coords) < 3:
        raise ValueError("Need at least 3 points to form a polygon")

    mean_lat = sum(c[0] for c in coords) / len(coords)
    mean_lat_rad = math.radians(mean_lat)

    # Project lat/lon (degrees) to local x/y in km
    def project(lat, lon):
        x = math.radians(lon) * EARTH_RADIUS_KM * math.cos(mean_lat_rad)
        y = math.radians(lat) * EARTH_RADIUS_KM
        return x, y

    pts = [project(lat, lon) for lat, lon in coords]

    # Shoelace formula
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def gps_distance_km(lat1, lon1, lat2, lon2) -> float:
    """Haversine distance between two GPS points, in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


if __name__ == "__main__":
    # Quick sanity check: a small ~1km x 1km square near the equator-ish
    sample_polygon = [
        (12.9716, 77.5946),
        (12.9716, 77.6046),
        (12.9806, 77.6046),
        (12.9806, 77.5946),
    ]
    area = polygon_area_km2(sample_polygon)
    print(f"Sample drawn-zone area: {area:.4f} km2")
