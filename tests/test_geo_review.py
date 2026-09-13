"""The override file and the review tool that writes to it.

The bug these pin down was quiet and expensive: `write_override_template` dumped
every lake's current coordinate into the CSV, and `_load_overrides` treated
every row as a correction. So the file froze whatever the geocoder guessed
first, and every later fix became a no-op - the repair pass reported 52 lakes
"corrected" while changing nothing at all.
"""
from __future__ import annotations

import csv

import pytest

from pwf import geo, geo_review


@pytest.fixture()
def csvfile(tmp_path, monkeypatch):
    path = tmp_path / "lake_coords.csv"
    monkeypatch.setattr(geo, "OVERRIDES", path)
    return path


def write(path, rows, cols=("lake", "town", "lat", "lon", "reports",
                            "uncertain", "confirmed", "note")):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_an_unconfirmed_row_is_not_an_override(csvfile):
    write(csvfile, [{"lake": "Angel Lake", "lat": "32.8", "lon": "-96.8",
                     "confirmed": ""}])
    assert geo._load_overrides() == {}


def test_a_confirmed_row_is(csvfile):
    write(csvfile, [{"lake": "Angel Lake", "lat": "31.88", "lon": "-97.07",
                     "confirmed": "yes"}])
    assert geo._load_overrides() == {"Angel Lake": (31.88, -97.07)}


def test_confirm_marks_and_survives_a_template_rewrite(csvfile):
    write(csvfile, [{"lake": "Angel Lake", "lat": "32.8", "lon": "-96.8",
                     "confirmed": ""}])
    geo.confirm("Angel Lake", 31.8849, -97.0733, "checked by hand")
    assert geo._load_overrides()["Angel Lake"] == pytest.approx(
        (31.8849, -97.0733))


def test_confirm_adds_a_lake_the_file_has_never_seen(csvfile):
    write(csvfile, [])
    geo.confirm("Melody Acres", 31.3182, -95.4566)
    assert "Melody Acres" in geo._load_overrides()


def test_compass_names_the_direction():
    assert geo_review.compass(0) == "N"
    assert geo_review.compass(90) == "E"
    assert geo_review.compass(181) == "S"
    assert geo_review.compass(315) == "NW"


def test_describe_reports_drive_and_direction():
    # Tyler is east of Dallas, a bit over ninety miles.
    got = geo_review.describe({"lat": 32.3513, "lon": -95.3011})
    assert 80 <= got["miles"] <= 105
    assert got["dir"] in ("E", "ESE", "ENE")


def test_useful_snippets_exclude_the_obvious_false_friends():
    noise = ["Fished 3 hours on Saturday.",
             "You do not need four wheel drive if the ground is dry."]
    for s in noise:
        assert not (geo_review._USEFUL.search(s)
                    and not geo_review._NOISE.search(s))


def test_useful_snippets_keep_a_real_location_hint():
    s = "Enjoyed the backroad drive from Dallas and got there by eight."
    assert geo_review._USEFUL.search(s)
    assert not geo_review._NOISE.search(s)


def test_a_real_town_outranks_an_unincorporated_dot():
    """The club publishes a town, and a town has a population.

    Leading with proximity to other club lakes put Burnet in Fannin County and
    Palestine in Hopkins - both are the seats of the counties they are named
    for. Nameless geocoder entries are localities and landmarks, and they sit
    near a club lake as often as not, purely by chance.
    """
    anchors = [(33.4, -96.6)]          # a club lake right next to the dot
    cands = [{"lat": 33.40, "lon": -96.60, "population": None},
             {"lat": 30.76, "lon": -98.23, "population": 6239}]
    assert geo_review.rank(cands, anchors)[0]["population"] == 6239


def test_directions_outrank_everything_else():
    from pwf.geo_verify import parse_directions

    claims = parse_directions(
        "General Directions 2 hours from Downtown Houston").get("claims")
    # The near one has company and is small; the far one matches the page.
    cands = [{"lat": 33.10, "lon": -97.42, "population": 500},
             {"lat": 30.67, "lon": -96.37, "population": 82118}]
    got = geo_review.rank(cands, [(33.10, -97.42)], claims=claims)
    assert got[0]["population"] == 82118
    assert got[0]["basis"] == "directions"


def test_club_region_outranks_the_clustering_heuristic():
    cands = [{"lat": 33.10, "lon": -97.42, "population": 500},
             {"lat": 30.67, "lon": -96.37, "population": 500}]
    got = geo_review.rank(cands, [(33.10, -97.42)], region=(29.76, -95.37))
    assert got[0]["lat"] == pytest.approx(30.67)
    assert got[0]["basis"] == "club region"
