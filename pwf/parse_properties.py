"""Surveyed coordinates, taken from the club's own property map.

Every other coordinate in this project is inferred: a town name, geocoded, then
disambiguated against the directions a property page happens to print. That was
the best available until it turned out the club publishes the real thing.

`/properties` is a public page - no login - carrying the marker payload for a
Google map: one object per active property with a title, the property slug, and
latitude and longitude to twelve decimal places. Measured against it, the
inferred coordinates were off by a median of 6.2 miles, and the worst were not
obscure lakes: Six O Ranch, the most-reported water in the archive, sat 15.5
miles from where it actually is.

Two cautions, both learned from the data rather than assumed:

* **Trust the coordinates and the slug, nothing else.** The same payload files
  Moonshine Lake under "Coalgate" and "Dallas / Fort Worth Area", which are 150
  miles apart. Town and region are carried through for reference and are never
  used to place anything.
* **A title is not an identity.** The club runs two separate properties called
  "Twin Lakes" - one at Cody Ranch in Coalgate, Oklahoma and one in Ben Wheeler,
  Texas - so the slug is the join key and the title is only a fallback.
"""
from __future__ import annotations

import html as _html
import json
import re

# Each marker is a flat object; matching braces non-greedily is enough because
# the nested HTML in `content` has its quotes escaped.
_OBJ = re.compile(r'\{[^{}]*"lat"\s*:\s*"-?\d[\d.]*"[^{}]*\}')
_SLUG = re.compile(r"/view-property/([a-z0-9_\-]+)", re.I)
_PLACE = re.compile(r"<h4>(.*?)</h4>", re.S | re.I)

# The club's footprint. A coordinate outside it is a parse error, not a lake.
LAT_RANGE = (25.8, 37.1)
LON_RANGE = (-103.1, -93.5)


def parse(doc: str) -> list[dict]:
    """Every surveyed property on the club's map page."""
    out: list[dict] = []
    seen: set[str] = set()
    for raw in _OBJ.finditer(doc or ""):
        try:
            obj = json.loads(_html.unescape(raw.group(0)))
        except ValueError:
            continue
        try:
            lat, lon = float(obj["lat"]), float(obj["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]
                and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            continue
        content = obj.get("content") or ""
        slug = _SLUG.search(content)
        slug = slug.group(1).lower() if slug else None
        key = slug or (obj.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        place = _PLACE.search(content)
        out.append({
            "club_id": str(obj.get("id") or "").strip() or None,
            "title": " ".join((obj.get("title") or "").split()),
            "slug": slug,
            "lat": lat, "lon": lon,
            # Reference only - never used to place a lake.
            "place": " ".join(_html.unescape(place.group(1)).split())
                     if place else None,
        })
    return out
