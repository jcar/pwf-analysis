"""One lake, one day: what to expect, what to throw, and the receipts.

This module adds no statistics. It assembles what the analysis modules already
produce into the order an angler needs it the night before a trip, and attaches
the evidence behind each claim.

The receipts matter as much as the recommendation. Every figure here rests on a
modest effect measured on observational data, so each one carries its sample,
its interval, and - because the club's report pages are public - links to the
actual trips it was computed from. A reader who wants to check whether four
"backed" trips were really four good days can go and read them.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from . import analysis as A
from .baits import bait_evidence, club_stability, recommendation
from .consistency import CAVEAT, club_bust_rate, describe, lake_consistency
from .profile import lake_profile, miles_from_home
from .recommend import _expected_rate, _next_saturday, describe_forecast
from .technique import summary as tech_summary
from .technique import technique_effects

REPORT_URL = "https://www.privatewaterfishing.com/forums/view_report/{id}"
MAX_CITES = 10

# Measured within lake-month: AM vs PM is -0.025 with a 95% interval of
# [-0.068, +0.018]. There is no edge either way, which is worth saying rather
# than leaving the reader to guess.
SLOT_NOTE = (
    "Morning against afternoon is a wash here and club-wide — measured within "
    "lake and month the gap is 0.03 fish an hour with an interval straddling "
    "zero. Book whichever half-day suits you. An all-day ticket does catch more "
    "fish in total, because it is more hours on the water, not a better window."
)


def evidence_trips(scored: pd.DataFrame, lures: pd.DataFrame, bait: str,
                   limit: int = MAX_CITES) -> list[list]:
    """The most recent trips behind one bait, as [report_id, date, fish]."""
    ids = set(lures[lures["category"] == bait]["report_id"])
    sel = scored[scored["report_id"].isin(ids)]
    if sel.empty:
        return []
    sel = sel.sort_values("trip_date", ascending=False).head(limit)
    out = []
    for r in sel.itertuples():
        fish = None if r.fish_total != r.fish_total else int(r.fish_total)
        out.append([int(r.report_id), str(r.trip_date), fish])
    return out


def report_url(report_id: int) -> str:
    return REPORT_URL.format(id=report_id)


def _conditions_note(fc: dict) -> str | None:
    """A sentence only when the forecast actually warrants one.

    Weather barely moves catch rate in this archive - the largest measured
    effect has an interval including zero - but a hundred-degree Saturday still
    changes how the day should be fished, and a brief that ignored it would be
    no use.
    """
    if not fc:
        return None
    t, wind = fc.get("temp_max_f"), fc.get("wind_max_mph")
    precip, cloud = fc.get("precip_in") or 0, fc.get("cloud_pct")
    bits = []
    if t is not None and t >= 95:
        bits.append(
            f"{t:.0f}°F is punishing. Be on the water at first light and expect "
            "the window to close early; shade, deeper water and the first hour "
            "are worth more than any lure choice")
    elif t is not None and t <= 50:
        bits.append(
            f"{t:.0f}°F is cold for here. Expect a late, short bite and slow "
            "everything down")
    if wind is not None and wind >= 18:
        bits.append(f"{wind:.0f} mph will make boat control the limiting factor")
    elif wind is not None and wind <= 6:
        bits.append("dead calm, which tends to mean spooky fish in clear water")
    if precip >= 0.25:
        bits.append(f"{precip:.2f}\" of rain forecast")
    if cloud is not None and cloud <= 15 and not bits:
        bits.append("bluebird and bright")
    if not bits:
        return None
    return bits[0][0].upper() + bits[0][1:] + (
        ("; " + "; ".join(bits[1:])) if len(bits) > 1 else "") + "."


def trip_brief(conn: sqlite3.Connection, lake: str, when: date | None = None,
               trips: pd.DataFrame | None = None,
               lures: pd.DataFrame | None = None,
               tags: pd.DataFrame | None = None,
               club_tech: list | None = None,
               consistency: dict | None = None,
               bait_stab: dict | None = None,
               forecast: dict | None = None) -> dict:
    """Everything needed to decide on, and fish, one lake on one day."""
    when = when or _next_saturday()
    trips = A.trips_frame(conn) if trips is None else trips
    lures = A.lures_frame(conn) if lures is None else lures
    tags = A.tags_frame(conn) if tags is None else tags

    sel_all = trips[trips["lake"].fillna("").str.lower() == lake.lower()]
    if sel_all.empty:
        return {"error": f"no trips for {lake!r}"}
    name = sel_all["lake"].iloc[0]
    scored = sel_all.dropna(subset=["fish_per_hour"])
    mine_lures = lures[lures["report_id"].isin(sel_all["report_id"])]

    if bait_stab is None:
        bait_stab = club_stability(trips, lures)
    if consistency is None:
        consistency = lake_consistency(trips)
    if club_tech is None:
        club_tech = technique_effects(trips, tags, lures)

    prof = lake_profile(conn, name, trips=trips, lures=lures,
                        club_technique=club_tech, consistency=consistency,
                        bait_stability=bait_stab)

    # Expected rate for the target month, the same figure the shortlist ranks on.
    club_scored = trips.dropna(subset=["fish_per_hour"])
    club_mean = float(club_scored["fish_per_hour"].mean())
    month_mean = float(club_scored.groupby("month")["fish_per_hour"].mean()
                       .get(when.month, club_mean))
    est = _expected_rate(sel_all, when.month, month_mean, club_mean)

    ev = bait_evidence(sel_all, mine_lures, stability=bait_stab)
    rec = recommendation(ev)
    cites = {e["bait"]: evidence_trips(scored, mine_lures, e["bait"])
             for e in ev}

    lake_tech = (prof.get("technique") or {}).get("lake") or []
    fc = describe_forecast(forecast or {})

    cons = consistency.get(name, {})
    club_bust = consistency.get("__club_bust__")
    if club_bust is None:
        club_bust = club_bust_rate(trips)

    return {
        "lake": name,
        "date": when.isoformat(),
        "weekday": when.strftime("%A"),
        "facts": prof["facts"],
        "volume": prof["volume"],
        "expected": {
            "fph": est.get("expected"),
            "lower": est.get("lower"),
            "basis": est.get("basis"),
            "n_basis": est.get("n"),
            "n_total": est.get("n_total"),
            "club_month_mean": round(month_mean, 2),
            "month_name": when.strftime("%B"),
        },
        "expect": {
            **{k: cons.get(k) for k in
               ("typical_fish", "worst_decile", "best_decile", "bust_rate",
                "cv", "band", "trips")},
            "club_bust_rate": club_bust,
            "sentence": describe(cons, club_bust) if cons else None,
            "caveat": CAVEAT,
        },
        "conditions": {"forecast": fc or None, "note": _conditions_note(fc)},
        "plan": {
            "presentation": _presentation_plan(club_tech, lake_tech),
            "baits": rec,
            "where": (prof["water"].get("structure") or [])[:5],
            "vegetation": (prof["water"].get("vegetation") or [])[:4],
            "skip": rec.get("below") or [],
            "slot_note": SLOT_NOTE,
        },
        "by_month": prof["by_month"],
        "citations": cites,
        "summary": prof.get("summary"),
    }


def _presentation_plan(club_tech: list, lake_tech: list) -> dict:
    """Presentation leads the plan because it measures larger than bait choice.

    Club-wide effects are the reliable part - they survive a year-by-year
    stability check that individual lakes almost never have the trips to run -
    so this lake's own numbers ride alongside rather than replacing them.
    """
    s = tech_summary(club_tech) if club_tech else {}
    local = {e["technique"]: e for e in lake_tech}
    lead, avoid = [], []
    for e in (s.get("backed") or [])[:3]:
        here = local.get(e["technique"])
        lead.append({**{k: e[k] for k in
                        ("technique", "label", "trips", "diff", "lo", "hi",
                         "years", "years_agreeing")},
                     "here": ({"diff": here["diff"], "trips": here["trips"]}
                              if here else None)})
    for e in (s.get("below") or [])[:2]:
        avoid.append({k: e[k] for k in ("technique", "label", "trips", "diff")})
    return {"lead": s.get("lead"), "use": lead, "avoid": avoid,
            "unstable": [e["label"] for e in (s.get("unstable") or [])]}


def shortlist_briefs(conn: sqlite3.Connection, when: date, lakes: list[str],
                     **shared) -> dict[str, dict]:
    """Briefs for a set of lakes, sharing one pass over the frames."""
    out = {}
    for lake in lakes:
        b = trip_brief(conn, lake, when, **shared)
        if "error" not in b:
            out[lake] = b
    return out


def next_weekend(today: date | None = None) -> tuple[date, date]:
    """The Saturday and Sunday a booking would land on."""
    sat = _next_saturday(today)
    return sat, sat + timedelta(days=1)
