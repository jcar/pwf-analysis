"""State outlines for the map, baked in at build time.

A tile map cannot work in the published artifact: its content policy blocks
images and network calls from outside a short allowlist, so Leaflet, Google Maps
and Mapbox would all fail silently - map tiles are images fetched from a tile
server. The policy governs the page, not the build, so the geometry is fetched
once here, simplified, and committed to data/region.json. The page then draws it
as inline SVG with no network at all, which loads instantly and themes with
everything else.

Fetching is a one-off. `pwf.brief` reads the committed file and never calls out.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from .config import DATA

SOURCE = ("https://raw.githubusercontent.com/PublicaMundi/MappingAPI/"
          "master/data/geojson/us-states.json")
REGION_PATH = DATA / "region.json"
STATES = ("Texas", "Oklahoma", "Louisiana", "Arkansas", "New Mexico")
# Tolerance in degrees. At the size this map is drawn, 0.02 keeps the Gulf
# curve and the Red River border reading correctly in about 5 KB.
TOLERANCE = 0.02

# Reference points, so a lake reads as "east toward Tyler" rather than as an
# abstract dot.
CITIES = [
    {"name": "Dallas", "lat": 32.7767, "lon": -96.7970, "home": True},
    {"name": "Fort Worth", "lat": 32.7555, "lon": -97.3308},
    {"name": "Tyler", "lat": 32.3513, "lon": -95.3011},
    {"name": "Waco", "lat": 31.5493, "lon": -97.1467},
    {"name": "Austin", "lat": 30.2672, "lon": -97.7431},
    {"name": "Houston", "lat": 29.7604, "lon": -95.3698},
    {"name": "Oklahoma City", "lat": 35.4676, "lon": -97.5164},
]
# Drive-distance rings. These double as the page's contour device.
RINGS_MILES = (60, 100, 150, 200)


def _perp(p, a, b) -> float:
    if a == b:
        return math.dist(p, a)
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) /
                     (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def simplify(points: list[tuple], tolerance: float) -> list[tuple]:
    """Douglas-Peucker, iterative so a long coastline cannot blow the stack."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        worst, dist = lo, -1.0
        for i in range(lo + 1, hi):
            d = _perp(points[i], points[lo], points[hi])
            if d > dist:
                worst, dist = i, d
        if dist > tolerance:
            keep[worst] = True
            stack.append((lo, worst))
            stack.append((worst, hi))
    return [p for p, k in zip(points, keep) if k]


def _rings(feature) -> list[list]:
    geo = feature["geometry"]
    polys = [geo["coordinates"]] if geo["type"] == "Polygon" \
        else geo["coordinates"]
    return [ring for poly in polys for ring in poly]


def build(tolerance: float = TOLERANCE, path: Path = REGION_PATH) -> dict:
    """Fetch, simplify and write the region file. Run once; the result ships."""
    import httpx

    from .config import USER_AGENT

    raw = httpx.get(SOURCE, headers={"User-Agent": USER_AGENT},
                    timeout=60, follow_redirects=True).json()
    out = {"tolerance": tolerance, "states": [], "cities": CITIES,
           "rings_miles": list(RINGS_MILES), "source": SOURCE}
    for feature in raw["features"]:
        name = feature["properties"]["name"]
        if name not in STATES:
            continue
        rings = []
        for ring in _rings(feature):
            pts = simplify([(round(x, 3), round(y, 3)) for x, y in ring],
                           tolerance)
            if len(pts) >= 3:
                rings.append(pts)
        out["states"].append({"name": name, "rings": rings})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":")))
    return out


def load(path: Path = REGION_PATH) -> dict:
    if not path.exists():
        return {"states": [], "cities": CITIES, "rings_miles": list(RINGS_MILES)}
    return json.loads(path.read_text())


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #
def mercator_y(lat: float) -> float:
    """Web Mercator y, returned in degrees so it shares units with longitude.

    The raw log-tangent is in radians; mixing it with degrees of longitude
    flattens the region into a thin band, because the y span comes out roughly
    57x too small.
    """
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def make_projection(lats, lons, width: float, height: float, pad: float = 0.9):
    """Return (project, bounds) fitting the supplied points into the viewport."""
    lo_lon, hi_lon = min(lons) - pad, max(lons) + pad
    lo_lat, hi_lat = min(lats) - pad * 0.8, max(lats) + pad * 0.8
    y0, y1 = mercator_y(lo_lat), mercator_y(hi_lat)

    # Preserve aspect so the region is not stretched to fill the box.
    span_x, span_y = hi_lon - lo_lon, y1 - y0
    scale = min(width / span_x, height / span_y)
    off_x = (width - span_x * scale) / 2
    off_y = (height - span_y * scale) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (round(off_x + (lon - lo_lon) * scale, 1),
                round(off_y + (y1 - mercator_y(lat)) * scale, 1))

    return project, {"lo_lon": lo_lon, "hi_lon": hi_lon,
                     "lo_lat": lo_lat, "hi_lat": hi_lat, "scale": scale}


def miles_between(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


if __name__ == "__main__":  # pragma: no cover
    info = build()
    n = sum(len(r) for s in info["states"] for r in s["rings"])
    size = REGION_PATH.stat().st_size
    print(f"wrote {REGION_PATH}: {len(info['states'])} states, {n} points, "
          f"{size / 1000:.1f} KB", file=sys.stderr)
