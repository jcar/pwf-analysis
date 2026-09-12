"""Historical weather per lake-date from the Open-Meteo archive (free, no key).

One request covers a lake's entire history because the archive exposes daily
aggregates, including mean sea-level pressure and cloud cover. Sea-level
pressure is used rather than surface pressure so that lakes at different
elevations stay comparable.

This is the layer that makes the sparse narrative fields tolerable: clarity
appears in ~18% of reports and water temperature in ~7%, but pressure, wind,
temperature and cloud are available for 100% of attributed trips.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import date, timedelta

import httpx

from .astro import moon, sun_times
from .config import USER_AGENT

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
DAILY = ("temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
         "precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant,"
         "cloud_cover_mean,pressure_msl_mean")
UNITS = {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
         "precipitation_unit": "inch", "timezone": "America/Chicago"}
# A day either side of this band counts as a front rather than normal drift.
TREND_HPA = 2.0


def classify_trend(delta_24h: float | None) -> str | None:
    if delta_24h is None:
        return None
    if delta_24h >= TREND_HPA:
        return "rising"
    if delta_24h <= -TREND_HPA:
        return "falling"
    return "steady"


def _series(payload: dict) -> dict[str, list]:
    return payload.get("daily") or {}


def fetch_range(client: httpx.Client, lat: float, lon: float,
                start: date, end: date, url: str = ARCHIVE) -> dict[str, list]:
    params = {"latitude": lat, "longitude": lon, "daily": DAILY, **UNITS}
    if url == ARCHIVE:
        params |= {"start_date": start.isoformat(), "end_date": end.isoformat()}
    else:
        params |= {"past_days": 7, "forecast_days": 16}
    r = client.get(url, params=params, timeout=90)
    r.raise_for_status()
    return _series(r.json())


def _rows_from_series(lake_id: int, lat: float, lon: float,
                      s: dict[str, list]) -> list[tuple]:
    times = s.get("time") or []
    get = lambda k, i: (s.get(k) or [None] * len(times))[i]  # noqa: E731
    press = s.get("pressure_msl_mean") or [None] * len(times)
    temps = s.get("temperature_2m_mean") or [None] * len(times)

    rows = []
    for i, t in enumerate(times):
        try:
            d = date.fromisoformat(t)
        except ValueError:
            continue
        p = press[i]
        p24 = press[i - 1] if i >= 1 else None
        p48 = press[i - 2] if i >= 2 else None
        d24 = round(p - p24, 2) if (p is not None and p24 is not None) else None
        d48 = round(p - p48, 2) if (p is not None and p48 is not None) else None

        window = [x for x in temps[max(0, i - 6): i + 1] if x is not None]
        t7 = round(sum(window) / len(window), 1) if window else None

        phase, illum = moon(d)
        rise, set_, daylen = sun_times(d, lat, lon)

        rows.append((
            lake_id, d.isoformat(),
            get("temperature_2m_max", i), get("temperature_2m_min", i),
            get("temperature_2m_mean", i), t7,
            get("precipitation_sum", i), get("wind_speed_10m_max", i),
            get("wind_direction_10m_dominant", i), get("cloud_cover_mean", i),
            p, d24, d48, classify_trend(d24),
            phase, illum, rise, set_, daylen,
        ))
    return rows


def _store(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO conditions (lake_id,date,temp_max_f,temp_min_f,"
        "temp_mean_f,temp_7d_mean_f,precip_in,wind_max_mph,wind_dir_deg,cloud_pct,"
        "pressure_hpa,pressure_delta_24h,pressure_delta_48h,pressure_trend,"
        "moon_phase,moon_illum,sunrise,sunset,day_length_h)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def backfill(conn: sqlite3.Connection, progress=print) -> dict:
    """Fetch history for every lake that has geocoded coordinates and trips."""
    lakes = conn.execute("""
        SELECT l.lake_id, l.name, l.lat, l.lon,
               MIN(t.trip_date) AS d0, MAX(t.trip_date) AS d1, COUNT(*) AS n
        FROM lakes l JOIN trips t ON t.lake_id = l.lake_id
        WHERE l.lat IS NOT NULL AND t.trip_date IS NOT NULL
        GROUP BY l.lake_id ORDER BY n DESC""").fetchall()

    stats = {"lakes": 0, "rows": 0, "failed": 0}
    today = date.today()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90,
                      follow_redirects=True) as client:
        for i, lk in enumerate(lakes, 1):
            try:
                start = date.fromisoformat(lk["d0"]) - timedelta(days=3)
                end = min(date.fromisoformat(lk["d1"]), today - timedelta(days=1))
            except (TypeError, ValueError):
                continue
            if end < start:
                continue
            try:
                s = fetch_range(client, lk["lat"], lk["lon"], start, end)
                rows = _rows_from_series(lk["lake_id"], lk["lat"], lk["lon"], s)
                # Write and commit immediately - the fetch above must never sit
                # inside an open write transaction.
                _store(conn, rows)
                conn.commit()
                stats["lakes"] += 1
                stats["rows"] += len(rows)
            except Exception as exc:
                stats["failed"] += 1
                progress(f"  ! {lk['name']}: {type(exc).__name__}: {exc}")
            if i % 10 == 0:
                progress(f"  weather {i}/{len(lakes)} lakes, {stats['rows']} rows")
            time.sleep(0.2)
    conn.commit()
    return stats


def forecast(lat: float, lon: float) -> dict[str, dict]:
    """Near-term forecast keyed by ISO date, for the trip planner."""
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60,
                      follow_redirects=True) as client:
        s = fetch_range(client, lat, lon, date.today(), date.today(), url=FORECAST)
    rows = _rows_from_series(0, lat, lon, s)
    cols = ("lake_id", "date", "temp_max_f", "temp_min_f", "temp_mean_f",
            "temp_7d_mean_f", "precip_in", "wind_max_mph", "wind_dir_deg",
            "cloud_pct", "pressure_hpa", "pressure_delta_24h",
            "pressure_delta_48h", "pressure_trend", "moon_phase", "moon_illum",
            "sunrise", "sunset", "day_length_h")
    return {r[1]: dict(zip(cols, r)) for r in rows}
