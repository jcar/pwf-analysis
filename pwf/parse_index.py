"""Parse a listing page (/forums/reports/all/<offset>) into report cards.

This is the source of lake attribution. Listing cards carry
``Property : <Lake>, <Town>`` for reports back to roughly mid-2012, whereas the
detail pages only gained a Property Name field around 2019. Reading the lake off
the index avoids guessing it from prose, which was measured to be unreliable.
"""
from __future__ import annotations

import re
from datetime import date

from selectolax.parser import HTMLParser

_REPORT_ID = re.compile(r"view_report/(\d+)")
_PROPERTY = re.compile(r"Property\s*:\s*([^\n<]{2,90})")
_STARTED = re.compile(
    r"Started\s*By\s*:\s*(.*?)\s*,\s*([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4})", re.S
)
_CARD_DATE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})")
_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").replace("\xa0", " ").strip()


def _card_date(s: str) -> str | None:
    m = _CARD_DATE.search(s or "")
    if not m:
        return None
    mon, day, year = m.groups()
    if mon not in _MONTHS:
        return None
    try:
        return date(int(year), _MONTHS[mon], int(day)).isoformat()
    except ValueError:
        return None


def split_property(s: str) -> tuple[str | None, str | None]:
    """'Dogwood Lakes Estate: East Lake, Henderson' -> (lake, town).

    Split on the final comma: several lake names contain a colon, and a few
    carry stray whitespace before the comma.
    """
    s = _clean(s)
    if not s:
        return None, None
    if "," in s:
        name, town = s.rsplit(",", 1)
        return _clean(name) or None, _clean(town) or None
    return s, None


def _int_after(node, label: str) -> int | None:
    if node is None:
        return None
    m = re.search(re.escape(label) + r"\s*:?\s*</span>\s*(\d+)", node.html or "")
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*$", _clean(node.text()))
    return int(m.group(1)) if m else None


def parse(html: str) -> list[dict]:
    """Return one dict per report card on the page."""
    tree = HTMLParser(html)
    out: dict[int, dict] = {}

    for row in tree.css(".divTableRow"):
        summary = row.css_first(".table-summary")
        if summary is None:
            continue
        link = summary.css_first("a[href*='view_report']")
        if link is None:
            continue
        m = _REPORT_ID.search(link.attributes.get("href", ""))
        if not m:
            continue
        rid = int(m.group(1))

        block = summary.html or ""
        text = _clean(HTMLParser(block).text(deep=True))

        lake = town = None
        pm = _PROPERTY.search(block) or _PROPERTY.search(text)
        if pm:
            lake, town = split_property(pm.group(1))

        author = None
        posted = None
        sm = _STARTED.search(text)
        if sm:
            author = _clean(sm.group(1)) or None
            posted = _card_date(sm.group(2))
        if posted is None:
            posted = _card_date(text)

        out[rid] = {
            "report_id": rid,
            "title": _clean(link.text()) or None,
            "lake_name": lake,
            "lake_town": town,
            "author": author,
            "posted_date": posted,
            "replies": _int_after(row.css_first(".table-replies"), "Replies"),
            "views": _int_after(row.css_first(".table-views"), "Views"),
        }

    return list(out.values())


def max_report_id(html: str) -> int | None:
    ids = [int(m) for m in _REPORT_ID.findall(html)]
    return max(ids) if ids else None
