"""Does an effect repeat, or is it noise with a confidence interval on it?

A confidence interval says how precisely a number was measured. It does not say
the number will be there next time. For anything computed on a few dozen trips
those are very different questions, and the honest test is simple: split a
lake's history in half by date, measure the same effect in each half, and see
whether the halves agree.

Run on this archive the answer is uncomfortable and worth stating plainly:

| what                              | split-half r | sign agreement |
|-----------------------------------|--------------|----------------|
| a lake's catch rate               | **+0.70**    | —              |
| a lake's own *bait* effects       | -0.02        | 48%            |
| a lake's own *technique* effects  | +0.12        | 46%            |

The method finds the real signal at r=0.70, so it works. It then says per-lake
tackle effects do not repeat within the same lake. Restricting to the
best-sampled cells does not rescue them - 34 cells with 25+ trips in both halves
come out at r=+0.06 and 38% sign agreement, which is worse than chance.

Club-wide effects are a different matter: measured on thousands of trips and
checked year by year, soft plastic holds its sign in 9 of 9 years and wacky in
8 of 8. Those are the ones worth acting on.

So per-lake tackle numbers are reported as description - what members actually
throw at a lake - and never as a recommendation. Making them the advice, however
tempting, would be inventing a pattern the archive cannot support.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .effect import bait_count_strata, stratified_effect

# Below this, an effect measured on one half of a lake's history tells you
# nothing about the other half.
REPEATS_THRESHOLD = 0.25
MIN_TRIPS_PER_HALF = 20
MIN_USING = 8

CAVEAT = (
    "Measured on this lake alone, tackle effects do not repeat: split its "
    "history in half and the two halves agree at about r=0.0 for baits and "
    "r=0.1 for presentations, against r=0.7 for the lake's own catch rate. The "
    "method finds the real signal, so the flat result is the answer, not a "
    "failure. What a lake's own trips do tell you reliably is what people "
    "actually throw there — which is shown — and how many fish they catch, "
    "which is what the ranking uses."
)


def _half_effect(sel: pd.DataFrame, using: set, lures: pd.DataFrame,
                 level: str) -> float | None:
    scored = sel.dropna(subset=["fish_per_hour"]).set_index("report_id")
    scored = scored[~scored.index.duplicated()]
    if len(scored) < MIN_TRIPS_PER_HALF:
        return None
    rates = scored["fish_per_hour"]
    strata = bait_count_strata(
        lures[lures["report_id"].isin(rates.index)], rates.index, level=level)
    ids = [i for i in using if i in rates.index]
    if len(ids) < MIN_USING:
        return None
    res = stratified_effect(rates.loc[ids],
                            rates.drop(index=ids, errors="ignore"),
                            strata, min_stratum=3)
    return None if res is None else res[0]


def split_half(trips: pd.DataFrame, lures: pd.DataFrame,
               groups: pd.DataFrame, key: str, level: str = "category",
               min_lake_trips: int = 60, max_lakes: int = 90) -> dict:
    """Correlate an effect measured on each half of every lake's history.

    `groups` maps report_id to the thing being measured (a bait or a technique)
    through the column `key`.
    """
    pairs = []
    counts = trips[trips["lake_known"] == 1]["lake"].value_counts()
    for lake in counts.index[:max_lakes]:
        sel = trips[trips["lake"] == lake].dropna(subset=["fish_per_hour"])
        if len(sel) < min_lake_trips:
            continue
        sel = sel.sort_values("trip_date")
        mid = len(sel) // 2
        early, late = sel.iloc[:mid], sel.iloc[mid:]
        mine = groups[groups["report_id"].isin(sel["report_id"])]
        for value, grp in mine.groupby(key):
            using = set(grp["report_id"])
            a = _half_effect(early, using, lures, level)
            b = _half_effect(late, using, lures, level)
            if a is not None and b is not None:
                pairs.append((lake, value, a, b))

    if len(pairs) < 15:
        return {"cells": len(pairs), "r": None, "sign_agreement": None,
                "repeats": None}
    df = pd.DataFrame(pairs, columns=["lake", "value", "early", "late"])
    r = float(np.corrcoef(df["early"], df["late"])[0, 1])
    agree = float((np.sign(df["early"]) == np.sign(df["late"])).mean())
    return {"cells": len(df), "lakes": int(df["lake"].nunique()),
            "r": round(r, 3), "sign_agreement": round(agree, 3),
            "repeats": bool(r >= REPEATS_THRESHOLD)}


def lake_rate_split_half(trips: pd.DataFrame, min_lake_trips: int = 60,
                         max_lakes: int = 90) -> dict:
    """The control: a lake's catch rate, which does repeat.

    Without this the flat tackle result could be a broken method rather than a
    real finding.
    """
    rows = []
    counts = trips[trips["lake_known"] == 1]["lake"].value_counts()
    for lake in counts.index[:max_lakes]:
        sel = trips[trips["lake"] == lake].dropna(subset=["fish_per_hour"])
        if len(sel) < min_lake_trips:
            continue
        sel = sel.sort_values("trip_date")
        mid = len(sel) // 2
        rows.append((sel.iloc[:mid]["fish_per_hour"].mean(),
                     sel.iloc[mid:]["fish_per_hour"].mean()))
    if len(rows) < 10:
        return {"lakes": len(rows), "r": None}
    df = pd.DataFrame(rows, columns=["early", "late"])
    return {"lakes": len(df),
            "r": round(float(np.corrcoef(df["early"], df["late"])[0, 1]), 3)}


def report(trips: pd.DataFrame, lures: pd.DataFrame,
           tags: pd.DataFrame) -> dict:
    """All three figures, for the CLI and for the tests that pin them."""
    tech = tags[tags["kind"] == "technique"]
    baits = lures.drop_duplicates(subset=["report_id", "category"])
    return {
        "lake_rate": lake_rate_split_half(trips),
        "lake_baits": split_half(trips, lures, baits, "category"),
        "lake_techniques": split_half(trips, lures, tech, "value"),
        "caveat": CAVEAT,
    }
