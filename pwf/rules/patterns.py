"""Regex extractors for the narrative body.

Measured coverage on a 200-report sample: structure ~49%, bite window ~47%,
vegetation ~28%, technique ~22%, clarity ~18%, water temp ~7%. The sparse ones
are sparse because members rarely write them down, not because they are hard to
parse - so precision is the metric that matters here, not recall. Two traps
found in the sample and guarded against below:

  * bare clarity adjectives must be anchored to water/lake/pond, or
    "the launch area is large and clear" scores as clear water;
  * "cleared the water" must never match, hence \\bclear\\b with no -ed form.
"""
from __future__ import annotations

import re

_N = r"(\d+(?:\.\d+)?)"
_UNIT_FT = r"(?:feet|foot|ft\b|fow\b|'|’)"
_UNIT_IN = r"(?:inches|inch\b|in\b|\"|”)"
_VIZ = r"(?:visibility|visibilty|visbility|visability|viz|clarity|clear to|see down)"

# --- clarity ---------------------------------------------------------------
_CLARITY_NUM = [
    # Number before the word is the least ambiguous form, so try it first:
    # "<1' visbility", "7FT viz", "2 feet of visibility".
    re.compile(rf"{_N}\s*({_UNIT_FT}|{_UNIT_IN})\s*(?:of\s*)?{_VIZ}", re.I),
    # Word before the number: "visibility about 2 feet", "clear to 4'".
    # The filler must not cross a comma or full stop, or
    # "visbility, about 6' less than normal" reports the normal clarity
    # rather than the day's.
    re.compile(rf"{_VIZ}[^.,;\n]{{0,20}}?{_N}\s*(?:-|to)?\s*"
               rf"(?:\d+(?:\.\d+)?)?\s*({_UNIT_FT}|{_UNIT_IN})", re.I),
]
_CLARITY_WORDS = [
    ("gin_clear", r"gin[\s-]?clear|crystal[\s-]?clear"),
    ("clear", r"very clear|pretty clear|fairly clear|clear"),
    ("lightly_stained", r"slightly stained|lightly stained|light stain|a little stained"),
    ("stained", r"heavily stained|stained|dingy|off[\s-]?colou?r|tannic"),
    ("murky", r"murky|turbid|cloudy"),
    ("muddy", r"muddy|chocolate|mud[\s-]?hole|dirty"),
]
# The adjective must sit within a short window of a water noun.
_WATER = r"(?:water|lake|pond|tank|creek)"
_CLARITY_ANCHORED = [
    (label, re.compile(rf"(?:{_WATER}\b[^.\n]{{0,45}}?\b(?:{pat})\b)"
                       rf"|(?:\b(?:{pat})\b[^.\n]{{0,30}}?\b{_WATER}\b)", re.I))
    for label, pat in _CLARITY_WORDS
]
_CLARITY_RANK = {"gin_clear": 0, "clear": 1, "lightly_stained": 2,
                 "stained": 3, "murky": 4, "muddy": 5}

# --- water temperature -----------------------------------------------------
# Must be anchored to "water": "Temperature in the high 30s" is air temp.
_WATER_TEMP = [
    re.compile(rf"water\s*temp\w*\D{{0,18}}?{_N}\s*(?:-|to)?\s*(?:\d+)?\s*"
               rf"(?:degrees?|deg\b|°|\*?\s*f\b)?", re.I),
    re.compile(rf"water\s*(?:was|is|at)\s*{_N}\s*(?:degrees?|deg\b|°|\*?\s*f\b)", re.I),
    re.compile(rf"{_N}\s*(?:degree|°|\*)\s*(?:f\b)?\s*water", re.I),
]

# --- depth fished ----------------------------------------------------------
_DEPTH = re.compile(
    rf"\b(?:in|at|around|about|down\s+to|out\s+to|to)\s*{_N}\s*(?:-|to)?\s*"
    rf"({_N})?\s*{_UNIT_FT}(?:\s*of\s*water)?", re.I)

# --- tag vocabularies ------------------------------------------------------
VEGETATION = {
    "hydrilla": r"hydrilla",
    "milfoil": r"milfoil",
    "coontail": r"coontail",
    "lily_pads": r"lily\s*pad|lilypad|\bpads\b|lilies",
    "reeds": r"\breeds?\b|cattail|bulrush",
    "moss": r"\bmoss\b|filamentous",
    "algae": r"algae|\bscum\b",
    "duckweed": r"duckweed",
    "pepper_grass": r"pepper\s*grass",
    "mats": r"\bmats?\b|\bslop\b|matted",
    "grass_generic": r"\bgrass\b|\bweeds?\b|\bvegetation\b|\bsalad\b|\bgreenery\b",
}
_VEG_DENSITY = [
    ("heavy", r"thick|heavy|dense|matted|choked|loaded with|tons of|lots of|full of|solid"),
    ("moderate", r"some|moderate|patchy|scattered|decent|fair amount"),
    ("light", r"sparse|thin|little|minimal|not much|hardly any|starting to|minimum"),
    ("none", r"\bno\b|none|without any|died off|gone"),
]
STRUCTURE = {
    "weed_edge": r"weed\s*(?:edge|line)|grass\s*(?:edge|line)|edge of the (?:grass|weeds|hydrilla)",
    "points": r"\bpoints?\b",
    "docks": r"\bdocks?\b|boat house|boathouse|pier",
    "timber": r"timber|standing tree|dead tree|snag",
    "laydowns": r"laydown|fallen tree|blow\s*down",
    "brush": r"brush\s*pile|brushpile|\bbrush\b",
    "stumps": r"\bstumps?\b",
    "dam": r"\bdam\b|levee",
    "riprap": r"rip\s*rap|riprap|rock wall",
    "creek_channel": r"creek\s*channel|old channel|channel swing",
    "drop_off": r"drop\s*off|dropoff|\bledge\b|break line|breakline",
    "flats": r"\bflats?\b",
    "coves": r"\bcoves?\b|\bpockets?\b|back of the creek",
    "shoreline": r"shoreline|\bbank\b|shallows|\bshore\b",
    "island": r"\bisland\b",
    "spillway": r"spillway|overflow|culvert|inflow",
    "open_water": r"open water|middle of the lake|main lake",
}
TECHNIQUE = {
    "weightless": r"weightless|no weight|unweighted",
    "texas_rig": r"texas\s*rig|t-?rig\b|tx\s*rig",
    "carolina_rig": r"carolina\s*rig|c-?rig\b",
    "drop_shot": r"drop\s*shot|dropshot",
    "wacky": r"wacky",
    "neko": r"\bneko\b",
    "ned": r"\bned\b",
    "shaky_head": r"shak(?:e|y)y?\s*head",
    "punching": r"punch(?:ing|ed)?\b",
    "flipping": r"flipp?(?:ing|ed)|pitch(?:ing|ed)",
    "burning": r"burn(?:ing|ed)\s|fast retrieve|reeling fast",
    "slow_roll": r"slow\s*roll|slow\s*retriev|crawl(?:ing|ed)?\s+it",
    "dead_stick": r"dead\s*stick|let it sit|soak(?:ing|ed)?\b",
    "twitching": r"twitch(?:ing|ed)?",
    "walking": r"walk(?:ing)?\s*the\s*dog",
    "dragging": r"drag(?:ging|ged)",
    "hopping": r"hopp(?:ing|ed)|stroking",
    "pauses": r"\bpaus(?:e|es|ing|ed)\b|long pause|let it fall",
    "topwater_early": r"top\s*water early|early top",
}
BITE_WINDOW = [
    ("dawn", r"sun\s*rise|sunrise|sun\s*up|\bdawn\b|first light|before light|day\s*break|daybreak"),
    ("morning", r"\bmorning\b|\bam\b(?!\s*-)|early"),
    ("midday", r"mid\s*day|midday|\bnoon\b|lunch"),
    ("afternoon", r"afternoon"),
    ("evening", r"\bevening\b|\bdusk\b|sun\s*set|sunset|last light"),
    ("night", r"\bnight\b|after dark|\bdark\b"),
]
_SKUNK = re.compile(
    r"skunk(?:ed)?|\bno fish\b|zero fish|didn'?t catch|did not catch|"
    r"never caught|blanked|struck out|nothing to show|got\s+skunked|"
    r"no bites|not a (?:single )?(?:fish|bite)", re.I)


def _to_feet(value: float, unit: str) -> float:
    return value / 12.0 if re.match(rf"^{_UNIT_IN}$", unit.strip(), re.I) else value


def clarity_ft(body: str | None) -> float | None:
    if not body:
        return None
    for rx in _CLARITY_NUM:
        m = rx.search(body)
        if m:
            try:
                val = float(m.group(1))
            except (TypeError, ValueError):
                continue
            unit = m.group(2) or "ft"
            ft = _to_feet(val, unit)
            if 0 < ft <= 30:
                return round(ft, 2)
    return None


def clarity_label(body: str | None) -> str | None:
    if not body:
        return None
    found = [label for label, rx in _CLARITY_ANCHORED if rx.search(body)]
    if not found:
        return None
    return sorted(found, key=lambda l: _CLARITY_RANK[l])[0]


def water_temp_f(body: str | None) -> float | None:
    if not body:
        return None
    for rx in _WATER_TEMP:
        m = rx.search(body)
        if m:
            try:
                t = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if 32 <= t <= 100:
                return t
    return None


def depth_range_ft(body: str | None) -> tuple[float | None, float | None]:
    if not body:
        return None, None
    lo_all, hi_all = [], []
    for m in _DEPTH.finditer(body):
        try:
            a = float(m.group(1))
        except (TypeError, ValueError):
            continue
        b = float(m.group(2)) if m.group(2) else a
        if 0 < a <= 60 and 0 < b <= 60:
            lo_all.append(min(a, b))
            hi_all.append(max(a, b))
    if not lo_all:
        return None, None
    return min(lo_all), max(hi_all)


def bite_window(body: str | None) -> str | None:
    if not body:
        return None
    for label, pat in BITE_WINDOW:
        if re.search(pat, body, re.I):
            return label
    return None


def skunked(body: str | None, fish_total: int | None) -> int | None:
    if fish_total is not None and fish_total > 0:
        return 0
    if not body:
        return None
    return 1 if _SKUNK.search(body) else None


def _density_near(body: str, match: re.Match) -> str | None:
    window = body[max(0, match.start() - 60): match.end() + 20]
    for label, pat in _VEG_DENSITY:
        if re.search(pat, window, re.I):
            return label
    return None


def tags(body: str | None) -> list[tuple[str, str, str | None]]:
    """Return (kind, value, detail) triples for vegetation/structure/technique."""
    out: list[tuple[str, str, str | None]] = []
    if not body:
        return out
    for value, pat in VEGETATION.items():
        m = re.search(pat, body, re.I)
        if m:
            out.append(("vegetation", value, _density_near(body, m)))
    for value, pat in STRUCTURE.items():
        if re.search(pat, body, re.I):
            out.append(("structure", value, None))
    for value, pat in TECHNIQUE.items():
        if re.search(pat, body, re.I):
            out.append(("technique", value, None))
    return out
