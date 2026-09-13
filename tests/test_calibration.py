"""Effort calibration.

The naive assumption that an all-day trip is twice a half-day trip is wrong and
biased: measured, all-day anglers catch about 1.45x what half-day anglers catch,
not 2x. Dividing by eight hours understates them by roughly a quarter, and
because booking mix varies enormously by lake the error does not wash out - it
biases comparisons *between* lakes, which is what a recommender ranks.
"""
import pytest

from pwf.analysis import calibrate_effort, effort_hours
from pwf.config import DB_PATH, HALF_DAY_HOURS
from pwf.db import init


@pytest.fixture
def conn(tmp_path):
    return init(tmp_path / "t.sqlite")


def _seed(conn, n=200, half_fish=16, all_fish=24):
    rows = []
    for i in range(n):
        slot = "ALL_DAY" if i % 2 else ("AM" if i % 4 == 1 else "PM")
        fish = all_fish if slot == "ALL_DAY" else half_fish
        rows.append((i, slot, fish))
    conn.executemany(
        "INSERT INTO trips (report_id, time_slot, fish_total) VALUES (?,?,?)", rows)
    conn.commit()


class TestCalibrateEffort:
    def test_derives_all_day_hours_from_the_catch_ratio(self, conn):
        _seed(conn, n=400, half_fish=16, all_fish=24)
        stats = calibrate_effort(conn)
        assert stats["source"] == "measured"
        # 24/16 = 1.5x, so all-day effort is 4 x 1.5 = 6 hours, not 8.
        assert stats["hours"]["ALL_DAY"] == pytest.approx(6.0, abs=0.05)
        assert effort_hours(conn)["ALL_DAY"] == pytest.approx(6.0, abs=0.05)

    def test_falls_back_when_there_is_too_little_data(self, conn):
        _seed(conn, n=20)
        stats = calibrate_effort(conn)
        assert stats["source"] == "fallback"
        assert effort_hours(conn)["ALL_DAY"] == 8.0

    def test_refuses_an_implausible_ratio(self, conn):
        """An all-day trip catching 4x a half-day one means the data is wrong,
        not that anglers changed - keep the fallback rather than propagate it."""
        _seed(conn, n=400, half_fish=5, all_fish=20)
        assert calibrate_effort(conn)["source"] == "fallback"

    def test_half_day_hours_are_left_alone(self, conn):
        _seed(conn, n=400)
        hours = calibrate_effort(conn)["hours"]
        assert hours["AM"] == HALF_DAY_HOURS
        assert hours["PM"] == HALF_DAY_HOURS

    def test_records_its_reasoning(self, conn):
        _seed(conn, n=400)
        calibrate_effort(conn)
        note = conn.execute(
            "SELECT note FROM calibration WHERE key='all_day_hours'").fetchone()[0]
        assert "all-day" in note and "not 8.0" in note


class TestLiveCalibration:
    """Against the real database, the three slots must end up comparable."""

    def test_slots_converge(self):
        if not DB_PATH.exists():
            pytest.skip("no database yet")
        c = init(DB_PATH)
        rows = c.execute(
            "SELECT time_slot, AVG(fish_per_hour) FROM trips"
            " WHERE fish_per_hour IS NOT NULL GROUP BY time_slot").fetchall()
        if len(rows) < 3:
            pytest.skip("not enough slots")
        means = [r[1] for r in rows]
        spread = (max(means) - min(means)) / min(means)
        assert spread <= 0.10, (
            f"slot means differ by {spread:.0%}; the effort constant is biased "
            "and every between-lake comparison inherits it")

    def test_all_day_hours_were_measured_not_assumed(self):
        if not DB_PATH.exists():
            pytest.skip("no database yet")
        c = init(DB_PATH)
        row = c.execute(
            "SELECT value FROM calibration WHERE key='all_day_hours'").fetchone()
        if row is None:
            pytest.skip("not calibrated yet")
        assert 4.0 < row[0] < 8.0
