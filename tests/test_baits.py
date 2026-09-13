"""Bait evidence.

The claim being tested is narrow and specific: a bait's apparent edge must be
measured against equally-documented trips, because members who name more baits
catch more fish. Without that matching, nearly every bait at nearly every lake
scored above its own lake's average - which cannot be true of all of them.
"""
import numpy as np
import pandas as pd
import pytest

from pwf import analysis as A
from pwf.baits import (BACKED_MIN_TRIPS, _classify, bait_detail, bait_evidence,
                       recommendation)
from pwf.config import DB_PATH
from pwf.db import init


def _frame(rates, ids=None, month=5, season="spring"):
    n = len(rates)
    ids = ids if ids is not None else list(range(n))
    return pd.DataFrame({"report_id": ids, "fish_per_hour": rates,
                         "month": [month] * n, "season": [season] * n,
                         "year": [2025] * n})


def _lures(pairs):
    return pd.DataFrame(
        [{"report_id": r, "category": c, "subtype": s, "color": None,
          "source": "field"} for r, c, s in pairs])


class TestConfoundRemoval:
    def test_a_bait_that_only_rides_busy_trips_is_not_credited(self):
        """Construct the confound deliberately: trips naming more baits catch
        more, and one bait appears only on those. Its naive edge is large; the
        matched estimate should be roughly nothing."""
        rng = np.random.default_rng(5)
        rows, pairs = [], []
        rid = 0
        for n_baits, rate in ((1, 3.0), (2, 4.0), (3, 5.0)):
            for i in range(60):
                rows.append(rng.normal(rate, 0.4))
                cats = ["soft_plastic", "jig", "crankbait"][:n_baits]
                # "rider" appears only on busy trips, but on just half of them,
                # so its own stratum still contains trips to compare against.
                if n_baits == 3 and i % 2 == 0:
                    cats = ["rider", "jig", "crankbait"]
                for cat in cats:
                    pairs.append((rid, cat, "x"))
                rid += 1
        trips = _frame(rows, ids=list(range(rid)))
        ev = {e["bait"]: e for e in bait_evidence(trips, _lures(pairs))}
        rider = ev.get("rider")
        assert rider is not None
        # Naive comparison sees the whole busy-trip effect.
        assert rider["naive_diff"] > 1.0
        # Matched on how many baits the trip named, it should be far smaller.
        assert abs(rider["diff"]) < rider["naive_diff"] / 2

    def test_live_data_is_not_uniformly_positive(self):
        """Before matching, almost every bait at every lake beat its own lake's
        average. That is the signature of the confound, and it should be gone."""
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        trips, lures = A.trips_frame(conn), A.lures_frame(conn)
        naive_pos = matched_pos = total = 0
        for lake in trips[trips.lake_known == 1]["lake"].value_counts().index[:25]:
            sel = trips[trips["lake"] == lake]
            ev = bait_evidence(sel, lures[lures["report_id"].isin(sel["report_id"])])
            for e in ev:
                if e["diff"] is None or e["naive_diff"] is None:
                    continue
                total += 1
                naive_pos += e["naive_diff"] > 0
                matched_pos += e["diff"] > 0
        if total < 40:
            pytest.skip("not enough comparisons")
        assert naive_pos / total > 0.6, "expected the naive bias to be visible"
        assert matched_pos / total < naive_pos / total, (
            "matching should remove some of the across-the-board positivity")


class TestSupportLabels:
    @pytest.mark.parametrize("diff,lo,hi,n,expected", [
        (2.0, 0.5, 3.5, 40, "backed"),
        (2.0, 0.5, 3.5, 8, "thin"),            # excludes zero, but far too few trips
        (0.3, -0.1, 0.7, 30, "suggestive"),    # near miss, well sampled
        (0.3, -0.1, 0.7, 8, "unproven"),       # near miss, thin -> no credit
        (0.4, -2.0, 2.8, 30, "unproven"),
        (-1.5, -2.6, -0.4, 30, "below"),
        (5.0, 1.0, 9.0, 3, "thin"),
    ])
    def test_classify(self, diff, lo, hi, n, expected):
        assert _classify(diff, lo, hi, n) == expected

    def test_backed_requires_a_real_sample(self):
        from pwf.baits import SUGGESTIVE_MIN_TRIPS
        assert _classify(2.0, 0.5, 3.5, BACKED_MIN_TRIPS) == "backed"
        assert _classify(2.0, 0.5, 3.5, BACKED_MIN_TRIPS - 1) == "suggestive"
        assert _classify(2.0, 0.5, 3.5, SUGGESTIVE_MIN_TRIPS - 1) == "thin"


class TestOutputShape:
    def test_every_row_carries_its_interval_and_sample(self):
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        trips, lures = A.trips_frame(conn), A.lures_frame(conn)
        lake = trips[trips.lake_known == 1]["lake"].value_counts().index[0]
        sel = trips[trips["lake"] == lake]
        ev = bait_evidence(sel, lures[lures["report_id"].isin(sel["report_id"])])
        assert ev
        for e in ev:
            assert e["trips"] >= 1 and e["rate"] is not None
            assert e["support"] in {"backed", "suggestive", "unproven",
                                    "below", "thin"}
            if e["diff"] is not None:
                assert e["lo"] <= e["diff"] <= e["hi"], e

    def test_interval_always_brackets_the_estimate(self):
        """A point estimate outside its own interval would mean the arithmetic
        is wrong, and the whole display rests on it."""
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        trips, lures = A.trips_frame(conn), A.lures_frame(conn)
        for lake in trips[trips.lake_known == 1]["lake"].value_counts().index[:20]:
            sel = trips[trips["lake"] == lake]
            for e in bait_evidence(sel, lures[lures["report_id"].isin(sel["report_id"])]):
                if e["diff"] is not None:
                    assert e["lo"] < e["hi"]
                    assert e["lo"] <= e["diff"] <= e["hi"]

    def test_recommendation_groups_everything_once(self):
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        trips, lures = A.trips_frame(conn), A.lures_frame(conn)
        lake = trips[trips.lake_known == 1]["lake"].value_counts().index[0]
        sel = trips[trips["lake"] == lake]
        ev = bait_evidence(sel, lures[lures["report_id"].isin(sel["report_id"])])
        rec = recommendation(ev)
        grouped = sum(len(rec[k]) for k in
                      ("backed", "suggestive", "unproven", "below", "thin"))
        assert grouped == len(ev)
        assert rec["lead"]

    def test_lead_never_rests_on_a_handful_of_trips(self):
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        trips, lures = A.trips_frame(conn), A.lures_frame(conn)
        for lake in trips[trips.lake_known == 1]["lake"].value_counts().index[:20]:
            sel = trips[trips["lake"] == lake]
            ev = bait_evidence(sel, lures[lures["report_id"].isin(sel["report_id"])])
            if not ev:
                continue
            rec = recommendation(ev)
            import re as _re
            named = [e for e in ev
                     if _re.search(rf"(?<![\w ]){_re.escape(e['bait'].replace('_', ' '))}"
                                   rf"(?![\w])", rec["lead"])]
            for e in named:
                assert e["trips"] >= 12, f"{lake}: {e['bait']} on {e['trips']} trips"

    def test_detail_is_attached_only_where_it_matters(self):
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        from pwf.profile import lake_profile
        trips, lures = A.trips_frame(conn), A.lures_frame(conn)
        lake = trips[trips.lake_known == 1]["lake"].value_counts().index[0]
        p = lake_profile(conn, lake, trips=trips, lures=lures)
        for e in p["baits"]["evidence"]:
            if e["support"] in ("backed", "suggestive"):
                assert "detail" in e

    def test_bait_detail_shape(self):
        trips = _frame([4.0, 5.0, 6.0, 3.0, 7.0, 5.5])
        lures = _lures([(i, "topwater", "frog") for i in range(6)])
        d = bait_detail(trips, lures, "topwater")
        assert d["subtypes"][0]["value"] == "frog"
        assert d["from_field"] == 6


class TestEstimatorExtraction:
    """The stratified estimator moved to pwf/effect.py so techniques could use
    it. These pin that the move was behaviour-preserving and that baits still
    route through the shared code rather than a drifting copy."""

    def test_baits_uses_the_shared_estimator(self):
        import inspect

        import pwf.baits as b
        src = inspect.getsource(b)
        assert "from .effect import" in src
        assert "def _stratified_diff" not in src, "a local copy has come back"

    def test_shared_estimator_reproduces_a_hand_computation(self):
        import numpy as np
        import pandas as pd

        from pwf.effect import stratified_effect
        rng = np.random.default_rng(4)
        idx = list(range(120))
        rates = pd.Series(rng.normal(5, 1.5, 120), index=idx)
        strata = pd.Series([0] * 60 + [1] * 60, index=idx)
        used = rates.loc[list(range(0, 60, 2)) + list(range(60, 120, 2))]
        other = rates.drop(index=used.index)
        got = stratified_effect(used, other, strata)
        assert got is not None
        diff, se, n = got
        # Recompute the inverse-variance combination independently.
        parts = []
        for k in (0, 1):
            u = used[strata.reindex(used.index) == k]
            o = other[strata.reindex(other.index) == k]
            v = u.var(ddof=1) / len(u) + o.var(ddof=1) / len(o)
            parts.append((u.mean() - o.mean(), 1 / v))
        w = np.array([p[1] for p in parts])
        d = np.array([p[0] for p in parts])
        assert diff == pytest.approx(float((w * d).sum() / w.sum()))
        assert se == pytest.approx(float(np.sqrt(1 / w.sum())))
        assert n == len(used)


class TestYearStability:
    """The same filter techniques use, applied to baits.

    It matters less here - on the whole archive only one club-wide verdict
    changes, where two techniques flipped - and the important part is where it
    deliberately does *not* apply.
    """

    def _live(self):
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        return conn, A.trips_frame(conn), A.lures_frame(conn)

    def test_club_stability_finds_the_erratic_baits(self):
        from pwf.baits import club_stability
        _c, trips, lures = self._live()
        st = club_stability(trips, lures)
        assert st, "no club stability computed"
        unstable = {k for k, v in st.items() if v["stable"] is False}
        assert unstable, "the check found nothing - it is doing no work"
        for bait in unstable:
            v = st[bait]
            assert v["agreeing"] / v["years"] < 2 / 3

    def test_club_instability_never_changes_a_lake_verdict(self):
        """A bait that cannot hold its sign across ninety lakes is not thereby
        wrong about one of them. The club verdict is a caveat, not a demotion -
        folding it in would erase real local evidence."""
        from pwf.baits import bait_evidence, club_stability
        _c, trips, lures = self._live()
        st = club_stability(trips, lures)
        for lake in trips[trips.lake_known == 1]["lake"].value_counts().index[:25]:
            sel = trips[trips["lake"] == lake]
            ml = lures[lures["report_id"].isin(sel["report_id"])]
            plain = {e["bait"]: e["support"] for e in bait_evidence(sel, ml)}
            withst = bait_evidence(sel, ml, stability=st)
            for e in withst:
                assert e["support"] == plain[e["bait"]], (
                    f"{lake}/{e['bait']} changed verdict on club-wide grounds")

    def test_the_caveat_is_carried_instead(self):
        from pwf.baits import bait_evidence, club_stability
        _c, trips, lures = self._live()
        st = club_stability(trips, lures)
        unstable = {k for k, v in st.items() if v["stable"] is False}
        if not unstable:
            pytest.skip("nothing unstable club-wide")
        seen = 0
        for lake in trips[trips.lake_known == 1]["lake"].value_counts().index[:25]:
            sel = trips[trips["lake"] == lake]
            ml = lures[lures["report_id"].isin(sel["report_id"])]
            for e in bait_evidence(sel, ml, stability=st):
                if e["bait"] in unstable:
                    assert e["club_unstable"] is True
                    seen += 1
                else:
                    assert e["club_unstable"] is False
        assert seen, "no flagged rows found"

    def test_a_lake_with_its_own_year_record_can_still_demote_itself(self):
        """Local evidence outranks the club caveat in both directions."""
        import numpy as np
        import pandas as pd

        from pwf.baits import bait_evidence
        rng = np.random.default_rng(9)
        rows, pairs = [], []
        rid = 0
        # Strongly positive in five years, negative in three. The pooled effect
        # clears zero, so without the year check it reads as backed - which is
        # exactly the failure mode the check exists to catch.
        bad_years = {2020, 2023, 2026}
        for year in range(2019, 2027):
            for i in range(40):
                uses = i % 2 == 0
                if not uses:
                    base = 4.0
                elif year in bad_years:
                    base = 2.5
                else:
                    base = 6.5
                rows.append({"report_id": rid, "fish_per_hour": rng.normal(base, .5),
                             "year": year, "month": 5, "season": "spring"})
                pairs.append({"report_id": rid, "category":
                              "flipflop" if uses else "steady",
                              "subtype": "x", "color": None, "source": "field"})
                rid += 1
        ev = {e["bait"]: e for e in bait_evidence(
            pd.DataFrame(rows), pd.DataFrame(pairs))}
        ff = ev.get("flipflop")
        assert ff is not None
        assert ff["years"] >= 3, "the local year check should have run"
        assert ff["support"] == "unstable", ff["support"]
