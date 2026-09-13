"""The booking brief, the map, and the receipts.

This module adds no statistics, so the tests are mostly about agreement: the
brief must equal its sources, the citations must be real trips, and the map must
agree with the drive column. A map whose rings contradicted the mileage would be
worse than no map.
"""
import math
from datetime import date

import pytest

from pwf import analysis as A
from pwf.brief import (SLOT_NOTE, evidence_trips, next_weekend, report_url,
                       trip_brief)
from pwf.config import DB_PATH
from pwf.consistency import lake_consistency
from pwf.db import init
from pwf.geo_shapes import RINGS_MILES, load, make_projection, miles_between
from pwf.recommend import recommend


@pytest.fixture(scope="module")
def live():
    if not DB_PATH.exists():
        pytest.skip("no database - run `pwf build`")
    conn = init(DB_PATH)
    trips = A.trips_frame(conn)
    if trips.empty:
        pytest.skip("no trips")
    return conn, trips, A.lures_frame(conn)


def _busiest(trips, k=6):
    return trips[trips.lake_known == 1]["lake"].value_counts().index[:k].tolist()


class TestBriefMatchesItsSources:
    def test_expected_rate_equals_the_shortlist(self, live):
        """The brief must present the ranking, not quietly re-score it."""
        conn, _t, _l = live
        sat = next_weekend()[0]
        rec = recommend(conn, when=sat, max_miles=200, limit=8,
                        with_forecast=False)
        for row in rec["lakes"][:5]:
            b = trip_brief(conn, row["lake"], sat)
            assert b["expected"]["fph"] == row["expected_fph"], row["lake"]
            assert b["expected"]["basis"] == row["basis"]
            assert b["expected"]["n_total"] == row["n_total"]

    def test_consistency_equals_the_module(self, live):
        conn, trips, _l = live
        cons = lake_consistency(trips)
        for lake in _busiest(trips, 5):
            if lake not in cons:
                continue
            b = trip_brief(conn, lake, next_weekend()[0])
            for key in ("typical_fish", "worst_decile", "bust_rate", "cv", "band"):
                assert b["expect"][key] == cons[lake][key], f"{lake}/{key}"

    def test_baits_equal_bait_evidence(self, live):
        from pwf.baits import bait_evidence, club_stability
        conn, trips, lures = live
        st = club_stability(trips, lures)
        lake = _busiest(trips, 1)[0]
        sel = trips[trips["lake"] == lake]
        direct = bait_evidence(sel, lures[lures.report_id.isin(sel.report_id)],
                               stability=st)
        b = trip_brief(conn, lake, next_weekend()[0])
        flat = []
        for key in ("backed", "suggestive", "unproven", "below", "thin", "unstable"):
            flat += b["plan"]["baits"].get(key) or []
        assert len(flat) == len(direct)
        by = {e["bait"]: e for e in direct}
        for e in flat:
            assert e["diff"] == by[e["bait"]]["diff"]

    def test_slot_note_is_present_and_honest(self, live):
        conn, trips, _l = live
        b = trip_brief(conn, _busiest(trips, 1)[0], next_weekend()[0])
        assert b["plan"]["slot_note"] == SLOT_NOTE
        assert "wash" in SLOT_NOTE and "all-day" in SLOT_NOTE.lower()


class TestCitationsAreReal:
    def test_every_cited_trip_exists_and_belongs_to_the_lake(self, live):
        conn, trips, _l = live
        for lake in _busiest(trips, 5):
            b = trip_brief(conn, lake, next_weekend()[0])
            ids_at_lake = set(trips[trips["lake"] == lake]["report_id"])
            for bait, cites in b["citations"].items():
                for rid, when, fish in cites:
                    assert rid in ids_at_lake, f"{lake}/{bait}: {rid} is elsewhere"
                    row = conn.execute(
                        "SELECT trip_date, fish_total FROM trips WHERE report_id=?",
                        (rid,)).fetchone()
                    assert row is not None
                    assert row["trip_date"] == when
                    if fish is not None:
                        assert int(row["fish_total"]) == fish

    def test_citations_carry_no_text_or_names(self, live):
        """Receipts are ids and numbers. Member words stay on the club's site."""
        conn, trips, _l = live
        for lake in _busiest(trips, 4):
            b = trip_brief(conn, lake, next_weekend()[0])
            for cites in b["citations"].values():
                for row in cites:
                    assert len(row) == 3
                    assert isinstance(row[0], int)
                    assert isinstance(row[1], str) and len(row[1]) == 10
                    assert row[2] is None or isinstance(row[2], int)

    def test_report_url_shape(self):
        u = report_url(14329)
        assert u.endswith("/forums/view_report/14329")
        assert u.startswith("https://")

    def test_evidence_trips_is_bounded_and_recent(self, live):
        conn, trips, lures = live
        lake = _busiest(trips, 1)[0]
        sel = trips[trips["lake"] == lake].dropna(subset=["fish_per_hour"])
        ml = lures[lures.report_id.isin(sel.report_id)]
        cat = ml["category"].value_counts().index[0]
        cites = evidence_trips(sel, ml, cat, limit=6)
        assert len(cites) <= 6
        dates = [c[1] for c in cites]
        assert dates == sorted(dates, reverse=True), "should be most recent first"


class TestMapAgreesWithTheDriveColumn:
    def _map(self, conn):
        from dashboard.mapview import build_map
        lakes = [dict(r) for r in conn.execute(
            "SELECT name, lat, lon FROM lakes"
            " WHERE lat IS NOT NULL AND report_count > 0")]
        return build_map(lakes), lakes

    def test_every_lake_plots_inside_the_viewport(self, live):
        conn, _t, _l = live
        m, _ = self._map(conn)
        for mark in m["lakes"]:
            assert 0 <= mark["x"] <= m["width"], mark["lake"]
            assert 0 <= mark["y"] <= m["height"], mark["lake"]

    def test_every_lake_sits_in_texas_or_oklahoma(self, live):
        conn, _t, _l = live
        rows = conn.execute(
            "SELECT name, lat, lon FROM lakes WHERE lat IS NOT NULL").fetchall()
        for r in rows:
            assert 25.8 <= r["lat"] <= 37.1, r["name"]
            assert -106.7 <= r["lon"] <= -93.5, r["name"]

    def test_rings_agree_with_the_mileage(self, live):
        """The map exists to answer 'how far am I driving'. If a lake plots
        outside the 100-mile ring while the table calls it 90 miles, the map is
        lying."""
        conn, _t, _l = live
        m, lakes = self._map(conn)
        home = (m["home"]["x"], m["home"]["y"])
        ring = next(r for r in m["rings"] if r["miles"] == 100)
        pts = [tuple(map(float, p.split(",")))
               for p in __import__("re").findall(r"[-\d.]+,[-\d.]+", ring["d"])]
        coords = {lk["name"]: (lk["lat"], lk["lon"]) for lk in lakes}
        errs = []
        for mark in m["lakes"]:
            lat, lon = coords[mark["lake"]]
            true_mi = miles_between(32.7767, -96.7970, lat, lon)
            ang = math.atan2(mark["y"] - home[1], mark["x"] - home[0])
            nearest = min(pts, key=lambda p: abs(
                math.atan2(p[1] - home[1], p[0] - home[0]) - ang))
            r_at = math.dist(nearest, home)
            est = math.dist((mark["x"], mark["y"]), home) / r_at * 100
            errs.append(abs(est - true_mi))
        assert sum(errs) / len(errs) < 3.0, f"mean ring error {sum(errs)/len(errs):.1f} mi"
        assert max(errs) < 15.0, f"worst ring error {max(errs):.1f} mi"

    def test_projection_places_a_known_point(self, live):
        """Dallas must land where Dallas is, relative to the lakes around it."""
        conn, _t, _l = live
        m, lakes = self._map(conn)
        home = m["home"]
        near = [mk for mk in m["lakes"] if mk["lake"] == "Malouf Lake"]
        if not near:
            pytest.skip("Malouf Lake absent")
        d = math.dist((near[0]["x"], near[0]["y"]), (home["x"], home["y"]))
        ring60 = next(r for r in m["rings"] if r["miles"] == 60)
        pts = [tuple(map(float, p.split(",")))
               for p in __import__("re").findall(r"[-\d.]+,[-\d.]+", ring60["d"])]
        r60 = sum(math.dist(p, (home["x"], home["y"])) for p in pts) / len(pts)
        assert d < r60, "a 13-mile lake must plot inside the 60-mile ring"

    def test_region_geometry_is_committed_and_small(self):
        region = load()
        assert len(region["states"]) >= 4
        n = sum(len(r) for s in region["states"] for r in s["rings"])
        assert 100 < n < 2000, f"{n} points - check the simplification tolerance"
        assert list(RINGS_MILES) == region["rings_miles"]


class TestProjection:
    def test_mercator_keeps_the_aspect_sane(self):
        """Latitude in radians mixed with longitude in degrees once flattened
        the region into a 17-pixel band."""
        proj, _ = make_projection([26.9, 35.9], [-99.3, -94.2], 520, 620)
        x0, y0 = proj(-99.3, 26.9)
        x1, y1 = proj(-94.2, 35.9)
        assert abs(y0 - y1) > 300, "vertical span collapsed"
        assert abs(x0 - x1) > 100

    def test_north_is_up(self):
        proj, _ = make_projection([30.0, 35.0], [-98.0, -95.0], 400, 400)
        _, y_north = proj(-96.5, 35.0)
        _, y_south = proj(-96.5, 30.0)
        assert y_north < y_south
