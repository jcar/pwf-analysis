"""Assemble the aggregate figures the dashboard page renders.

Aggregates only. No member names and no report text leave this module: the
narratives belong to the club's members, and the published page carries
statistics rather than their words.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from pwf import analysis as A

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BAIT_LABELS = {
    "soft_plastic": "Soft plastic", "jig": "Jig", "topwater": "Topwater",
    "crankbait": "Crankbait", "lipless": "Lipless", "spinnerbait": "Spinnerbait",
    "bladed_jig": "Bladed jig", "jerkbait": "Jerkbait", "swimbait": "Swimbait",
    "underspin": "Underspin", "spoon": "Spoon", "crappie_jig": "Crappie jig",
    "fly": "Fly", "live_bait": "Live bait", "other": "Other",
}
MIN_CELL = 5


def _num(v, nd=2):
    if v is None or v != v:
        return None
    return round(float(v), nd)


def collect(conn: sqlite3.Connection) -> dict:
    trips = A.trips_frame(conn)
    lures = A.lures_frame(conn)
    scored = trips.dropna(subset=["fish_per_hour"])

    # Same-day weather only means anything for trips whose date is exact.
    # Legacy reports carry a date estimated from when they were posted, and a
    # one-day error destroys a pressure reading, so they are excluded here.
    exact = scored[scored["trip_date_source"] == "reservation"]

    out: dict = {"profiles": _profiles(conn, trips, lures),
                 "weekend": _weekend(conn),
                 "headline": _headline(conn, trips, scored),
                 "coverage": _coverage(conn),
                 "by_month": _by_month(scored),
                 "heatmap": _heatmap(trips, lures),
                 "exact_trips": int(len(exact)),
                 "pressure": _condition(exact, lures, "pressure_trend",
                                        ["falling", "steady", "rising"]),
                 "clouds": _condition(exact, lures, "cloud_band",
                                      ["clear_sky", "partly", "overcast"]),
                 "baits_overall": _baits_overall(trips, lures),
                 "lakes": _lakes(trips),
                 "cohorts": _cohorts(trips, lures)}
    return out


def _scored_window(scored) -> tuple:
    """Catch rates need both a fish count and an AM/PM window, and both live in
    the structured field block that only exists from about 2018. Legacy reports
    still contribute baits and narrative detail, but no rate."""
    if scored.empty:
        return (None, None)
    years = scored["year"].dropna()
    if years.empty:
        return (None, None)
    return (int(years.min()), int(years.max()))


def _headline(conn, trips, scored) -> dict:
    lakes = conn.execute(
        "SELECT COUNT(*) FROM lakes WHERE report_count > 0").fetchone()[0]
    d0 = trips["trip_date"].min()
    d1 = trips["trip_date"].max()
    return {
        "reports": int(len(trips)),
        "lakes": int(lakes),
        "scored": int(len(scored)),
        "first": d0, "last": d1,
        "scored_from": _scored_window(scored)[0],
        "scored_to": _scored_window(scored)[1],
        "median_fph": _num(scored["fish_per_hour"].median()),
        "best_lb": _num(trips["max_weight_lb"].max(), 1),
        "lake_known_pct": _num(100 * trips["lake_known"].mean(), 1),
    }


def _coverage(conn) -> list[dict]:
    df = A.coverage(conn)
    if df.empty:
        return []
    label = {
        "lake": "Lake identified",
        "fish_count": "Countable catch", "lure_any": "Bait named",
        "lure_field_matched": "Bait matched to taxonomy",
        "trip_date_exact": "Exact trip date (reservation)",
        "trip_date_estimated": "Trip date estimated from posting",
        "narrative": "Has a written report", "clarity": "Water clarity stated",
        "water_temp": "Water temperature stated", "depth": "Depth stated",
        "bite_window": "Time of day stated", "vegetation": "Vegetation described",
        "structure": "Cover or structure described",
        "technique": "Technique described",
    }
    return [{"dimension": label.get(r.dimension, r.dimension), "pct": _num(r.pct, 1),
             "n": int(r.n_with), "of": int(r.n_total), "tier": r.tier}
            for r in df.itertuples() if r.dimension in label]


def _by_month(scored) -> list[dict]:
    if scored.empty:
        return []
    g = scored.groupby("month")["fish_per_hour"].agg(["size", "median", "mean"])
    return [{"month": MONTHS[int(m) - 1], "n": int(r["size"]),
             "median": _num(r["median"]), "mean": _num(r["mean"])}
            for m, r in g.iterrows() if 1 <= int(m) <= 12]


def _heatmap(trips, lures) -> dict:
    """Bait (rows) by month (columns). Value is lift vs that month's baseline."""
    rows, cats = [], []
    for month in range(1, 13):
        slice_ = trips[trips["month"] == month]
        lift = A.lure_lift(slice_, lures, min_n=MIN_CELL)
        if lift.empty:
            continue
        for cat, r in lift.iterrows():
            rows.append({"month": month, "bait": cat, "lift": _num(r["lift"]),
                         "lift_lb": _num(r["lift_lb"]), "n": int(r["n_trips"]),
                         "fph": _num(r["shrunk_fph"])})
            cats.append(cat)
    order = (pd.Series(cats).value_counts().index.tolist() if cats else [])
    return {"cells": rows, "baits": order, "months": MONTHS, "min_cell": MIN_CELL}


def _condition(scored, lures, column: str, order: list[str]) -> list[dict]:
    if scored.empty or column not in scored:
        return []
    out = []
    for value in order:
        sl = scored[scored[column].astype("object") == value]
        if sl.empty:
            continue
        lift = A.lure_lift(sl, lures, min_n=MIN_CELL)
        top = [{"bait": i, "lift": _num(r["lift"]), "lift_lb": _num(r["lift_lb"]),
                "n": int(r["n_trips"])} for i, r in lift.head(4).iterrows()]
        out.append({"value": value, "n": int(len(sl)),
                    "median_fph": _num(sl["fish_per_hour"].median()),
                    "top": top})
    return out


def _baits_overall(trips, lures) -> list[dict]:
    lift = A.lure_lift(trips, lures, min_n=MIN_CELL)
    if lift.empty:
        return []
    return [{"bait": i, "n": int(r["n_trips"]), "fph": _num(r["shrunk_fph"]),
             "lift": _num(r["lift"]), "lift_lb": _num(r["lift_lb"])}
            for i, r in lift.iterrows()]


def _lakes(trips) -> list[dict]:
    df = trips[trips["lake_known"] == 1]
    if df.empty:
        return []
    g = df.groupby("lake").agg(
        trips=("report_id", "size"), acres=("acres", "first"),
        depth=("max_depth_ft", "first"), cohort=("cohort", "first"),
        fph=("fish_per_hour", "median"), best=("max_weight_lb", "max"),
        clarity=("clarity_ft", "median"), rate=("day_rate", "first"),
        town=("town", "first"))
    g = g[g["trips"] >= 15].sort_values("trips", ascending=False)
    return [{"lake": i, "town": r.town, "trips": int(r.trips),
             "acres": _num(r.acres, 0), "depth": _num(r.depth, 0),
             "cohort": r.cohort, "fph": _num(r.fph), "best": _num(r.best, 1),
             "clarity": _num(r.clarity, 1), "rate": _num(r.rate, 0)}
            for i, r in g.iterrows()]


def _cohorts(trips, lures) -> list[dict]:
    df = trips[trips["cohort"].notna()]
    if df.empty:
        return []
    out = []
    for cohort, g in df.groupby("cohort"):
        lift = A.lure_lift(g, lures, min_n=MIN_CELL)
        out.append({
            "cohort": cohort, "trips": int(len(g)),
            "lakes": int(g["lake"].nunique()),
            "median_fph": _num(g["fish_per_hour"].median()),
            "median_acres": _num(g["acres"].median(), 0),
            "top": [{"bait": i, "lift": _num(r["lift_lb"]), "n": int(r["n_trips"])}
                    for i, r in lift.head(5).iterrows()]})
    return sorted(out, key=lambda c: -c["trips"])

def _profiles(conn, trips, lures) -> dict:
    """One profile per lake, embedded so a click opens instantly with no
    network round-trip. Aggregates only - no member names, no report text."""
    from pwf.config import DB_PATH
    from pwf.profile import lake_profile
    from pwf.summarize import mention_index

    # One pass over every report body, shared by all profiles.
    mentions = mention_index(conn, str(DB_PATH))
    counts = trips[trips["lake_known"] == 1]["lake"].value_counts()
    out = {}
    for name, n in counts.items():
        if n < 8:
            continue
        prof = lake_profile(conn, name, trips=trips, lures=lures,
                            mentions=mentions)
        if "error" not in prof:
            out[name] = _slim(prof)
    return out


def _slim(prof: dict) -> dict:
    """Trim a profile to what the page actually renders, so the payload stays
    small enough to ship inside the page."""
    prof = dict(prof)
    prof["by_month"] = [m for m in prof["by_month"] if m["n"]]
    prof["by_year"] = prof["by_year"][-8:]
    baits = prof["baits"]
    prof["baits"] = {
        "overall": baits["overall"][:8],
        "by_season": {k: v[:4] for k, v in baits["by_season"].items()},
        "evidence": baits.get("evidence", [])[:12],
        "recommendation": {k: (v[:6] if isinstance(v, list) else v)
                           for k, v in (baits.get("recommendation") or {}).items()},
    }
    w = prof["water"]
    for key, keep in (("vegetation", 6), ("structure", 7), ("technique", 6),
                      ("clarity_labels", 4), ("veg_density", 4)):
        w[key] = w.get(key, [])[:keep]
    f = prof["fish"]
    f["species"] = f["species"][:5]
    summ = prof.get("summary") or {}
    if summ:
        summ["mentions"] = summ.get("mentions", [])[:8]
    return prof


def _weekend(conn) -> dict:
    """Next Saturday's ranking. Built without a forecast call: the page is a
    static snapshot, and a forecast baked in at publish time would go stale and
    read as current. The ranking itself does not use one."""
    from pwf.recommend import recommend

    try:
        out = recommend(conn, max_miles=200, limit=12, with_forecast=False)
    except Exception:
        return {}
    for row in out.get("lakes", []):
        row.pop("forecast", None)
    return out
