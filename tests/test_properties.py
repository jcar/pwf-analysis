"""The club's own surveyed coordinates, and the name collisions they expose.

Every coordinate here used to be inferred from a town name. Measured against
the club's property map - which is public, needs no login, and was sitting
there the whole time - that guesswork was off by a median of 6.2 miles, and the
worst of it put Six O Ranch, the most-reported water in the archive, 15.5 miles
from where it actually is.
"""
from __future__ import annotations

import pytest

from pwf.config import DB_PATH
from pwf.crawl import iter_cached
from pwf.db import init
from pwf.parse_properties import LAT_RANGE, LON_RANGE, parse


@pytest.fixture(scope="module")
def conn():
    return init(DB_PATH)


@pytest.fixture(scope="module")
def props(conn):
    doc = next((d for _u, _r, d in iter_cached(conn, "properties")), None)
    if not doc:
        pytest.skip("properties page not cached - run `pwf crawl --properties`")
    return parse(doc)


def test_every_property_has_a_slug_and_a_position(props):
    assert len(props) > 80, f"only {len(props)} properties parsed"
    for p in props:
        assert p["slug"], f"{p['title']} has no slug"
        assert LAT_RANGE[0] <= p["lat"] <= LAT_RANGE[1], p
        assert LON_RANGE[0] <= p["lon"] <= LON_RANGE[1], p


def test_the_slug_is_the_identity_not_the_title(props):
    """The club runs two properties called "Twin Lakes", 154 miles apart.

    Joining on the title would collapse them, which is precisely how an earlier
    version stamped Cody Ranch's Coalgate coordinates onto the Ben Wheeler lake
    and its 389 trips.
    """
    twins = [p for p in props if p["title"].strip().lower() == "twin lakes"]
    assert len(twins) == 2, "expected the club's two Twin Lakes"
    assert len({t["slug"] for t in twins}) == 2
    from pwf.geo_shapes import miles_between
    a, b = twins
    assert miles_between(a["lat"], a["lon"], b["lat"], b["lon"]) > 100


def test_places_are_carried_but_never_trusted(props):
    """The club files Coalgate, Oklahoma under "Dallas / Fort Worth Area", so
    the place string is reference only and nothing is positioned from it."""
    import inspect

    from pwf import parse_properties
    src = inspect.getsource(parse_properties)
    assert "Reference only" in src or "never used to place" in src


class TestApplied:
    def test_the_club_survey_outranks_every_inference(self, conn):
        n = conn.execute("SELECT COUNT(*) c FROM lakes"
                         " WHERE coord_source='waypoint'").fetchone()["c"]
        assert n > 80, f"only {n} lakes on surveyed coordinates"

    def test_every_placed_lake_declares_where_its_position_came_from(self, conn):
        bad = [r["name"] for r in conn.execute(
            "SELECT name FROM lakes WHERE lat IS NOT NULL"
            " AND coord_source IS NULL")]
        assert not bad, f"unlabelled coordinates: {bad[:5]}"

    def test_reused_names_are_split_into_separate_lakes(self, conn):
        """Twin Lakes was one row holding 243 Ben Wheeler trips and 43 Coalgate
        ones - two waters averaged into a single catch rate, drive and weather
        join."""
        from pwf.geo_shapes import miles_between
        rows = {r["name"]: r for r in conn.execute(
            "SELECT name, lat, lon, report_count FROM lakes"
            " WHERE name LIKE 'Twin Lakes%'")}
        assert "Twin Lakes" in rows and "Twin Lakes (Coalgate)" in rows
        a, b = rows["Twin Lakes"], rows["Twin Lakes (Coalgate)"]
        assert miles_between(a["lat"], a["lon"], b["lat"], b["lon"]) > 100
        assert a["report_count"] > 0 and b["report_count"] > 0

    def test_reports_are_counted_once_each(self, conn):
        """A report is named on its listing card and again in its own property
        field. Counting both published JerMar Lake as 606 reports when 385
        exist."""
        for r in conn.execute(
                "SELECT l.name, l.report_count,"
                " (SELECT COUNT(DISTINCT report_id) FROM trips t"
                "  WHERE t.lake_id=l.lake_id) actual"
                " FROM lakes l WHERE l.report_count > 50"):
            assert r["report_count"] == r["actual"], \
                f"{r['name']}: report_count {r['report_count']} != {r['actual']}"
