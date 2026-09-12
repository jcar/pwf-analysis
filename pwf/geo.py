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
# Club properties are all in Texas and Oklahoma.
_STATES = {"Texas": 0, "Oklahoma": 1}


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


def geocode_town(client: httpx.Client, town: str) -> tuple[float, float] | None:
    try:
        r = client.get(GEOCODE, params={"name": town, "count": 10,
                                        "language": "en", "format": "json"})
        results = r.json().get("results") or []
    except Exception:
        return None
    best, best_rank = None, 99
    for res in results:
        if res.get("country_code") != "US":
            continue
        rank = _STATES.get(res.get("admin1", ""), 9)
        if rank < best_rank:
            best, best_rank = res, rank
    if best is None:
        return None
    return best["latitude"], best["longitude"]


def geocode_lakes(conn: sqlite3.Connection, force: bool = False) -> dict:
    overrides = _load_overrides()
    rows = conn.execute(
        "SELECT lake_id, name, town, lat, lon FROM lakes ORDER BY report_count DESC"
    ).fetchall()
    stats = {"override": 0, "geocoded": 0, "cached": 0, "failed": 0, "no_town": 0}
    cache: dict[str, tuple[float, float] | None] = {}

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                      follow_redirects=True) as client:
        for r in rows:
            if r["name"] in overrides:
                lat, lon = overrides[r["name"]]
                conn.execute("UPDATE lakes SET lat=?, lon=? WHERE lake_id=?",
                             (lat, lon, r["lake_id"]))
                stats["override"] += 1
                continue
            if r["lat"] is not None and not force:
                stats["cached"] += 1
                continue
            town = (r["town"] or "").strip()
            if not town:
                stats["no_town"] += 1
                continue
            if town not in cache:
                cache[town] = geocode_town(client, town)
                time.sleep(0.25)
            hit = cache[town]
            if hit is None:
                stats["failed"] += 1
                continue
            conn.execute("UPDATE lakes SET lat=?, lon=? WHERE lake_id=?",
                         (hit[0], hit[1], r["lake_id"]))
            stats["geocoded"] += 1
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
