"""Technique effects, and the year-stability filter that guards them.

The filter is the point of this module. A pooled confidence interval treats
every trip as independent when trips cluster within seasons, so it runs narrow.
Two techniques in this archive clear the pooled interval and then flip sign in
half the years they appear in. Promoting them would be reporting noise with a
decimal point on it.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pwf import analysis as A
from pwf.config import DB_PATH
from pwf.db import init
from pwf.effect import (MIN_STABLE_YEARS, classify, stratified_effect,
                        year_consistency)
from pwf.technique import summary, technique_effects


@pytest.fixture(scope="module")
def live():
    if not DB_PATH.exists():
        pytest.skip("no database - run `pwf build`")
    conn = init(DB_PATH)
    trips, lures, tags = (A.trips_frame(conn), A.lures_frame(conn),
                          A.tags_frame(conn))
    if trips.empty or tags.empty:
        pytest.skip("no data")
    return conn, trips, lures, tags


class TestYearStabilityFilter:
    """The distinction this whole module exists to draw."""

    def test_consistent_techniques_are_backed(self, live):
        _c, trips, lures, tags = live
        ev = {e["technique"]: e for e in technique_effects(trips, tags, lures)}
        for name in ("wacky", "weightless"):
            e = ev.get(name)
            assert e, f"{name} missing"
            assert e["support"] == "backed", f"{name}: {e['support']}"
            assert e["years_agreeing"] / e["years"] >= 2 / 3

    def test_sign_flipping_techniques_are_demoted(self, live):
        """Drop shot and the ned rig both clear the pooled interval. Both flip
        sign in half the years. Neither may be presented as backed."""
        _c, trips, lures, tags = live
        ev = {e["technique"]: e for e in technique_effects(trips, tags, lures)}
        for name in ("drop_shot", "ned"):
            e = ev.get(name)
            if not e:
                continue
            assert e["lo"] > 0 or e["hi"] < 0, f"{name} should clear the pooled CI"
            assert e["support"] == "unstable", f"{name}: {e['support']}"
            assert e["support"] != "backed"

    def test_the_filter_actually_changes_the_answer(self, live):
        """Without the year check these would be backed. If that ever stops
        being true the filter has quietly become a no-op."""
        _c, trips, lures, tags = live
        with_check = {e["technique"]: e["support"]
                      for e in technique_effects(trips, tags, lures)}
        without = {e["technique"]: e["support"]
                   for e in technique_effects(trips, tags, lures,
                                              check_years=False)}
        changed = [k for k in with_check
                   if with_check[k] != without.get(k)]
        assert changed, "the year filter demoted nothing - it is doing no work"

    def test_too_few_years_is_unknown_not_unstable(self):
        """A technique measurable in one year is not thereby inconsistent."""
        rng = np.random.default_rng(3)
        n = 120
        rates = pd.Series(rng.normal(4, 1, n), index=range(n))
        years = pd.Series([2025] * n, index=range(n))
        strata = pd.Series([1] * n, index=range(n))
        out = year_consistency(rates, years, set(range(40)), strata, 1)
        assert out["years"] < MIN_STABLE_YEARS
        assert out["stable"] is None
        # And an unknown verdict must not demote a significant result.
        assert classify(1.0, 0.4, 1.6, 80, 25, 40, 60, stable=None) == "backed"
        assert classify(1.0, 0.4, 1.6, 80, 25, 40, 60, stable=False) == "unstable"


class TestConfound:
    def test_a_technique_that_only_rides_busy_trips_is_not_credited(self):
        """Same construction as the bait test: trips describing more catch
        more, and one technique appears only on those."""
        rng = np.random.default_rng(11)
        rows, lures, tags = [], [], []
        rid = 0
        for n_baits, rate in ((1, 3.0), (2, 4.0), (3, 5.0)):
            for i in range(70):
                rows.append({"report_id": rid, "fish_per_hour": rng.normal(rate, .4),
                             "year": 2023 + (i % 3), "month": 5, "season": "spring"})
                for cat in ["soft_plastic", "jig", "crankbait"][:n_baits]:
                    lures.append({"report_id": rid, "category": cat,
                                  "subtype": "x", "color": None, "source": "field"})
                if n_baits == 3 and i % 2 == 0:
                    tags.append({"report_id": rid, "kind": "technique",
                                 "value": "rider", "detail": None})
                if i % 3 == 0:
                    tags.append({"report_id": rid, "kind": "technique",
                                 "value": "spread_evenly", "detail": None})
                rid += 1
        ev = {e["technique"]: e for e in technique_effects(
            pd.DataFrame(rows), pd.DataFrame(tags), pd.DataFrame(lures),
            min_trips=20, backed_min=30, check_years=False)}
        rider = ev.get("rider")
        assert rider is not None
        assert rider["naive_diff"] > 0.8, "the confound should be visible raw"
        assert abs(rider["diff"]) < rider["naive_diff"] / 2


class TestShape:
    def test_every_row_carries_its_interval(self, live):
        _c, trips, lures, tags = live
        for e in technique_effects(trips, tags, lures):
            assert e["lo"] <= e["diff"] <= e["hi"]
            assert e["trips"] >= 1 and e["label"]
            assert e["support"] in {"backed", "suggestive", "unproven",
                                    "unstable", "below", "thin"}

    def test_summary_groups_everything(self, live):
        _c, trips, lures, tags = live
        ev = technique_effects(trips, tags, lures)
        s = summary(ev)
        total = sum(len(s[k]) for k in
                    ("backed", "suggestive", "unproven", "unstable", "below", "thin"))
        assert total == len(ev)
        assert s["lead"]

    def test_per_lake_scoping_works(self, live):
        from pwf.technique import lake_technique_effects
        _c, trips, lures, tags = live
        lake = trips[trips.lake_known == 1]["lake"].value_counts().index[0]
        sel = trips[trips["lake"] == lake]
        ids = set(sel["report_id"])
        ev = lake_technique_effects(sel, tags[tags["report_id"].isin(ids)],
                                    lures[lures["report_id"].isin(ids)])
        for e in ev:
            assert e["stable"] is None, "per-lake results are not year-checked"
