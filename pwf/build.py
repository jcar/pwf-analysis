"""Turn cached HTML into the analysis tables.

Runs entirely offline against ``raw_pages``; no network, no API keys. Safe to
re-run at any time - every table it owns is rebuilt from scratch.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from functools import lru_cache

from .config import DATA
from .crawl import iter_cached
from .parse_index import parse as parse_index
from .parse_report import parse as parse_report

# Median days between fishing and posting, measured on reports that state both.
POST_LAG_DAYS = 1

_SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer",
            9: "fall", 10: "fall", 11: "fall"}


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    """Report-page spellings folded onto the club's own listing name.

    A property page and a report page do not always spell a lake the same way,
    and keying lakes on the exact string split one lake into two rows - Tara
    Lake and "Tara lake", 174 reports and 40 - so each half was ranked on part
    of its own history and shrunk toward the club mean as if it were sparse.

    Kept as committed data rather than a rule, because no rule can tell the
    difference between a spelling and a second property of the same name: the
    club has two lakes called "Twin Lakes" and two called "Moonshine Lake".
    """
    path = DATA / "lake_aliases.json"
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text()).get("aliases") or {})
    except (OSError, ValueError):
        return {}


def _norm_lake(name: str | None) -> str | None:
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" .,-")
    n = re.sub(r"\s*:\s*", ": ", n)
    return _aliases().get(n, n) or None


def build_index(conn: sqlite3.Connection) -> int:
    """Parse every cached listing page into report_index."""
    conn.execute("DELETE FROM report_index")
    rows: dict[int, dict] = {}
    for _url, _ref, html in iter_cached(conn, "index"):
        for r in parse_index(html):
            r["lake_name"] = _norm_lake(r["lake_name"])
            prev = rows.get(r["report_id"])
            # Prefer the card that actually named a lake.
            if prev is None or (not prev.get("lake_name") and r.get("lake_name")):
                rows[r["report_id"]] = r
    conn.executemany(
        "INSERT OR REPLACE INTO report_index"
        " (report_id,title,lake_name,lake_town,author,posted_date,replies,views)"
        " VALUES (:report_id,:title,:lake_name,:lake_town,:author,:posted_date,"
        ":replies,:views)", list(rows.values()))
    conn.commit()
    return len(rows)


def build_reports(conn: sqlite3.Connection) -> tuple[int, int]:
    """Parse every cached report detail page into reports."""
    conn.execute("DELETE FROM reports")
    kept = skipped = 0
    batch = []
    for _url, ref, html in iter_cached(conn, "report"):
        row = parse_report(html, int(ref))
        if row is None:
            skipped += 1
            continue
        row["property_name"] = _norm_lake(row["property_name"])
        batch.append(row)
        kept += 1
        if len(batch) >= 2000:
            _flush_reports(conn, batch)
            batch = []
    if batch:
        _flush_reports(conn, batch)
    conn.commit()
    return kept, skipped


def _flush_reports(conn, batch):
    conn.executemany(
        "INSERT OR REPLACE INTO reports (report_id,title,posted_date,author,"
        "author_rank,member_since,post_count,reservation_number,property_name,"
        "trip_date,time_slot,total_fish_raw,lures_raw,body,photo_count,era,parsed_at)"
        " VALUES (:report_id,:title,:posted_date,:author,:author_rank,:member_since,"
        ":post_count,:reservation_number,:property_name,:trip_date,:time_slot,"
        ":total_fish_raw,:lures_raw,:body,:photo_count,:era,:parsed_at)", batch)


def build_lakes(conn: sqlite3.Connection) -> int:
    """Create the lake table from every lake name seen in index or reports."""
    counts: dict[str, dict] = {}

    def bump(name, town=None):
        name = _norm_lake(name)
        if not name:
            return
        e = counts.setdefault(name, {"town": None, "n": 0})
        e["n"] += 1
        if town and not e["town"]:
            e["town"] = re.sub(r"\s+", " ", town).strip(" .,-") or None

    for name, town in conn.execute(
            "SELECT lake_name, lake_town FROM report_index WHERE lake_name IS NOT NULL"):
        bump(name, town)
    for (name,) in conn.execute(
            "SELECT property_name FROM reports WHERE property_name IS NOT NULL"):
        bump(name)

    # Fold names that differ only by case, keeping the spelling seen most often.
    # "Tara Lake" and "Tara lake" were two rows holding 174 and 40 reports of one
    # lake; the alias file catches the ones already known, this stops new ones.
    folded: dict[str, dict] = {}
    for name, e in counts.items():
        key = name.casefold()
        cur = folded.get(key)
        if cur is None:
            folded[key] = {"name": name, **e}
        else:
            cur["n"] += e["n"]
            cur["town"] = cur["town"] or e["town"]
            if e["n"] > counts[cur["name"]]["n"]:
                cur["name"] = name
    counts = {v["name"]: {"town": v["town"], "n": v["n"]} for v in folded.values()}

    for name, e in counts.items():
        conn.execute(
            "INSERT INTO lakes (name, town, report_count) VALUES (?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET"
            "   town=COALESCE(lakes.town, excluded.town),"
            "   report_count=excluded.report_count",
            (name, e["town"], e["n"]))
    conn.commit()
    return len(counts)


def build_trips(conn: sqlite3.Connection) -> dict:
    """Resolve each report to a lake, a date and an effort window."""
    from .analysis import calibrate_effort, effort_hours
    from .rules.fish import parse_total_fish

    hours_by_slot = effort_hours(conn)

    conn.execute("DELETE FROM trips")
    lake_ids = {r["name"]: r["lake_id"] for r in conn.execute(
        "SELECT lake_id, name FROM lakes")}
    idx = {r["report_id"]: r for r in conn.execute(
        "SELECT report_id, lake_name, posted_date FROM report_index")}

    stats = {"total": 0, "lake_known": 0, "date_exact": 0, "with_count": 0}
    batch = []
    for r in conn.execute("SELECT * FROM reports"):
        rid = r["report_id"]
        ix = idx.get(rid)
        # Detail-page field first, then the listing card.
        lake_name = r["property_name"] or (ix["lake_name"] if ix else None)
        lake_id = lake_ids.get(lake_name) if lake_name else None

        if r["trip_date"]:
            trip_date, src = r["trip_date"], "reservation"
        else:
            # Legacy reports carry no reservation date. Measured against the
            # 2019+ reports that have both, the median gap between fishing and
            # posting is one day (the club pays a credit for reporting within
            # 24 hours): 28% post same-day, 52% the next day. Backing the
            # posted date up by POST_LAG_DAYS lands on the right day for about
            # half of them instead of about a quarter - but it is an estimate,
            # and `trip_date_source` marks it so weather-sensitive analysis can
            # exclude it.
            posted = r["posted_date"] or (ix["posted_date"] if ix else None)
            trip_date, src = None, None
            if posted:
                try:
                    trip_date = (date.fromisoformat(posted)
                                 - timedelta(days=POST_LAG_DAYS)).isoformat()
                    src = "posted_estimate"
                except ValueError:
                    trip_date, src = posted, "posted_estimate"

        fish = parse_total_fish(r["total_fish_raw"])
        hours = hours_by_slot.get(r["time_slot"] or "", None)
        fph = (fish["total"] / hours) if (fish["total"] is not None and hours) else None

        y = m = season = None
        if trip_date:
            try:
                d = date.fromisoformat(trip_date)
                y, m, season = d.year, d.month, _SEASONS[d.month]
            except ValueError:
                pass

        stats["total"] += 1
        stats["lake_known"] += bool(lake_id)
        stats["date_exact"] += (src == "reservation")
        stats["with_count"] += fish["total"] is not None

        batch.append({
            "report_id": rid, "lake_id": lake_id, "lake_known": int(bool(lake_id)),
            "trip_date": trip_date, "year": y, "month": m, "season": season,
            "time_slot": r["time_slot"], "trip_date_source": src, "hours": hours,
            "fish_total": fish["total"], "fish_per_hour": fph,
            "max_weight_lb": fish["max_weight_lb"],
        })

    conn.executemany(
        "INSERT OR REPLACE INTO trips (report_id,lake_id,lake_known,trip_date,year,"
        "month,season,time_slot,trip_date_source,hours,fish_total,fish_per_hour,"
        "max_weight_lb) VALUES (:report_id,:lake_id,:lake_known,:trip_date,:year,"
        ":month,:season,:time_slot,:trip_date_source,:hours,:fish_total,"
        ":fish_per_hour,:max_weight_lb)", batch)
    conn.commit()

    # Now that every trip's slot and catch is known, measure the real effort
    # ratio and restate the rates in place. Doing it after the insert lets a
    # fresh database converge in one pass instead of needing a second build.
    cal = calibrate_effort(conn)
    measured = effort_hours(conn)
    if measured != hours_by_slot:
        for slot, hrs in measured.items():
            conn.execute(
                "UPDATE trips SET hours=?,"
                " fish_per_hour = CASE WHEN fish_total IS NULL THEN NULL"
                "                      ELSE fish_total / ? END"
                " WHERE time_slot=?", (hrs, hrs, slot))
        conn.commit()
    stats["all_day_hours"] = measured["ALL_DAY"]
    stats["effort_source"] = cal["source"]
    return stats


def slugify(name: str) -> str:
    """Lake name -> URL slug, matching the site's own convention."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def lake_variant_map(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Candidate slugs per lake, busiest lake first."""
    return {r["name"]: _slug_variants(r["name"])
            for r in conn.execute(
                "SELECT name FROM lakes ORDER BY report_count DESC")}


@lru_cache(maxsize=1)
def _site_slugs() -> dict[str, tuple[str, ...]]:
    """Authoritative name -> slug pairs harvested from the site's own property
    listing endpoint. The site's slugs are not always derivable from the name
    ("Beaver Lake: Heartland 10-10 Ranch" is `heartland_beaver_2`), so these
    win over anything guessed.

    A display name is not unique: the club runs two properties called "Twin
    Lakes", one at Cody Ranch in Coalgate, Oklahoma and one in Ben Wheeler,
    Texas. Inverting the file into a plain name -> slug dict silently kept
    whichever came last and dropped the other, so every value is a tuple.
    """
    path = DATA / "site_slugs.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    out: dict[str, list[str]] = {}
    for slug, name in raw.items():
        out.setdefault(re.sub(r"[^a-z0-9]", "", name.lower()), []).append(slug)
    return {k: tuple(v) for k, v in out.items()}


def _slug_variants(name: str) -> list[str]:
    """The site is inconsistent, so try a few plausible spellings."""
    known = list(_site_slugs().get(re.sub(r"[^a-z0-9]", "", name.lower()), ()))
    base = slugify(name)
    # Prefer a slug the club itself published, then the guess.
    variants = known + [base] if known else [base]
    # "Dogwood Lakes Estate: East Lake" also appears as just its second half.
    if ":" in name:
        tail = slugify(name.split(":", 1)[1])
        head = slugify(name.split(":", 1)[0])
        variants += [tail, head]
    # Some properties drop a trailing generic word.
    for suffix in ("_lake", "_lakes", "_ranch", "_farms"):
        if base.endswith(suffix):
            variants.append(base[: -len(suffix)])
    return [v for v in variants if v]


def build_lake_details(conn: sqlite3.Connection) -> dict:
    """Merge parsed lake property pages into the lakes table."""
    from .parse_lake import parse as parse_lake

    names = {r["name"].lower(): r["name"] for r in conn.execute("SELECT name FROM lakes")}
    stats = {"pages": 0, "matched": 0, "unmatched": 0}

    for _url, slug, html in iter_cached(conn, "lake"):
        info = parse_lake(html, slug)
        if not info:
            continue
        stats["pages"] += 1

        target = None
        # Exact match only. An earlier `slug in slugify(cand)` let a short slug
        # claim a longer, differently-named lake: the Ben Wheeler page at
        # `twin_lakes` matched "Cody Ranch Twin Lakes" and stamped its slug,
        # acreage and day rate onto a property 200 miles away in Coalgate,
        # Oklahoma - which then looked like proof the two were one lake.
        for cand in names:
            if slugify(cand) == slug:
                target = names[cand]
                break
        if target is None:
            # The club's own listing knows slugs that are not derivable from
            # the name, so consult it rather than guessing at substrings.
            for cand in names:
                key = re.sub(r"[^a-z0-9]", "", cand)
                if slug in _site_slugs().get(key, ()):
                    target = names[cand]
                    break
        if target is None and info.get("name"):
            # Property pages title themselves "Town, Lake Name".
            tail = info["name"].split(",")[-1].strip().lower()
            target = names.get(tail)
        if target is None:
            stats["unmatched"] += 1
            continue

        conn.execute(
            "UPDATE lakes SET slug=?, acres=COALESCE(?,acres),"
            " max_depth_ft=COALESCE(?,max_depth_ft),"
            " membership_tier=COALESCE(?,membership_tier),"
            " bank_fishing=COALESCE(?,bank_fishing), boat_type=COALESCE(?,boat_type),"
            " day_rate=COALESCE(?,day_rate), half_day_rate=COALESCE(?,half_day_rate),"
            " region=COALESCE(?,region), harvest_rules=COALESCE(?,harvest_rules)"
            " WHERE name=?",
            (slug, info["acres"], info["max_depth_ft"], info["membership_tier"],
             info["bank_fishing"], info["boat_type"], info["day_rate"],
             info["half_day_rate"], info["region"], info["harvest_rules"], target))
        stats["matched"] += 1
    conn.commit()
    return stats


def merge_alias_rows(conn: sqlite3.Connection) -> list[dict]:
    """Fold already-stored variant rows onto their canonical lake.

    A rebuild would produce the right rows from scratch, but the database
    carries hand-settled coordinates and a weather backfill that cost a day of
    API budget, so the split is repaired in place instead.
    """
    merged = []
    for variant, canonical in _aliases().items():
        v = conn.execute("SELECT lake_id, report_count FROM lakes WHERE name=?",
                         (variant,)).fetchone()
        c = conn.execute("SELECT lake_id, report_count FROM lakes WHERE name=?",
                         (canonical,)).fetchone()
        if not v or not c or v["lake_id"] == c["lake_id"]:
            continue
        moved = conn.execute("SELECT COUNT(*) n FROM trips WHERE lake_id=?",
                             (v["lake_id"],)).fetchone()["n"]
        conn.execute("UPDATE trips SET lake_id=? WHERE lake_id=?",
                     (c["lake_id"], v["lake_id"]))
        # Conditions are one row per lake-day; keep the canonical lake's.
        conn.execute(
            "INSERT OR IGNORE INTO conditions"
            " SELECT ? AS lake_id, date, temp_max_f, temp_min_f, temp_mean_f,"
            "  temp_7d_mean_f, precip_in, wind_max_mph, wind_dir_deg, cloud_pct,"
            "  pressure_hpa, pressure_delta_24h, pressure_delta_48h,"
            "  pressure_trend, moon_phase, moon_illum, sunrise, sunset,"
            "  day_length_h FROM conditions WHERE lake_id=?",
            (c["lake_id"], v["lake_id"]))
        conn.execute("DELETE FROM conditions WHERE lake_id=?", (v["lake_id"],))
        conn.execute("DELETE FROM lakes WHERE lake_id=?", (v["lake_id"],))
        total = conn.execute("SELECT COUNT(*) n FROM trips WHERE lake_id=?",
                             (c["lake_id"],)).fetchone()["n"]
        conn.execute("UPDATE lakes SET report_count=? WHERE lake_id=?",
                     (total, c["lake_id"]))
        merged.append({"variant": variant, "canonical": canonical,
                       "trips_moved": moved, "canonical_trips": total})
    conn.commit()
    return merged
