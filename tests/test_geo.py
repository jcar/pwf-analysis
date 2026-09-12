"""Geocoding guards.

Town names repeat across states - there is a Lancaster in California as well as
the one in Texas - and a wrong hit silently attaches the wrong weather to every
trip on that lake, which is worse than having no coordinates at all.
"""
import pytest

from pwf.config import DB_PATH
from pwf.db import init

# Texas + Oklahoma, generously bounded.
TX_OK_BOX = (25.8, 37.1, -106.7, -93.5)


class TestGeocodeFilter:
    def test_rejects_out_of_state_matches(self):
        """A town that exists only outside TX/OK must return nothing rather
        than fall back to another state."""
        import httpx

        from pwf.geo import geocode_town
        with httpx.Client(timeout=30, follow_redirects=True) as c:
            assert geocode_town(c, "Poughkeepsie") is None

    def test_ambiguous_town_resolves_in_texas(self):
        import httpx

        from pwf.geo import geocode_town
        with httpx.Client(timeout=30, follow_redirects=True) as c:
            hit = geocode_town(c, "Lancaster")
        assert hit is not None
        lat, lon = hit
        lo_lat, hi_lat, lo_lon, hi_lon = TX_OK_BOX
        assert lo_lat <= lat <= hi_lat and lo_lon <= lon <= hi_lon


class TestStoredCoordinates:
    def test_every_lake_sits_in_texas_or_oklahoma(self):
        if not DB_PATH.exists():
            pytest.skip("no database yet")
        conn = init(DB_PATH)
        rows = conn.execute(
            "SELECT name, lat, lon FROM lakes WHERE lat IS NOT NULL").fetchall()
        if not rows:
            pytest.skip("not geocoded yet")
        lo_lat, hi_lat, lo_lon, hi_lon = TX_OK_BOX
        stray = [r["name"] for r in rows
                 if not (lo_lat <= r["lat"] <= hi_lat and lo_lon <= r["lon"] <= hi_lon)]
        assert not stray, f"lakes geocoded outside TX/OK: {stray}"
