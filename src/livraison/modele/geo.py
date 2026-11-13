"""Géométrie simple : points (longitude, latitude) et distance à vol d'oiseau."""

import math

Point = tuple[float, float]  # (longitude, latitude), comme dans PostGIS
RAYON_TERRE_M = 6_371_000


def distance_m(a: Point, b: Point) -> float:
    """Distance orthodromique (formule de haversine), en mètres."""
    (lon1, lat1), (lon2, lat2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(h))
