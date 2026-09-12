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


def geocode_town(client: httpx.Client, town: str,
                 state: str | None = None) -> tuple[float, float] | None:
    """Look up a town, accepting only Texas and Oklahoma matches.

    Common town names repeat across states, so a match outside the club's two
    states is rejected outright rather than used as a fallback.
    """
    try:
        r = client.get(GEOCODE, params={"name": town, "count": 100,
                                        "language": "en", "format": "json"})
        results = r.json().get("results") or []
    except Exception:
        return None

    wanted = {state} if state else set(_STATES)
    best, best_rank, best_pop = None, 99, -1
    for res in results:
        if res.get("country_code") != "US":
            continue
        admin1 = res.get("admin1", "")
        if admin1 not in wanted:
            continue
        rank = _STATES.get(admin1, 9)
        pop = res.get("population") or 0
        if (rank, -pop) < (best_rank, -best_pop):
            best, best_rank, best_pop = res, rank, pop
    if best is None:
        return None
    return best["latitude"], best["longitude"]


def geocode_lakes(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Resolve coordinates for every lake.

    The network phase runs first and the database is written afterwards: holding
    a write transaction open across HTTP calls locks out anything else using the
    database, which is fatal to a crawl running at the same time.
    """
    overrides = _load_overrides()
    rows = conn.execute(
        "SELECT lake_id, name, town, lat, lon FROM lakes ORDER BY report_count DESC"
    ).fetchall()
    stats = {"override": 0, "geocoded": 0, "cached": 0, "failed": 0, "no_town": 0}
    cache: dict[tuple, tuple[float, float] | None] = {}
    pending: list[tuple[float, float, int]] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                      follow_redirects=True) as client:
        for r in rows:
            if r["name"] in overrides:
                lat, lon = overrides[r["name"]]
                pending.append((lat, lon, r["lake_id"]))
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

            key = (town, state)
            if key not in cache:
                cache[key] = geocode_town(client, town, state)
                time.sleep(0.25)
            hit = cache[key]
            if hit is None:
                stats["failed"] += 1
                continue
            pending.append((hit[0], hit[1], r["lake_id"]))
            stats["geocoded"] += 1

    # Single short write transaction, after all network work is done.
    conn.executemany("UPDATE lakes SET lat=?, lon=? WHERE lake_id=?", pending)
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
