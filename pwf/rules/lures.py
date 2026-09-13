"""Map free-text lure strings onto the taxonomy in lures.yaml.

Members write the same bait many ways, mix colours into the name, and often
name a rig instead of a bait. The matcher therefore:

  1. splits the field on separators that are never part of a bait name
     (``and`` is *not* one of them - "black and blue" is a colour),
  2. strips and records colours,
  3. records rigs as techniques, and
  4. scans for every bait term in the remainder, longest phrase first.

Anything that yields no category and is not a known filler word goes to the
review queue rather than being dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).parent / "lures.yaml"
# "and" is deliberately absent: it appears inside colour names.
_SPLIT = re.compile(r"[;,/+|\n]|\bthen\b|\balso\b", re.I)
_PUNCT = re.compile(r"[^a-z0-9\s\"'.-]")
_WS = re.compile(r"\s+")


@dataclass
class LureHit:
    raw: str
    category: str | None = None
    subtype: str | None = None
    color: str | None = None


@dataclass
class LureResult:
    hits: list[LureHit] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return any(h.category for h in self.hits)


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    data = yaml.safe_load(TAXONOMY_PATH.read_text())

    def phrase_re(p: str) -> re.Pattern:
        # Tolerate plural 's' and internal spacing/hyphen variation.
        body = r"[\s-]*".join(re.escape(w) for w in p.split())
        return re.compile(rf"\b{body}s?\b", re.I)

    colors = sorted(data["colors"], key=len, reverse=True)
    terms = []
    for entry in data["terms"]:
        for p in entry["match"]:
            terms.append((p, phrase_re(p), entry["category"], entry["subtype"]))
    # Longest surface form wins, so "swim jig" beats "jig".
    terms.sort(key=lambda t: len(t[0]), reverse=True)

    techs = []
    for entry in data["techniques"]:
        for p in entry["match"]:
            techs.append((p, phrase_re(p), entry["name"], entry.get("implies")))
    techs.sort(key=lambda t: len(t[0]), reverse=True)

    return {
        "colors": [(c, phrase_re(c)) for c in colors],
        "terms": terms,
        "techniques": techs,
        "ambiguous": {a.lower() for a in data["ambiguous"]},
    }


def normalize(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def split_parts(raw: str) -> list[str]:
    return [p.strip(" .-\"'") for p in _SPLIT.split(raw or "") if p.strip(" .-\"'")]


def parse_lures(raw: str | None, source: str = "field") -> LureResult:
    """Parse a 'Lures Used' field (or a narrative sentence) into hits.

    Bait terms are matched *before* colours are stripped. Several words are both
    ("craw", "shad", "yellow"), and taking the colour first destroyed the bait:
    "Rage Craw" became "rage" and "Yellow Magic" became "magic", each matching
    nothing. A bait name is the more specific reading, so it wins; whatever
    survives is then searched for a colour.
    """
    res = LureResult()
    if not raw:
        return res
    tax = _taxonomy()

    for part in split_parts(raw):
        text = normalize(part)
        if not text:
            continue
        # A bare number ("0", "50") names no bait; it is filler, not a term the
        # taxonomy is missing.
        if text in tax["ambiguous"] or text.isdigit():
            res.ambiguous.append(part.strip())
            continue

        # 1. rigs and presentations
        implied = None
        for _p, rx, name, implies in tax["techniques"]:
            if rx.search(text):
                if name not in res.techniques:
                    res.techniques.append(name)
                text = rx.sub(" ", text).strip()
                implied = implied or implies

        # 2. bait terms, longest surface form first
        found: list[LureHit] = []
        consumed = text
        for _p, rx, cat, sub in tax["terms"]:
            m = rx.search(consumed)
            if not m:
                continue
            found.append(LureHit(part.strip(), cat, sub, None))
            consumed = (consumed[: m.start()] + " " + consumed[m.end():]).strip()

        # 3. colour, from whatever the bait terms did not consume
        color = None
        haystack = consumed if found else text
        for name, rx in tax["colors"]:
            if rx.search(haystack):
                color = name
                consumed = rx.sub(" ", consumed).strip()
                break
        for h in found:
            h.color = color
        res.hits.extend(found)

        if not found:
            if implied:
                res.hits.append(LureHit(part.strip(), implied, "unspecified", color))
                continue
            leftover = _WS.sub(" ", consumed).strip()
            if not leftover:
                if color:
                    res.hits.append(LureHit(part.strip(), None, None, color))
            elif leftover in tax["ambiguous"]:
                res.ambiguous.append(part.strip())
            else:
                res.unknown.append(part.strip())

    _dedupe(res)
    return res


def _dedupe(res: LureResult) -> None:
    """Drop a generic 'unspecified' hit when the same category also named a
    specific subtype, so "topwater poppers" counts once, not twice."""
    specific = {h.category for h in res.hits
                if h.category and h.subtype not in (None, "unspecified")}
    res.hits = [h for h in res.hits
                if not (h.category in specific and h.subtype == "unspecified")]
    seen, out = set(), []
    for h in res.hits:
        key = (h.category, h.subtype, h.color)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    res.hits = out


def find_lures_in_text(body: str | None) -> LureResult:
    """Scan a narrative for bait mentions. Recovers lures for the pre-2019 era."""
    res = LureResult()
    if not body:
        return res
    tax = _taxonomy()
    text = normalize(body)
    seen: set[tuple] = set()
    for _p, rx, cat, sub in tax["terms"]:
        for m in rx.finditer(text):
            key = (cat, sub)
            if key in seen:
                break
            seen.add(key)
            res.hits.append(LureHit(m.group(0).strip(), cat, sub, None))
            break
    for _p, rx, name, _implies in tax["techniques"]:
        if rx.search(text) and name not in res.techniques:
            res.techniques.append(name)
    _dedupe(res)
    return res
