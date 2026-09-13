"""Geocode each lake from its town. Free Open-Meteo endpoint, no API key.

Town-level precision is deliberate: weather systems are regional, and the club
publishes a town rather than coordinates. Corrections live in
data/lake_coords.csv, which is committed and always wins over the lookup.
"""
from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path

import httpx

from .config import DATA, USER_AGENT

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OVERRIDES = DATA / "lake_coords.csv"
# Club properties are all in Texas and Oklahoma. Anything else is a wrong hit -
# there is a Lancaster in California as well as in Texas, and accepting it would
# silently attach the wrong weather to every trip on that lake.
_STATES = {"Texas": 0, "Oklahoma": 1}
_STATE_CODES = {"TX": "Texas", "OK": "Oklahoma"}

# Town names repeat inside Texas too: 82 of the club's 111 towns have more than
# one Texas or Oklahoma match. Picking the most populous one is actively wrong
# here - these are private lakes on rural ranches, so the small candidate is
# usually the right one. Walnut Springs resolved to a town of 27,864 near San
# Antonio when the club's lake is in Bosque County, population 811, 170 miles
# north.
#
# The club publishes which metro each property belongs to, so where that exists
# it is the disambiguator: take the candidate nearest the stated region.
#
# Where it does not - 95 of 183 lakes, mostly retired properties whose pages are
# gone - there is no reliable signal, and guessing "nearest Dallas" is actively
# harmful: it drags genuinely distant lakes north, moving Kyle, Taylor, Vernon
# and Houston away from the real towns of those names. Those lakes fall back to
# the largest same-named town, which is right for well-known names, and any that
# remain ambiguous are marked uncertain rather than quietly trusted.
REGION_CENTRES = {
    "Dallas / Fort Worth Area": (32.78, -96.80),
    "Houston Area": (29.76, -95.37),
    "Austin Area": (30.27, -97.74),
    "San Antonio Area": (29.42, -98.49),
    "Oklahoma Area": (35.47, -97.52),
    "East Texas": (32.35, -95.30),
    "West Texas": (32.45, -99.73),
}
CLUB_CENTRE = (32.78, -96.80)


def _load_overrides() -> dict[str, tuple[float, float]]:
    if not OVERRIDES.exists():
        return {}
    out = {}
    with OVERRIDES.open() as fh:
        for row in csv.DictReader(fh):
            try:
                out[row["lake"].strip()] = (float(row["lat"]), float(row["lon"]))
            except (KeyError, ValueError):
                continue
    return out


def geocode_town(client: httpx.Client, town: str, state: str | None = None,
                 near: tuple[float, float] | None = None
                 ) -> tuple[float, float] | None:
    hit = _geocode(client, town, state, near)
    return None if hit is None else (hit["lat"], hit["lon"])


def _geocode(client: httpx.Client, town: str, state: str | None = None,
             near: tuple[float, float] | None = None) -> dict | None:
    """Look up a town, accepting only Texas and Oklahoma matches.

    Common town names repeat across states *and* within Texas, so a match
    outside the club's two states is rejected outright, and among the survivors
    the one nearest `near` wins. Population is deliberately not the tiebreak:
    these lakes sit on rural ranches, so the biggest same-named town is usually
    the wrong one.
    """
    from .geo_shapes import miles_between

    try:
        r = client.get(GEOCODE, params={"name": town, "count": 100,
                                        "language": "en", "format": "json"})
        results = r.json().get("results") or []
    except Exception:
        return None

    wanted = {state} if state else set(_STATES)
    cands = [r for r in results
             if r.get("country_code") == "US" and r.get("admin1") in wanted]
    if not cands:
        return None

    if near is not None:
        # A stated region: take the candidate nearest it.
        best = min(cands, key=lambda r: (
            _STATES.get(r.get("admin1", ""), 9),
            miles_between(near[0], near[1], r["latitude"], r["longitude"])))
        uncertain = False
    else:
        # No region to go on. The largest same-named town is right for
        # well-known names; flag the rest rather than pretend.
        best = max(cands, key=lambda r: (
            -_STATES.get(r.get("admin1", ""), 9), r.get("population") or 0))
        spread = max(
            miles_between(best["latitude"], best["longitude"],
                          r["latitude"], r["longitude"]) for r in cands)
        uncertain = len(cands) > 1 and spread > 25

    return {"lat": best["latitude"], "lon": best["longitude"],
            "uncertain": uncertain, "candidates": len(cands)}


def geocode_lakes(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Resolve coordinates for every lake.

    The network phase runs first and the database is written afterwards: holding
    a write transaction open across HTTP calls locks out anything else using the
    database, which is fatal to a crawl running at the same time.
    """
    overrides = _load_overrides()
    rows = conn.execute(
        "SELECT lake_id, name, town, lat, lon, region FROM lakes"
        " ORDER BY report_count DESC").fetchall()
    stats = {"override": 0, "geocoded": 0, "cached": 0, "failed": 0,
             "no_town": 0, "uncertain": 0}
    cache: dict[tuple, tuple[float, float] | None] = {}
    pending: list[tuple[float, float, int]] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                      follow_redirects=True) as client:
        for r in rows:
            if r["name"] in overrides:
                lat, lon = overrides[r["name"]]
                # A hand-corrected coordinate is never uncertain.
                pending.append((lat, lon, 0, r["lake_id"]))
                stats["override"] += 1
                continue
            if r["lat"] is not None and not force:
                stats["cached"] += 1
                continue

            town = (r["town"] or "").strip()
            state = None
            # A few listing strings carry "<Lake>, <Town>, <ST>", which leaves a
            # bare state code in the town column.
            if town.upper() in _STATE_CODES:
                state = _STATE_CODES[town.upper()]
                town = (r["name"] or "").rsplit(",", 1)[-1].strip()
            if not town:
                stats["no_town"] += 1
                continue

            # The club's own region for this property is the best available
            # prior on which same-named town is meant.
            anchor = REGION_CENTRES.get(r["region"] or "") if r["region"] else None
            key = (town, state, anchor)
            if key not in cache:
                cache[key] = _geocode(client, town, state, near=anchor)
                time.sleep(0.25)
            hit = cache[key]
            if hit is None:
                stats["failed"] += 1
                continue
            pending.append((hit["lat"], hit["lon"], int(hit["uncertain"]),
                            r["lake_id"]))
            stats["geocoded"] += 1
            stats["uncertain"] += int(hit["uncertain"])

    # Single short write transaction, after all network work is done.
    conn.executemany(
        "UPDATE lakes SET lat=?, lon=?, geo_uncertain=? WHERE lake_id=?", pending)
    conn.commit()
    return stats


def write_override_template(conn: sqlite3.Connection) -> Path:
    """Dump current coordinates so outliers can be hand-corrected."""
    rows = conn.execute(
        "SELECT name, town, lat, lon, report_count FROM lakes"
        " ORDER BY report_count DESC").fetchall()
    with OVERRIDES.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lake", "town", "lat", "lon", "reports"])
        for r in rows:
            w.writerow([r["name"], r["town"] or "", r["lat"] or "",
                        r["lon"] or "", r["report_count"] or 0])
    return OVERRIDES
