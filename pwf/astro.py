"""Moon phase and daylight, computed locally. No API, no key, no network."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

# Reference new moon: 2000-01-06 18:14 UTC.
_NEW_MOON = datetime(2000, 1, 6, 18, 14)
_SYNODIC = 29.53058867


def moon(d: date) -> tuple[float, float]:
    """Return (phase 0..1, illuminated fraction 0..1).

    phase 0 = new, 0.25 = first quarter, 0.5 = full, 0.75 = last quarter.
    """
    days = (datetime(d.year, d.month, d.day, 12) - _NEW_MOON).total_seconds() / 86400.0
    phase = (days % _SYNODIC) / _SYNODIC
    illum = (1 - math.cos(2 * math.pi * phase)) / 2
    return round(phase, 4), round(illum, 4)


def moon_name(phase: float) -> str:
    edges = [(0.033, "new"), (0.217, "waxing_crescent"), (0.283, "first_quarter"),
             (0.467, "waxing_gibbous"), (0.533, "full"), (0.717, "waning_gibbous"),
             (0.783, "last_quarter"), (0.967, "waning_crescent"), (1.01, "new")]
    for edge, name in edges:
        if phase < edge:
            return name
    return "new"


def _us_dst(d: date) -> bool:
    """US DST: second Sunday in March to first Sunday in November."""
    if d.month in (1, 2, 12):
        return False
    if 4 <= d.month <= 10:
        return True
    if d.month == 3:
        start = date(d.year, 3, 8)
        start += timedelta(days=(6 - start.weekday()) % 7)
        return d >= start
    end = date(d.year, 11, 1)
    end += timedelta(days=(6 - end.weekday()) % 7)
    return d < end


def sun_times(d: date, lat: float, lon: float, tz_offset_h: float | None = None
              ) -> tuple[str | None, str | None, float | None]:
    """NOAA sunrise/sunset. Returns (sunrise, sunset, day length hours), local.

    Defaults to US Central time with daylight saving applied, which is where
    every club property sits.
    """
    if tz_offset_h is None:
        tz_offset_h = -5.0 if _us_dst(d) else -6.0
    if lat is None or lon is None:
        return None, None, None
    # Days since the J2000 epoch (2000-01-01 12:00 UT), with the longitude
    # correction that turns it into mean solar time at this meridian.
    # JD 2451545.0 is 2000-01-01 12:00 UT, so `days` alone already lands on
    # local noon UT; only the longitude correction is needed on top of it.
    days = d.toordinal() - date(2000, 1, 1).toordinal()
    n = days + 0.0008 - lon / 360.0
    m = (357.5291 + 0.98560028 * n) % 360
    c = (1.9148 * math.sin(math.radians(m)) + 0.0200 * math.sin(math.radians(2 * m))
         + 0.0003 * math.sin(math.radians(3 * m)))
    lam = (m + c + 180 + 102.9372) % 360
    j_transit = 2451545.0 + n + 0.0053 * math.sin(math.radians(m)) \
        - 0.0069 * math.sin(math.radians(2 * lam))
    decl = math.asin(math.sin(math.radians(lam)) * math.sin(math.radians(23.44)))

    try:
        cos_w = ((math.sin(math.radians(-0.833)) - math.sin(math.radians(lat)) * math.sin(decl))
                 / (math.cos(math.radians(lat)) * math.cos(decl)))
        w = math.degrees(math.acos(max(-1.0, min(1.0, cos_w))))
    except (ValueError, ZeroDivisionError):
        return None, None, None

    j_set = j_transit + w / 360.0
    j_rise = j_transit - w / 360.0

    def to_local(j: float) -> str:
        hours = (j - 2451545.0 + 0.5) % 1.0 * 24.0 + tz_offset_h
        hours %= 24.0
        return f"{int(hours):02d}:{int((hours % 1) * 60):02d}"

    day_len = round(2 * w / 360.0 * 24.0, 2)
    return to_local(j_rise), to_local(j_set), day_len
