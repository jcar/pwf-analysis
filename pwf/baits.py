"""What to throw at a lake, and how much the archive actually backs it.

The naive comparison - trips that named a bait against trips that did not - is
confounded. Members who name several baits catch more fish (one bait named,
3.68 fish/hr club-wide; five, 4.62), because a longer or better day gets
described in more detail. So any bait looks good simply for appearing on a
well-documented trip, and nearly every bait at nearly every lake scored above
its own lake's average, which cannot be true of all of them at once.

The estimate here compares a bait against the *other* baits on trips that named
the same number of them, then combines those strata by inverse variance. That
removes the effort signal and changes real conclusions: at one lake a jig moved
from +1.37 to -0.24 fish an hour once the trips it appeared on were matched
against equally-documented ones.

Every figure carries a confidence interval, and most intervals contain zero.
That is the honest headline: at a typical lake only one or two baits separate
from the rest, and the rest are things people throw, not things that work
better.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

Z = 1.96
MIN_TRIPS = 6
MIN_STRATUM = 4
# A bait needs this many trips before an interval excluding zero is called
# backed rather than merely suggestive.
BACKED_MIN_TRIPS = 15
# And this many before a near-miss is worth calling suggestive at all. Below it
# the interval is so wide that "close to significant" means nothing.
SUGGESTIVE_MIN_TRIPS = 12

SUPPORT_ORDER = {"backed": 0, "suggestive": 1, "unproven": 2, "thin": 3,
                 "below": 4}


def _stratified_diff(used: pd.Series, other: pd.Series,
                     strata: pd.Series) -> tuple[float, float, int] | None:
    """Difference in catch rate, matched on how many baits the trip named.

    Each stratum contributes its own difference; strata are combined by inverse
    variance, which is the standard way to pool independent estimates and gives
    the better-sampled strata the weight they deserve.
    """
    diffs, weights, n_used = [], [], 0
    for key in strata.unique():
        u = used[strata.loc[used.index] == key] if len(used) else used
        o = other[strata.loc[other.index] == key] if len(other) else other
        if len(u) < MIN_STRATUM or len(o) < MIN_STRATUM:
            continue
        var = u.var(ddof=1) / len(u) + o.var(ddof=1) / len(o)
        if not var or var != var or var <= 0:
            continue
        diffs.append(u.mean() - o.mean())
        weights.append(1.0 / var)
        n_used += len(u)
    if not diffs:
        return None
    w = np.array(weights)
    d = np.array(diffs)
    diff = float((w * d).sum() / w.sum())
    se = float(math.sqrt(1.0 / w.sum()))
    return diff, se, n_used


def _classify(diff: float, lo: float, hi: float, n: int) -> str:
    if n < MIN_TRIPS:
        return "thin"
    if hi < 0:
        return "below"
    if lo > 0:
        if n >= BACKED_MIN_TRIPS:
            return "backed"
        # An interval can exclude zero on a handful of trips and still be far
        # too wide to headline a lake with.
        return "suggestive" if n >= SUGGESTIVE_MIN_TRIPS else "thin"
    if diff > 0 and lo > -0.25 and n >= SUGGESTIVE_MIN_TRIPS:
        return "suggestive"
    return "unproven"


def bait_evidence(trips: pd.DataFrame, lures: pd.DataFrame,
                  level: str = "category", min_trips: int = MIN_TRIPS
                  ) -> list[dict]:
    """Evidence for each bait at one lake, strongest support first."""
    scored = trips.dropna(subset=["fish_per_hour"])
    if len(scored) < 12 or lures.empty:
        return []

    mine = lures[lures["report_id"].isin(scored["report_id"])]
    mine = mine.drop_duplicates(subset=["report_id", level])
    if mine.empty:
        return []

    # How many distinct baits each trip named - the thing being matched on.
    per_trip = mine.groupby("report_id")[level].nunique()
    sel = scored.set_index("report_id")
    sel = sel[~sel.index.duplicated()]
    strata = per_trip.reindex(sel.index).fillna(0).clip(upper=5).astype(int)
    rates = sel["fish_per_hour"]
    baseline = float(rates.mean())

    out = []
    for bait, grp in mine.groupby(level):
        ids = [i for i in grp["report_id"].unique() if i in rates.index]
        if len(ids) < min_trips:
            continue
        used = rates.loc[ids]
        other = rates.drop(index=ids, errors="ignore")
        if len(other) < MIN_STRATUM:
            continue

        res = _stratified_diff(used, other, strata)
        naive = float(used.mean() - other.mean()) if len(other) else None
        if res is None:
            # Not enough matched strata to say anything defensible.
            out.append({
                "bait": bait, "trips": int(len(used)),
                "rate": round(float(used.mean()), 2), "baseline": round(baseline, 2),
                "diff": None, "lo": None, "hi": None, "naive_diff": _r(naive),
                "support": "thin", "share": round(100 * len(used) / len(rates), 0),
            })
            continue

        diff, se, _n = res
        lo, hi = diff - Z * se, diff + Z * se
        out.append({
            "bait": bait,
            "trips": int(len(used)),
            "share": round(100 * len(used) / len(rates), 0),
            "rate": round(float(used.mean()), 2),
            "baseline": round(baseline, 2),
            "diff": _r(diff), "lo": _r(lo), "hi": _r(hi),
            "naive_diff": _r(naive),
            "support": _classify(diff, lo, hi, len(used)),
        })

    out.sort(key=lambda d: (SUPPORT_ORDER.get(d["support"], 9),
                            -(d["diff"] if d["diff"] is not None else -99)))
    return out


def _r(v, nd=2):
    return None if v is None or v != v else round(float(v), nd)


def bait_detail(trips: pd.DataFrame, lures: pd.DataFrame, bait: str,
                tags: pd.DataFrame | None = None) -> dict:
    """Supporting detail for one bait: which versions, colours, and when."""
    scored = trips.dropna(subset=["fish_per_hour"])
    ids = set(lures[lures["category"] == bait]["report_id"])
    sel = scored[scored["report_id"].isin(ids)]
    if sel.empty:
        return {}

    mine = lures[(lures["category"] == bait) & (lures["report_id"].isin(ids))]
    subtypes = [{"value": k, "n": int(v)} for k, v in
                mine[mine["subtype"].notna() & (mine["subtype"] != "unspecified")]
                ["subtype"].value_counts().head(4).items()]
    colors = [{"value": k, "n": int(v)} for k, v in
              mine[mine["color"].notna()]["color"].value_counts().head(4).items()]

    by_season = {}
    for season, g in sel.groupby("season"):
        if len(g) >= 4:
            by_season[season] = {"n": int(len(g)),
                                 "rate": _r(g["fish_per_hour"].mean())}
    months = sel.groupby("month")["fish_per_hour"].agg(["size", "mean"])
    months = months[months["size"] >= 3]
    best_month = int(months["mean"].idxmax()) if len(months) else None

    return {"subtypes": subtypes, "colors": colors, "by_season": by_season,
            "best_month": best_month,
            "from_field": int((mine["source"] == "field").sum()),
            "from_narrative": int((mine["source"] == "narrative").sum())}


def recommendation(evidence: list[dict], detail_fn=None) -> dict:
    """Group the evidence into what to actually do with it."""
    backed = [e for e in evidence if e["support"] == "backed"]
    suggestive = [e for e in evidence if e["support"] == "suggestive"]
    unproven = [e for e in evidence if e["support"] == "unproven"]
    below = [e for e in evidence if e["support"] == "below"]
    thin = [e for e in evidence if e["support"] == "thin"]

    if backed:
        lead = (f"{_name(backed[0]['bait'])} is the one bait here the archive "
                f"actually separates from the rest")
        if len(backed) > 1:
            lead = (f"{len(backed)} baits separate from the rest here: "
                    + ", ".join(_name(b["bait"]) for b in backed))
    elif suggestive:
        best = max(suggestive, key=lambda e: e["trips"])
        lead = (f"Nothing clears the bar outright; {_name(best['bait'])} comes "
                f"closest, over {best['trips']} trips")
    else:
        lead = ("No bait at this lake separates from the others once trips are "
                "matched on how much they described")

    return {
        "lead": lead,
        "backed": backed, "suggestive": suggestive,
        "unproven": unproven, "below": below, "thin": thin,
        "n_compared": len(evidence),
    }


def _name(bait: str) -> str:
    return bait.replace("_", " ")
