"""Parse a /view-property/<slug> page for lake attributes."""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

_NUM = r"(\d+(?:\.\d+)?)"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").replace("\xa0", " ").strip()


def parse(html: str, slug: str) -> dict | None:
    tree = HTMLParser(html)
    text = _clean(tree.text(deep=True))
    if "Property Info" not in text and "Fishing Locations" not in text:
        return None

    h1 = tree.css_first("h1") or tree.css_first("h2")
    name = _clean(h1.text()) if h1 is not None else None

    # Lake pages embed recent fishing reports below the description. Depth and
    # acreage must come from the description only, or "deep diving crank" in a
    # member's lure list gets read as lake depth.
    # Cut at the first embedded report. "Fishing Reports" is unusable as a
    # marker because it also appears in the nav above the description;
    # "Reservation Number" only ever appears inside a member's report.
    info = re.split(r"Reservation Number", text, maxsplit=1)[0]

    def after(label: str, window: int = 120) -> str | None:
        m = re.search(re.escape(label) + r"\s*(.{0,%d})" % window, text, re.I)
        return _clean(m.group(1)) if m else None

    acres = None
    m = re.search(rf"{_NUM}\s*(?:\+/-\s*)?acres?", info, re.I)
    if m:
        try:
            acres = float(m.group(1))
        except ValueError:
            acres = None

    # Members and copywriters phrase depth a dozen ways: "depths reaching 45
    # feet", "depths of up to 28 feet", "deep pockets (up to 32 feet)",
    # "ranging from 6-8 feet", "under 6 feet deep". Take the deepest match.
    depth_pats = [
        rf"depths?[^.\d]{{0,28}}?{_NUM}\s*(?:-|to|–|—)?\s*(?:\d+(?:\.\d+)?)?\s*(?:feet|foot|ft)\b",
        rf"(?:deep|depth)[^.\d]{{0,24}}?\({{0,1}}\s*up to\s*{_NUM}\s*(?:feet|foot|ft)\b",
        rf"{_NUM}\s*(?:feet|foot|ft)\s*(?:deep|in depth|of depth)\b",
    ]
    found = []
    for pat in depth_pats:
        for m in re.finditer(pat, info, re.I):
            try:
                v = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if 2 <= v <= 120:
                found.append(v)
    depth = max(found) if found else None

    def money(label: str) -> float | None:
        m = re.search(re.escape(label) + r"\D{0,30}?\$\s*([\d,]+(?:\.\d+)?)", text, re.I)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    tier = None
    m = re.search(r"(Gold and Silver Members|Gold Member[s]? (?:Only|Exclusive)|"
                  r"All Members|Silver Members)", text, re.I)
    if m:
        tier = _clean(m.group(1))

    boat = after("Boat Availability", 80)
    if boat:
        boat = re.split(r"Boat Launch|Tent Camping|Property Info", boat)[0].strip()
    region = None
    m = re.search(r"(Dallas\s*/\s*Fort Worth Area|Houston Area|Austin Area|"
                  r"San Antonio Area|Oklahoma Area|East Texas|West Texas)", text, re.I)
    if m:
        region = _clean(m.group(1))

    harvest = None
    m = re.search(r"(Please harvest[^.]{0,200}\.)", text, re.I)
    if m:
        harvest = _clean(m.group(1))

    return {
        "slug": slug,
        "name": name,
        "acres": acres,
        "max_depth_ft": depth,
        "membership_tier": tier,
        "bank_fishing": 1 if re.search(r"Bank fishing is available", text, re.I)
        else (0 if re.search(r"Bank fishing is not available", text, re.I) else None),
        "boat_type": boat,
        "day_rate": money("Day Rate"),
        "half_day_rate": money("Half-Day Rate"),
        "region": region,
        "harvest_rules": harvest,
    }
