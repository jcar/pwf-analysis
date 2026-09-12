"""Parser tests pinned to committed HTML fixtures."""
import pytest

from pwf.parse_index import parse as parse_index
from pwf.parse_index import max_report_id, split_property
from pwf.parse_report import (is_missing, parse, parse_posted_date,
                              parse_reservation_date)


class TestReportDetail:
    def test_modern_structured_report(self, fx):
        r = parse(fx("report_modern_14329"), 14329)
        assert r["title"] == "Subtle Bite on a Beautiful Morning"
        assert r["posted_date"] == "2026-09-11"
        assert r["author"] == "JORDAN JUNEWATER"
        assert r["author_rank"] == "Fry"
        assert r["member_since"] == 2025
        assert r["post_count"] == 12
        assert r["reservation_number"] == "48003"
        assert r["property_name"] == "JerMar Lake"
        assert r["trip_date"] == "2026-09-11"
        assert r["time_slot"] == "AM"
        assert r["total_fish_raw"] == "4 LMB - 2-2.5 lbs"
        assert r["lures_raw"] == "Green Pumpkin Fluke; Drop Shot Finesse Worm"
        assert r["era"] == "structured"
        assert r["photo_count"] == 3
        assert "weed edge" in r["body"]
        # The field block must never leak into the narrative.
        assert "Reservation Number" not in r["body"]

    def test_legacy_report_has_no_field_block(self, fx):
        r = parse(fx("report_legacy_2000"), 2000)
        assert r["era"] == "legacy"
        assert r["title"] == "Not much happening at Malouf"
        assert r["posted_date"] == "2014-03-09"
        assert r["author"] == "Flint Gullick"
        assert r["property_name"] is None
        assert r["trip_date"] is None
        assert r["lures_raw"] is None

    def test_legacy_report_joins_all_paragraphs(self, fx):
        """Legacy narratives span several <p> elements; none may be dropped."""
        r = parse(fx("report_legacy_2000"), 2000)
        assert "high 30s this morning" in r["body"]      # first paragraph
        assert "Water temperature was about 49" in r["body"]  # second paragraph
        assert "Posted By" not in r["body"]

    def test_legacy_3500(self, fx):
        r = parse(fx("report_legacy_3500"), 3500)
        assert r["era"] == "legacy"
        assert r["posted_date"] == "2017-03-29"
        assert r["body"]

    def test_missing_report_is_detected_despite_http_200(self, fx):
        html = fx("report_missing_14330")
        assert is_missing(html) is True
        assert parse(html, 14330) is None

    def test_real_report_is_not_flagged_missing(self, fx):
        assert is_missing(fx("report_modern_14329")) is False
        assert is_missing(fx("report_legacy_2000")) is False


class TestDateParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("Sep 11 2026", "2026-09-11"),
        ("Mar 09 2014", "2014-03-09"),
        ("garbage", None),
        ("", None),
    ])
    def test_posted_date(self, raw, expected):
        assert parse_posted_date(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("09/11/2026 AM -", ("2026-09-11", "AM")),
        ("04/03/2026 All Day -", ("2026-04-03", "ALL_DAY")),
        ("12/28/2025 PM -", ("2025-12-28", "PM")),
        ("", (None, None)),
        ("13/45/2026 AM", (None, None)),
    ])
    def test_reservation_date(self, raw, expected):
        assert parse_reservation_date(raw) == expected


class TestListingIndex:
    def test_cards_carry_lake_for_2015_reports(self, fx):
        """Detail pages lack Property Name before ~2019; the index has it."""
        rows = {r["report_id"]: r for r in parse_index(fx("index_offset_11000"))}
        assert len(rows) == 12
        assert all(r["lake_name"] for r in rows.values())
        r = rows[2536]
        assert r["lake_name"] == "Deer Trail Ranch"
        assert r["lake_town"] == "Sulphur Bluff"
        assert r["posted_date"] == "2015-04-19"
        assert r["author"] == "Cedar Dellworth"
        assert r["views"] == 1265

    def test_oldest_cards_have_no_lake(self, fx):
        """Pre-mid-2012 cards carry no property; these stay unattributed."""
        rows = parse_index(fx("index_offset_12600"))
        assert len(rows) == 12
        assert all(r["lake_name"] is None for r in rows)
        assert all(r["posted_date"].startswith("2011") for r in rows)

    def test_max_report_id(self, fx):
        assert max_report_id(fx("index_offset_0")) == 14329

    @pytest.mark.parametrize("raw,expected", [
        ("JerMar Lake, Van Alstyne", ("JerMar Lake", "Van Alstyne")),
        # A colon in the lake name must not be mistaken for the town separator.
        ("Dogwood Lakes Estate: East Lake, Henderson",
         ("Dogwood Lakes Estate: East Lake", "Henderson")),
        ("Butler Lake , Brenham", ("Butler Lake", "Brenham")),
        ("NoComma Lake", ("NoComma Lake", None)),
        ("", (None, None)),
    ])
    def test_split_property(self, raw, expected):
        assert split_property(raw) == expected
