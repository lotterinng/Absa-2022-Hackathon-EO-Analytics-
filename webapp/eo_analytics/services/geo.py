"""Small geometry helpers (no heavy GIS dependency needed)."""
import math

EARTH_RADIUS_M = 6_371_008.8


class GeometryError(ValueError):
    pass


def outer_ring(geometry):
    """Return the outer ring [[lon, lat], ...] of a GeoJSON Polygon (or first part of a MultiPolygon)."""
    if not isinstance(geometry, dict):
        raise GeometryError("Geometry must be a GeoJSON object.")
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Feature":
        return outer_ring(geometry.get("geometry"))
    if gtype == "Polygon" and coords:
        ring = coords[0]
    elif gtype == "MultiPolygon" and coords:
        ring = coords[0][0]
    else:
        raise GeometryError("Please draw a polygon around your field.")
    ring = [[float(p[0]), float(p[1])] for p in ring]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    if len(ring) < 4:
        raise GeometryError("A field needs at least three corners.")
    for lon, lat in ring:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise GeometryError("Coordinates are outside the valid range.")
    return ring


def normalise_polygon(geometry):
    return {"type": "Polygon", "coordinates": [outer_ring(geometry)]}


def area_hectares(geometry):
    """Geodesic polygon area on a sphere (accurate to well under 1% for farm-sized shapes)."""
    ring = outer_ring(geometry)
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        total += math.radians(lon2 - lon1) * (
            2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        )
    return abs(total * EARTH_RADIUS_M**2 / 2.0) / 10_000.0


def centroid(geometry):
    """Area-weighted centroid as (lat, lon)."""
    ring = outer_ring(geometry)
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-15:
        xs = [p[0] for p in ring[:-1]]
        ys = [p[1] for p in ring[:-1]]
        return sum(ys) / len(ys), sum(xs) / len(xs)
    a *= 0.5
    return cy / (6 * a), cx / (6 * a)


def bounds(geometry):
    """(min_lon, min_lat, max_lon, max_lat)."""
    ring = outer_ring(geometry)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)
