"""Lake consistency - and the constraint that it must not leak into ranking.

Two measured facts govern this module. A lake's average says nothing about its
spread (r=+0.04), so volatility is real information. But past volatility barely
predicts future volatility (r~0.20, against r~0.65 for the catch rate), so it is
history and must never be scored.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pwf import analysis as A
from pwf.config import DB_PATH
from pwf.consistency import (BUST_FISH, club_bust_rate, describe,
                             lake_consistency, volatility_band)
from pwf.db import init
from pwf.recommend import recommend


@pytest.fixture(scope="module")
def live():
    if not DB_PATH.exists():
        pytest.skip("no database")
    conn = init(DB_PATH)
    trips = A.trips_frame(conn)
    if trips.empty:
        pytest.skip("no trips")
    return conn, trips


class TestDoesNotAffectRanking:
    """The whole point of showing it as a column rather than folding it in."""

    def test_ranking_is_identical_with_the_columns_present(self, live):
        conn, _ = live
        out = recommend(conn, when=date(2026, 5, 16), limit=25,
                        with_forecast=False)
        assert out["lakes"]
        assert any(L.get("consistency") for L in out["lakes"]), \
            "consistency should be attached"
        scores = [L["score"] for L in out["lakes"]]
        assert scores == sorted(scores, reverse=True)

    def test_order_follows_score_not_steadiness(self, live):
        """A steadier lake must not outrank a better one just for being steady."""
        conn, _ = live
        out = recommend(conn, when=date(2026, 5, 16), limit=30,
                        with_forecast=False)
        rows = [L for L in out["lakes"] if (L.get("consistency") or {}).get("cv")]
        if len(rows) < 6:
            pytest.skip("not enough rows")
        by_score = [L["lake"] for L in sorted(rows, key=lambda r: -r["score"])]
        assert [L["lake"] for L in rows] == by_score


class TestMeasures:
    def test_volatility_is_independent_of_the_average(self, live):
        """If these ever collapse together, the column stops adding anything."""
        _c, trips = live
        cons = lake_consistency(trips)
        cons.pop("__club_bust__", None)
        rows = [(v["mean"], v["cv"]) for v in cons.values()
                if v["mean"] and v["cv"]]
        if len(rows) < 25:
            pytest.skip("not enough lakes")
        means, cvs = zip(*rows)
        r = abs(np.corrcoef(means, cvs)[0, 1])
        assert r < 0.35, f"volatility now tracks the mean (r={r:.2f})"

    def test_bust_rate_largely_restates_the_average(self, live):
        """Documented so nobody presents it as independent evidence."""
        _c, trips = live
        cons = lake_consistency(trips)
        cons.pop("__club_bust__", None)
        rows = [(v["mean"], v["bust_rate"]) for v in cons.values()
                if v["mean"] and v["bust_rate"] is not None]
        if len(rows) < 25:
            pytest.skip("not enough lakes")
        means, busts = zip(*rows)
        assert np.corrcoef(means, busts)[0, 1] < -0.3

    def test_club_bust_rate_is_plausible(self, live):
        _c, trips = live
        rate = club_bust_rate(trips)
        assert rate is not None and 2 < rate < 25

    @pytest.mark.parametrize("cv,band", [
        (0.5, "steady"), (0.7, "steady"), (0.85, "typical"),
        (1.2, "swingy"), (None, None),
    ])
    def test_bands(self, cv, band):
        assert volatility_band(cv) == band

    def test_every_entry_carries_its_sample(self, live):
        _c, trips = live
        cons = lake_consistency(trips)
        cons.pop("__club_bust__", None)
        for name, v in cons.items():
            assert v["trips"] >= 20
            if v["bust_rate"] is not None:
                assert v["bust_n"] >= 1


class TestDescribe:
    def test_sentence_mentions_the_club_comparison(self, live):
        _c, trips = live
        cons = lake_consistency(trips)
        cons.pop("__club_bust__", None)
        club = club_bust_rate(trips)
        name = next(iter(cons))
        s = describe(cons[name], club)
        assert s and s.endswith(".")
        assert "club" in s

    def test_survives_a_sparse_entry(self):
        assert describe({}, None) is None
        entry = {"typical_fish": None, "worst_decile": None, "bust_rate": None,
                 "band": "typical"}
        assert describe(entry, None) is None

    def test_a_swingy_lake_says_so(self):
        entry = {"typical_fish": 20, "worst_decile": 0.5, "bust_rate": 15.0,
                 "band": "swingy"}
        s = describe(entry, 8.7)
        assert "swingier" in s and "15%" in s and "above" in s
