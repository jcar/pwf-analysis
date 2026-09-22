"""The map, rendered server-side into inline SVG.

No tiles, no library, no network at view time - the artifact's content policy
blocks external images and requests, so a slippy map would simply fail to draw.
Everything here is geometry computed at build time and shipped as path data,
which also means it themes with the page instead of fighting it.

The distance rings are the page's contour device doing double duty: they are
literally what a bathymetric chart looks like, and they answer the question the
map exists for - how far am I driving.
"""
from __future__ import annotations

import math

from pwf.geo_shapes import CITIES, RINGS_MILES, load, make_projection

# The map is the page's primary surface, not a side panel, so it is drawn at
# hero size. The club's footprint is taller than it is wide, so is this.
WIDTH, HEIGHT = 660, 760
HOME = next(c for c in CITIES if c.get("home"))


def _ring_path(project, miles: float, steps: int = 72) -> str:
    """A true distance ring, drawn as a projected polygon.

    A plain circle would be wrong: Mercator's scale factor varies with latitude,
    so a ring that is exactly 200 miles due north is up to 8% out to the east
    and west. Since the map exists to answer "how far am I driving", the ring
    has to agree with the mileage column, so each vertex is placed at a true
    bearing and distance and then projected.
    """
    lat0 = math.radians(HOME["lat"])
    lon0 = math.radians(HOME["lon"])
    ang = miles / 3958.8  # angular distance in radians
    pts = []
    for i in range(steps + 1):
        brg = 2 * math.pi * i / steps
        lat = math.asin(math.sin(lat0) * math.cos(ang)
                        + math.cos(lat0) * math.sin(ang) * math.cos(brg))
        lon = lon0 + math.atan2(
            math.sin(brg) * math.sin(ang) * math.cos(lat0),
            math.cos(ang) - math.sin(lat0) * math.sin(lat))
        pts.append(project(math.degrees(lon), math.degrees(lat)))
    return "M" + "L".join(f"{x},{y}" for x, y in pts) + "Z"


def build_map(lakes: list[dict]) -> dict:
    """Geometry for every mark on the map, ready to emit as SVG.

    `lakes` are dicts carrying name, lat, lon and (optionally) rank and
    expected_fph for the shortlist.
    """
    region = load()
    pts = [(lk["lat"], lk["lon"]) for lk in lakes
           if lk.get("lat") is not None and lk.get("lon") is not None]
    if not pts:
        return {}
    project, bounds = make_projection([p[0] for p in pts], [p[1] for p in pts],
                                      WIDTH, HEIGHT)

    states = []
    for state in region.get("states", []):
        for ring in state["rings"]:
            coords = [project(lon, lat) for lon, lat in ring]
            # Drop rings that fall entirely outside the viewport; the region
            # file covers neighbouring states for orientation, not all of them
            # intersect the frame.
            if all(x < -60 or x > WIDTH + 60 or y < -60 or y > HEIGHT + 60
                   for x, y in coords):
                continue
            d = "M" + "L".join(f"{x},{y}" for x, y in coords) + "Z"
            states.append({"name": state["name"], "d": d})

    cities = []
    for city in region.get("cities", CITIES):
        x, y = project(city["lon"], city["lat"])
        if -20 <= x <= WIDTH + 20 and -20 <= y <= HEIGHT + 20:
            cities.append({"name": city["name"], "x": x, "y": y,
                           "lat": city["lat"], "lon": city["lon"],
                           "home": bool(city.get("home"))})

    hx, hy = project(HOME["lon"], HOME["lat"])
    rings = []
    for m in region.get("rings_miles", RINGS_MILES):
        # Label each ring where it crosses due north of home.
        _, ly = project(HOME["lon"], HOME["lat"] + m / 69.0)
        rings.append({"miles": m, "d": _ring_path(project, m),
                      "label_x": hx, "label_y": round(ly, 1)})

    # The eighty-mile ring is not one of the round distance rings: it is where
    # the club's catch rates change, so it is drawn as its own mark.
    from pwf.geography import SPLIT_MILES
    _, gy = project(HOME["lon"], HOME["lat"] + SPLIT_MILES / 69.0)
    gradient_ring = {"miles": SPLIT_MILES, "d": _ring_path(project, SPLIT_MILES),
                     "label_x": hx, "label_y": round(gy, 1)}

    marks = []
    for lk in lakes:
        if lk.get("lat") is None or lk.get("lon") is None:
            continue
        x, y = project(lk["lon"], lk["lat"])
        marks.append({
            # Leaflet needs real coordinates; x/y stay for the trade-off plot
            # and for anything that still wants the flat projection.
            "lat": round(lk["lat"], 5), "lon": round(lk["lon"], 5),
            "lake": lk["name"], "x": x, "y": y,
            "rank": lk.get("rank"),
            "fph": lk.get("expected_fph"),
            "miles": lk.get("miles"),
            "trips": lk.get("trips"),
            "acres": lk.get("acres"),
            "rate": lk.get("day_rate"),
            "unsure": bool(lk.get("geo_uncertain")) or None,
        })

    return {"width": WIDTH, "height": HEIGHT, "states": states,
            "cities": cities, "rings": rings,
            "gradient_ring": gradient_ring,
            "home": {"x": hx, "y": hy, "lat": HOME["lat"], "lon": HOME["lon"],
                     "name": HOME["name"]},
            "lakes": marks, "bounds": bounds}
