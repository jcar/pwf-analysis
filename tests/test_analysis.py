"""Analysis-layer tests on synthetic data, plus coverage regression floors."""
import pandas as pd
import pytest

from pwf import analysis as A
from pwf.db import init


@pytest.fixture
def conn(tmp_path):
    return init(tmp_path / "t.sqlite")


def _seed(conn, n_good=30, n_bad=30):
    conn.execute("INSERT INTO lakes (name, town, acres) VALUES ('Test Lake','Athens',12)")
    lake_id = conn.execute("SELECT lake_id FROM lakes").fetchone()[0]
    rows, lures = [], []
    for i in range(n_good + n_bad):
        good = i < n_good
        rows.append((i, lake_id, 1, f"2024-04-{(i % 28) + 1:02d}", 2024, 4, "spring",
                     "AM", "reservation", 4.0, 12 if good else 2,
                     (12 if good else 2) / 4.0, 3.0))
        lures.append((i, "x", "topwater" if good else "crankbait",
                      "frog" if good else "deep", None, "field"))
    conn.executemany(
        "INSERT INTO trips (report_id,lake_id,lake_known,trip_date,year,month,season,"
        "time_slot,trip_date_source,hours,fish_total,fish_per_hour,max_weight_lb)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.executemany(
        "INSERT INTO report_lures (report_id,raw,category,subtype,color,source)"
        " VALUES (?,?,?,?,?,?)", lures)
    conn.commit()
    return lake_id


class TestLureLift:
    def test_better_bait_gets_higher_lift(self, conn):
        _seed(conn)
        trips = A.trips_frame(conn)
        out = A.lure_lift(trips, A.lures_frame(conn))
        assert out.loc["topwater", "lift"] > 1.0
        assert out.loc["crankbait", "lift"] < 1.0
        assert out.index[0] == "topwater"

    def test_small_cells_are_shrunk_toward_baseline(self, conn):
        """A bait that went 1-for-1 must not outrank a well-sampled one."""
        _seed(conn, n_good=40, n_bad=40)
        conn.execute(
            "INSERT INTO trips (report_id,lake_id,lake_known,trip_date,year,month,"
            "season,time_slot,trip_date_source,hours,fish_total,fish_per_hour)"
            " VALUES (999,1,1,'2024-04-15',2024,4,'spring','AM','reservation',4,80,20.0)")
        conn.execute("INSERT INTO report_lures (report_id,raw,category,subtype,"
                     "color,source) VALUES (999,'x','spoon','spoon',NULL,'field')")
        conn.commit()
        out = A.lure_lift(A.trips_frame(conn), A.lures_frame(conn), min_n=1)
        # Raw rate is far higher, but one trip must not beat forty.
        assert out.loc["spoon", "raw_fph"] > out.loc["topwater", "raw_fph"]
        assert out.loc["spoon", "shrunk_fph"] < out.loc["spoon", "raw_fph"]
        # Shrinking the mean alone is not enough here - the standard-error
        # penalty on n=1 is what demotes the lucky trip.
        assert out.loc["spoon", "lift_lb"] < out.loc["topwater", "lift_lb"]
        assert out.index[0] == "topwater", "ranking must put the sampled bait first"

    def test_min_n_filters_thin_cells(self, conn):
        _seed(conn)
        out = A.lure_lift(A.trips_frame(conn), A.lures_frame(conn), min_n=1000)
        assert out.empty

    def test_every_row_reports_its_sample_size(self, conn):
        _seed(conn)
        out = A.lure_lift(A.trips_frame(conn), A.lures_frame(conn))
        assert (out["n_trips"] > 0).all()
        assert "baseline_fph" in out and "scored_trips" in out
        assert (out["lower_fph"] <= out["shrunk_fph"]).all()


class TestSimilarTrips:
    def test_month_distance_is_circular(self, conn):
        _seed(conn)
        trips = A.trips_frame(conn)
        trips.loc[:, "month"] = 12
        sim = A.similar_trips(trips, {"month": 1}, lake="Test Lake")
        # December to January is one month apart, not eleven.
        assert sim["similarity"].min() == pytest.approx(1.0)

    def test_ranks_closest_conditions_first(self, conn):
        _seed(conn)
        trips = A.trips_frame(conn)
        trips.loc[:, "temp_max_f"] = [60.0] * len(trips)
        trips.iloc[0, trips.columns.get_loc("temp_max_f")] = 80.0
        sim = A.similar_trips(trips, {"month": 4, "temp_max_f": 80.0},
                              lake="Test Lake")
        assert sim.iloc[0]["temp_max_f"] == 80.0


class TestFrames:
    def test_bands_are_derived(self, conn):
        _seed(conn)
        df = A.trips_frame(conn)
        assert {"cloud_band", "wind_band", "clarity_band", "acres_band"} <= set(df.columns)
        assert (df["acres_band"] == "small").all()

    def test_empty_database_does_not_crash(self, conn):
        assert A.trips_frame(conn).empty
        assert A.lure_lift(pd.DataFrame(), pd.DataFrame()).empty


class TestCoverageFloors:
    """Regression floors, set just under the values measured on the full
    13,672-report corpus. These only ever move up: a rule edit that drops one
    below its floor has lost recall, which is exactly what should fail a build.
    """

    FLOORS = {
        # full tier
        "lure_field_matched": 88.0,   # measured 92.1
        "lake": 85.0,                 # measured 89.1
        "lure_any": 82.0,             # measured 85.8
        "fish_count": 52.0,           # measured 55.7
        # partial tier - what members actually bothered to write down
        "narrative": 95.0,            # measured 99.0
        "bite_window": 55.0,          # measured 58.5
        "structure": 50.0,            # measured 53.8
        "technique": 32.0,            # measured 35.8
        "vegetation": 30.0,           # measured 32.5
        "clarity": 23.0,              # measured 25.4
        "depth": 14.0,                # measured 15.4
        "water_temp": 12.0,           # measured 13.3
    }

    def test_live_coverage_meets_floors(self):
        from pwf.config import DB_PATH
        if not DB_PATH.exists():
            pytest.skip("no database yet - run `pwf build`")
        conn = init(DB_PATH)
        df = A.coverage(conn)
        if df.empty:
            pytest.skip("coverage not computed yet - run `pwf build`")
        got = dict(zip(df["dimension"], df["pct"]))
        missing = [d for d in self.FLOORS if d not in got]
        assert not missing, f"coverage rows absent: {missing}"
        low = {d: got[d] for d, floor in self.FLOORS.items() if got[d] < floor}
        assert not low, f"coverage regressed: {low}"

    def test_catch_rate_denominator_is_stated(self):
        """Catch rates rest on the reports that gave a countable number, which
        is barely half of them. If that is ever silently assumed to be all
        reports, every rate on the page is inflated."""
        from pwf.config import DB_PATH
        if not DB_PATH.exists():
            pytest.skip("no database yet")
        conn = init(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM trips WHERE fish_per_hour IS NOT NULL").fetchone()[0]
        if not total:
            pytest.skip("no trips yet")
        assert scored < total, "scored trips must be a strict subset"
        df = A.trips_frame(conn)
        out = A.lure_lift(df, A.lures_frame(conn))
        if not out.empty:
            assert int(out["scored_trips"].iloc[0]) == scored
