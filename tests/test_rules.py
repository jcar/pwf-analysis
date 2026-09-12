"""Rule-layer tests. Precision matters more than recall here, so the
adversarial cases found while prototyping are pinned as must-not-match."""
import pytest

from pwf.rules import patterns as P
from pwf.rules.fish import parse_total_fish, species_in_text
from pwf.rules.lures import find_lures_in_text, parse_lures


def cats(raw):
    return {(h.category, h.subtype) for h in parse_lures(raw).hits if h.category}


class TestLureTaxonomy:
    @pytest.mark.parametrize("raw,expected", [
        ("Green Pumpkin Fluke", ("soft_plastic", "fluke")),
        ("spinner bait", ("spinnerbait", "spinnerbait")),
        ("spinnerbaits", ("spinnerbait", "spinnerbait")),
        ("chatter bait", ("bladed_jig", "bladed_jig")),
        ("rattle trap", ("lipless", "lipless")),
        ("squarebill", ("crankbait", "squarebill")),
        ("whopper plopper", ("topwater", "prop")),
        ("white swim jig", ("jig", "swim_jig")),
        ("senkos", ("soft_plastic", "stickbait")),
        ("brush hog", ("soft_plastic", "creature")),
        ("crappie jig", ("crappie_jig", "crappie_jig")),
        ("fly rod", ("fly", "fly")),
        ("underspin", ("underspin", "underspin")),
    ])
    def test_surface_forms_map_to_taxonomy(self, raw, expected):
        assert expected in cats(raw)

    def test_specific_beats_generic(self):
        """'swim jig' must not collapse to a bare jig."""
        assert ("jig", "swim_jig") in cats("swim jig")
        assert ("jig", "unspecified") not in cats("swim jig")

    def test_generic_dropped_when_specific_present(self):
        """'topwater poppers' is one bait, not two."""
        assert cats("topwater poppers") == {("topwater", "popper")}

    def test_multiple_baits_in_one_string(self):
        got = cats("Crappie jig, small crank bait")
        assert ("crappie_jig", "crappie_jig") in got
        assert ("crankbait", "unspecified") in got

    def test_and_does_not_split_a_colour(self):
        """'black and blue' is one colour, not two lure fragments."""
        res = parse_lures("black and blue jig")
        assert res.hits[0].color == "black and blue"
        assert res.hits[0].category == "jig"

    def test_colour_is_extracted(self):
        res = parse_lures("Green Pumpkin Fluke")
        assert res.hits[0].color == "green pumpkin"

    @pytest.mark.parametrize("raw,tech", [
        ("TXRIG worm", "texas_rig"),
        ("wacky senko", "wacky"),
        ("Drop Shot Finesse Worm", "drop_shot"),
        ("neko rig", "neko"),
    ])
    def test_rigs_recorded_as_techniques(self, raw, tech):
        assert tech in parse_lures(raw).techniques

    def test_filler_words_are_ambiguous_not_unknown(self):
        res = parse_lures("various")
        assert res.ambiguous and not res.unknown and not res.matched

    def test_unrecognised_string_goes_to_review_queue(self):
        assert parse_lures("Zorblax Wobbletron 9000").unknown

    def test_narrative_scan_finds_lures(self):
        body = "Switched to a green pumpkin fluke and found 3 on the weed edge."
        assert ("soft_plastic", "fluke") in {
            (h.category, h.subtype) for h in find_lures_in_text(body).hits}


class TestClarity:
    @pytest.mark.parametrize("text", [
        "We were 15 feet from it when it cleared the water and it spit the bait.",
        "The launch area is large and clear and the ramp was excellent.",
    ])
    def test_must_not_match(self, text):
        """Adversarial cases found in the sample: a bare adjective needs a
        water noun near it, and 'cleared' is not 'clear'."""
        assert P.clarity_label(text) is None

    @pytest.mark.parametrize("text,ft", [
        ("Water temp was 56 degrees and visibility about 2 feet.", 2.0),
        ("water was very muddy, <1' visbility, about 6' less than normal", 1.0),
        ("And it is stained with visibility to 18\"", 1.5),   # inches -> feet
        ("The water temp was 87*F and clear with 7FT viz.", 7.0),
        ("Water clarity is about 2 feet.", 2.0),
        ("Water clear to 4'.", 4.0),
        ("no numbers here", None),
    ])
    def test_numeric_clarity(self, text, ft):
        assert P.clarity_ft(text) == ft

    @pytest.mark.parametrize("text,label", [
        ("Water was very clear, beautiful day.", "clear"),
        ("Lake slightly murky and various pond weeds.", "murky"),
        ("the water was muddy after the rain", "muddy"),
    ])
    def test_anchored_labels(self, text, label):
        assert P.clarity_label(text) == label


class TestWaterTemp:
    def test_air_temperature_is_not_water_temperature(self):
        assert P.water_temp_f("Temperature in the high 30s this morning.") is None

    @pytest.mark.parametrize("text,temp", [
        ("Water temp was 56 to 57 degrees", 56.0),
        ("Water temperature was about 49* when we started", 49.0),
        ("The water temp was 87*F and clear", 87.0),
        ("Water temp was 78 which was warmer than air temp!", 78.0),
    ])
    def test_water_temp(self, text, temp):
        assert P.water_temp_f(text) == temp

    def test_implausible_values_rejected(self):
        assert P.water_temp_f("water temp was 350 degrees") is None


class TestTotalFish:
    @pytest.mark.parametrize("raw,total", [
        ("4 LMB - 2-2.5 lbs", 4),
        ("21", 21),
        ("6/10-19\"", 6),
        ("45 under 3#", 45),
        ("42 (biggest was 3.4)", 42),
        ("20 LMB 2 Crappie", 20),
        ("All small", None),
        ("Fair number", None),
    ])
    def test_total(self, raw, total):
        assert parse_total_fish(raw)["total"] == total

    def test_leading_weight_is_not_a_count(self):
        """'4lb x2' starts with a size, not four fish."""
        assert parse_total_fish("4lb x2, 2lb x1")["total"] != 4

    def test_weight_and_length_separated(self):
        r = parse_total_fish("13 total LMB - Range 2lbs - 5.3lbs")
        assert r["max_weight_lb"] == 5.3 and r["max_length_in"] is None
        r2 = parse_total_fish("49/up to 20\"")
        assert r2["max_length_in"] == 20.0 and r2["max_weight_lb"] is None

    def test_species_split(self):
        r = parse_total_fish("18: 2 huge crappie, 16 LMB 2 -4 lbs")
        assert dict(r["species"]) == {"largemouth": 16, "crappie": 2}

    def test_vague_flagged(self):
        assert parse_total_fish("lots")["vague"] is True

    def test_bare_bass_is_largemouth(self):
        assert species_in_text("caught a few bass") == ["largemouth"]


class TestTagsAndWindows:
    def test_vegetation_with_density(self):
        tags = P.tags("The lake was choked with thick hydrilla all over.")
        veg = [t for t in tags if t[0] == "vegetation" and t[1] == "hydrilla"]
        assert veg and veg[0][2] == "heavy"

    def test_structure_and_technique(self):
        tags = P.tags("Found them on the weed edge, punching mats near the dam.")
        kinds = {(k, v) for k, v, _d in tags}
        assert ("structure", "weed_edge") in kinds
        assert ("structure", "dam") in kinds
        assert ("technique", "punching") in kinds

    @pytest.mark.parametrize("text,window", [
        ("Arrived 15 minutes before sunrise.", "dawn"),
        ("Fished the afternoon session.", "afternoon"),
        ("Bite turned on in the evening.", "evening"),
    ])
    def test_bite_window(self, text, window):
        assert P.bite_window(text) == window

    def test_skunk_only_when_no_fish(self):
        assert P.skunked("We got skunked today.", 0) == 1
        # A stated catch overrides any unlucky phrasing in the prose.
        assert P.skunked("My buddy got skunked but I did fine.", 12) == 0
