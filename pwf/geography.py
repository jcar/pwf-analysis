"""What the club's geography is worth, measured rather than assumed.

The planner's central trade is drive against quality, so it is worth knowing
whether distance actually buys anything. It does, but less than the raw numbers
claim, and for reasons worth stating plainly.

Sorted by drive from Dallas, the club splits cleanly at about eighty miles:
inside it lakes average 3.7 fish an hour, outside 5.3. That gap is real but it
is not all distance. Three things travel together:

* **The far lakes are bigger.** Median 23 acres beyond eighty miles against 13
  inside it, and bigger water fishes better across this club's whole range.
* **The near lakes are fished harder.** Trips per lake correlate with drive at
  r=-0.29, and a lake's own trip count correlates with its catch rate at
  r=-0.21. The close water absorbs most of the club's pressure.
* **Distance itself.** Holding acreage constant, a hundred extra miles is worth
  about half a fish an hour - roughly a third of the raw gap.

So the honest claim is not "drive further, catch more". It is that the close-in
water is small, hard-fished and measurably slower, and that the size and
pressure explanations cannot be separated from each other by this archive - they
are properties of the same lakes.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .geo_shapes import miles_between
from .geo_verify import HOME

# This is the cut-point with the largest gap, which is exactly the kind of
# choice that flatters a finding, so `split_scan` publishes the neighbours
# alongside it. The reassurance is not that 80 is special - it is that every
# cut-point from 40 to 120 miles gives a positive gap, so the pattern does not
# depend on where the line is drawn.
SPLIT_MILES = 80.0
MIN_TRIPS = 20
MAX_ACRES = 500


def _frame(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT l.name, l.lat, l.lon, l.acres, t.fish_per_hour"
        " FROM trips t JOIN lakes l ON l.lake_id = t.lake_id"
        " WHERE t.fish_per_hour IS NOT NULL AND l.lat IS NOT NULL", conn)
    if df.empty:
        return df
    df["miles"] = [miles_between(HOME[0], HOME[1], a, b)
                   for a, b in zip(df["lat"], df["lon"])]
    return df


def _per_lake(df: pd.DataFrame, need_acres: bool = False) -> pd.DataFrame:
    per = df.groupby("name").agg(miles=("miles", "first"),
                                 acres=("acres", "first"),
                                 fph=("fish_per_hour", "mean"),
                                 n=("fish_per_hour", "size"))
    per = per[per["n"] >= MIN_TRIPS]
    if need_acres:
        per = per.dropna(subset=["acres"])
        per = per[(per["acres"] > 0) & (per["acres"] <= MAX_ACRES)]
    return per


def split_scan(conn: sqlite3.Connection) -> list[dict]:
    """Catch rate either side of several cut-points, so the chosen one is not
    the only one the reader gets to see."""
    df = _frame(conn)
    if df.empty:
        return []
    per = _per_lake(df)
    out = []
    for cut in (40, 60, 80, 100, 120):
        near, far = per[per["miles"] <= cut], per[per["miles"] > cut]
        if len(near) < 5 or len(far) < 5:
            continue
        out.append({"cut": cut, "near_lakes": int(len(near)),
                    "far_lakes": int(len(far)),
                    "near_fph": round(float(near["fph"].mean()), 2),
                    "far_fph": round(float(far["fph"].mean()), 2),
                    "gap": round(float(far["fph"].mean() - near["fph"].mean()), 2)})
    return out


def drive_gradient(conn: sqlite3.Connection) -> dict:
    """The drive-versus-quality picture, with its confounds measured."""
    df = _frame(conn)
    if df.empty:
        return {}
    per = _per_lake(df)
    near, far = per[per["miles"] <= SPLIT_MILES], per[per["miles"] > SPLIT_MILES]
    if len(near) < 5 or len(far) < 5:
        return {}

    sized = _per_lake(df, need_acres=True)
    coef = {}
    if len(sized) >= 20:
        # Catch rate against drive and acreage together, so the part of the gap
        # that is really lake size is taken out of the part credited to driving.
        x = np.column_stack([np.ones(len(sized)), sized["miles"], sized["acres"]])
        beta, *_ = np.linalg.lstsq(x, sized["fph"].to_numpy(), rcond=None)
        coef = {"per_100_miles": round(float(beta[1]) * 100, 2),
                "per_acre": round(float(beta[2]), 3),
                "lakes": int(len(sized))}

    def r(a, b, frame=None):
        f = per if frame is None else frame
        # Correlations touching acreage must use the subset that has it;
        # computed over the full set they come back NaN, which is not even
        # valid JSON and would have shipped as a blank to the page.
        if len(f) < 3:
            return None
        v = float(np.corrcoef(f[a], f[b])[0, 1])
        return None if v != v else round(v, 3)

    return {
        "split_miles": SPLIT_MILES,
        "near": {"lakes": int(len(near)), "fph": round(float(near["fph"].mean()), 2),
                 "median_acres": _num(near["acres"].median()),
                 "median_trips": _num(near["n"].median())},
        "far": {"lakes": int(len(far)), "fph": round(float(far["fph"].mean()), 2),
                "median_acres": _num(far["acres"].median()),
                "median_trips": _num(far["n"].median())},
        "raw_gap": round(float(far["fph"].mean() - near["fph"].mean()), 2),
        "held_for_size": coef,
        "corr": {"miles_rate": r("miles", "fph"),
                 "acres_rate": r("acres", "fph", sized),
                 "miles_acres": r("miles", "acres", sized),
                 "trips_rate": r("n", "fph"), "miles_trips": r("miles", "n")},
        "scan": split_scan(conn),
        "caveat": (
            "Distance, lake size and fishing pressure travel together here and "
            "this archive cannot separate them: the near lakes are the small "
            "ones and also the hard-fished ones. Holding acreage constant "
            "leaves about a third of the gap attributable to the drive itself."
        ),
    }


def _num(v):
    return None if v is None or v != v else round(float(v), 1)
