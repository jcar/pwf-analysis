"""Apply the rule layer to every parsed report.

Writes catches, lures, features and tags, records unmatched lure strings to the
review queue, and stores the coverage of every dimension so the CLI can always
state the sample behind a number.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime

from . import patterns as P
from .fish import parse_total_fish, species_in_text
from .lures import find_lures_in_text, parse_lures

# Dimensions available on essentially every trip vs. those that depend on a
# member having bothered to write the detail down.
FULL_TIER = {"lake", "trip_date", "fish_count", "lure_any"}


def extract_all(conn: sqlite3.Connection) -> dict:
    for t in ("catches", "report_lures", "report_features", "report_tags",
              "lure_review"):
        conn.execute(f"DELETE FROM {t}")

    catches, lures, features, tags = [], [], [], []
    review: Counter = Counter()
    cov: Counter = Counter()
    total = 0

    for r in conn.execute("SELECT * FROM reports"):
        rid, body = r["report_id"], r["body"]
        total += 1

        # --- catches --------------------------------------------------------
        fish = parse_total_fish(r["total_fish_raw"])
        species = fish["species"]
        if not species and fish["total"] is not None:
            named = species_in_text(r["total_fish_raw"]) or species_in_text(body)
            species = [(named[0] if named else "unspecified", fish["total"])]
        for name, n in species:
            catches.append((rid, name, n, fish["max_weight_lb"], r["total_fish_raw"]))
        if fish["total"] is not None:
            cov["fish_count"] += 1

        # --- lures ----------------------------------------------------------
        seen: set[tuple] = set()
        res = parse_lures(r["lures_raw"])
        for h in res.hits:
            if h.category and (h.category, h.subtype) not in seen:
                seen.add((h.category, h.subtype))
                lures.append((rid, h.raw, h.category, h.subtype, h.color, "field"))
        review.update(res.unknown)
        techs = list(res.techniques)

        if body:
            nres = find_lures_in_text(body)
            for h in nres.hits:
                if h.category and (h.category, h.subtype) not in seen:
                    seen.add((h.category, h.subtype))
                    lures.append((rid, h.raw, h.category, h.subtype, h.color,
                                  "narrative"))
            techs += [t for t in nres.techniques if t not in techs]

        if r["lures_raw"]:
            cov["lure_field"] += 1
        if res.matched:
            cov["lure_field_matched"] += 1
        if seen:
            cov["lure_any"] += 1

        # --- narrative features --------------------------------------------
        c_ft = P.clarity_ft(body)
        c_lb = P.clarity_label(body)
        wt = P.water_temp_f(body)
        d_lo, d_hi = P.depth_range_ft(body)
        bw = P.bite_window(body)
        sk = P.skunked(body, fish["total"])
        features.append((rid, c_ft, c_lb, wt, d_lo, d_hi, bw, sk))

        if c_ft is not None or c_lb:
            cov["clarity"] += 1
        if wt is not None:
            cov["water_temp"] += 1
        if d_lo is not None:
            cov["depth"] += 1
        if bw:
            cov["bite_window"] += 1
        if body:
            cov["narrative"] += 1

        # --- tags ------------------------------------------------------------
        kinds = set()
        for kind, value, detail in P.tags(body):
            tags.append((rid, kind, value, detail))
            kinds.add(kind)
        for t in techs:
            tags.append((rid, "technique", t, None))
            kinds.add("technique")
        for k in kinds:
            cov[k] += 1

    conn.executemany("INSERT INTO catches (report_id,species,n,max_weight_lb,size_note)"
                     " VALUES (?,?,?,?,?)", catches)
    conn.executemany("INSERT INTO report_lures (report_id,raw,category,subtype,color,source)"
                     " VALUES (?,?,?,?,?,?)", lures)
    conn.executemany("INSERT INTO report_features (report_id,clarity_ft,clarity_label,"
                     "water_temp_f,depth_min_ft,depth_max_ft,bite_window,skunked)"
                     " VALUES (?,?,?,?,?,?,?,?)", features)
    conn.executemany("INSERT INTO report_tags (report_id,kind,value,detail)"
                     " VALUES (?,?,?,?)", tags)
    conn.executemany("INSERT OR REPLACE INTO lure_review (raw,n) VALUES (?,?)",
                     review.items())
    conn.commit()

    _record_coverage(conn, cov, total)
    return {"reports": total, "catches": len(catches), "lures": len(lures),
            "tags": len(tags), "review_queue": len(review)}


def _record_coverage(conn: sqlite3.Connection, cov: Counter, total: int) -> None:
    conn.execute("DELETE FROM coverage_stats")
    now = datetime.now().isoformat(timespec="seconds")
    rows = []

    lake = conn.execute("SELECT COUNT(*) FROM trips WHERE lake_known=1").fetchone()[0]
    exact = conn.execute(
        "SELECT COUNT(*) FROM trips WHERE trip_date_source='reservation'").fetchone()[0]
    trips = conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] or total
    rows.append(("lake", lake, trips))
    rows.append(("trip_date_exact", exact, trips))

    for dim in ("fish_count", "lure_any", "lure_field", "lure_field_matched",
                "narrative", "clarity", "water_temp", "depth", "bite_window",
                "vegetation", "structure", "technique"):
        denom = cov["lure_field"] if dim == "lure_field_matched" else total
        rows.append((dim, cov[dim], denom))

    conn.executemany(
        "INSERT OR REPLACE INTO coverage_stats (dimension,n_with,n_total,pct,tier,computed_at)"
        " VALUES (?,?,?,?,?,?)",
        [(d, n, t, round(100 * n / t, 1) if t else 0.0,
          "full" if d in FULL_TIER or d.startswith("trip_date") or d == "lure_field_matched"
          else "partial", now) for d, n, t in rows])
    conn.commit()
