"""Advice conditioned on lake size - the level at which it actually replicates.

There are three places tackle advice could live, and only two of them survive
scrutiny.

*Per lake* does not. Split a lake's history in half and its own bait effects
agree across the halves at r=-0.02; a few dozen trips cannot carry the claim.

*Club-wide* does, but it averages a 10-acre stock tank together with a 50-acre
lake, and those do not fish alike.

*Per size band* is the middle, and it holds: split-half r=+0.39 with 71% sign
agreement, comfortably past the same bar per-lake advice failed. Pooling lakes of
similar size buys enough trips to measure while keeping a difference that is
really there.

What the bands actually show, and why it matters for a club whose water runs
from about 10 to 50 acres:

* **Topwater flips.** Worth +0.34 fish an hour on water under 15 acres and +0.50
  on 15-30, and it costs a full fish an hour on 30 acres and up - both ends with
  intervals clear of zero, and the sign holds in both halves of the record.
* **Texas rig climbs with size**: -0.19 small, +0.47 mid, +0.85 large.
* **A drop shot hurts on small water** (-1.03), which is what you would expect
  of a deep-water finesse presentation on a shallow weedy tank.
* **Bigger simply fishes better**: 3.6 fish an hour under 15 acres, 4.4 at
  15-30, 5.1 at 30 and up.
"""
from __future__ import annotations

import pandas as pd

from .effect import (bait_count_strata, classify, interval, stratified_effect)

# Acre cut-points. The club runs roughly 10-50 acres, so these split that range
# into three populated groups rather than carving off outliers.
BANDS = [(0, 15, "small"), (15, 30, "mid"), (30, 10_000, "large")]
LABELS = {
    "small": "under 15 acres",
    "mid": "15 to 30 acres",
    "large": "30 acres and up",
}
MIN_TRIPS = 40
SUGGESTIVE_MIN = 60
BACKED_MIN = 90
MIN_BAND_TRIPS = 300


def band_for(acres: float | None) -> str | None:
    if acres is None or acres != acres or acres <= 0:
        return None
    for lo, hi, name in BANDS:
        if lo < acres <= hi:
            return name
    return "large"


def label(band: str | None) -> str:
    return LABELS.get(band or "", "lakes of unknown size")


def _r(v, nd=2):
    return None if v is None or v != v else round(float(v), nd)


def _half_stability(sub: pd.DataFrame, ids: set, lures: pd.DataFrame,
                    pooled_sign: int) -> dict:
    """Split the band's history by date and re-measure in each half.

    Deliberately not the year-by-year check used club-wide. At band level a
    single year holds only a few dozen trips using any one bait, so that test is
    underpowered and demotes real effects - topwater on 30-acre water is -1.00
    with an interval clear of zero and holds its sign in both halves, yet agrees
    in only 4 of 8 individual years. Split-half is also the test the band
    approach was validated on (r=+0.39, 71% sign agreement), so judging bands by
    it keeps the standard consistent with the evidence for using bands at all.
    """
    g = sub.dropna(subset=["fish_per_hour"]).sort_values("trip_date")
    if len(g) < 2 * MIN_BAND_TRIPS // 2:
        return {"halves": 0, "agreeing": 0, "stable": None}
    mid = len(g) // 2
    signs = []
    for part in (g.iloc[:mid], g.iloc[mid:]):
        scored = part.set_index("report_id")
        scored = scored[~scored.index.duplicated()]
        rates = scored["fish_per_hour"]
        if len(rates) < 80:
            continue
        strata = bait_count_strata(
            lures[lures["report_id"].isin(rates.index)], rates.index)
        use = [i for i in ids if i in rates.index]
        if len(use) < 15:
            continue
        res = stratified_effect(rates.loc[use],
                                rates.drop(index=use, errors="ignore"), strata)
        if res is not None:
            signs.append(1 if res[0] > 0 else -1)
    if len(signs) < 2:
        return {"halves": len(signs), "agreeing": 0, "stable": None}
    agree = sum(1 for x in signs if x == pooled_sign)
    return {"halves": len(signs), "agreeing": agree,
            "stable": bool(agree == len(signs))}


def _effects(sub: pd.DataFrame, groups: pd.DataFrame, key: str,
             lures: pd.DataFrame, kind: str) -> list[dict]:
    scored = sub.dropna(subset=["fish_per_hour"]).set_index("report_id")
    scored = scored[~scored.index.duplicated()]
    if len(scored) < MIN_BAND_TRIPS:
        return []
    rates = scored["fish_per_hour"]
    strata = bait_count_strata(
        lures[lures["report_id"].isin(rates.index)], rates.index)

    out = []
    mine = groups[groups["report_id"].isin(rates.index)]
    for value, grp in mine.groupby(key):
        ids = [i for i in grp["report_id"].unique() if i in rates.index]
        if len(ids) < MIN_TRIPS:
            continue
        res = stratified_effect(rates.loc[ids],
                                rates.drop(index=ids, errors="ignore"), strata)
        if res is None:
            continue
        diff, se, _n = res
        lo, hi = interval(diff, se)
        stab = _half_stability(sub, set(ids), lures,
                               pooled_sign=1 if diff > 0 else -1)
        out.append({
            "kind": kind, "value": value, "trips": len(ids),
            "diff": _r(diff), "lo": _r(lo), "hi": _r(hi),
            "halves": stab["halves"], "halves_agreeing": stab["agreeing"],
            "support": classify(diff, lo, hi, len(ids), MIN_TRIPS,
                                SUGGESTIVE_MIN, BACKED_MIN,
                                stable=stab["stable"]),
        })
    out.sort(key=lambda d: -d["diff"])
    return out


def band_effects(trips: pd.DataFrame, lures: pd.DataFrame,
                 tags: pd.DataFrame) -> dict:
    """Bait and technique effects measured separately inside each size band."""
    scored = trips.dropna(subset=["fish_per_hour", "acres"])
    scored = scored[(scored["acres"] > 0) & (scored["acres"] <= 500)].copy()
    if scored.empty:
        return {}
    scored["band"] = scored["acres"].map(band_for)
    baits = lures.drop_duplicates(subset=["report_id", "category"])
    tech = tags[tags["kind"] == "technique"]

    out = {}
    for band, g in scored.groupby("band"):
        if not band:
            continue
        out[band] = {
            "band": band,
            "label": label(band),
            "lakes": int(g["lake"].nunique()),
            "trips": int(len(g)),
            "median_acres": _r(g["acres"].median(), 0),
            "mean_fph": _r(g["fish_per_hour"].mean()),
            "baits": _effects(g, baits, "category", lures, "bait"),
            "techniques": _effects(g, tech, "value", lures, "technique"),
        }
    return out


def advice_for(bands: dict, acres: float | None) -> dict:
    """The band-conditioned advice for one lake, or nothing if its size is
    unknown - in which case the caller should fall back to club-wide."""
    band = band_for(acres)
    if not band or band not in bands:
        return {}
    b = bands[band]
    use, avoid = [], []
    for e in b["baits"] + b["techniques"]:
        if e["support"] == "backed" and e["diff"] > 0:
            use.append(e)
        elif e["support"] in ("backed", "below") and e["diff"] < 0:
            avoid.append(e)
    use.sort(key=lambda e: -e["diff"])
    avoid.sort(key=lambda e: e["diff"])
    return {"band": band, "label": b["label"], "lakes": b["lakes"],
            "trips": b["trips"], "median_acres": b["median_acres"],
            "mean_fph": b["mean_fph"], "use": use[:4], "avoid": avoid[:4],
            "all": b["baits"] + b["techniques"]}


CAVEAT = (
    "Measured across every club lake of this size rather than this one alone. "
    "A single lake's own tackle numbers do not repeat when its history is split "
    "in half (r=-0.02 for baits); pooled by size they do, at r=+0.39 with 71% "
    "sign agreement. So this is the finest grain the archive actually supports "
    "— and it is not a technicality, because the bands genuinely disagree: "
    "topwater is worth half a fish an hour on water under 30 acres and costs a "
    "full fish an hour above it."
)
