"""Which lake to fish on a given day.

The ranking is built on the one signal that measurably predicts anything.
Backtested year by year (see tests/test_recommend.py), a lake's own history
predicts its next season's catch rate at r ~= 0.65, six years running. Lake x
month separates lakes by about 3.1x.

Weather does not. Measured *within* each lake-month, so lake and season cannot
confound it, the largest effect in the archive - calm versus windy - is about
10%, and its 95% bootstrap interval includes zero. Cloud is 9%, pressure 7%,
moon 3%. Those are real directions and match angling lore, but at this sample
size none of them is distinguishable from noise.

So the forecast is fetched and shown, because you want to know it will blow 25
and hit 99 degrees, and it is deliberately kept out of the score. Passing
`weight_conditions=True` applies the measured multipliers anyway, for anyone who
wants them; it is off by default and labelled as within noise.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import json
import time

import httpx
import numpy as np
import pandas as pd

from . import analysis as A
from .config import USER_AGENT, DATA
from .profile import confidence, miles_from_home
from .weather import DAILY, UNITS, grid_key

FORECAST = "https://api.open-meteo.com/v1/forecast"
# Trips inside this window count as "recent form".
RECENT_YEARS = 3
# Weight on recent form when blending with the long run; chosen by backtest.
RECENT_WEIGHT = 0.6
# Prior strength, in equivalent trips, pulling a month figure toward the lake's
# own level.
SHRINK_K = 12.0
# Prior strength pulling a thin lake's whole level toward the club mean, so a
# handful of lucky trips cannot make a lake look twice as good as it is.
CLUB_SHRINK_K = 15.0
MIN_TRIPS = 5
# Widening applied when a lake has no trips in the target month and its annual
# average has to stand in for one.
EXTRAPOLATION_PENALTY = 1.6

# Measured multipliers, only applied when explicitly asked for. Every one of
# these sits inside noise - they are here for curiosity, not for ranking.
CONDITION_MULTIPLIERS = {
    "wind_band": {"calm": 1.06, "moderate": 1.00, "windy": 0.96},
    "cloud_band": {"clear_sky": 0.96, "partly": 1.00, "overcast": 1.02},
    "pressure_trend": {"falling": 0.98, "steady": 1.02, "rising": 1.00},
}


FORECAST_CACHE = DATA / "forecast_cache.json"
# A forecast for a day still six days out does not move much in an hour, and
# Open-Meteo's free tier meters by request weight - a weather backfill can eat
# the budget and leave the page with no conditions at all. So the last good
# answer is kept and reused when the live call fails.
FORECAST_CACHE_HOURS = 12


def _load_forecast_cache() -> dict:
    try:
        raw = json.loads(FORECAST_CACHE.read_text())
    except (OSError, ValueError):
        return {}
    age = time.time() - raw.get("fetched_at", 0)
    if age > FORECAST_CACHE_HOURS * 3600:
        return {}
    return {tuple(json.loads(k)): v for k, v in (raw.get("cells") or {}).items()}


def _save_forecast_cache(out: dict) -> None:
    try:
        FORECAST_CACHE.parent.mkdir(parents=True, exist_ok=True)
        FORECAST_CACHE.write_text(json.dumps({
            "fetched_at": time.time(),
            "cells": {json.dumps(list(k)): v for k, v in out.items()},
        }))
    except OSError:
        pass


def fetch_forecast(cells: list[tuple[float, float]],
                   allow_stale: bool = False) -> dict[tuple, dict[str, dict]]:
    """Forecast for every lake grid cell in a single request.

    Open-Meteo takes comma-separated coordinate lists and returns one block per
    location, so the whole club costs one call rather than ninety.

    With `allow_stale`, a rate-limited call falls back to the last good answer
    rather than returning nothing - a slightly old forecast beats a brief with
    no conditions in it. The caller is told which it got.
    """
    if not cells:
        return {}
    params = {
        "latitude": ",".join(str(a) for a, _ in cells),
        "longitude": ",".join(str(b) for _, b in cells),
        "daily": DAILY, **UNITS,
        "forecast_days": 16, "past_days": 2,
    }
    try:
        r = httpx.get(FORECAST, params=params,
                      headers={"User-Agent": USER_AGENT}, timeout=90)
        r.raise_for_status()
    except Exception:
        if not allow_stale:
            raise
        # Prefer the last good Open-Meteo answer, because it matches the ERA5
        # baseline the forecast gets compared against. Fall back to the NWS for
        # whatever the cache does not cover - a forecast from a second source
        # beats a brief with no conditions in it.
        cached = _load_forecast_cache()
        out = {c: cached[c] for c in cells if c in cached}
        missing = [c for c in cells if c not in out]
        if missing:
            from .forecast_nws import fetch_forecast_nws
            try:
                out.update(fetch_forecast_nws(missing))
            except Exception:
                pass
        return out
    payload = r.json()
    blocks = payload if isinstance(payload, list) else [payload]

    out: dict[tuple, dict[str, dict]] = {}
    for cell, block in zip(cells, blocks):
        daily = block.get("daily") or {}
        times = daily.get("time") or []
        press = daily.get("pressure_msl_mean") or [None] * len(times)
        by_date = {}
        for i, t in enumerate(times):
            p = press[i]
            p24 = press[i - 1] if i >= 1 else None
            by_date[t] = {
                "temp_max_f": _at(daily, "temperature_2m_max", i),
                "temp_min_f": _at(daily, "temperature_2m_min", i),
                "precip_in": _at(daily, "precipitation_sum", i),
                "wind_max_mph": _at(daily, "wind_speed_10m_max", i),
                "wind_dir_deg": _at(daily, "wind_direction_10m_dominant", i),
                "cloud_pct": _at(daily, "cloud_cover_mean", i),
                "pressure_hpa": p,
                "pressure_delta_24h": (round(p - p24, 2)
                                       if p is not None and p24 is not None else None),
            }
        out[cell] = by_date
    _save_forecast_cache(out)
    return out

def _at(daily, key, i):
    vals = daily.get(key)
    return vals[i] if vals and i < len(vals) else None


def _band(value, edges, labels):
    if value is None:
        return None
    for edge, label in zip(edges, labels):
        if value <= edge:
            return label
    return labels[-1]


def describe_forecast(fc: dict) -> dict:
    """Turn raw forecast numbers into the bands the archive is binned by."""
    if not fc:
        return {}
    d = dict(fc)
    d["wind_band"] = _band(fc.get("wind_max_mph"), [7, 15], ["calm", "moderate", "windy"])
    d["cloud_band"] = _band(fc.get("cloud_pct"), [30, 70], ["clear_sky", "partly", "overcast"])
    delta = fc.get("pressure_delta_24h")
    d["pressure_trend"] = (None if delta is None else
                           "rising" if delta >= 2 else
                           "falling" if delta <= -2 else "steady")
    return d


def _expected_rate(lake_trips: pd.DataFrame, month: int,
                   club_month_mean: float, club_mean: float) -> dict:
    """Blend this lake's recent form and long run for the target month.

    Three fallbacks, widest last: the lake in that month, the lake in any month
    scaled by the club's seasonal shape, then the club mean. Each is shrunk
    toward the level above it by how little data supports it.
    """
    scored = lake_trips.dropna(subset=["fish_per_hour"])
    if len(scored) < MIN_TRIPS:
        return {"expected": None, "n": len(scored), "basis": "insufficient"}

    this_year = date.today().year
    recent = scored[scored["year"] >= this_year - RECENT_YEARS]

    def blended(df):
        if df.empty:
            return None, 0
        rec = df[df["year"] >= this_year - RECENT_YEARS]["fish_per_hour"]
        allt = df["fish_per_hour"]
        if len(rec) >= MIN_TRIPS:
            val = RECENT_WEIGHT * rec.mean() + (1 - RECENT_WEIGHT) * allt.mean()
        else:
            val = allt.mean()
        return float(val), int(len(allt))

    in_month = scored[scored["month"] == month]
    lake_all, n_all = blended(scored)
    seasonal = (club_month_mean / club_mean) if club_mean else 1.0

    # Two levels of shrinkage, so the chain bottoms out at the club rather than
    # at the lake's own average. Without this a lake with five trips at twelve
    # fish an hour was simply believed: its month figure was pulled toward its
    # own annual figure, which the same five trips produced, so nothing pulled
    # it toward reality at all.
    lake_level = ((n_all * lake_all + CLUB_SHRINK_K * club_mean)
                  / (n_all + CLUB_SHRINK_K)) if lake_all is not None else club_mean

    if len(in_month) >= MIN_TRIPS:
        raw, n = blended(in_month)
        prior = lake_level * seasonal
        basis = "lake-month"
    else:
        raw, n = lake_level, n_all
        raw = raw * seasonal if raw else None
        prior = club_month_mean
        basis = "lake-year" if n_all else "club"

    if raw is None:
        return {"expected": None, "n": 0, "basis": "insufficient"}

    expected = (n * raw + SHRINK_K * prior) / (n + SHRINK_K)

    # Penalise thin evidence so a four-trip lake cannot top the list on luck.
    #
    # The sample behind the estimate is everything known about the lake, not
    # just the trips in the target month: the month figure is blended with a
    # lake-level prior that all of them inform. Using the month count alone
    # penalised well-covered lakes hardest - a lake with 105 trips and 15 in
    # September scored worse than one with 36 trips and none - which is exactly
    # backwards.
    n_eff = len(scored) + SHRINK_K
    se = scored["fish_per_hour"].std(ddof=0) / np.sqrt(n_eff)
    if se != se:
        se = 0.0
    # Carrying an annual average into a specific month is an extra assumption,
    # so widen the interval when there is no month-specific evidence.
    if basis != "lake-month":
        se *= EXTRAPOLATION_PENALTY
    lower = max(0.0, expected - se)
    return {"expected": round(expected, 2), "lower": round(lower, 2),
            "raw": round(raw, 2), "n": int(n), "n_total": int(len(scored)),
            "n_recent": int(len(recent)), "basis": basis,
            "se": round(float(se), 3)}


def recommend(conn: sqlite3.Connection, when: date | None = None,
              max_miles: float | None = 200, limit: int = 15,
              cohort: str | None = None, min_trips: int = MIN_TRIPS,
              weight_conditions: bool = False,
              with_forecast: bool = True) -> dict:
    """Rank lakes for a given day."""
    when = when or _next_saturday()
    trips = A.trips_frame(conn)
    lures = A.lures_frame(conn)
    if trips.empty:
        return {"date": when.isoformat(), "lakes": [], "error": "no trips"}

    scored_all = trips.dropna(subset=["fish_per_hour"])
    club_mean = float(scored_all["fish_per_hour"].mean())
    month_means = scored_all.groupby("month")["fish_per_hour"].mean()
    club_month_mean = float(month_means.get(when.month, club_mean))

    lakes = conn.execute(
        "SELECT lake_id, name, town, lat, lon, acres, max_depth_ft, cohort,"
        " membership_tier, day_rate, half_day_rate, region"
        " FROM lakes WHERE lat IS NOT NULL AND report_count > 0").fetchall()

    # How steady each lake has been. Shown, never scored - past volatility
    # predicts future volatility at only r~0.20, so it informs the choice
    # without pretending to forecast it.
    from .consistency import club_bust_rate, lake_consistency
    consistency = lake_consistency(trips)
    club_bust = club_bust_rate(trips)

    # One request covers every grid cell the club occupies.
    forecasts: dict = {}
    if with_forecast:
        cells = sorted({grid_key(r["lat"], r["lon"]) for r in lakes})
        try:
            forecasts = fetch_forecast(cells)
        except Exception:
            forecasts = {}

    rows = []
    for lk in lakes:
        miles = miles_from_home(lk["lat"], lk["lon"])
        if max_miles is not None and (miles is None or miles > max_miles):
            continue
        if cohort and lk["cohort"] != cohort:
            continue

        mine = trips[trips["lake_id"] == lk["lake_id"]]
        est = _expected_rate(mine, when.month, club_month_mean, club_mean)
        if est["expected"] is None or est["n_total"] < min_trips:
            continue

        fc = describe_forecast(
            forecasts.get(grid_key(lk["lat"], lk["lon"]), {}).get(when.isoformat(), {}))

        score = est["lower"]
        adj = 1.0
        if weight_conditions and fc:
            for key, table in CONDITION_MULTIPLIERS.items():
                adj *= table.get(fc.get(key) or "", 1.0)
            score *= adj

        month_trips = mine[mine["month"] == when.month]
        top = A.lure_lift(month_trips if len(month_trips.dropna(
            subset=["fish_per_hour"])) >= 8 else mine,
            lures[lures["report_id"].isin(mine["report_id"])], min_n=3)

        rows.append({
            "lake": lk["name"], "town": lk["town"], "miles": miles,
            "acres": lk["acres"], "cohort": lk["cohort"],
            "membership_tier": lk["membership_tier"],
            "day_rate": lk["day_rate"], "region": lk["region"],
            "expected_fph": est["expected"], "score": round(score, 3),
            "n_basis": est["n"], "n_total": est["n_total"],
            "basis": est["basis"], "confidence": confidence(est["n_total"]),
            "condition_adj": round(adj, 3) if weight_conditions else None,
            "forecast": {k: fc.get(k) for k in
                         ("temp_max_f", "wind_max_mph", "wind_band", "cloud_pct",
                          "cloud_band", "precip_in", "pressure_trend",
                          "pressure_delta_24h")} if fc else None,
            "consistency": _slim_consistency(consistency.get(lk["name"])),
            "top_baits": [{"bait": i, "n": int(r["n_trips"]),
                           "lift": round(float(r["lift"]), 2)}
                          for i, r in top.head(3).iterrows()],
        })

    # Sort on the score alone. Consistency rides along as a column so that a
    # long drive to the club's swingiest lake is a choice, not a surprise.
    rows.sort(key=lambda r: -r["score"])
    return {
        "date": when.isoformat(),
        "club_bust_rate": club_bust,
        "month_name": when.strftime("%B"),
        "max_miles": max_miles,
        "cohort": cohort,
        "club_month_mean": round(club_month_mean, 2),
        "weighted_by_conditions": weight_conditions,
        "forecast_available": bool(forecasts),
        "lakes": rows[:limit],
        "considered": len(rows),
    }


def _slim_consistency(entry: dict | None) -> dict | None:
    if not entry:
        return None
    return {k: entry[k] for k in
            ("cv", "band", "bust_rate", "worst_decile", "typical_fish", "trips")
            if k in entry}


def _next_saturday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)
