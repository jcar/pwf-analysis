"""How reliable a lake has been - as history, not as a forecast.

Two facts shape everything in this module, and both were measured rather than
assumed.

**A lake's average tells you nothing about its spread.** The correlation between
a lake's mean catch rate and its coefficient of variation is +0.04. The club's
best September lake is also its most volatile, which is worth knowing before a
126-mile drive.

**But spread does not carry forward well.** A lake's volatility in past years
predicts its volatility in the next year at only r≈0.20, against r≈0.65 for its
catch rate. So this is reported as what a lake *has done*, and deliberately not
as what it will do. Nothing here feeds the ranking.

A third measured fact keeps the display honest: bust rate is largely a
restatement of the average (r=-0.68 with mean rate) - good lakes blank less, and
saying so twice is not two pieces of information. Volatility is the measure that
adds something the catch rate does not already carry.
"""
from __future__ import annotations

import pandas as pd

# Fish per trip at or below which a day counts as a blank. Club-wide this
# catches 8.7% of trips; the median trip brings 15.
BUST_FISH = 2
MIN_TRIPS = 20

# Measured: how well past volatility predicts future volatility, across five
# held-out years. Quoted wherever the figure is shown so nobody reads it as a
# forecast.
VOLATILITY_PERSISTENCE_R = 0.20

BANDS = [(0.70, "steady"), (0.95, "typical"), (99.0, "swingy")]


def volatility_band(cv: float | None) -> str | None:
    if cv is None or cv != cv:
        return None
    for edge, name in BANDS:
        if cv <= edge:
            return name
    return "swingy"


def _r(v, nd=2):
    return None if v is None or v != v else round(float(v), nd)


def lake_consistency(trips: pd.DataFrame, min_trips: int = MIN_TRIPS) -> dict:
    """Per-lake spread of outcomes, keyed by lake name."""
    scored = trips.dropna(subset=["fish_per_hour"])
    if scored.empty or "lake" not in scored:
        return {}

    out = {}
    for lake, g in scored.groupby("lake"):
        if len(g) < min_trips:
            continue
        rates = g["fish_per_hour"]
        fish = g["fish_total"].dropna()
        mean = float(rates.mean())
        cv = float(rates.std(ddof=1) / mean) if mean else None
        out[lake] = {
            "trips": int(len(g)),
            "median": _r(rates.median()),
            "mean": _r(mean),
            "cv": _r(cv),
            "band": volatility_band(cv),
            "worst_decile": _r(rates.quantile(0.10)),
            "best_decile": _r(rates.quantile(0.90)),
            "bust_rate": _r(100 * (fish <= BUST_FISH).mean(), 0) if len(fish) else None,
            "bust_n": int(len(fish)),
            "typical_fish": _r(fish.median(), 0) if len(fish) else None,
        }
    return out


def describe(entry: dict, club_bust: float | None = None) -> str | None:
    """One sentence a person can act on, with its own caveat attached."""
    if not entry:
        return None
    bits = []
    if entry["typical_fish"] is not None:
        bits.append(f"a typical day here brings {entry['typical_fish']:.0f} fish")
    if entry["worst_decile"] is not None:
        bits.append(f"the slowest one in ten runs {entry['worst_decile']} an hour")
    if entry["bust_rate"] is not None:
        cmp = ""
        if club_bust is not None:
            cmp = (" — below the club's " if entry["bust_rate"] < club_bust
                   else " — above the club's " if entry["bust_rate"] > club_bust
                   else " — matching the club's ")
            cmp += f"{club_bust:.0f}%"
        bits.append(f"{entry['bust_rate']:.0f}% of trips came back with "
                    f"{BUST_FISH} fish or fewer{cmp}")
    if not bits:
        return None
    band = {"steady": "It has been one of the steadier lakes",
            "typical": "Its spread is about average for the club",
            "swingy": "It has been one of the swingier lakes"}.get(entry["band"])
    s = (band + ": " if band else "") + "; ".join(bits) + "."
    return s


def club_bust_rate(trips: pd.DataFrame) -> float | None:
    fish = trips.dropna(subset=["fish_per_hour"])["fish_total"].dropna()
    if fish.empty:
        return None
    return round(100 * (fish <= BUST_FISH).mean(), 1)


CAVEAT = (
    "Spread is history, not a forecast: a lake's volatility in past years "
    f"predicts the next year's at only about r={VOLATILITY_PERSISTENCE_R:.2f}, "
    "against r=0.65 for its catch rate. Bust rate also largely restates the "
    "average — good lakes blank less — so volatility is the column that adds "
    "something the rate does not already tell you."
)
