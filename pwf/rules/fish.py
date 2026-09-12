"""Parse the free-text 'Total Fish/Sizes' field.

The field has no agreed format. Real examples:

    "4 LMB - 2-2.5 lbs"      "21"            "6/10-19\""     "45 under 3#"
    "18: 2 huge crappie, 16 LMB 2 -4 lbs"    "4lb x2, 2lb x1, 4 culls"
    "Fair number"            "27/10.6,8.0,6.2"

The dependable signal is that the first number is the trip total - unless it is
immediately followed by a weight or length unit, in which case it is a size and
must be skipped. Weights and lengths are pulled out separately, and explicit
"<n> <species>" pairs give the species split when a member bothered to write one.
"""
from __future__ import annotations

import re

SPECIES_ALIASES = [
    ("largemouth", r"lmb\b|largemouth|large mouth|black bass|\bl\.?m\.?\b"),
    ("smallmouth", r"smb\b|smallmouth|small mouth"),
    ("spotted_bass", r"spotted bass|spots\b|kentucky bass"),
    ("crappie", r"crappie|slab"),
    ("catfish", r"catfish|channel cat|blue cat|flathead|\bcats\b|\bcat\b"),
    ("sunfish", r"bluegill|blue gill|bream|brim\b|perch|sunfish|\bgills?\b|redear|shellcracker"),
    ("white_bass", r"white bass|sand bass|sandie|striper|hybrid|wiper"),
    ("carp", r"\bcarp\b"),
    ("gar", r"\bgar\b"),
    ("drum", r"\bdrum\b"),
    # Bare "bass" on a Texas bass club is largemouth; kept last so the more
    # specific aliases above win.
    ("largemouth", r"\bbass\b"),
]
_SPECIES_RX = [(name, re.compile(pat, re.I)) for name, pat in SPECIES_ALIASES]

_NUM = r"\d+(?:[.,]\d+)?"
_WEIGHT_UNIT = r"(?:lbs?\b|lb\b|pounds?\b|#)"
_LEN_UNIT = r"(?:\"|”|''|inch(?:es)?\b|in\b)"

# A number that is immediately followed by a unit is a size, not a count.
_SIZE_NUM = re.compile(rf"{_NUM}\s*(?:{_WEIGHT_UNIT}|{_LEN_UNIT})", re.I)
_WEIGHT = re.compile(rf"({_NUM})\s*{_WEIGHT_UNIT}", re.I)
_LENGTH = re.compile(rf"({_NUM})\s*{_LEN_UNIT}", re.I)
_COUNT_SPECIES = re.compile(
    rf"(\d+)\s*(?:[a-z]+\s+){{0,2}}?"
    rf"({'|'.join(p for _n, p in SPECIES_ALIASES)})", re.I)
_ANY_NUM = re.compile(_NUM)
# Words that mean "some fish" but carry no number.
_VAGUE = re.compile(r"\b(?:lots|bunch|many|several|plenty|fair number|"
                    r"a few|handful|numerous|good number|tons)\b", re.I)


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def parse_total_fish(raw: str | None) -> dict:
    """Return {'total','max_weight_lb','max_length_in','species':[(name,n)],'vague'}."""
    out = {"total": None, "max_weight_lb": None, "max_length_in": None,
           "species": [], "vague": False}
    if not raw or not raw.strip():
        return out
    s = raw.strip()

    weights = [_f(m.group(1)) for m in _WEIGHT.finditer(s)]
    weights = [w for w in weights if 0.1 <= w <= 25]
    if weights:
        out["max_weight_lb"] = max(weights)

    lengths = [_f(m.group(1)) for m in _LENGTH.finditer(s)]
    lengths = [ln for ln in lengths if 4 <= ln <= 40]
    if lengths:
        out["max_length_in"] = max(lengths)

    # Species splits, e.g. "18: 2 huge crappie, 16 LMB 2 -4 lbs".
    seen: dict[str, int] = {}
    for m in _COUNT_SPECIES.finditer(s):
        n = int(m.group(1))
        token = m.group(2)
        for name, rx in _SPECIES_RX:
            if rx.fullmatch(token) or rx.match(token):
                if 0 < n <= 500:
                    seen[name] = seen.get(name, 0) + n
                break
    out["species"] = sorted(seen.items(), key=lambda kv: -kv[1])

    # Trip total: first number that is not a size.
    size_spans = [m.span() for m in _SIZE_NUM.finditer(s)]
    for m in _ANY_NUM.finditer(s):
        if any(a <= m.start() < b for a, b in size_spans):
            continue
        try:
            val = _f(m.group(0))
        except ValueError:
            continue
        if val.is_integer() and 0 <= val <= 500:
            out["total"] = int(val)
            break

    if out["total"] is None and out["species"]:
        out["total"] = sum(n for _s, n in out["species"])
    if out["total"] is None and _VAGUE.search(s):
        out["vague"] = True
    return out


def species_in_text(body: str | None) -> list[str]:
    if not body:
        return []
    found = []
    for name, rx in _SPECIES_RX:
        if rx.search(body) and name not in found:
            found.append(name)
    return found
