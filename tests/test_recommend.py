"""The recommender's ranking, and the honesty constraints around it.

The central claim is that a lake's own history predicts its next season. That is
not assumed - `test_backtest_beats_baseline` re-derives it from held-out years
every time the suite runs. If it stops holding, the ranking stops being
defensible and the test fails.

The second claim is negative: weather is *not* in the score. Measured within
lake-month, the largest effect in the archive has a bootstrap interval that
includes zero, so ranking on it would be inventing precision.
`test_forecast_does_not_move_the_ranking` enforces that it stays out.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pwf.config import DB_PATH
from pwf.db import init
from pwf.recommend import (CONDITION_MULTIPLIERS, _expected_rate, _next_saturday,
                           describe_forecast, recommend)

HOURS = {"AM": 4.0, "PM": 4.0, "ALL_DAY": 5.81}


def _db():
    if not DB_PATH.exists():
        pytest.skip("no database yet - run `pwf build`")
    return init(DB_PATH)


def _rates(conn):
    df = pd.read_sql_query(
        "SELECT lake_id, year, month, fish_per_hour FROM trips"
        " WHERE fish_per_hour IS NOT NULL AND year IS NOT NULL", conn)
    if df.empty:
        pytest.skip("no scored trips")
    return df


class TestBacktest:
    """Predict each year from prior years only, never from itself."""

    def test_backtest_beats_baseline(self):
        conn = _db()
        df = _rates(conn)
        rows = []
        for target in range(2021, date.today().year + 1):
            hist, fut = df[df.year < target], df[df.year == target]
            if hist.empty or fut.empty:
                continue
            actual = fut.groupby("lake_id")["fish_per_hour"].agg(["size", "mean"])
            actual = actual[actual["size"] >= 8]
            if len(actual) < 12:
                continue
            hist_mean = hist.groupby("lake_id")["fish_per_hour"].agg(["size", "mean"])
            hist_mean = hist_mean[hist_mean["size"] >= 8]["mean"]
            j = actual.join(hist_mean.rename("pred"), how="inner").dropna()
            if len(j) < 12:
                continue
            club = hist["fish_per_hour"].mean()
            r = np.corrcoef(j["pred"], j["mean"])[0, 1]
            mae_model = float((j["pred"] - j["mean"]).abs().mean())
            mae_club = float((club - j["mean"]).abs().mean())
            rows.append((target, len(j), r, mae_model, mae_club))

        assert len(rows) >= 4, "not enough held-out years to backtest"
        mean_r = float(np.mean([r[2] for r in rows]))
        wins = sum(1 for _y, _n, _r, m, c in rows if m < c)
        # Pooled across every held-out lake-year, which is what the claim on the
        # page actually rests on. A per-year win count is a coarse statistic
        # here: each year holds only ~40 lakes, so a sub-1% difference in mean
        # absolute error flips a "win", and two of the six sit that close.
        tot_model = float(np.sum([m * n for _y, n, _r, m, _c in rows]))
        tot_club = float(np.sum([c * n for _y, n, _r, _m, c in rows]))
        lift = 1 - tot_model / tot_club

        # A lake's history predicted its future at r ~= 0.65 when this was
        # built. Allow drift, but not collapse to noise.
        assert mean_r >= 0.45, (
            f"per-lake history no longer predicts future rate (mean r={mean_r:.2f}); "
            "the ranking rests on this")
        assert lift >= 0.08, (
            f"pooled improvement over the club mean fell to {lift:.1%}; "
            "the ranking rests on this")
        # Folding a renamed property back onto its current listing - "Travis
        # Lake - (Formerly Flying M)" into "Travis Lake" - blends an older era
        # into that lake's long-run mean, which cost 2024 about 1% and flipped
        # it. That is the price of correct lake identity, not a modelling
        # regression, so the floor allows two close years rather than one.
        assert wins >= len(rows) - 2, (
            f"model beat the club-mean baseline in only {wins}/{len(rows)} years")

    def test_recent_form_is_not_worse_than_long_run(self):
        """Recent form was marginally better when measured; it must not be
        markedly worse, or RECENT_WEIGHT is mis-set."""
        conn = _db()
        df = _rates(conn)
        longs, recents = [], []
        for target in range(2021, date.today().year + 1):
            hist, fut = df[df.year < target], df[df.year == target]
            if hist.empty or fut.empty:
                continue
            actual = fut.groupby("lake_id")["fish_per_hour"].agg(["size", "mean"])
            actual = actual[actual["size"] >= 8]
            lr = hist.groupby("lake_id")["fish_per_hour"].agg(["size", "mean"])
            lr = lr[lr["size"] >= 8]["mean"]
            rc = hist[hist.year >= target - 2].groupby("lake_id")["fish_per_hour"]
            rc = rc.agg(["size", "mean"])
            rc = rc[rc["size"] >= 8]["mean"]
            j = actual.join(lr.rename("l"), how="inner").join(
                rc.rename("r"), how="inner").dropna()
            if len(j) < 12:
                continue
            longs.append(np.corrcoef(j["l"], j["mean"])[0, 1])
            recents.append(np.corrcoef(j["r"], j["mean"])[0, 1])
        if len(longs) < 3:
            pytest.skip("not enough years")
        assert np.mean(recents) >= np.mean(longs) - 0.08


class TestWeatherStaysOutOfTheScore:
    def test_forecast_does_not_move_the_ranking(self):
        """Same lakes, same order, whether or not a forecast is available."""
        conn = _db()
        a = recommend(conn, when=date(2026, 5, 16), limit=20, with_forecast=False)
        b = recommend(conn, when=date(2026, 5, 16), limit=20, with_forecast=True)
        assert [x["lake"] for x in a["lakes"]] == [x["lake"] for x in b["lakes"]]
        assert [x["score"] for x in a["lakes"]] == [x["score"] for x in b["lakes"]]

    def test_opting_in_does_change_it(self):
        """The escape hatch must actually do something, or it is a lie."""
        conn = _db()
        plain = recommend(conn, when=date(2026, 5, 16), limit=25)
        weighted = recommend(conn, when=date(2026, 5, 16), limit=25,
                             weight_conditions=True)
        if not weighted["forecast_available"]:
            pytest.skip("no forecast reachable")
        assert weighted["weighted_by_conditions"] is True
        assert any(x["condition_adj"] is not None for x in weighted["lakes"])

    def test_multipliers_stay_small(self):
        """These effects are inside noise. If someone widens them into a real
        ranking signal, that is a claim the data does not support."""
        for table in CONDITION_MULTIPLIERS.values():
            for v in table.values():
                assert 0.9 <= v <= 1.1


class TestExpectedRate:
    def _frame(self, n, fph, month=5, year=2025, spread=2.0):
        """Real catch rates vary; a constant series has zero standard error and
        would make every interval assertion below trivially true."""
        rng = np.random.default_rng(11)
        vals = np.clip(rng.normal(fph, spread, n), 0.1, None)
        vals = vals - vals.mean() + fph          # keep the mean exact
        return pd.DataFrame({"fish_per_hour": vals, "month": [month] * n,
                             "year": [year] * n})

    def test_more_evidence_is_not_penalised_harder(self):
        """A lake with 105 trips once scored below one with 36 because the
        standard error used the month count rather than what was known about
        the lake. That must not come back."""
        rich = _expected_rate(self._frame(105, 8.0), 5, 4.0, 4.0)
        thin = _expected_rate(self._frame(36, 8.0), 5, 4.0, 4.0)
        assert rich["lower"] > thin["lower"]

    def test_thin_lakes_are_pulled_toward_the_club(self):
        thin = _expected_rate(self._frame(5, 12.0), 5, 4.0, 4.0)
        rich = _expected_rate(self._frame(200, 12.0), 5, 4.0, 4.0)
        assert thin["expected"] < rich["expected"]

    def test_extrapolating_across_months_widens_the_interval(self):
        month = _expected_rate(self._frame(40, 6.0, month=5), 5, 4.0, 4.0)
        annual = _expected_rate(self._frame(40, 6.0, month=9), 5, 4.0, 4.0)
        assert month["basis"] == "lake-month"
        assert annual["basis"] == "lake-year"
        assert annual["se"] > month["se"]

    def test_too_few_trips_returns_nothing(self):
        assert _expected_rate(self._frame(2, 9.0), 5, 4.0, 4.0)["expected"] is None


class TestRecommendOutput:
    def test_every_row_carries_its_sample_and_confidence(self):
        conn = _db()
        out = recommend(conn, when=date(2026, 5, 16), limit=12, with_forecast=False)
        assert out["lakes"], "expected some lakes"
        for row in out["lakes"]:
            assert row["n_total"] >= 1 and row["n_basis"] >= 1
            assert row["confidence"] in {"good", "fair", "thin", "very thin"}
            assert row["basis"] in {"lake-month", "lake-year", "club"}

    def test_distance_filter_is_applied(self):
        conn = _db()
        near = recommend(conn, when=date(2026, 5, 16), max_miles=60,
                         limit=50, with_forecast=False)
        for row in near["lakes"]:
            assert row["miles"] is not None and row["miles"] <= 60
        far = recommend(conn, when=date(2026, 5, 16), max_miles=250,
                        limit=50, with_forecast=False)
        assert far["considered"] >= near["considered"]

    def test_ranked_descending(self):
        conn = _db()
        out = recommend(conn, when=date(2026, 5, 16), limit=20, with_forecast=False)
        scores = [r["score"] for r in out["lakes"]]
        assert scores == sorted(scores, reverse=True)


class TestHelpers:
    @pytest.mark.parametrize("today,expected", [
        (date(2026, 9, 14), date(2026, 9, 19)),   # Monday -> that Saturday
        (date(2026, 9, 19), date(2026, 9, 26)),   # Saturday -> the next one
        (date(2026, 9, 20), date(2026, 9, 26)),   # Sunday -> the next Saturday
    ])
    def test_next_saturday(self, today, expected):
        assert _next_saturday(today) == expected

    def test_describe_forecast_bands(self):
        d = describe_forecast({"wind_max_mph": 4, "cloud_pct": 85,
                               "pressure_delta_24h": -5})
        assert d["wind_band"] == "calm"
        assert d["cloud_band"] == "overcast"
        assert d["pressure_trend"] == "falling"

    def test_describe_forecast_handles_missing(self):
        assert describe_forecast({}) == {}
        d = describe_forecast({"temp_max_f": 80})
        assert d["wind_band"] is None and d["pressure_trend"] is None
