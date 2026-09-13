"""The lake summary.

The narrated half must not overstate what a thin sample supports. The mined
half must never surface a member's name, and must never reproduce a sentence -
a phrase earns its place by appearing across many separate reports, which makes
it a statistic about language rather than somebody's words.
"""
import re

import pytest

from pwf.config import DB_PATH
from pwf.db import init
from pwf.profile import lake_profile
from pwf.summarize import (_stem, distinctive_mentions, mention_index,
                           summarize)


@pytest.fixture(scope="module")
def live():
    if not DB_PATH.exists():
        pytest.skip("no database yet - run `pwf build`")
    conn = init(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM trips WHERE lake_known=1").fetchone()[0]
    if not n:
        pytest.skip("no trips")
    return conn, mention_index(conn, str(DB_PATH))


def _busiest(conn, k=8):
    return [r[0] for r in conn.execute(
        "SELECT l.name FROM trips t JOIN lakes l ON l.lake_id=t.lake_id"
        " WHERE t.lake_known=1 GROUP BY t.lake_id"
        " ORDER BY COUNT(*) DESC LIMIT ?", (k,))]


class TestNoMemberNames:
    """The single most important constraint in this module."""

    def test_no_author_name_ever_surfaces(self, live):
        conn, idx = live
        authors = set()
        for (a,) in conn.execute(
                "SELECT DISTINCT author FROM reports WHERE author IS NOT NULL"):
            for part in re.split(r"[^A-Za-z']+", a.lower()):
                if len(part) > 2:
                    authors.add(part)
        leaked = []
        for lake in _busiest(conn, 25):
            for m in distinctive_mentions(idx, lake, limit=12):
                for word in m["phrase"].split():
                    if word in authors:
                        leaked.append((lake, m["phrase"]))
        assert not leaked, f"member names surfaced as mentions: {leaked[:6]}"

    def test_lake_and_town_names_are_filtered(self, live):
        conn, idx = live
        rows = {r[0]: r[1] for r in conn.execute(
            "SELECT name, town FROM lakes WHERE town IS NOT NULL")}
        bad = []
        for lake in _busiest(conn, 20):
            own = set()
            for src in (lake, rows.get(lake) or ""):
                spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", src)
                for variant in (src, spaced):
                    own.update(w for w in re.split(r"[^A-Za-z']+", variant.lower())
                               if len(w) > 2)
            for m in distinctive_mentions(idx, lake, limit=12):
                if any(w in own for w in m["phrase"].split()):
                    bad.append((lake, m["phrase"]))
        assert not bad, f"lake or town name surfaced: {bad[:6]}"


class TestMentionsArePatternsNotQuotes:
    def test_phrases_are_short(self, live):
        conn, idx = live
        for lake in _busiest(conn, 15):
            for m in distinctive_mentions(idx, lake):
                assert len(m["phrase"].split()) <= 2, m["phrase"]

    def test_every_phrase_is_backed_by_several_reports(self, live):
        conn, idx = live
        for lake in _busiest(conn, 15):
            for m in distinctive_mentions(idx, lake):
                assert m["reports"] >= 6
                assert m["of"] >= m["reports"]

    def test_phrases_are_distinctive_not_merely_common(self, live):
        conn, idx = live
        for lake in _busiest(conn, 15):
            for m in distinctive_mentions(idx, lake):
                assert m["times_club"] > 1.0

    def test_variants_are_collapsed(self, live):
        conn, idx = live
        for lake in _busiest(conn, 15):
            stems = [_stem(m["phrase"]) for m in distinctive_mentions(idx, lake)]
            assert len(stems) == len(set(stems)), f"{lake}: {stems}"

    @pytest.mark.parametrize("word,stem", [
        ("batteries", "battery"), ("islands", "island"),
        ("bass", "bass"), ("grass", "grass"), ("pier", "pier"),
    ])
    def test_stemming(self, word, stem):
        assert _stem(word) == stem


class TestNarrative:
    def test_busiest_lakes_all_get_a_summary(self, live):
        conn, idx = live
        for lake in _busiest(conn, 10):
            p = lake_profile(conn, lake, mentions=idx)
            s = p["summary"]
            assert s["paragraphs"], f"{lake} produced no summary"
            assert all(t.strip().endswith(".") for t in s["paragraphs"])

    def test_best_month_is_not_crowned_on_a_handful_of_trips(self, live):
        """A six-trip January once outranked a lake's real season. Whatever
        month the summary names must be reasonably sampled."""
        conn, idx = live
        from pwf.summarize import MIN_MONTH_TRIPS
        months = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5,
                  "June": 6, "July": 7, "August": 8, "September": 9,
                  "October": 10, "November": 11, "December": 12}
        for lake in _busiest(conn, 12):
            p = lake_profile(conn, lake, mentions=idx)
            line = next((t for t in p["summary"]["paragraphs"]
                         if t.startswith("Fishes best")), None)
            if not line:
                continue
            named = re.search(r"Fishes best in (\w+)", line).group(1)
            m = months[named]
            row = next(x for x in p["by_month"] if x["m"] == m)
            assert row["n"] >= MIN_MONTH_TRIPS, f"{lake}: {named} on {row['n']} trips"

    def test_thin_lakes_are_warned_about(self, live):
        conn, idx = live
        row = conn.execute(
            "SELECT l.name FROM trips t JOIN lakes l ON l.lake_id=t.lake_id"
            " WHERE t.lake_known=1 AND t.fish_per_hour IS NOT NULL"
            " GROUP BY t.lake_id HAVING COUNT(*) BETWEEN 3 AND 9 LIMIT 1").fetchone()
        if not row:
            pytest.skip("no thin lake to check")
        p = lake_profile(conn, row[0], mentions=idx)
        assert p["summary"]["caveat"], "a thin lake must say so"

    def test_summary_survives_a_lake_with_almost_nothing(self):
        empty = {"volume": {"scored": 1, "reports": 1, "confidence": "very thin"},
                 "rate": {"median": None, "club_median": None, "percentile": None},
                 "by_month": [], "by_year": [], "by_slot": [],
                 "baits": {"overall": [], "by_season": {}},
                 "water": {"clarity_ft_median": None, "clarity_ft_n": 0,
                           "veg_mention_rate": None, "vegetation": [],
                           "structure": [], "technique": []},
                 "fish": {"median_fish_per_trip": None, "best_lb": None,
                          "over_5lb_rate": None, "species": [],
                          "weight_bands": [], "weight_reports": 0},
                 "conditions": {}}
        s = summarize(empty, [])
        assert isinstance(s["paragraphs"], list)
        assert s["caveat"]
