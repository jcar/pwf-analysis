"""Does an effect repeat, or is it noise wearing a confidence interval?

These pin the finding that per-lake tackle effects do not replicate, and — just
as important — that the method detects the signal that does. Without the control
a flat result could mean a broken test rather than a real answer.
"""
import numpy as np
import pandas as pd
import pytest

from pwf import analysis as A
from pwf.config import DB_PATH
from pwf.db import init
from pwf.reliability import (REPEATS_THRESHOLD, lake_rate_split_half, report,
                             split_half)


@pytest.fixture(scope="module")
def live():
    if not DB_PATH.exists():
        pytest.skip("no database - run `pwf build`")
    conn = init(DB_PATH)
    trips = A.trips_frame(conn)
    if trips.empty:
        pytest.skip("no trips")
    return conn, trips, A.lures_frame(conn), A.tags_frame(conn)


class TestTheControl:
    def test_a_lakes_catch_rate_does_repeat(self, live):
        """The signal the ranking rests on. If this ever goes flat the method
        is broken and every other result here is meaningless."""
        _c, trips, _l, _t = live
        out = lake_rate_split_half(trips)
        assert out["r"] is not None and out["lakes"] >= 20
        assert out["r"] > 0.5, (
            f"lake catch rate stopped repeating (r={out['r']}) — the split-half "
            "method is no longer detecting a signal we know is there")


class TestPerLakeTackleDoesNotRepeat:
    def test_bait_effects_do_not_replicate_within_a_lake(self, live):
        _c, trips, lures, _t = live
        baits = lures.drop_duplicates(subset=["report_id", "category"])
        out = split_half(trips, lures, baits, "category")
        assert out["cells"] >= 40
        assert out["repeats"] is False, (
            f"per-lake bait effects now replicate (r={out['r']}) — if that is "
            "real, lake-specific bait advice becomes defensible and the brief "
            "should be changed back")
        assert abs(out["r"]) < REPEATS_THRESHOLD

    def test_technique_effects_do_not_replicate_within_a_lake(self, live):
        _c, trips, lures, tags = live
        tech = tags[tags["kind"] == "technique"]
        out = split_half(trips, lures, tech, "value")
        assert out["cells"] >= 15
        assert out["repeats"] is False
        assert abs(out["r"]) < REPEATS_THRESHOLD

    def test_the_gap_between_control_and_tackle_is_large(self, live):
        """The whole argument is that one repeats and the other does not."""
        _c, trips, lures, tags = live
        rep = report(trips, lures, tags)
        assert rep["lake_rate"]["r"] - abs(rep["lake_baits"]["r"]) > 0.4


class TestSplitHalfMechanics:
    def test_it_finds_an_effect_that_is_genuinely_there(self):
        """A synthetic bait that really does add fish, consistently, must come
        out as repeating — otherwise the flat live result proves nothing."""
        rng = np.random.default_rng(4)
        rows, pairs = [], []
        rid = 0
        for lake in range(12):
            for i in range(90):
                uses = i % 2 == 0
                rows.append({
                    "report_id": rid, "lake": f"L{lake}", "lake_known": 1,
                    "trip_date": f"20{20 + i // 30:02d}-0{1 + i % 9}-15",
                    "fish_per_hour": rng.normal(6.0 if uses else 3.0, 0.5),
                })
                pairs.append({"report_id": rid,
                              "category": "real" if uses else "other",
                              "subtype": "x", "color": None, "source": "field"})
                rid += 1
        out = split_half(pd.DataFrame(rows), pd.DataFrame(pairs),
                         pd.DataFrame(pairs), "category", min_lake_trips=60)
        assert out["r"] is not None and out["r"] > REPEATS_THRESHOLD, out


class TestBriefReflectsIt:
    def test_the_plan_leads_with_club_wide_effects(self, live):
        from pwf.brief import next_weekend, trip_brief
        conn, trips, _l, _t = live
        lake = trips[trips.lake_known == 1]["lake"].value_counts().index[0]
        plan = trip_brief(conn, lake, next_weekend()[0])["plan"]
        assert plan["club_baits"].get("use"), "no club-wide bait advice"
        assert plan["presentation"].get("use"), "no club-wide presentation advice"
        # every club-wide figure must rest on far more than one lake's trips
        for e in plan["club_baits"]["use"]:
            assert e["trips"] > 500, e
        for u in plan["presentation"]["use"]:
            assert u["trips"] > 200, u

    def test_the_lake_section_is_descriptive_only(self, live):
        from pwf.brief import next_weekend, trip_brief
        conn, trips, _l, _t = live
        lake = trips[trips.lake_known == 1]["lake"].value_counts().index[0]
        plan = trip_brief(conn, lake, next_weekend()[0])["plan"]
        here = plan["here"]
        assert here["share"], "no local usage reported"
        # shares are shares - a count that exceeded its denominator was a bug
        for x in here["share"]:
            assert 0 < x["share"] <= 100, x
        # and the caveat must travel with it
        assert plan["lake_reliability"]
        assert "do not repeat" in plan["lake_reliability"]
