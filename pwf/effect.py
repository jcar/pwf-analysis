"""Measuring whether a thing people do actually changes the catch.

Shared by the bait and technique analyses, because the confound is identical:
members who describe more of what they did catch more fish (one bait named,
3.68 fish/hr club-wide; five, 4.62), since a longer or better day gets written
up in more detail. Anything that appears on well-documented trips therefore
looks good for free.

The estimator matches a thing against the trips that named about as much, then
combines the strata by inverse variance.

The second guard here is less obvious and matters more. A pooled confidence
interval treats every trip as independent, and trips are not - they cluster
within seasons and within anglers, so the pooled interval is too narrow. Two
techniques in this archive clear the pooled interval and flip sign in half the
years they appear in; they are noise wearing a p-value. `year_consistency`
re-estimates on each year separately, which are genuinely independent samples,
and the classifier will not promote anything whose sign does not hold across
most of them.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

Z = 1.96
MIN_STRATUM = 4
# Fraction of years whose sign must match the pooled sign before an effect is
# treated as real rather than as an artefact of pooling.
STABLE_FRACTION = 2 / 3
MIN_STABLE_YEARS = 3


def stratified_effect(used: pd.Series, other: pd.Series, strata: pd.Series,
                      min_stratum: int = MIN_STRATUM
                      ) -> tuple[float, float, int] | None:
    """Difference in catch rate, matched on how much the trip described.

    Returns (difference, standard error, trips used), or None when no stratum
    holds enough trips on both sides to compare.
    """
    diffs, weights, n_used = [], [], 0
    for key in strata.unique():
        u = used[strata.reindex(used.index) == key]
        o = other[strata.reindex(other.index) == key]
        if len(u) < min_stratum or len(o) < min_stratum:
            continue
        var = u.var(ddof=1) / len(u) + o.var(ddof=1) / len(o)
        if not var or var != var or var <= 0:
            continue
        diffs.append(u.mean() - o.mean())
        weights.append(1.0 / var)
        n_used += len(u)
    if not diffs:
        return None
    w = np.asarray(weights)
    d = np.asarray(diffs)
    diff = float((w * d).sum() / w.sum())
    se = float(math.sqrt(1.0 / w.sum()))
    return diff, se, n_used


def year_consistency(rates: pd.Series, years: pd.Series, ids: set,
                     strata: pd.Series, pooled_sign: int,
                     min_stratum: int = MIN_STRATUM) -> dict:
    """Re-estimate the effect within each year and count the agreements.

    Each year is an independent sample in a way that individual trips are not,
    so this is the honest check on whether a pooled interval means anything.
    """
    per_year: dict[int, float] = {}
    for year in sorted(y for y in years.dropna().unique()):
        idx = years[years == year].index
        sub_rates = rates.reindex(idx).dropna()
        if len(sub_rates) < 25:
            continue
        in_year = [i for i in ids if i in sub_rates.index]
        if len(in_year) < 8:
            continue
        used = sub_rates.loc[in_year]
        other = sub_rates.drop(index=in_year, errors="ignore")
        res = stratified_effect(used, other, strata, min_stratum=min_stratum)
        if res is None:
            continue
        per_year[int(year)] = round(res[0], 3)

    if not per_year:
        return {"per_year": {}, "years": 0, "agreeing": 0, "stable": None}
    agree = sum(1 for v in per_year.values() if (v > 0) == (pooled_sign > 0))
    n = len(per_year)
    if n < MIN_STABLE_YEARS:
        # Too few independent years to judge. That is "unknown", not "unstable"
        # - a technique measurable in only one year is not thereby inconsistent,
        # and marking it so would demote it for having less data rather than
        # for contradicting itself.
        return {"per_year": per_year, "years": n, "agreeing": agree,
                "stable": None}
    return {"per_year": per_year, "years": n, "agreeing": agree,
            "stable": bool(agree / n >= STABLE_FRACTION)}


def classify(diff: float, lo: float, hi: float, n: int,
             min_trips: int, suggestive_min: int, backed_min: int,
             stable: bool | None = None) -> str:
    """Label how much the archive supports an effect.

    `stable` is the year-agreement verdict. When it is False, an interval that
    excludes zero is reported as `unstable` rather than backed: significant on
    paper, inconsistent in fact.
    """
    if n < min_trips:
        return "thin"
    if hi < 0:
        return "unstable" if stable is False else "below"
    if lo > 0:
        if stable is False:
            return "unstable"
        if n >= backed_min:
            return "backed"
        # An interval can exclude zero on a handful of trips and still be far
        # too wide to headline with.
        return "suggestive" if n >= suggestive_min else "thin"
    if diff > 0 and lo > -0.25 and n >= suggestive_min:
        return "suggestive"
    return "unproven"


def interval(diff: float, se: float) -> tuple[float, float]:
    return diff - Z * se, diff + Z * se


def bait_count_strata(lures: pd.DataFrame, index: pd.Index,
                      level: str = "category", cap: int = 5) -> pd.Series:
    """How many distinct baits each trip named - the thing being matched on."""
    if lures.empty:
        return pd.Series(0, index=index, dtype=int)
    per_trip = lures.drop_duplicates(subset=["report_id", level]) \
        .groupby("report_id")[level].nunique()
    return per_trip.reindex(index).fillna(0).clip(upper=cap).astype(int)
