"""The booking brief, the map, and the receipts.

This module adds no statistics, so the tests are mostly about agreement: the
brief must equal its sources, the citations must be real trips, and the map must
agree with the drive column. A map whose rings contradicted the mileage would be
worse than no map.
"""
import math
import re
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
    """The map exists to answer "how far am I driving", so its rings have to
    agree with the mileage column.

    That guarantee used to live in a projected SVG path built in Python. The map
    is MapLibre now and draws the rings in JavaScript from real coordinates, so
    the test follows it there rather than being deleted with the code it
    covered.
    """

    def test_every_lake_sits_in_texas_or_oklahoma(self, live):
        conn, _t, _l = live
        for r in conn.execute(
                "SELECT name, lat, lon FROM lakes WHERE lat IS NOT NULL"):
            assert 25.8 <= r["lat"] <= 37.1, r["name"]
            assert -106.7 <= r["lon"] <= -93.5, r["name"]

    def test_rings_are_true_distances_not_circles(self):
        """A plain circle on a Mercator projection is up to 8% out east and
        west. Every vertex has to be the stated distance from Dallas."""
        import json
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if not shutil.which("node"):
            pytest.skip("node not available")
        page = next((q for q in (Path("docs/index.html"),
                                 Path("dashboard/index.html")) if q.exists()), None)
        if page is None:
            pytest.skip("dashboard not built")
        stub = Path("tests/support/domstub.js")
        m = re.search(r"(?s)<script>(.*)</script>", page.read_text(encoding="utf-8"))
        src = (stub.read_text() + "\n" + m.group(1)
               + "\nconsole.log(JSON.stringify("
                 "ringFeature(100, 64).geometry.coordinates));")
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                         encoding="utf-8") as f:
            f.write(src)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True,
                               timeout=120)
            assert r.returncode == 0, r.stderr[:1200]
            pts = json.loads(r.stdout.strip().splitlines()[-1])
        finally:
            Path(path).unlink(missing_ok=True)

        assert len(pts) >= 64
        errs = [abs(miles_between(32.7767, -96.7970, lat, lon) - 100)
                for lon, lat in pts]
        assert max(errs) < 1.0, f"worst ring vertex is {max(errs):.2f} mi out"


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
