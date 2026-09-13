"""How you fish it, as distinct from what you tie on.

Presentation turns out to carry more measurable signal than bait choice. Across
the archive, fishing something weightless or wacky-rigged is worth roughly a
fish an hour against the alternatives on comparable trips - larger than almost
any bait effect, and it holds year after year.

Two guards, both from `pwf.effect`:

*Matching.* Techniques are compared against the other trips that named about as
many baits, because a trip describing three presentations also describes more
tackle, and undescribed trips catch less.

*Year stability.* A pooled interval treats trips as independent when they
cluster within seasons, so it runs too narrow. Re-estimating year by year sorts
the real patterns from the artefacts, and it changes the answer here: wacky
holds its sign in 8 of 8 years and weightless in 6 of 8, while drop shot (5 of
8) and the ned rig (4 of 8) clear the pooled interval and then flip sign in half
the years they appear in. Those two are reported as `unstable` rather than
promoted - significant on paper, inconsistent in fact.
"""
from __future__ import annotations

import pandas as pd

from .effect import (bait_count_strata, classify, interval, stratified_effect,
                     year_consistency)

MIN_TRIPS = 25
SUGGESTIVE_MIN_TRIPS = 40
BACKED_MIN_TRIPS = 60
# Per-lake samples are far thinner than club-wide ones.
LAKE_MIN_TRIPS = 12
LAKE_BACKED_MIN = 25

SUPPORT_ORDER = {"backed": 0, "suggestive": 1, "unproven": 2, "unstable": 3,
                 "thin": 4, "below": 5}

LABELS = {
    "weightless": "weightless",
    "texas_rig": "Texas rig",
    "carolina_rig": "Carolina rig",
    "drop_shot": "drop shot",
    "wacky": "wacky rig",
    "neko": "neko rig",
    "ned": "ned rig",
    "shaky_head": "shaky head",
    "punching": "punching",
    "flipping": "flipping / pitching",
    "flip_punch": "flipping & punching",
    "burning": "burning it",
    "slow_roll": "slow rolling",
    "dead_stick": "dead sticking",
    "twitching": "twitching",
    "walking": "walking the dog",
    "dragging": "dragging",
    "hopping": "hopping",
    "pauses": "pausing the retrieve",
    "freeline": "free-lining",
    "split_shot": "split shot",
}


def label(value: str) -> str:
    return LABELS.get(value, value.replace("_", " "))


def _r(v, nd=2):
    return None if v is None or v != v else round(float(v), nd)


def technique_effects(trips: pd.DataFrame, tags: pd.DataFrame,
                      lures: pd.DataFrame, min_trips: int | None = None,
                      backed_min: int | None = None,
                      check_years: bool = True) -> list[dict]:
    """Effect of each presentation, strongest support first."""
    min_trips = MIN_TRIPS if min_trips is None else min_trips
    backed_min = BACKED_MIN_TRIPS if backed_min is None else backed_min

    scored = trips.dropna(subset=["fish_per_hour"])
    if len(scored) < 40 or tags.empty:
        return []

    sel = scored.set_index("report_id")
    sel = sel[~sel.index.duplicated()]
    rates = sel["fish_per_hour"]
    years = sel["year"] if "year" in sel else pd.Series(dtype=float)
    strata = bait_count_strata(
        lures[lures["report_id"].isin(rates.index)], rates.index)

    mine = tags[(tags["kind"] == "technique")
                & tags["report_id"].isin(rates.index)]
    if mine.empty:
        return []

    out = []
    for value, grp in mine.groupby("value"):
        ids = [i for i in grp["report_id"].unique() if i in rates.index]
        if len(ids) < min_trips:
            continue
        used = rates.loc[ids]
        other = rates.drop(index=ids, errors="ignore")
        res = stratified_effect(used, other, strata)
        if res is None:
            continue
        diff, se, _n = res
        lo, hi = interval(diff, se)

        stability = {"per_year": {}, "years": 0, "agreeing": 0, "stable": None}
        if check_years and len(years):
            stability = year_consistency(rates, years, set(ids), strata,
                                         pooled_sign=1 if diff > 0 else -1)

        out.append({
            "technique": value,
            "label": label(value),
            "trips": int(len(used)),
            "share": round(100 * len(used) / len(rates), 0),
            "rate": _r(used.mean()),
            "baseline": _r(rates.mean()),
            "diff": _r(diff), "lo": _r(lo), "hi": _r(hi),
            "naive_diff": _r(used.mean() - other.mean()) if len(other) else None,
            "years": stability["years"],
            "years_agreeing": stability["agreeing"],
            "per_year": stability["per_year"],
            "stable": stability["stable"],
            "support": classify(diff, lo, hi, len(used), min_trips,
                                SUGGESTIVE_MIN_TRIPS, backed_min,
                                stable=stability["stable"]),
        })

    out.sort(key=lambda d: (SUPPORT_ORDER.get(d["support"], 9), -d["diff"]))
    return out


def lake_technique_effects(trips: pd.DataFrame, tags: pd.DataFrame,
                           lures: pd.DataFrame) -> list[dict]:
    """The same, scoped to one lake.

    Per-lake samples are far thinner, so the year check is skipped - a single
    lake rarely has enough trips per year to re-estimate meaningfully - and the
    caller should present these as suggestive rather than settled.
    """
    return technique_effects(trips, tags, lures, min_trips=LAKE_MIN_TRIPS,
                             backed_min=LAKE_BACKED_MIN, check_years=False)


def summary(effects: list[dict]) -> dict:
    """Group the effects into something a person can act on."""
    by = {k: [e for e in effects if e["support"] == k]
          for k in ("backed", "suggestive", "unproven", "unstable", "below",
                    "thin")}
    if by["backed"]:
        named = by["backed"][:2]
        verb = "holds" if len(named) == 1 else "hold"
        lead = ("Presentation carries more here than bait choice: "
                + " and ".join(e["label"] for e in named)
                + f" {verb} up across the archive")
    elif by["suggestive"]:
        lead = f"{by['suggestive'][0]['label']} leans positive, short of proof"
    else:
        lead = "No presentation separates once trips are matched on detail"
    return {"lead": lead, "n_compared": len(effects), **by}
