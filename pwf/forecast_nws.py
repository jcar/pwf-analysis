"""A second forecast source, so one vendor's daily cap cannot empty the page.

Open-Meteo meters by request weight on a free tier, and a single large weather
backfill can spend the whole day's budget - after which the planner's briefs
ship with no conditions at all. The US National Weather Service publishes the
same kind of forecast with no key and no daily cap, and every club property is
in Texas or Oklahoma, so it covers the entire footprint.

What it cannot supply is **pressure**: the gridpoint feed carries the field but
returns no values. That is tolerable here and nowhere else - the archive's own
pressure-trend effects all sat within noise, the largest weather effect measured
being calm-versus-windy at a 95%% interval of [-1%%, +21%%] - so a forecast
without it loses nothing the page was entitled to claim.

Two things this is deliberately *not* used for:

* **Backfilling history.** The stored conditions are ERA5 reanalysis. Filling
  some lakes from a different source would make those lakes systematically
  unlike the rest and quietly bias every cross-lake comparison. History stays
  on one source even when that means waiting.
* **The primary path.** Open-Meteo is tried first so the forecast matches the
  historical baseline it gets compared against. This is the fallback.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime

import httpx

from .config import DATA, USER_AGENT

POINTS = "https://api.weather.gov/points/{lat},{lon}"
# The points -> gridpoint mapping never changes, so it is worth keeping: it
# halves the request count on every later run.
GRID_CACHE = DATA / "nws_gridpoints.json"
_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?")


def _hours(duration: str) -> int:
    m = _DURATION.match(duration or "")
    if not m:
        return 1
    days, hours = m.group(1), m.group(2)
    return max(1, int(days or 0) * 24 + int(hours or 0))


def _by_date(series: dict | None) -> dict[str, list[float]]:
    """Expand an NWS interval series into values bucketed by calendar date."""
    out: dict[str, list[float]] = defaultdict(list)
    for entry in (series or {}).get("values") or []:
        raw = entry.get("value")
        if raw is None:
            continue
        stamp, _, dur = (entry.get("validTime") or "").partition("/")
        try:
            start = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        for h in range(_hours(dur)):
            day = start.replace(hour=0, minute=0, second=0, microsecond=0)
            idx = (start.hour + h) // 24
            key = (day.toordinal() + idx)
            out[datetime.fromordinal(key).date().isoformat()].append(float(raw))
    return out


def _c_to_f(c):
    return None if c is None else c * 9 / 5 + 32


def _kmh_to_mph(k):
    return None if k is None else k * 0.621371


def _load_grid_cache() -> dict:
    try:
        return json.loads(GRID_CACHE.read_text())
    except (OSError, ValueError):
        return {}


def gridpoint_url(client: httpx.Client, lat: float, lon: float,
                  cache: dict) -> str | None:
    key = f"{lat},{lon}"
    if key in cache:
        return cache[key]
    r = client.get(POINTS.format(lat=lat, lon=lon))
    r.raise_for_status()
    url = (r.json().get("properties") or {}).get("forecastGridData")
    if url:
        cache[key] = url
    return url


def fetch_forecast_nws(cells: list[tuple[float, float]]
                       ) -> dict[tuple, dict[str, dict]]:
    """Daily forecast per grid cell, shaped exactly like the Open-Meteo one.

    Missing values stay `None` rather than being invented, so a brief shows the
    fields this source actually has and says nothing about the rest.
    """
    if not cells:
        return {}
    cache = _load_grid_cache()
    out: dict[tuple, dict[str, dict]] = {}
    headers = {"User-Agent": f"{USER_AGENT} (pwf-analysis)",
               "Accept": "application/geo+json"}
    with httpx.Client(headers=headers, timeout=60,
                      follow_redirects=True) as client:
        for cell in cells:
            try:
                url = gridpoint_url(client, cell[0], cell[1], cache)
                if not url:
                    continue
                g = client.get(url)
                g.raise_for_status()
                props = g.json().get("properties") or {}
            except Exception:
                continue

            hi = _by_date(props.get("maxTemperature"))
            lo = _by_date(props.get("minTemperature"))
            sky = _by_date(props.get("skyCover"))
            wind = _by_date(props.get("windSpeed"))
            wdir = _by_date(props.get("windDirection"))
            rain = _by_date(props.get("quantitativePrecipitation"))

            by_date = {}
            for day in sorted(set(hi) | set(lo)):
                tmax = _c_to_f(max(hi[day])) if hi.get(day) else None
                tmin = _c_to_f(min(lo[day])) if lo.get(day) else None
                mean = None
                if tmax is not None and tmin is not None:
                    mean = (tmax + tmin) / 2
                by_date[day] = {
                    "temp_max_f": tmax, "temp_min_f": tmin,
                    "temp_mean_f": mean,
                    "precip_in": (sum(rain[day]) / 25.4
                                  if rain.get(day) else None),
                    "wind_max_mph": (_kmh_to_mph(max(wind[day]))
                                     if wind.get(day) else None),
                    "wind_dir_deg": (wdir[day][len(wdir[day]) // 2]
                                     if wdir.get(day) else None),
                    "cloud_pct": (sum(sky[day]) / len(sky[day])
                                  if sky.get(day) else None),
                    # The gridpoint feed carries the field but no values.
                    "pressure_hpa": None, "pressure_delta_24h": None,
                    "pressure_trend": None,
                    "source": "nws",
                }
            if by_date:
                out[cell] = by_date

    try:
        GRID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GRID_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    except OSError:
        pass
    return out
