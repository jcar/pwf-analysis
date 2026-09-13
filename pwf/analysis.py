"""Statistics over the extracted data.

Two rules run through everything here:

  * every figure carries the sample it rests on, because many segment cells
    hold only a handful of trips;
  * rates are shrunk toward the segment mean, so a bait that went 1-for-1 does
    not outrank one that produced over two hundred trips.

This is observational data with real confounds - popular baits get thrown more,
better anglers write more reports, and only ~3% of reports admit a skunk, which
is not a believable rate. The output describes association, never causation.
"""
from __future__ import annotations

import sqlite3

from datetime import datetime

import numpy as np
import pandas as pd

from .config import HALF_DAY_HOURS, HOURS_BY_SLOT

# Strength of the prior pulling a small cell toward the segment mean, measured
# in equivalent trips.
SHRINK_K = 8.0
MIN_CELL = 3


def calibrate_effort(conn: sqlite3.Connection) -> dict:
    """Measure hours per booking slot instead of assuming them.

    The naive assumption is that an all-day trip is twice a half-day trip. It is
    not: measured across thousands of trips, all-day anglers catch roughly 1.4x
    what half-day anglers catch, not 2x. Dividing their fish by eight hours
    therefore understates them by about a quarter - and because booking mix
    varies enormously by lake (some properties are booked all-day almost
    exclusively, others hardly at all), that error does not wash out. It biases
    every comparison *between* lakes, which is exactly what a recommender ranks.

    So the all-day figure is derived: half-day hours stay the club's own
    definition, and all-day hours are scaled by the observed catch ratio.
    """
    df = pd.read_sql_query(
        "SELECT time_slot, fish_total FROM trips"
        " WHERE fish_total IS NOT NULL AND time_slot IS NOT NULL", conn)
    out = {"AM": HALF_DAY_HOURS, "PM": HALF_DAY_HOURS,
           "ALL_DAY": HOURS_BY_SLOT["ALL_DAY"]}
    stats = {"hours": out, "ratio": None, "n_all_day": 0, "n_half": 0,
             "source": "fallback"}
    if df.empty:
        return stats

    half = df[df["time_slot"].isin(("AM", "PM"))]["fish_total"]
    allday = df[df["time_slot"] == "ALL_DAY"]["fish_total"]
    stats["n_half"], stats["n_all_day"] = len(half), len(allday)
    # Too few trips to measure anything - keep the documented fallback.
    if len(half) < 100 or len(allday) < 100 or half.mean() <= 0:
        return stats

    ratio = float(allday.mean() / half.mean())
    # A ratio outside this range means something is wrong with the data, not
    # that anglers behave strangely; refuse it rather than propagate it.
    if not 1.0 <= ratio <= 2.0:
        return stats

    out["ALL_DAY"] = round(HALF_DAY_HOURS * ratio, 2)
    stats.update(ratio=round(ratio, 4), source="measured")

    conn.execute(
        "INSERT OR REPLACE INTO calibration (key, value, n, note, computed_at)"
        " VALUES (?,?,?,?,?)",
        ("all_day_hours", out["ALL_DAY"], len(allday),
         f"all-day trips average {allday.mean():.1f} fish vs {half.mean():.1f} "
         f"for half-day ({ratio:.2f}x), so all-day effort is "
         f"{HALF_DAY_HOURS} x {ratio:.2f} hours, not {HALF_DAY_HOURS * 2}",
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return stats


def effort_hours(conn: sqlite3.Connection) -> dict:
    """Hours per slot: the measured value when one exists, else the fallback."""
    hours = dict(HOURS_BY_SLOT)
    row = conn.execute(
        "SELECT value FROM calibration WHERE key='all_day_hours'").fetchone()
    if row and row[0]:
        hours["ALL_DAY"] = float(row[0])
    return hours


def trips_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    """Master table: one row per trip, joined to lake, conditions and features."""
    df = pd.read_sql_query("""
        SELECT t.report_id, t.lake_id, t.lake_known, t.trip_date, t.year, t.month,
               t.season, t.time_slot, t.trip_date_source, t.hours, t.fish_total,
               t.fish_per_hour, t.max_weight_lb,
               l.name AS lake, l.town, l.acres, l.max_depth_ft, l.cohort,
               l.region, l.day_rate,
               c.temp_max_f, c.temp_mean_f, c.temp_7d_mean_f, c.precip_in,
               c.wind_max_mph, c.wind_dir_deg, c.cloud_pct, c.pressure_hpa,
               c.pressure_delta_24h, c.pressure_trend, c.moon_illum, c.day_length_h,
               f.clarity_ft, f.clarity_label, f.water_temp_f, f.depth_min_ft,
               f.depth_max_ft, f.bite_window, f.skunked,
               r.author, r.title, r.era
        FROM trips t
        LEFT JOIN lakes l ON l.lake_id = t.lake_id
        LEFT JOIN conditions c ON c.lake_id = t.lake_id AND c.date = t.trip_date
        LEFT JOIN report_features f ON f.report_id = t.report_id
        LEFT JOIN reports r ON r.report_id = t.report_id
    """, conn)
    if not df.empty:
        # A LEFT JOIN that matched nothing leaves object-dtype columns full of
        # None, which pd.cut cannot order. Coerce before banding.
        numeric = ["acres", "max_depth_ft", "day_rate", "temp_max_f", "temp_mean_f",
                   "temp_7d_mean_f", "precip_in", "wind_max_mph", "wind_dir_deg",
                   "cloud_pct", "pressure_hpa", "pressure_delta_24h", "moon_illum",
                   "day_length_h", "clarity_ft", "water_temp_f", "depth_min_ft",
                   "depth_max_ft", "fish_total", "fish_per_hour", "max_weight_lb",
                   "hours"]
        for col in numeric:
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["cloud_band"] = pd.cut(df["cloud_pct"], [-1, 30, 70, 101],
                                  labels=["clear_sky", "partly", "overcast"])
        df["wind_band"] = pd.cut(df["wind_max_mph"], [-1, 7, 15, 200],
                                 labels=["calm", "moderate", "windy"])
        df["clarity_band"] = pd.cut(df["clarity_ft"], [-0.01, 1.0, 3.0, 100],
                                    labels=["murky", "stained", "clear"])
        df["acres_band"] = pd.cut(df["acres"], [-1, 12, 30, 100000],
                                  labels=["small", "medium", "large"])
    return df


def lures_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT report_id, category, subtype, color, source FROM report_lures", conn)


def tags_frame(conn: sqlite3.Connection, kind: str | None = None) -> pd.DataFrame:
    q = "SELECT report_id, kind, value, detail FROM report_tags"
    if kind:
        q += f" WHERE kind = '{kind}'"
    return pd.read_sql_query(q, conn)


def _shrunk(obs_mean: float, n: int, baseline: float, k: float = SHRINK_K) -> float:
    return (n * obs_mean + k * baseline) / (n + k)


def lure_lift(trips: pd.DataFrame, lures: pd.DataFrame,
              level: str = "category", min_n: int = MIN_CELL) -> pd.DataFrame:
    """Catch rate by bait within the supplied slice of trips.

    Ranking is by `lift_lb`, the *conservative* end of the estimate: the shrunk
    rate minus one standard error, divided by the slice baseline. Shrinking the
    mean alone is not enough - a single lucky trip can still post a huge shrunk
    rate, and the standard-error penalty is what actually stops one trip from
    outranking forty. `lift` is kept alongside it for reading, but sorting on
    the point estimate would put noise at the top of the table.

    A value of 1.0 means the bait performed like the slice average. This is an
    association, not a causal effect: popular baits are thrown more, and under
    different conditions, than rare ones.
    """
    if trips.empty or lures.empty or "fish_per_hour" not in trips:
        return pd.DataFrame()
    scored = trips.dropna(subset=["fish_per_hour"])
    if scored.empty:
        return pd.DataFrame()

    baseline = scored["fish_per_hour"].mean()
    # Pooled spread of the slice, used to penalise thin cells.
    pooled_std = scored["fish_per_hour"].std(ddof=0)
    if not pooled_std or pooled_std != pooled_std:
        pooled_std = 0.0

    merged = lures.merge(scored[["report_id", "fish_per_hour"]], on="report_id")
    if merged.empty:
        return pd.DataFrame()
    merged = merged.drop_duplicates(subset=["report_id", level])

    g = merged.groupby(level)["fish_per_hour"]
    out = pd.DataFrame({"n_trips": g.size(), "raw_fph": g.mean(),
                        "median_fph": g.median()})
    out = out[out["n_trips"] >= min_n].copy()
    if out.empty:
        return out

    out["shrunk_fph"] = [_shrunk(m, int(n), baseline)
                         for m, n in zip(out["raw_fph"], out["n_trips"])]
    se = pooled_std / np.sqrt(out["n_trips"].astype(float))
    out["lower_fph"] = (out["shrunk_fph"] - se).clip(lower=0.0)
    out["lift"] = out["shrunk_fph"] / baseline if baseline else np.nan
    out["lift_lb"] = out["lower_fph"] / baseline if baseline else np.nan
    out["baseline_fph"] = baseline
    out["scored_trips"] = len(scored)
    return out.sort_values("lift_lb", ascending=False)


def lake_scorecard(conn: sqlite3.Connection, lake: str) -> dict:
    trips = trips_frame(conn)
    sel = trips[trips["lake"].str.lower() == lake.lower()] if not trips.empty \
        else pd.DataFrame()
    if sel.empty:
        return {"error": f"no trips found for {lake!r}"}

    lures = lures_frame(conn)
    mine = lures[lures["report_id"].isin(sel["report_id"])]
    scored = sel.dropna(subset=["fish_per_hour"])
    club = trips.dropna(subset=["fish_per_hour"])["fish_per_hour"].median()

    by_month = (scored.groupby("month")["fish_per_hour"]
                .agg(["size", "mean"]).rename(columns={"size": "n", "mean": "fph"}))

    veg = tags_frame(conn, "vegetation")
    veg = veg[veg["report_id"].isin(sel["report_id"])]
    struct = tags_frame(conn, "structure")
    struct = struct[struct["report_id"].isin(sel["report_id"])]

    return {
        "lake": sel["lake"].iloc[0],
        "town": sel["town"].iloc[0],
        "acres": sel["acres"].iloc[0],
        "max_depth_ft": sel["max_depth_ft"].iloc[0],
        "cohort": sel["cohort"].iloc[0],
        "day_rate": sel["day_rate"].iloc[0],
        "trips": len(sel),
        "scored_trips": len(scored),
        "date_range": (sel["trip_date"].min(), sel["trip_date"].max()),
        "fish_per_hour_median": scored["fish_per_hour"].median(),
        "club_median_fph": club,
        "best_fish_lb": sel["max_weight_lb"].max(),
        "avg_best_fish_lb": sel["max_weight_lb"].mean(),
        "by_month": by_month,
        "top_lures": lure_lift(sel, mine),
        "clarity_ft_median": sel["clarity_ft"].median(),
        "clarity_n": int(sel["clarity_ft"].notna().sum()),
        "water_temp_n": int(sel["water_temp_f"].notna().sum()),
        "vegetation": veg["value"].value_counts(),
        "veg_mention_rate": (veg["report_id"].nunique() / len(sel)) if len(sel) else 0,
        "structure": struct["value"].value_counts(),
        "species": _species_mix(conn, sel["report_id"]),
    }


def _species_mix(conn: sqlite3.Connection, report_ids) -> pd.Series:
    """Species named on this lake's reports.

    "unspecified" is the largest bucket club-wide - most members just write a
    number, and on a bass club that number is almost certainly bass. It is left
    unlabelled rather than silently relabelled, so what shows here is only what
    somebody actually named.
    """
    ids = set(int(r) for r in report_ids)
    if not ids:
        return pd.Series(dtype=int)
    df = pd.read_sql_query("SELECT report_id, species, n FROM catches", conn)
    df = df[df["report_id"].isin(ids) & (df["species"] != "unspecified")]
    if df.empty:
        return pd.Series(dtype=int)
    return df.groupby("species")["n"].sum().sort_values(ascending=False)


def assign_cohorts(conn: sqlite3.Connection) -> pd.DataFrame:
    """Type each lake by size, clarity and how often members mention vegetation.

    Per-report vegetation and clarity coverage is low (~28% and ~18%), but a
    lake with two hundred reports still accumulates dozens of observations, so
    the lake-level aggregate is solid even though any single report is not.
    """
    trips = trips_frame(conn)
    if trips.empty:
        return pd.DataFrame()
    veg = tags_frame(conn, "vegetation")
    veg_by_report = set(veg["report_id"])

    rows = []
    for lake_id, g in trips[trips["lake_known"] == 1].groupby("lake_id"):
        n = len(g)
        veg_rate = sum(1 for r in g["report_id"] if r in veg_by_report) / n if n else 0
        clarity = g["clarity_ft"].median()
        acres = g["acres"].iloc[0]
        rows.append({"lake_id": lake_id, "lake": g["lake"].iloc[0], "trips": n,
                     "acres": acres, "veg_rate": round(veg_rate, 3),
                     "clarity_ft": clarity,
                     "clarity_n": int(g["clarity_ft"].notna().sum())})
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    def cohort(r) -> str:
        small = (r["acres"] is not None and not pd.isna(r["acres"]) and r["acres"] <= 30)
        grassy = r["veg_rate"] >= 0.25
        clear = (not pd.isna(r["clarity_ft"]) and r["clarity_ft"] >= 2.0)
        if small and grassy and clear:
            return "small_clear_grassy"
        if small and grassy:
            return "small_grassy"
        if small:
            return "small_other"
        if grassy:
            return "larger_grassy"
        return "larger_open"

    df["cohort"] = df.apply(cohort, axis=1)
    for _, r in df.iterrows():
        conn.execute("UPDATE lakes SET cohort=? WHERE lake_id=?",
                     (r["cohort"], int(r["lake_id"])))
    conn.commit()
    return df


def similar_trips(trips: pd.DataFrame, target: dict, lake: str | None = None,
                  cohort: str | None = None) -> pd.DataFrame:
    """Historical trips fished under conditions close to `target`."""
    if trips.empty or "fish_per_hour" not in trips:
        return pd.DataFrame()
    df = trips.dropna(subset=["fish_per_hour"]).copy()
    if lake:
        df = df[df["lake"].str.lower() == lake.lower()]
    elif cohort:
        df = df[df["cohort"] == cohort]
    if df.empty:
        return df

    score = pd.Series(0.0, index=df.index)
    if target.get("month"):
        # Circular month distance, so December sits next to January.
        d = (df["month"] - target["month"]).abs()
        score += np.minimum(d, 12 - d) * 1.0
    for key, col, scale in [("temp_max_f", "temp_max_f", 10.0),
                            ("wind_max_mph", "wind_max_mph", 8.0),
                            ("cloud_pct", "cloud_pct", 40.0),
                            ("pressure_delta_24h", "pressure_delta_24h", 3.0)]:
        if target.get(key) is not None and col in df:
            score += (df[col] - target[key]).abs().fillna(scale) / scale
    df["similarity"] = score
    return df.sort_values("similarity")


def coverage(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT dimension, n_with, n_total, pct, tier FROM coverage_stats"
        " ORDER BY tier DESC, pct DESC", conn)
