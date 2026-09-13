"""Human-in-the-loop resolution for lakes no evidence can settle.

Three passes run before this one, and each is preferred because it needs nobody:

1. **The club's own directions** on a property page - "2 hours and 30 minutes
   east of Downtown Dallas ... 1 hour east of Tyler" - which triangulate a town
   to within a few miles. This settles 41 lakes.
2. **A verified same-town sibling**: a retired lake in Crockett is in the same
   Crockett as the live property whose page proves where Crockett is. 13 more.
3. **The club's published region**, then town population.

What is left is 29 retired properties whose pages are gone, sitting in towns
whose names repeat inside Texas with nothing to break the tie. There is no
evidence left to find, so the honest move is to ask, and to show enough context
that answering takes seconds: every candidate town with its county, population,
drive from Dallas and compass direction, plus how much of the archive rides on
getting it right.

Answers are written to `data/lake_coords.csv` with `confirmed=yes`, which beats
every automatic pass and survives any later re-geocode.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time

import httpx

from .config import DATA, USER_AGENT
from .geo import GEOCODE, _STATES, confirm
from .geo_shapes import miles_between
from .geo_verify import HOME, bearing_from_home

CACHE = DATA / "geo_candidates.json"

_POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

# Members write about drive time often enough to be worth surfacing, but most
# matches are "fished 3 hours" or "four wheel drive". Only keep a snippet that
# actually names a place or a journey.
_USEFUL = re.compile(
    r"\b(?:drive|drove|driving)\s+(?:up\s+|down\s+|over\s+|out\s+)?"
    r"(?:from|to|past|through)\s+[A-Z]"
    r"|\b(?:north|south|east|west)\s+of\s+[A-Z]"
    r"|\b(?:highway|hwy|fm|us|i-)\s*\d+"
    r"|\b[A-Z][a-z]+\s+County\b")
_NOISE = re.compile(r"\b(?:four|4)\s*wheel\s*drive\b|\bfished?\s+\d+\s*(?:hour|hr)",
                    re.I)


def compass(bearing: float) -> str:
    return _POINTS[int((bearing + 11.25) % 360 // 22.5)]


def pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Lakes still unresolved, worst-consequence first."""
    return conn.execute(
        "SELECT lake_id, name, town, slug, region, lat, lon, report_count"
        " FROM lakes"
        " WHERE geo_uncertain=1 ORDER BY report_count DESC").fetchall()


def fetch_candidates(conn: sqlite3.Connection, refresh: bool = False) -> dict:
    """Every Texas/Oklahoma town matching each unresolved lake's town name.

    Cached to disk, because the review is a conversation and nobody should wait
    on the network between questions.
    """
    cache = {}
    if CACHE.exists() and not refresh:
        try:
            cache = json.loads(CACHE.read_text())
        except ValueError:
            cache = {}
    towns = {(r["town"] or "").strip() for r in pending(conn)}
    towns = {t for t in towns if t and t not in cache}
    if towns:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                          follow_redirects=True) as client:
            for town in sorted(towns):
                try:
                    res = client.get(GEOCODE, params={
                        "name": town, "count": 100, "language": "en",
                        "format": "json"}).json().get("results") or []
                except Exception:
                    res = []
                cache[town] = [
                    {"lat": c["latitude"], "lon": c["longitude"],
                     "county": c.get("admin2"), "state": c.get("admin1"),
                     "population": c.get("population")}
                    for c in res
                    if c.get("country_code") == "US"
                    and c.get("admin1") in _STATES]
                time.sleep(0.25)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return cache


def club_anchors(conn: sqlite3.Connection) -> list[tuple[float, float]]:
    """Lakes whose position is settled, which is where this club demonstrably is."""
    return [(r["lat"], r["lon"]) for r in conn.execute(
        "SELECT lat, lon FROM lakes WHERE lat IS NOT NULL AND geo_uncertain=0")]


def rank(cands: list[dict], anchors: list[tuple[float, float]],
         claims: list[dict] | None = None,
         region: tuple[float, float] | None = None) -> list[dict]:
    """Order candidate towns by the strongest evidence available for this lake.

    The evidence is not equal, so it is not blended - it is a precedence:

    1. **The page's own directions**, where they exist. They are a statement
       about this lake and beat everything else.
    2. **The club's published region.** Coarse, but published by the club.
    3. **Being an actual town.** The club publishes a town name, and a town has
       a population. Most of what the geocoder returns for a common name is
       unincorporated localities, neighbourhoods and physical features, which
       carry none - and those sit near a club lake as often as not, purely by
       chance. Leading with proximity therefore put Burnet in Fannin County and
       Palestine in Hopkins, when both are the seats of the counties they are
       named for. So a candidate with a population outranks one without.
    4. **Company and size.** Among real towns, the club leases in clusters, so
       one with another club lake nearby is a likelier fit; and these are
       private lakes on working ranches, so the biggest same-named town is
       usually wrong. Both are weak, which is why they break ties rather than
       set them - and why an earlier version leading with them put Bryan third
       for a lake the club itself files under "Houston Area".

    This orders the question. It does not answer it.
    """
    from .geo_verify import score

    out = []
    for c in cands:
        near = (min(miles_between(c["lat"], c["lon"], a, b) for a, b in anchors)
                if anchors else None)
        pop = c.get("population") or 0
        penalty = 12.0 if pop > 50_000 else 6.0 if pop > 15_000 else 0.0
        # An entry with no population is a locality or a landmark, not the town
        # the club named - rank it below every real town before anything else.
        weak = (0 if pop else 1, (near if near is not None else 0) + penalty)
        if claims:
            key = (0, score(c["lat"], c["lon"], claims)["miss"]) + weak
        elif region is not None:
            key = (1, miles_between(region[0], region[1], c["lat"],
                                    c["lon"])) + weak
        else:
            key = (2, 0) + weak
        out.append({**c, "near": None if near is None else round(near),
                    "_key": key})
    out.sort(key=lambda c: c["_key"])
    for c in out:
        c["basis"] = ("directions" if claims else
                      "club region" if region is not None else
                      "real town, then club cluster")
        c.pop("_key")
    return out


def describe(cand: dict) -> dict:
    """A candidate annotated with what a person needs to judge it."""
    miles = miles_between(HOME[0], HOME[1], cand["lat"], cand["lon"])
    return {**cand, "miles": round(miles),
            "dir": compass(bearing_from_home(cand["lat"], cand["lon"]))}


def snippets(conn: sqlite3.Connection, lake_id: int, limit: int = 4
             ) -> list[str]:
    """Anything members wrote that actually hints at where a lake is."""
    out = []
    for r in conn.execute(
            "SELECT r.body FROM trips t JOIN reports r"
            " ON r.report_id=t.report_id"
            " WHERE t.lake_id=? AND r.body IS NOT NULL", (lake_id,)):
        for m in re.finditer(r"[^.!?]{0,80}[.!?]", r["body"] or ""):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(s) < 30 or _NOISE.search(s) or not _USEFUL.search(s):
                continue
            if s not in out:
                out.append(s)
            if len(out) >= limit:
                return out
    return out


def context(conn: sqlite3.Connection, row: sqlite3.Row, cache: dict,
            anchors: list | None = None, pages: dict | None = None) -> dict:
    """Everything known about one unresolved lake, ready to render."""
    from .geo import REGION_CENTRES
    from .geo_verify import parse_directions

    if anchors is None:
        anchors = club_anchors(conn)
    claims = None
    if pages is not None:
        claims = (parse_directions(pages.get(row["slug"] or "", ""))
                  .get("claims") or None)
    cands = rank([describe(c) for c in
                  cache.get((row["town"] or "").strip(), [])],
                 anchors, claims=claims,
                 region=REGION_CENTRES.get(row["region"] or ""))
    span = conn.execute(
        "SELECT MIN(trip_date) a, MAX(trip_date) b FROM trips"
        " WHERE lake_id=? AND trip_date IS NOT NULL", (row["lake_id"],)
    ).fetchone()
    current = None
    if row["lat"] is not None:
        current = describe({"lat": row["lat"], "lon": row["lon"]})
    return {"lake": row["name"], "town": row["town"], "region": row["region"],
            "basis": cands[0]["basis"] if cands else None,
            "reports": row["report_count"] or 0, "candidates": cands,
            "current": current, "first": span["a"], "last": span["b"],
            "notes": snippets(conn, row["lake_id"])}


def apply_choice(conn: sqlite3.Connection, lake: str, lat: float, lon: float,
                 note: str = "") -> None:
    """Record a settled coordinate in the database and in the committed CSV."""
    conn.execute("UPDATE lakes SET lat=?, lon=?, geo_uncertain=0 WHERE name=?",
                 (lat, lon, lake))
    conn.commit()
    confirm(lake, lat, lon, note or "confirmed in geo-review")
