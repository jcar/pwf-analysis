"""Parse a report detail page into a row.

Two page shapes exist and both are handled here:

  structured (~2019+)  title, author block, a <p> of "<strong>Label : </strong>value"
                       pairs, then one or more narrative <p> elements.
  legacy     (~2010-18) same title/author block, no field block, and the narrative
                       split across several <p> elements.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from selectolax.parser import HTMLParser

from .config import MISSING_MARKERS, MISSING_MAX_BYTES

FIELD_LABELS = (
    "Reservation Number",
    "Property Name",
    "Reservation Date",
    "Total Fish/Sizes",
    "Lures Used",
)
_POSTED_DATE = re.compile(r"^([A-Z][a-z]{2})\s+(\d{1,2})[ ,]+(\d{4})$")
_RES_DATE = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s*(AM|PM|All\s*Day)?", re.I
)
_MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def is_missing(html: str) -> bool:
    """Absent reports return HTTP 200 with a PHP warning page, not a 404."""
    if len(html) > MISSING_MAX_BYTES:
        return False
    return any(m in html for m in MISSING_MARKERS)


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.text(deep=True)).replace("\xa0", " ").strip()


def parse_posted_date(s: str) -> str | None:
    m = _POSTED_DATE.match((s or "").strip())
    if not m:
        return None
    mon, day, year = m.groups()
    if mon not in _MONTHS:
        return None
    try:
        return date(int(year), _MONTHS[mon], int(day)).isoformat()
    except ValueError:
        return None


def parse_reservation_date(s: str) -> tuple[str | None, str | None]:
    """'09/11/2026 AM -' -> ('2026-09-11', 'AM').  'All Day' -> 'ALL_DAY'."""
    m = _RES_DATE.search(s or "")
    if not m:
        return None, None
    mm, dd, yy, slot = m.groups()
    try:
        iso = date(int(yy), int(mm), int(dd)).isoformat()
    except ValueError:
        return None, None
    if slot:
        slot = "ALL_DAY" if re.match(r"all", slot, re.I) else slot.upper()
    return iso, slot


def _fields(container) -> dict[str, str]:
    """Pull '<strong>Label : </strong> value<br/>' pairs out of the field block."""
    out: dict[str, str] = {}
    for p in container.css("p"):
        html = p.html or ""
        if not any(lbl in html for lbl in FIELD_LABELS):
            continue
        # Split on <br> so each label/value pair is isolated.
        for chunk in re.split(r"<br\s*/?>", html, flags=re.I):
            m = re.search(
                r"<strong>\s*([^<:]+?)\s*:\s*</strong>(.*)", chunk, re.S | re.I
            )
            if not m:
                continue
            label = m.group(1).strip()
            value = HTMLParser(m.group(2)).text(deep=True)
            value = re.sub(r"\s+", " ", value).replace("\xa0", " ").strip()
            if label in FIELD_LABELS and value:
                out[label] = value
    return out


def _body(container) -> str | None:
    """Join every narrative <p>, skipping the field block and the byline."""
    parts: list[str] = []
    for p in container.css("p"):
        html = p.html or ""
        if any(lbl in html for lbl in FIELD_LABELS):
            continue
        txt = _text(p)
        if txt:
            parts.append(txt)
    body = "\n\n".join(parts).strip()
    body = re.sub(r"\s*Posted By:.*$", "", body).strip()
    return body or None


def parse(html: str, report_id: int) -> dict | None:
    """Return a report row, or None if the page is a missing-report stub."""
    if is_missing(html):
        return None
    tree = HTMLParser(html)

    h2 = tree.css_first("h2.text-dark")
    title = _text(h2) or None

    user = tree.css_first(".post_left .user")
    posted_raw = author = rank = None
    if user is not None:
        ps = user.css("p")
        posted_raw = _text(ps[0]) if ps else None
        rank = _text(ps[1]) if len(ps) > 1 else None
        author = _text(user.css_first("h3")) or None

    member_since = post_count = None
    meta = tree.css_first(".user-meta")
    if meta is not None:
        ems = [_text(e) for e in meta.css("em")]
        nums = [int(x) for x in ems if x.isdigit()]
        if nums:
            member_since = nums[0]
        if len(nums) > 1:
            post_count = nums[1]

    right = tree.css_first(".post-right")
    fields = _fields(right) if right is not None else {}
    body = _body(right) if right is not None else None

    trip_date, slot = parse_reservation_date(fields.get("Reservation Date", ""))
    gallery = tree.css_first(".report-gallery")
    photo_count = len(gallery.css("a")) if gallery is not None else 0

    return {
        "report_id": report_id,
        "title": title,
        "posted_date": parse_posted_date(posted_raw or ""),
        "author": author,
        "author_rank": rank,
        "member_since": member_since,
        "post_count": post_count,
        "reservation_number": fields.get("Reservation Number"),
        "property_name": fields.get("Property Name"),
        "trip_date": trip_date,
        "time_slot": slot,
        "total_fish_raw": fields.get("Total Fish/Sizes"),
        "lures_raw": fields.get("Lures Used"),
        "body": body,
        "photo_count": photo_count,
        "era": "structured" if fields.get("Property Name") else "legacy",
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
    }
