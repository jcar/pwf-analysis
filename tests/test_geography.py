"""The drive-versus-quality gradient, which the map now puts in front of you.

The claim is deliberately narrow. Distance, lake size and fishing pressure move
together in this club - the near lakes are the small ones and also the
hard-fished ones - so the test checks that the module keeps saying so rather
than collapsing it into "drive further, catch more".
"""
from __future__ import annotations

import json

import pytest

from pwf.config import DB_PATH
from pwf.db import init
from pwf.geography import SPLIT_MILES, drive_gradient, split_scan


@pytest.fixture(scope="module")
def grad():
    return drive_gradient(init(DB_PATH))


def test_the_far_water_really_does_fish_better(grad):
    assert grad["far"]["fph"] > grad["near"]["fph"]
    assert grad["raw_gap"] > 0.5


def test_the_gap_does_not_depend_on_where_the_line_is_drawn(grad):
    """80 miles is the widest gap of the five cut-points, which is exactly the
    kind of choice that flatters a finding. The reassurance is that every other
    cut-point agrees in sign."""
    scan = grad["scan"]
    assert len(scan) >= 4
    assert all(s["gap"] > 0 for s in scan), \
        f"the pattern flips at some cut-point: {scan}"


def test_the_confounds_are_reported_not_buried(grad):
    # Far lakes are bigger, and near lakes carry more of the club's pressure.
    assert grad["far"]["median_acres"] > grad["near"]["median_acres"]
    assert grad["near"]["median_trips"] > grad["far"]["median_trips"]
    assert grad["corr"]["miles_trips"] < 0
    assert "cannot separate" in grad["caveat"]


def test_holding_size_shrinks_the_effect_but_does_not_erase_it(grad):
    held = grad["held_for_size"]["per_100_miles"]
    assert held > 0, "drive should still be worth something once size is held"
    # It must be a fraction of the raw gap, not all of it - otherwise the page
    # would be crediting the drive with the lake-size effect too.
    assert held < grad["raw_gap"], (
        f"holding acreage left {held} of a {grad['raw_gap']} gap, which would "
        "mean size explains none of it")


def test_every_number_is_json_safe(grad):
    """Correlations computed over rows with unknown acreage came back NaN,
    which is not valid JSON and would have shipped to the page as a blank."""
    text = json.dumps(grad)
    assert "NaN" not in text and "Infinity" not in text
    for k, v in grad["corr"].items():
        assert v is None or -1 <= v <= 1, f"{k}={v}"


def test_split_is_the_documented_one(grad):
    assert grad["split_miles"] == SPLIT_MILES
    assert any(s["cut"] == SPLIT_MILES for s in split_scan(init(DB_PATH)))
