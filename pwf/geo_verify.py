"""Check geocoded coordinates against what the club says in its own directions.

Every property page carries a "General Directions" line written by the club -
"68 miles from Dallas", "35 miles west of downtown San Antonio", "2 hours NE of
Downtown Houston. 3.5 from downtown Dallas. 30 miles east of College Station".
That is an independent statement of where a lake is, so it can be parsed and
compared against whatever coordinate a geocoder produced.

This matters because town names repeat inside Texas - 82 of the club's 111 towns
have more than one Texas or Oklahoma match - and a wrong pick can be 150 miles
out while looking perfectly reasonable in a table.

Two things follow from reading the directions properly:

* **They are written from whichever city is nearest**, not always Dallas. A
  first version of this module measured every claim from Dallas and declared 26
  lakes suspect; most of those were correct lakes described from San Antonio,
  Houston or College Station. Each claim has to be anchored to the city it
  actually names.
* **A page usually states two or three**, and together they triangulate. Any one
  distance describes a circle; two describe a pair of points; three pin it.

So the directions are not only a check - they are the best disambiguator
available, better than the club region or town population, and `best_candidate`
uses them to choose among same-named towns.

Retired properties have no page left and cannot be checked this way. Those go to
`pwf geo-review` for a person to settle.
"""
from __future__ import annotations

import html as _html
import math
import re
import sqlite3

from .geo_shapes import miles_between

HOME = (32.7767, -96.7970)          # downtown Dallas, where the drive starts

# Cities the club measures from. Coordinates are the downtown point the phrase
# "downtown X" refers to, since that is how the directions are written.
CITIES = {
    "dallas": (32.7767, -96.7970),
    "fort worth": (32.7555, -97.3308),
    "houston": (29.7604, -95.3698),
    "san antonio": (29.4241, -98.4936),
    "austin": (30.2672, -97.7431),
    "tyler": (32.3513, -95.3011),
    "waco": (31.5493, -97.1467),
    "college station": (30.6280, -96.3344),
    "oklahoma city": (35.4676, -97.5164),
    "texarkana": (33.4418, -94.0377),
    "shreveport": (32.5252, -93.7502),
    "abilene": (32.4487, -99.7331),
    "tulsa": (36.1540, -95.9928),
    "lubbock": (33.5779, -101.8552),
    # Smaller anchors the club leans on for its eastern and northern properties.
    "denton": (33.2148, -97.1331),
    "fairfield": (31.7243, -96.1653),
    "plano": (33.0198, -96.6989),
    "sulphur springs": (33.1384, -95.6011),
    "canton": (32.5565, -95.8633),
    "paris": (33.6609, -95.5555),
    "cleburne": (32.3476, -97.3867),
    "columbus": (29.7063, -96.5397),
    "athens": (32.2049, -95.8555),
    "mckinney": (33.1972, -96.6153),
    "bonham": (33.5773, -96.1775),
    "grand saline": (32.6729, -95.7094),
    "marshall": (32.5449, -94.3674),
    "beaumont": (30.0802, -94.1266),
}

# The pages spell these several ways; "OKC" and "Ft. Worth" are not typos to be
# dropped, they are the anchor for that lake.
ALIASES = {
    "okc": "oklahoma city", "ok city": "oklahoma city",
    "ft worth": "fort worth", "ftworth": "fort worth",
    "fortworth": "fort worth", "forthworth": "fort worth",
    "ft. worth": "fort worth", "paris texas": "paris",
}

# Interstate speed, for turning a stated drive time into a rough distance.
MILES_PER_HOUR = 55.0
# How far a coordinate may sit from a stated distance before it counts as
# suspect. Generous on purpose: the club rounds, and a town centroid is not the
# lake.
DISTANCE_TOLERANCE = 0.45           # proportion of the stated distance
MIN_TOLERANCE_MILES = 22.0
# Road miles always exceed straight-line, so a stated drive time gets more room.
TIME_TOLERANCE = 0.55
BEARING_TOLERANCE_DEG = 70.0

_DIRECTIONS = re.compile(r"General Directions(.{0,400})", re.S)

# One pass over the blurb picks up every distance expression it contains.
# Ordered so that a number carrying a unit is never mistaken for a bare one.
_TOKEN = re.compile(
    r"(?P<mi>\d{1,3}(?:\.\d+)?)\s*miles?\b"
    r"|(?P<h>\d+(?:\.\d+)?|an|one|two|three|four)\s*(?:hours?|hrs?)\b"
    r"(?:\s*(?:and\s+)?(?P<hm>\d{1,2})\s*min\w*)?"
    r"|(?P<m>\d{1,3})\s*min\w*\b"
    r"|(?P<bare>\d{1,2}(?:\.\d+)?)(?!\s*(?:miles?|hours?|hrs?|min|%|ac))\b",
    re.I)
_WORD_HOURS = {"an": 1.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0}
# "14 miles, around 24 minutes" is one claim stated twice, not two claims.
_RESTATEMENT_CHARS = 16

COMPASS = {
    "north": 0, "nne": 22.5, "northeast": 45, "ne": 45, "ene": 67.5,
    "east": 90, "ese": 112.5, "southeast": 135, "se": 135, "sse": 157.5,
    "south": 180, "ssw": 202.5, "southwest": 225, "sw": 225, "wsw": 247.5,
    "west": 270, "wnw": 292.5, "northwest": 315, "nw": 315, "nnw": 337.5,
}

_CLAIM = re.compile(
    r"(?:(?P<bearing>north\s*east|north\s*west|south\s*east|south\s*west|"
    r"northeast|northwest|southeast|southwest|north|south|east|west|"
    r"NNE|NNW|ENE|WNW|ESE|WSW|SSE|SSW|NE|NW|SE|SW)\s+)?"
    r"(?:of\s+|from\s+)?(?:down\s*town\s+)?"
    r"(?P<city>" + "|".join(
        sorted(list(CITIES) + list(ALIASES), key=len, reverse=True)
    ).replace(".", r"\.") + r")\b",
    re.I)


def _plain(doc: str) -> str:
    t = re.sub(r"(?s)<(script|style|head)[^>]*>.*?</\1>", " ", doc)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)


def _tokens(blurb: str) -> list[dict]:
    """Every distance expression in the blurb, in order.

    A drive time restated right after a mileage ("14 miles, around 24 minutes")
    is folded into the mileage, so the pair is consumed as the single claim it
    is rather than leaking a spurious 22-mile claim onto the next city.
    """
    out: list[dict] = []
    for t in _TOKEN.finditer(blurb):
        if t.group("mi"):
            tok = {"miles": float(t.group("mi")), "time": False}
        elif t.group("h"):
            raw = t.group("h").lower()
            hours = _WORD_HOURS.get(raw)
            if hours is None:
                try:
                    hours = float(raw)
                except ValueError:
                    continue
            if t.group("hm"):
                hours += int(t.group("hm")) / 60.0
            tok = {"miles": hours * MILES_PER_HOUR, "time": True}
        elif t.group("m"):
            tok = {"miles": int(t.group("m")) / 60.0 * MILES_PER_HOUR,
                   "time": True}
        else:
            tok = {"miles": float(t.group("bare")), "time": True, "bare": True}
        tok.update(start=t.start(), end=t.end(), used=False)
        if (out and tok["time"] and not tok.get("bare") and not out[-1]["time"]
                and tok["start"] - out[-1]["end"] <= _RESTATEMENT_CHARS):
            continue                      # the same claim, said again in hours
        out.append(tok)
    # A bare number only means anything if an earlier token set the unit:
    # "2 hours NE of Houston. 3.5 from downtown Dallas."
    seen_time = False
    for tok in out:
        if tok.get("bare") and not seen_time:
            tok["used"] = True            # not a distance; ignore it
        if tok["time"] and not tok.get("bare"):
            seen_time = True
        if tok.get("bare"):
            tok["miles"] *= MILES_PER_HOUR
    return out


def parse_directions(doc: str) -> dict:
    """Every distance-from-a-city claim stated on a property page.

    Each city mention takes the nearest distance not already spoken for,
    preferring one that precedes it - "70 miles NNE of Dallas" - and falling
    back to one stated immediately after, which is the other form the club uses:
    "North of Beaumont, approximately 14 miles". Taking the *first* distance in
    the blurb instead, as an earlier version did, read "10 miles east of Bonham
    70 miles NNE of Dallas" as a lake ten miles from Dallas.
    """
    text = _plain(doc)
    m = _DIRECTIONS.search(text)
    if not m:
        return {}
    # Stop before the member reports embedded further down the page.
    blurb = re.split(r"Fishing Report|Property Pricing", m.group(1))[0].strip()
    if not blurb:
        return {}

    toks = _tokens(blurb)
    hits = list(_CLAIM.finditer(blurb))
    spans = [h.start() for h in hits]
    claims: list[dict] = []

    for i, hit in enumerate(hits):
        prev_city = spans[i - 1] if i else -1
        next_city = spans[i + 1] if i + 1 < len(hits) else len(blurb) + 1
        pick = None
        # Preferred: the last free distance between the previous city and this.
        for tok in reversed(toks):
            if tok["used"] or tok["end"] > hit.start() or tok["start"] < prev_city:
                continue
            pick = tok
            break
        if pick is None and hit.group("bearing"):
            # "<bearing> of <city>, approximately N miles" - same clause only,
            # so a following sentence's distance is never stolen.
            for tok in toks:
                if tok["used"] or tok["start"] < hit.end() or tok["end"] > next_city:
                    continue
                if "." in blurb[hit.end():tok["start"]]:
                    break
                pick = tok
                break
        if pick is None:
            continue
        pick["used"] = True
        raw = re.sub(r"\s+", " ", hit.group("city")).lower()
        bearing = None
        if hit.group("bearing"):
            bearing = COMPASS.get(
                re.sub(r"\s+", "", hit.group("bearing")).lower())
        claims.append({
            "city": ALIASES.get(raw, raw), "miles": pick["miles"],
            "bearing": bearing, "from_time": pick["time"],
        })
    return {"text": blurb[:240], "claims": claims}


def bearing_from(origin: tuple[float, float], lat: float, lon: float) -> float:
    """Initial compass bearing from a city to a point, in degrees."""
    p1, p2 = math.radians(origin[0]), math.radians(lat)
    dl = math.radians(lon - origin[1])
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_from_home(lat: float, lon: float) -> float:
    return bearing_from(HOME, lat, lon)


def _angle_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def score(lat: float, lon: float, claims: list[dict]) -> dict:
    """How badly a coordinate disagrees with the club's own directions.

    The returned `miss` is the worst single disagreement in miles, past
    tolerance - zero when every claim on the page is satisfied. Worst rather
    than average, because one 150-mile contradiction is not excused by two
    claims that happen to fit.
    """
    worst, detail = 0.0, []
    for c in claims:
        origin = CITIES.get(c["city"])
        if origin is None or c.get("miles") is None:
            continue
        actual = miles_between(origin[0], origin[1], lat, lon)
        claimed = c["miles"]
        tol = max(MIN_TOLERANCE_MILES, claimed * DISTANCE_TOLERANCE)
        if c.get("from_time"):
            tol = max(tol, claimed * TIME_TOLERANCE)
        gap = max(0.0, abs(actual - claimed) - tol)
        bearing_gap = None
        if c.get("bearing") is not None:
            bearing_gap = _angle_gap(bearing_from(origin, lat, lon),
                                     c["bearing"])
            if bearing_gap > BEARING_TOLERANCE_DEG:
                # Right distance, wrong direction is still the wrong lake.
                gap = max(gap, actual * 0.5)
        worst = max(worst, gap)
        detail.append({
            "city": c["city"], "claimed": round(claimed),
            "actual": round(actual), "excess": round(gap),
            "bearing": c.get("bearing"),
            "bearing_gap": None if bearing_gap is None else round(bearing_gap),
            "from_time": bool(c.get("from_time")),
        })
    return {"miss": round(worst, 1), "claims": detail}


def check(lat: float, lon: float, stated: dict) -> dict:
    """Compare one coordinate against what a property page claims."""
    stated = stated or {}
    claims = stated.get("claims") or []
    res = score(lat, lon, claims)
    if not res["claims"]:
        return {"verdict": "no claim", "miss": None, "claims": [],
                "text": stated.get("text")}
    return {"verdict": "ok" if res["miss"] <= 0 else "suspect",
            "miss": res["miss"], "claims": res["claims"],
            "text": stated.get("text")}


def best_candidate(candidates: list[dict], claims: list[dict]) -> dict | None:
    """Pick the same-named town that best satisfies the stated directions.

    Candidates are raw Open-Meteo rows. Returns the winner annotated with its
    miss, or None when the directions cannot separate them.
    """
    usable = [c for c in claims if CITIES.get(c.get("city", "")) is not None
              and c.get("miles") is not None]
    if not usable or not candidates:
        return None
    scored = [(score(c["latitude"], c["longitude"], usable)["miss"], c)
              for c in candidates]
    scored.sort(key=lambda p: p[0])
    best_miss, best = scored[0]
    runner = scored[1][0] if len(scored) > 1 else None
    # Only trust the directions when they actually discriminate: a clear winner,
    # and one that genuinely fits rather than merely fitting least badly.
    if best_miss > MIN_TOLERANCE_MILES:
        return None
    if runner is not None and runner - best_miss < 10.0:
        return None
    return {"lat": best["latitude"], "lon": best["longitude"],
            "miss": best_miss, "runner_up_miss": runner,
            "claims": len(usable)}


def verify_all(conn: sqlite3.Connection) -> list[dict]:
    """Every lake whose property page is cached, checked against that page.

    A lake someone has settled by hand still gets checked - the disagreement is
    real and worth being able to see - but it is reported as settled rather than
    as an open problem. Post Oak is the standing case: Bryan is the right town,
    and the mismatch is the club's own compass, which calls Bryan "NE of
    Houston" and "west of Austin" when it is northwest and east respectively.
    """
    from .crawl import iter_cached
    from .geo import _load_overrides

    confirmed = set(_load_overrides())
    pages = {slug: doc for _u, slug, doc in iter_cached(conn, "lake")}
    out = []
    for r in conn.execute(
            "SELECT name, town, slug, lat, lon, report_count FROM lakes"
            " WHERE lat IS NOT NULL AND slug IS NOT NULL"
            " ORDER BY report_count DESC"):
        doc = pages.get(r["slug"])
        if not doc:
            continue
        res = check(r["lat"], r["lon"], parse_directions(doc))
        settled = r["name"] in confirmed
        if settled and res["verdict"] == "suspect":
            res["verdict"] = "settled"
        res.update(lake=r["name"], town=r["town"], slug=r["slug"],
                   reports=r["report_count"], lat=r["lat"], lon=r["lon"],
                   confirmed=settled)
        out.append(res)
    return out
