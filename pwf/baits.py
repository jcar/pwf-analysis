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

import pandas as pd

from .effect import MIN_STRATUM, Z, bait_count_strata, classify, interval
from .effect import stratified_effect, year_consistency

MIN_TRIPS = 6
# A bait needs this many trips before an interval excluding zero is called
# backed rather than merely suggestive.
BACKED_MIN_TRIPS = 15
# And this many before a near-miss is worth calling suggestive at all. Below it
# the interval is so wide that "close to significant" means nothing.
SUGGESTIVE_MIN_TRIPS = 12

SUPPORT_ORDER = {"backed": 0, "suggestive": 1, "unproven": 2, "thin": 3,
                 "unstable": 4, "below": 5}


def _classify(diff: float, lo: float, hi: float, n: int,
              stable: bool | None = None) -> str:
    return classify(diff, lo, hi, n, MIN_TRIPS, SUGGESTIVE_MIN_TRIPS,
                    BACKED_MIN_TRIPS, stable=stable)


def club_stability(trips: pd.DataFrame, lures: pd.DataFrame,
                   level: str = "category", min_trips: int = 60) -> dict:
    """Whether each bait's club-wide effect holds up year by year.

    A pooled interval treats trips as independent when they cluster within
    seasons, so it runs narrow. For techniques that mattered a lot - two cleared
    the pooled interval and then flipped sign in half the years. For baits it
    matters less: on the whole archive only one verdict changes. Worth knowing
    either way, and worth knowing *which* one.

    Individual lakes almost never carry enough trips per year to run this check
    themselves - 7 of 68 do - so the club-wide verdict is what a per-lake row
    leans on when its own sample cannot answer.
    """
    scored = trips.dropna(subset=["fish_per_hour"])
    if len(scored) < 200 or lures.empty:
        return {}
    sel = scored.set_index("report_id")
    sel = sel[~sel.index.duplicated()]
    rates = sel["fish_per_hour"]
    if "year" not in sel:
        return {}
    years = sel["year"]
    mine = lures[lures["report_id"].isin(rates.index)] \
        .drop_duplicates(subset=["report_id", level])
    strata = bait_count_strata(mine, rates.index, level=level)

    out = {}
    for bait, grp in mine.groupby(level):
        ids = {i for i in grp["report_id"].unique() if i in rates.index}
        if len(ids) < min_trips:
            continue
        used = rates.loc[list(ids)]
        other = rates.drop(index=list(ids), errors="ignore")
        res = stratified_effect(used, other, strata)
        if res is None:
            continue
        out[bait] = year_consistency(rates, years, ids, strata,
                                     pooled_sign=1 if res[0] > 0 else -1)
        out[bait]["diff"] = round(res[0], 3)
    return out


def bait_evidence(trips: pd.DataFrame, lures: pd.DataFrame,
                  level: str = "category", min_trips: int = MIN_TRIPS,
                  stability: dict | None = None) -> list[dict]:
    """Evidence for each bait at one lake, strongest support first.

    `stability` is the club-wide year-by-year verdict from `club_stability`.
    It is attached to each row as `club_unstable` - a caveat for the reader -
    and deliberately does not change the verdict. Only a lake's own year record
    can demote its own result; see the note in the loop below.
    """
    scored = trips.dropna(subset=["fish_per_hour"])
    if len(scored) < 12 or lures.empty:
        return []

    mine = lures[lures["report_id"].isin(scored["report_id"])]
    mine = mine.drop_duplicates(subset=["report_id", level])
    if mine.empty:
        return []

    sel = scored.set_index("report_id")
    sel = sel[~sel.index.duplicated()]
    strata = bait_count_strata(mine, sel.index, level=level)
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

        res = stratified_effect(used, other, strata)
        naive = float(used.mean() - other.mean()) if len(other) else None
        if res is None:
            # Not enough matched strata to say anything defensible.
            out.append({
                "bait": bait, "trips": int(len(used)),
                "rate": round(float(used.mean()), 2), "baseline": round(baseline, 2),
                "diff": None, "lo": None, "hi": None, "naive_diff": _r(naive),
                "support": "thin", "share": round(100 * len(used) / len(rates), 0),
                "years": 0, "years_agreeing": 0, "stable": None,
                "club_unstable": bool(stability and bait in stability
                                      and stability[bait]["stable"] is False),
            })
            continue

        diff, se, _n = res
        lo, hi = interval(diff, se)

        local = year_consistency(rates, sel["year"], set(ids), strata,
                                 pooled_sign=1 if diff > 0 else -1) \
            if "year" in sel else {"stable": None, "years": 0, "agreeing": 0}

        # Only this lake's own year-to-year record can demote this lake's
        # result. A bait that cannot hold its sign across ninety lakes with
        # different water is not thereby wrong about one of them - Hickory
        # Creek's crankbait bite is 61 trips with an interval clear of zero,
        # while club-wide crankbait averages nothing and swings from -1.9 to
        # +0.3 by year. Those are different claims, and folding the second into
        # the first would erase real local knowledge. The club verdict is
        # carried as a caveat instead.
        stable = local["stable"]
        club_unstable = bool(stability and bait in stability
                             and stability[bait]["stable"] is False)

        out.append({
            "bait": bait,
            "trips": int(len(used)),
            "share": round(100 * len(used) / len(rates), 0),
            "rate": round(float(used.mean()), 2),
            "baseline": round(baseline, 2),
            "diff": _r(diff), "lo": _r(lo), "hi": _r(hi),
            "naive_diff": _r(naive),
            "years": local["years"], "years_agreeing": local["agreeing"],
            "stable": stable, "club_unstable": club_unstable,
            "support": _classify(diff, lo, hi, len(used), stable),
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
    unstable = [e for e in evidence if e["support"] == "unstable"]

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
        "unstable": unstable,
        "n_compared": len(evidence),
    }


def _name(bait: str) -> str:
    return bait.replace("_", " ")
