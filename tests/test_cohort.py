"""Size-band advice — the finest grain that actually replicates.

Per-lake tackle effects fail split-half (r=-0.02). Club-wide effects hold but
average a 10-acre tank with a 50-acre lake. Pooling by size is the middle, and
these tests pin both halves of that claim: that it replicates, and that the
bands genuinely disagree — otherwise there would be no point conditioning on
size at all.
"""
import numpy as np
import pandas as pd
import pytest

from pwf import analysis as A
from pwf.cohort import BANDS, advice_for, band_effects, band_for, label
from pwf.config import DB_PATH
from pwf.db import init
from pwf.reliability import REPEATS_THRESHOLD, split_half


@pytest.fixture(scope="module")
def live():
    if not DB_PATH.exists():
        pytest.skip("no database - run `pwf build`")
    conn = init(DB_PATH)
    trips = A.trips_frame(conn)
    if trips.empty:
        pytest.skip("no trips")
    lures, tags = A.lures_frame(conn), A.tags_frame(conn)
    return conn, trips, lures, tags, band_effects(trips, lures, tags)


class TestBandsReplicate:
    def test_band_effects_survive_split_half(self, live):
        """The justification for conditioning on size at all. If this drops to
        the per-lake level, size-band advice is no better than per-lake advice
        and should be withdrawn."""
        _c, trips, lures, _t, _b = live
        d = trips.dropna(subset=["fish_per_hour", "acres"]).copy()
        d = d[(d["acres"] > 0) & (d["acres"] <= 200)]
        d["lake"] = d["acres"].map(band_for)      # treat the band as the unit
        d["lake_known"] = 1
        baits = lures.drop_duplicates(subset=["report_id", "category"])
        out = split_half(d, lures, baits, "category", min_lake_trips=300,
                         max_lakes=5)
        assert out["r"] is not None, "not enough data to test"
        assert out["r"] > REPEATS_THRESHOLD, (
            f"size-band effects stopped replicating (r={out['r']}) — the "
            "conditioning no longer earns its place")


class TestBandsDisagree:
    def test_topwater_flips_with_lake_size(self, live):
        """The finding that makes size worth conditioning on: topwater helps on
        small water and costs you on big water, both ends clear of zero."""
        _c, _t, _l, _g, bands = live
        def tw(b):
            return next((e for e in bands[b]["baits"]
                         if e["value"] == "topwater"), None)
        small, large = tw("small"), tw("large")
        assert small and large
        assert small["diff"] > 0 and small["lo"] > 0, small
        assert large["diff"] < 0 and large["hi"] < 0, large
        assert small["support"] == "backed"
        assert large["support"] == "below"

    def test_the_bands_give_different_advice(self, live):
        _c, _t, _l, _g, bands = live
        picks = {}
        for acres, band in ((10, "small"), (22, "mid"), (50, "large")):
            a = advice_for(bands, acres)
            assert a["band"] == band
            picks[band] = {e["value"] for e in a["use"]}
        assert picks["small"] != picks["large"], (
            "small and large water produce identical advice — conditioning on "
            "size is then pointless")

    def test_bigger_water_fishes_better(self, live):
        _c, _t, _l, _g, bands = live
        assert bands["large"]["mean_fph"] > bands["small"]["mean_fph"]


class TestBanding:
    @pytest.mark.parametrize("acres,band", [
        (8, "small"), (14.9, "small"), (15, "small"), (15.1, "mid"),
        (30, "mid"), (31, "large"), (160, "large"),
        (None, None), (0, None),
    ])
    def test_band_for(self, acres, band):
        assert band_for(acres) == band

    def test_labels_read_as_english(self):
        for _lo, _hi, name in BANDS:
            assert "acre" in label(name)

    def test_advice_is_empty_when_size_is_unknown(self, live):
        """No acreage means no band, and the caller falls back to club-wide
        rather than being handed the wrong band's advice."""
        _c, _t, _l, _g, bands = live
        assert advice_for(bands, None) == {}

    def test_every_band_effect_carries_its_interval(self, live):
        _c, _t, _l, _g, bands = live
        for b in bands.values():
            for e in b["baits"] + b["techniques"]:
                assert e["lo"] <= e["diff"] <= e["hi"]
                assert e["trips"] >= 1
                assert e["support"] in {"backed", "suggestive", "unproven",
                                        "unstable", "below", "thin"}

    def test_stability_is_judged_on_halves_not_years(self, live):
        """At band level a single year is too thin; the check is split-half."""
        _c, _t, _l, _g, bands = live
        seen = False
        for b in bands.values():
            for e in b["baits"] + b["techniques"]:
                assert "halves" in e and "years" not in e
                seen = True
        assert seen


class TestBriefUsesIt:
    def test_brief_carries_band_advice_and_its_caveat(self, live):
        from pwf.brief import next_weekend, trip_brief
        conn, trips, lures, tags, bands = live
        lake = trips[(trips.lake_known == 1) & trips.acres.notna()][
            "lake"].value_counts().index[0]
        b = trip_brief(conn, lake, next_weekend()[0], trips=trips, lures=lures,
                       tags=tags, bands=bands)
        sb = b["plan"]["size_band"]
        assert sb.get("label")
        assert sb.get("caveat") and "size" in sb["caveat"]
        for e in sb.get("use", []):
            # band advice must rest on far more than one lake's worth of trips
            assert e["trips"] >= 40
