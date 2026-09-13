"""The club's own directions, read as evidence about where a lake is.

These cases are all real text from property pages. Each one broke an earlier
version of the parser, and every break silently moved a lake by a hundred miles
or more - which is exactly the failure the module exists to catch, so they are
pinned here rather than left as anecdotes.
"""
from __future__ import annotations

import pytest

from pwf.geo_verify import (CITIES, best_candidate, check, parse_directions,
                            score)


def claims(text: str):
    return parse_directions("General Directions " + text).get("claims") or []


def as_pairs(text: str):
    return [(c["city"], round(c["miles"]), c["bearing"]) for c in claims(text)]


def test_distance_is_anchored_to_the_city_it_names():
    # Measuring this from Dallas, as the first version did, made a correctly
    # placed lake look 240 miles wrong.
    assert as_pairs("35 miles west of downtown San Antonio.") == [
        ("san antonio", 35, 270)]


def test_every_claim_on_the_page_is_kept():
    got = as_pairs("2 hours and 30 minutes east of Downtown Dallas "
                   "3 hours and 45 minutes from downtown Houston "
                   "1 hour east of Tyler")
    assert got == [("dallas", 138, 90), ("houston", 206, None),
                   ("tyler", 55, 90)]


def test_nearest_distance_wins_not_the_first_one():
    # "10 miles east of Bonham 70 miles NNE of Dallas" was read as a lake ten
    # miles from Dallas.
    assert as_pairs("10 miles east of Bonham 70 miles NNE of Dallas") == [
        ("bonham", 10, 90), ("dallas", 70, 22.5)]


def test_distance_stated_after_the_city():
    got = as_pairs("North of Beaumont, approximately 14 miles, around 24 "
                   "minutes. Northeast of Houston, approximately 79 miles, "
                   "around 1 hour and 30 minutes.")
    assert got == [("beaumont", 14, 0), ("houston", 79, 45)]


def test_a_restated_drive_time_is_not_a_second_claim():
    # "14 miles, around 24 minutes" is one claim said twice; letting the
    # minutes leak onto the next city produced a bogus 22-mile claim.
    got = claims("North of Beaumont, approximately 14 miles, around 24 minutes.")
    assert len(got) == 1


def test_bare_number_inherits_the_unit_from_the_previous_claim():
    got = as_pairs("2 hours NE of Downtown Houston. 3.5 from downtown Dallas.")
    assert got[1][0] == "dallas"
    assert got[1][1] == round(3.5 * 55)


def test_abbreviated_anchors_resolve():
    assert as_pairs("About 1 hour SW of OKC")[0][0] == "oklahoma city"


def test_a_lake_that_matches_its_page_is_not_flagged():
    # Crockett, Texas: the page says two and a half hours from Dallas.
    got = check(31.3182, -95.4566,
                parse_directions("General Directions 2.5 hours from Downtown "
                                 "Dallas 2 hours from Downtown Houston"))
    assert got["verdict"] == "ok"
    assert got["miss"] == 0


def test_the_wrong_crockett_is_flagged():
    # The geocoder had put this one twelve miles from Dallas.
    got = check(32.7396, -96.9964,
                parse_directions("General Directions 2.5 hours from Downtown "
                                 "Dallas 2 hours from Downtown Houston"))
    assert got["verdict"] == "suspect"
    assert got["miss"] > 25


def test_right_distance_wrong_direction_still_fails():
    # A lake 40 miles from Tyler is not the lake 40 miles the other way.
    stated = parse_directions("General Directions 40 miles NE of Tyler.")
    near = score(32.75, -94.94, stated["claims"])["miss"]
    away = score(32.10, -95.70, stated["claims"])["miss"]
    assert near == 0 and away > 0


def test_directions_pick_the_right_town_among_same_named_ones():
    cands = [
        {"latitude": 33.0168, "longitude": -97.2086},   # near Dallas
        {"latitude": 32.5449, "longitude": -94.3674},   # Harrison County
    ]
    stated = claims("2 hours and 30 minutes east of Downtown Dallas "
                    "3 hours and 45 minutes from downtown Houston "
                    "1 hour east of Tyler")
    pick = best_candidate(cands, stated)
    assert pick is not None
    assert pick["lat"] == pytest.approx(32.5449)
    assert pick["miss"] == 0


def test_no_pick_when_the_directions_cannot_separate_candidates():
    # Two towns that both satisfy a single loose claim must not be guessed at.
    stated = claims("About 2 hours from Dallas")
    cands = [{"latitude": 32.20, "longitude": -95.30},
             {"latitude": 33.30, "longitude": -95.40}]
    assert best_candidate(cands, stated) is None


def test_no_claims_is_not_a_failure():
    assert check(32.0, -97.0, {})["verdict"] == "no claim"
    assert check(32.0, -97.0, parse_directions("nothing here"))["verdict"] \
        == "no claim"


def test_every_anchor_sits_inside_texas_or_oklahoma():
    # A typo in the anchor table would silently move every lake that quotes it.
    for name, (lat, lon) in CITIES.items():
        assert 25.8 <= lat <= 37.1, name
        assert -103.1 <= lon <= -93.5, name
