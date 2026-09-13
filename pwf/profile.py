"""Everything about one lake, assembled once and rendered by both surfaces.

The CLI and the published page read the same dict, so a number can never differ
between them. Nothing here reproduces member text or names - it is all counts
and rates.

The median lake has only ~25 scored trips, so every section carries the sample
it rests on and the profile as a whole carries a confidence label. A lake with
nine trips gets a profile too; it just says so.
"""
from __future__ import annotations

import math
import sqlite3

import numpy as np
import pandas as pd

from . import analysis as A

# Dallas, from which drive distance is measured.
HOME = (32.7767, -96.7970)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASON_ORDER = ["spring", "summer", "fall", "winter"]
# Scored-trip thresholds behind the confidence label.
CONFIDENCE = [(80, "good"), (30, "fair"), (10, "thin"), (0, "very thin")]


def miles_from_home(lat: float | None, lon: float | None) -> float | None:
    """Great-circle miles from Dallas. Straight line, not drive time."""
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return None
    r = 3958.8
    p1, p2 = math.radians(HOME[0]), math.radians(lat)
    dp = math.radians(lat - HOME[0])
    dl = math.radians(lon - HOME[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 0)


def confidence(scored: int) -> str:
    for floor, label in CONFIDENCE:
        if scored >= floor:
            return label
    return "very thin"


def _num(v, nd=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return round(f, nd) if f == f else None


def _counts(series: pd.Series, total: int, top: int = 8) -> list[dict]:
    """Value counts with the denominator attached, so a share is never bare."""
    if series.empty or not total:
        return []
    vc = series.value_counts().head(top)
    return [{"value": k, "n": int(v), "pct": _num(100 * v / total, 1)}
            for k, v in vc.items()]


def lake_profile(conn: sqlite3.Connection, lake: str,
                 trips: pd.DataFrame | None = None,
                 lures: pd.DataFrame | None = None) -> dict:
    """Assemble one lake's profile. Frames may be passed in to avoid re-querying
    when profiling every lake at once."""
    trips = A.trips_frame(conn) if trips is None else trips
    lures = A.lures_frame(conn) if lures is None else lures
    if trips.empty:
        return {"error": f"no trips for {lake!r}"}

    sel = trips[trips["lake"].fillna("").str.lower() == lake.lower()]
    if sel.empty:
        return {"error": f"no trips for {lake!r}"}

    scored = sel.dropna(subset=["fish_per_hour"])
    club = trips.dropna(subset=["fish_per_hour"])
    mine_lures = lures[lures["report_id"].isin(sel["report_id"])]
    ids = set(sel["report_id"])
    first = sel.iloc[0]

    return {
        "lake": first["lake"],
        "facts": _facts(conn, first, sel),
        "volume": {
            "reports": int(len(sel)),
            "scored": int(len(scored)),
            "confidence": confidence(len(scored)),
            "first": sel["trip_date"].min(),
            "last": sel["trip_date"].max(),
            "exact_dates": int((sel["trip_date_source"] == "reservation").sum()),
        },
        "rate": _rate(scored, club),
        "by_month": _by_month(scored),
        "by_slot": _by_slot(scored),
        "by_year": _by_year(scored),
        "baits": _baits(sel, mine_lures),
        "water": _water(conn, sel, ids),
        "fish": _fish(conn, sel, ids),
        "conditions": _conditions(scored),
    }


def _facts(conn, first, sel) -> dict:
    row = conn.execute(
        "SELECT slug, region, acres, max_depth_ft, membership_tier, bank_fishing,"
        " boat_type, day_rate, half_day_rate, harvest_rules, lat, lon, cohort"
        " FROM lakes WHERE name = ?", (first["lake"],)).fetchone()
    d = dict(row) if row else {}
    return {
        "town": first["town"],
        "region": d.get("region"),
        "acres": _num(d.get("acres"), 0),
        "max_depth_ft": _num(d.get("max_depth_ft"), 0),
        "cohort": d.get("cohort"),
        "membership_tier": d.get("membership_tier"),
        "bank_fishing": d.get("bank_fishing"),
        "boat_type": d.get("boat_type"),
        "day_rate": _num(d.get("day_rate"), 0),
        "half_day_rate": _num(d.get("half_day_rate"), 0),
        "harvest_rules": d.get("harvest_rules"),
        "miles": miles_from_home(d.get("lat"), d.get("lon")),
        "slug": d.get("slug"),
    }


def _rate(scored, club) -> dict:
    if scored.empty:
        return {"median": None, "mean": None, "club_median": None,
                "percentile": None}
    club_rates = club["fish_per_hour"]
    mine = scored["fish_per_hour"].median()
    lake_medians = (club.groupby("lake")["fish_per_hour"].median()
                    .dropna().sort_values())
    pct = None
    if len(lake_medians) > 5 and mine == mine:
        pct = _num(100 * (lake_medians < mine).mean(), 0)
    return {
        "median": _num(mine),
        "mean": _num(scored["fish_per_hour"].mean()),
        "club_median": _num(club_rates.median()),
        "percentile": pct,
        "best_trip": _num(scored["fish_per_hour"].max()),
    }


def _by_month(scored) -> list[dict]:
    if scored.empty:
        return []
    g = scored.groupby("month")["fish_per_hour"].agg(["size", "median", "mean"])
    out = []
    for m in range(1, 13):
        if m in g.index:
            r = g.loc[m]
            out.append({"month": MONTHS[m - 1], "m": m, "n": int(r["size"]),
                        "median": _num(r["median"]), "mean": _num(r["mean"])})
        else:
            out.append({"month": MONTHS[m - 1], "m": m, "n": 0,
                        "median": None, "mean": None})
    return out


def _by_slot(scored) -> list[dict]:
    """AM / PM / All Day. Comparable only because effort hours are calibrated
    from the data - see analysis.calibrate_effort."""
    if scored.empty:
        return []
    g = scored.groupby("time_slot")["fish_per_hour"].agg(["size", "median", "mean"])
    order = {"AM": 0, "PM": 1, "ALL_DAY": 2}
    rows = [{"slot": k, "n": int(r["size"]), "median": _num(r["median"]),
             "mean": _num(r["mean"])} for k, r in g.iterrows()]
    return sorted(rows, key=lambda r: order.get(r["slot"], 9))


def _by_year(scored) -> list[dict]:
    if scored.empty:
        return []
    g = scored.groupby("year")["fish_per_hour"].agg(["size", "median"])
    return [{"year": int(y), "n": int(r["size"]), "median": _num(r["median"])}
            for y, r in g.iterrows() if y == y]


def _baits(sel, mine_lures) -> dict:
    """Producing baits overall and per season, at both levels of the taxonomy."""
    out = {"overall": [], "by_season": {}, "subtype": []}
    if mine_lures.empty:
        return out

    def rows(df, level, min_n):
        lift = A.lure_lift(df, mine_lures, level=level, min_n=min_n)
        return [{"bait": i, "n": int(r["n_trips"]), "fph": _num(r["shrunk_fph"]),
                 "lift": _num(r["lift"]), "lift_lb": _num(r["lift_lb"])}
                for i, r in lift.head(12).iterrows()]

    out["overall"] = rows(sel, "category", 3)
    out["subtype"] = rows(sel, "subtype", 4)
    for season in SEASON_ORDER:
        sl = sel[sel["season"] == season]
        if len(sl.dropna(subset=["fish_per_hour"])) >= 8:
            got = rows(sl, "category", 3)
            if got:
                out["by_season"][season] = got[:6]
    return out


def _water(conn, sel, ids) -> dict:
    """Clarity, vegetation and cover. Each carries how many reports mentioned it,
    because any single report usually does not."""
    tags = pd.read_sql_query(
        "SELECT report_id, kind, value, detail FROM report_tags", conn)
    tags = tags[tags["report_id"].isin(ids)]
    n = len(sel)

    veg = tags[tags["kind"] == "vegetation"]
    struct = tags[tags["kind"] == "structure"]
    tech = tags[tags["kind"] == "technique"]

    clarity = sel["clarity_ft"].dropna()
    labels = sel["clarity_label"].dropna()
    density = veg["detail"].dropna()

    return {
        "clarity_ft_median": _num(clarity.median(), 1),
        "clarity_ft_n": int(len(clarity)),
        "clarity_labels": _counts(labels, len(labels), 5),
        "water_temp_f_median": _num(sel["water_temp_f"].median(), 0),
        "water_temp_n": int(sel["water_temp_f"].notna().sum()),
        "depth_median_ft": _num(sel["depth_max_ft"].median(), 0),
        "depth_n": int(sel["depth_max_ft"].notna().sum()),
        "vegetation": _counts(veg["value"], n, 8),
        "veg_mention_rate": _num(100 * veg["report_id"].nunique() / n, 0) if n else None,
        "veg_density": _counts(density, len(density), 4),
        "structure": _counts(struct["value"], n, 10),
        "technique": _counts(tech["value"], n, 8),
    }


def _fish(conn, sel, ids) -> dict:
    catches = pd.read_sql_query(
        "SELECT report_id, species, n, max_weight_lb FROM catches", conn)
    catches = catches[catches["report_id"].isin(ids)]
    named = catches[catches["species"] != "unspecified"]
    species = []
    if not named.empty:
        tot = named["n"].sum()
        g = named.groupby("species")["n"].sum().sort_values(ascending=False)
        species = [{"species": k, "fish": int(v), "pct": _num(100 * v / tot, 0)}
                   for k, v in g.items()]

    weights = sel["max_weight_lb"].dropna()
    scored = sel.dropna(subset=["fish_total"])
    bands = []
    if not weights.empty:
        cut = pd.cut(weights, [0, 2, 3, 5, 8, 100],
                     labels=["<2 lb", "2-3", "3-5", "5-8", "8+"])
        bands = _counts(cut.dropna(), len(weights), 6)

    return {
        "species": species,
        "species_named_on": int(named["report_id"].nunique()),
        "best_lb": _num(weights.max(), 1),
        "median_best_lb": _num(weights.median(), 1),
        "weight_reports": int(len(weights)),
        "weight_bands": bands,
        "over_5lb_rate": _num(100 * (weights >= 5).mean(), 0) if len(weights) else None,
        "median_fish_per_trip": _num(scored["fish_total"].median(), 0),
        "skunk_rate": _num(100 * (scored["fish_total"] == 0).mean(), 0)
        if len(scored) else None,
    }


def _conditions(scored) -> dict:
    """What this lake has actually been fished in - useful for reading its
    numbers, not for predicting them."""
    if scored.empty:
        return {}
    out = {}
    for key, col in [("pressure_trend", "pressure_trend"),
                     ("wind_band", "wind_band"), ("cloud_band", "cloud_band")]:
        if col not in scored:
            continue
        sub = scored.dropna(subset=[col])
        if sub.empty:
            continue
        g = sub.groupby(col, observed=True)["fish_per_hour"].agg(["size", "median"])
        out[key] = [{"value": str(k), "n": int(r["size"]), "median": _num(r["median"])}
                    for k, r in g.iterrows() if r["size"] >= 5]
    wx = scored.dropna(subset=["temp_max_f"])
    out["weather_n"] = int(len(wx))
    if not wx.empty:
        out["typical"] = {
            "temp_max_f": _num(wx["temp_max_f"].median(), 0),
            "wind_mph": _num(wx["wind_max_mph"].median(), 0),
            "cloud_pct": _num(wx["cloud_pct"].median(), 0),
        }
    return out


def all_profiles(conn: sqlite3.Connection, min_reports: int = 8) -> dict[str, dict]:
    """Every lake worth profiling, sharing one pass over the frames."""
    trips = A.trips_frame(conn)
    lures = A.lures_frame(conn)
    if trips.empty:
        return {}
    counts = trips[trips["lake_known"] == 1]["lake"].value_counts()
    names = [n for n, c in counts.items() if c >= min_reports]
    out = {}
    for name in names:
        prof = lake_profile(conn, name, trips=trips, lures=lures)
        if "error" not in prof:
            out[name] = prof
    return out
