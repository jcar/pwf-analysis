"""Geocode each lake from its town. Free Open-Meteo endpoint, no API key.

Town-level precision is deliberate: weather systems are regional, and the club
publishes a town rather than coordinates. Corrections live in
data/lake_coords.csv, which is committed and always wins over the lookup.
"""
from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path

import httpx

from .config import DATA, USER_AGENT

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OVERRIDES = DATA / "lake_coords.csv"
# Club properties are all in Texas and Oklahoma. Anything else is a wrong hit -
# there is a Lancaster in California as well as in Texas, and accepting it would
# silently attach the wrong weather to every trip on that lake.
_STATES = {"Texas": 0, "Oklahoma": 1}
_STATE_CODES = {"TX": "Texas", "OK": "Oklahoma"}

# Town names repeat inside Texas too: 82 of the club's 111 towns have more than
# one Texas or Oklahoma match. Picking the most populous one is actively wrong
# here - these are private lakes on rural ranches, so the small candidate is
# usually the right one. Walnut Springs resolved to a town of 27,864 near San
# Antonio when the club's lake is in Bosque County, population 811, 170 miles
# north.
#
# The club publishes which metro each property belongs to, so where that exists
# it is the disambiguator: take the candidate nearest the stated region.
#
# Where it does not - 95 of 183 lakes, mostly retired properties whose pages are
# gone - there is no reliable signal, and guessing "nearest Dallas" is actively
# harmful: it drags genuinely distant lakes north, moving Kyle, Taylor, Vernon
# and Houston away from the real towns of those names. Those lakes fall back to
# the largest same-named town, which is right for well-known names, and any that
# remain ambiguous are marked uncertain rather than quietly trusted.
REGION_CENTRES = {
    "Dallas / Fort Worth Area": (32.78, -96.80),
    "Houston Area": (29.76, -95.37),
    "Austin Area": (30.27, -97.74),
    "San Antonio Area": (29.42, -98.49),
    "Oklahoma Area": (35.47, -97.52),
    "East Texas": (32.35, -95.30),
    "West Texas": (32.45, -99.73),
}
CLUB_CENTRE = (32.78, -96.80)


_TRUE = {"1", "y", "yes", "true", "t"}


def _load_overrides() -> dict[str, tuple[float, float]]:
    """Hand-confirmed coordinates, which beat everything else.

    Only rows marked `confirmed` count. The file also holds a dump of every
    lake's current coordinate so it can be reviewed in one place, and treating
    those dumped rows as corrections was actively harmful: it pinned each lake
    to whatever the geocoder guessed first and made later fixes no-ops. A
    coordinate is an override because a person said so, not because it is
    written down.
    """
    if not OVERRIDES.exists():
        return {}
    out = {}
    with OVERRIDES.open() as fh:
        for row in csv.DictReader(fh):
            if (row.get("confirmed") or "").strip().lower() not in _TRUE:
                continue
            try:
                out[row["lake"].strip()] = (float(row["lat"]), float(row["lon"]))
            except (KeyError, ValueError, TypeError):
                continue
    return out


def confirm(lake: str, lat: float, lon: float, note: str = "") -> None:
    """Record a hand-settled coordinate, so it survives every later re-geocode."""
    rows, seen = [], False
    if OVERRIDES.exists():
        with OVERRIDES.open() as fh:
            rows = list(csv.DictReader(fh))
    for row in rows:
        if row.get("lake", "").strip() == lake:
            row.update(lat=f"{lat:.5f}", lon=f"{lon:.5f}",
                       confirmed="yes", note=note or row.get("note", ""))
            seen = True
    if not seen:
        rows.append({"lake": lake, "town": "", "lat": f"{lat:.5f}",
                     "lon": f"{lon:.5f}", "reports": "", "uncertain": "0",
                     "confirmed": "yes", "note": note})
    cols = ["lake", "town", "lat", "lon", "reports", "uncertain", "confirmed",
            "note"]
    with OVERRIDES.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in cols})


def geocode_town(client: httpx.Client, town: str, state: str | None = None,
                 near: tuple[float, float] | None = None
                 ) -> tuple[float, float] | None:
    hit = _geocode(client, town, state, near)
    return None if hit is None else (hit["lat"], hit["lon"])


def _geocode(client: httpx.Client, town: str, state: str | None = None,
             near: tuple[float, float] | None = None,
             claims: list[dict] | None = None) -> dict | None:
    """Look up a town, accepting only Texas and Oklahoma matches.

    Common town names repeat across states *and* within Texas, so a match
    outside the club's two states is rejected outright. Among the survivors
    there are three disambiguators, in descending order of how much they can be
    trusted:

    1. **The club's own directions**, where the property page states them. These
       are a direct statement of where the lake is - "2 hours and 30 minutes
       east of Downtown Dallas ... 1 hour east of Tyler" - and two or three such
       claims triangulate a town to within a few miles. This is the only signal
       here that is actually *about the lake* rather than about the name.
    2. **The club's published region**, which narrows to a metro.
    3. **Population**, which is right for well-known names and a coin toss
       otherwise - so anything still ambiguous at this point is flagged rather
       than quietly trusted.
    """
    from .geo_shapes import miles_between
    from .geo_verify import best_candidate, score

    try:
        r = client.get(GEOCODE, params={"name": town, "count": 100,
                                        "language": "en", "format": "json"})
        results = r.json().get("results") or []
    except Exception:
        return None

    wanted = {state} if state else set(_STATES)
    cands = [r for r in results
             if r.get("country_code") == "US" and r.get("admin1") in wanted]
    if not cands:
        return None

    if claims:
        # The directions beat every other signal when they discriminate.
        pick = best_candidate(cands, claims)
        if pick is not None:
            return {"lat": pick["lat"], "lon": pick["lon"], "uncertain": False,
                    "candidates": len(cands), "source": "directions",
                    "miss": pick["miss"]}

    if near is not None:
        # A stated region: take the candidate nearest it.
        best = min(cands, key=lambda r: (
            _STATES.get(r.get("admin1", ""), 9),
            miles_between(near[0], near[1], r["latitude"], r["longitude"])))
        uncertain = False
    else:
        # No region to go on. The largest same-named town is right for
        # well-known names; flag the rest rather than pretend.
        best = max(cands, key=lambda r: (
            -_STATES.get(r.get("admin1", ""), 9), r.get("population") or 0))
        spread = max(
            miles_between(best["latitude"], best["longitude"],
                          r["latitude"], r["longitude"]) for r in cands)
        uncertain = len(cands) > 1 and spread > 25

    lat, lon = best["latitude"], best["longitude"]
    miss = None
    if claims:
        # Directions exist but could not pick a winner. If they also contradict
        # the fallback's choice, say so rather than publishing a drive distance
        # the club's own page disagrees with.
        miss = score(lat, lon, claims)["miss"]
        if miss > 0:
            uncertain = True
    return {"lat": lat, "lon": lon, "uncertain": uncertain,
            "candidates": len(cands),
            "source": "region" if near is not None else "population",
            "miss": miss}


def geocode_lakes(conn: sqlite3.Connection, force: bool = False,
                  only: set[int] | None = None) -> dict:
    """Resolve coordinates for every lake.

    The network phase runs first and the database is written afterwards: holding
    a write transaction open across HTTP calls locks out anything else using the
    database, which is fatal to a crawl running at the same time.
    """
    from .geo_verify import parse_directions

    overrides = _load_overrides()
    rows = conn.execute(
        "SELECT lake_id, name, town, slug, lat, lon, region FROM lakes"
        " ORDER BY report_count DESC").fetchall()
    if only is not None:
        rows = [r for r in rows if r["lake_id"] in only]
    # Cached property pages carry the club's own directions, which are the best
    # disambiguator available. Read once, up front, before any network work.
    from .crawl import iter_cached
    pages = {slug: doc for _u, slug, doc in iter_cached(conn, "lake")}
    stats = {"override": 0, "geocoded": 0, "cached": 0, "failed": 0,
             "no_town": 0, "uncertain": 0, "by_directions": 0}
    cache: dict[tuple, tuple[float, float] | None] = {}
    pending: list[tuple[float, float, int]] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30,
                      follow_redirects=True) as client:
        for r in rows:
            if r["name"] in overrides:
                lat, lon = overrides[r["name"]]
                # A hand-corrected coordinate is never uncertain.
                pending.append((lat, lon, 0, r["lake_id"]))
                stats["override"] += 1
                continue
            if r["lat"] is not None and not force:
                stats["cached"] += 1
                continue

            town = (r["town"] or "").strip()
            state = None
            # A few listing strings carry "<Lake>, <Town>, <ST>", which leaves a
            # bare state code in the town column.
            if town.upper() in _STATE_CODES:
                state = _STATE_CODES[town.upper()]
                town = (r["name"] or "").rsplit(",", 1)[-1].strip()
            if not town:
                stats["no_town"] += 1
                continue

            # The club's own region for this property is the best available
            # prior on which same-named town is meant.
            anchor = REGION_CENTRES.get(r["region"] or "") if r["region"] else None
            claims = (parse_directions(pages.get(r["slug"] or "", ""))
                      .get("claims") or [])
            # Two lakes on the same ranch share a page and therefore a key.
            sig = tuple((c["city"], round(c["miles"]), c["bearing"])
                        for c in claims)
            key = (town, state, anchor, sig)
            if key not in cache:
                cache[key] = _geocode(client, town, state, near=anchor,
                                      claims=claims)
                time.sleep(0.25)
            hit = cache[key]
            if hit is None:
                stats["failed"] += 1
                continue
            pending.append((hit["lat"], hit["lon"], int(hit["uncertain"]),
                            r["lake_id"]))
            stats["geocoded"] += 1
            stats["uncertain"] += int(hit["uncertain"])
            stats["by_directions"] += int(hit.get("source") == "directions")

    # Single short write transaction, after all network work is done.
    conn.executemany(
        "UPDATE lakes SET lat=?, lon=?, geo_uncertain=? WHERE lake_id=?", pending)
    conn.commit()
    return stats


def write_override_template(conn: sqlite3.Connection) -> Path:
    """Dump current coordinates for review, preserving anything confirmed."""
    keep = _load_overrides()
    rows = conn.execute(
        "SELECT name, town, lat, lon, report_count, geo_uncertain FROM lakes"
        " ORDER BY report_count DESC").fetchall()
    cols = ["lake", "town", "lat", "lon", "reports", "uncertain", "confirmed",
            "note"]
    with OVERRIDES.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            done = r["name"] in keep
            lat, lon = keep.get(r["name"], (r["lat"], r["lon"]))
            w.writerow([r["name"], r["town"] or "", lat or "", lon or "",
                        r["report_count"] or 0, int(bool(r["geo_uncertain"])),
                        "yes" if done else "",
                        "hand-confirmed" if done else ""])
    return OVERRIDES


def repair_suspect(conn: sqlite3.Connection) -> dict:
    """Re-resolve only the lakes their own property page contradicts.

    A full re-geocode would re-query every town and churn the weather join for
    lakes that were never wrong. This touches the ones the club's directions
    actually dispute, plus anything still flagged uncertain.
    """
    from .geo_verify import verify_all

    bad = {r["lake"] for r in verify_all(conn) if r["verdict"] == "suspect"}
    ids = {r["lake_id"] for r in conn.execute(
        "SELECT lake_id, name, geo_uncertain FROM lakes"
        " WHERE lat IS NOT NULL")
        if r["name"] in bad or r["geo_uncertain"]}
    if not ids:
        return {"targeted": 0}
    before = {r["lake_id"]: (r["lat"], r["lon"]) for r in conn.execute(
        "SELECT lake_id, lat, lon FROM lakes")}
    stats = geocode_lakes(conn, force=True, only=ids)
    from .geo_shapes import miles_between
    moved = [r["name"] for r in conn.execute(
        "SELECT lake_id, name, lat, lon FROM lakes WHERE lake_id IN (%s)"
        % ",".join("?" * len(ids)), tuple(ids))
        if before.get(r["lake_id"], (None, None))[0] is not None
        and miles_between(*before[r["lake_id"]], r["lat"], r["lon"]) > 5]
    stats.update(targeted=len(ids), moved=moved)
    return stats


def verified_towns(conn: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """Towns whose position is confirmed by a property page's own directions."""
    from .crawl import iter_cached
    from .geo_verify import check, parse_directions

    pages = {slug: doc for _u, slug, doc in iter_cached(conn, "lake")}
    out: dict[str, tuple[float, float]] = {}
    for r in conn.execute(
            "SELECT name, town, slug, lat, lon FROM lakes"
            " WHERE lat IS NOT NULL AND slug IS NOT NULL"
            " ORDER BY report_count DESC"):
        stated = parse_directions(pages.get(r["slug"] or "", ""))
        if not stated.get("claims"):
            continue
        if check(r["lat"], r["lon"], stated)["verdict"] != "ok":
            continue
        out.setdefault((r["town"] or "").strip().lower(), (r["lat"], r["lon"]))
    return out


def resolve_by_sibling(conn: sqlite3.Connection) -> list[dict]:
    """Settle ambiguous lakes from a same-town lake the club's directions pin.

    Most of what is left after the directions pass is a retired property whose
    page is gone, so there is nothing to check it against. But a retired lake in
    Crockett is in the same Crockett as the live property whose own page says it
    is two and a half hours from Dallas. That is real evidence, not a guess -
    the club had one town in mind - and it settles a third of the remainder
    without anyone having to look at them.
    """
    from .geo_shapes import miles_between

    pinned = verified_towns(conn)
    fixed = []
    # Also covers lakes with no coordinate at all, not only ambiguous ones: a
    # lake the club never gave a town, but which sits on a ranch whose other
    # lakes are placed, is settled by exactly the same evidence.
    for r in conn.execute(
            "SELECT lake_id, name, town, lat, lon, report_count FROM lakes"
            " WHERE geo_uncertain=1 OR lat IS NULL"
            " ORDER BY report_count DESC").fetchall():
        key = (r["town"] or "").strip().lower()
        if key not in pinned:
            continue
        lat, lon = pinned[key]
        moved = (miles_between(r["lat"], r["lon"], lat, lon)
                 if r["lat"] is not None else None)
        conn.execute("UPDATE lakes SET lat=?, lon=?, geo_uncertain=0"
                     " WHERE lake_id=?", (lat, lon, r["lake_id"]))
        fixed.append({"lake": r["name"], "town": r["town"],
                      "reports": r["report_count"] or 0,
                      "lat": lat, "lon": lon,
                      "moved": None if moved is None else round(moved, 1)})
    conn.commit()
    return fixed


def apply_waypoints(conn: sqlite3.Connection) -> dict:
    """Place every active lake from the club's own surveyed coordinates.

    This outranks everything else, including the hand-confirmed CSV, because it
    is the club's own survey rather than anybody's inference - mine or a
    member's. Retired properties are absent from the file and keep whatever the
    weaker passes worked out, marked as such.

    **Slug first, and a title never overwrites a slug match.** The first version
    fell back to the title whenever a slug missed, which quietly destroyed the
    thing it was meant to fix: the club runs two properties called "Twin Lakes",
    and the Cody Ranch one - whose slug matches no row here - fell through to
    the title and stamped its Coalgate coordinates onto the Ben Wheeler lake and
    its 389 trips. A title is claimed only when it is unambiguous among the
    properties that still need a home.
    """
    from .crawl import iter_cached
    from .geo_shapes import miles_between
    from .parse_properties import parse

    doc = next((d for _u, _r, d in iter_cached(conn, "properties")), None)
    if not doc:
        return {"error": "properties page not cached - run `pwf crawl --properties`"}
    props = parse(doc)
    if not props:
        return {"error": "no properties parsed"}

    rows = conn.execute(
        "SELECT lake_id, name, slug, lat, lon, report_count FROM lakes").fetchall()
    by_slug = {r["slug"]: r for r in rows if r["slug"]}
    by_title: dict[str, list] = {}
    for r in rows:
        by_title.setdefault(_norm_title(r["name"]), []).append(r)

    # A lake whose own slug was never resolved may still be named exactly what
    # the club's slug spells out: "Cody Ranch Twin Lakes" slugifies to
    # cody_ranch_twin_lakes. That is still a slug match, and unlike a title it
    # keeps the two Twin Lakes apart.
    from .build import slugify
    by_nameslug: dict[str, list] = {}
    for r in rows:
        by_nameslug.setdefault(slugify(r["name"]), []).append(r)

    pairs: list[tuple[dict, object]] = []
    claimed: set[int] = set()
    leftover: list[dict] = []
    for p in props:
        row = by_slug.get(p["slug"]) if p["slug"] else None
        if row is None and p["slug"]:
            cands = [r for r in by_nameslug.get(p["slug"], [])
                     if r["lake_id"] not in claimed]
            row = cands[0] if len(cands) == 1 else None
        if row is None:
            leftover.append(p)
            continue
        pairs.append((p, row))
        claimed.add(row["lake_id"])

    # Title matching only for what the slug could not place, only onto rows no
    # slug already claimed, and only where the title picks out exactly one lake
    # and exactly one property.
    titles_wanted: dict[str, int] = {}
    for p in leftover:
        titles_wanted[_norm_title(p["title"])] = \
            titles_wanted.get(_norm_title(p["title"]), 0) + 1
    ambiguous, unmatched = [], []
    for p in leftover:
        key = _norm_title(p["title"])
        cands = [r for r in by_title.get(key, []) if r["lake_id"] not in claimed]
        if titles_wanted[key] > 1 or len(cands) != 1:
            (ambiguous if cands else unmatched).append(p["title"])
            continue
        pairs.append((p, cands[0]))
        claimed.add(cands[0]["lake_id"])

    moved = []
    for p, row in pairs:
        was = None
        if row["lat"] is not None:
            was = miles_between(row["lat"], row["lon"], p["lat"], p["lon"])
        # The town on file was inferred from a listing string and can be stale
        # once the club moves a name to new water - Moonshine Lake still read
        # "Walnut Springs" while standing on Coalgate coordinates.
        town = (p.get("place") or "").split()[0:2]
        town = " ".join(town).strip() or None
        conn.execute(
            "UPDATE lakes SET lat=?, lon=?, geo_uncertain=0,"
            " coord_source='waypoint', club_id=?,"
            " town=COALESCE(?, town) WHERE lake_id=?",
            (p["lat"], p["lon"], p["club_id"], _club_town(p), row["lake_id"]))
        if was is not None and was > 0.5:
            moved.append({"lake": row["name"], "miles": round(was, 1),
                          "reports": row["report_count"] or 0})
    # Anything the club did not survey keeps its inferred position, labelled.
    conn.execute("UPDATE lakes SET coord_source='inferred'"
                 " WHERE lat IS NOT NULL AND coord_source IS NOT 'waypoint'")
    conn.commit()
    moved.sort(key=lambda m: -m["miles"])
    return {"properties": len(props), "matched": len(pairs),
            "by_slug": sum(1 for p, _ in pairs if p["slug"] in by_slug),
            "ambiguous": ambiguous, "unmatched": unmatched, "moved": moved}


def _club_town(prop: dict) -> str | None:
    """The town out of a club `place` string like "Coalgate Oklahoma"."""
    import re as _re
    place = (prop.get("place") or "").strip()
    if not place:
        return None
    # Strip the trailing region, which is the unreliable half: the club files
    # Coalgate, Oklahoma under "Dallas / Fort Worth Area".
    place = _re.split(r"\s+(?:Dallas|Houston|Austin|San Antonio|Oklahoma|East|West)\b",
                      place)[0]
    return place.strip() or None


def _norm_title(name: str | None) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", (name or "").lower())
