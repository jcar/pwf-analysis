"""A plain-language summary of what members report about a lake.

Two parts, both computed - no model reads anything here.

1. **Narrated statistics.** The profile's own numbers turned into sentences, so
   the headline facts read the way a person would say them.

2. **Distinctive mentions.** Words and short phrases that show up far more often
   in one lake's reports than across the club, scored by log-odds against the
   club baseline. This is what surfaces the things no fixed vocabulary would
   have thought to look for - that members keep mentioning the pontoon's
   batteries at one lake, bald eagles at another, the spillway at a third.

Two hard rules on the phrase mining:

* **Member names never appear.** Every token of every author name in the archive
  is blocked outright. A recurring phrase is a statistic about language across
  many reports; a name is a person.
* **Nothing is quoted.** Only fragments of one or two words, and only when at
  least six separate reports contain them - a pattern, never somebody's sentence.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from functools import lru_cache

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# Words that carry no information about a lake.
STOP = set("""
a an the and or but if then than that this these those there here it its it's
of in on at to from by for with without into onto up down out over under again
was were is are be been being am i we you he she they them us our my your his her
their not no nor so as too also just only really quite much many some few more
most had has have having do does did doing would could should will can may might
must about after before during while when where which who whom what how why all
any each every other another same such own off around back through between both
either neither got get getting gets went go going goes come came coming
day days today morning afternoon evening night tomorrow yesterday week weekend
trip trips time times hour hours minute minutes first second third last next
one two three four five six seven eight nine ten couple several
lake lakes pond ponds water waters fish fishes fishing fished caught catch
catching bass day good great nice better best little bit lot lots pretty well
area right left side end top bottom near far close long short big small
made make makes making take takes took think thought know knew like liked want
wanted need needed say said says tell told thanks thank looking looked look
start started starting ended ending finish finished nothing everything something
anything able tried try trying put putting kept keep still ever never always
much more less enough sure maybe probably definitely usually mostly majority
lots plenty bunch rest total overall around about almost nearly
guy guys man men friend friends buddy son dad wife family group folks member
members guest guests kid kids boy girl
back front middle main north south east west
stay stayed staying came come gone went
year years month months season seasons
mine ours theirs yours
pro wade cast casts casting square majority slower stacked chat sized
size sizes decent solid quality average
""".split())

# Fragments that are artefacts of writing, not observations.
_JUNK = re.compile(r"\d|^[a-z]{1,2}$|^(am|pm)$")


@lru_cache(maxsize=1)
def _blocked(db_path: str) -> frozenset:
    """Author names and lake/town names. Neither tells you anything about the
    fishing, and the first must never be published."""
    import sqlite3 as s3
    conn = s3.connect(db_path)
    out = set()
    for (author,) in conn.execute(
            "SELECT DISTINCT author FROM reports WHERE author IS NOT NULL"):
        for part in re.split(r"[^A-Za-z']+", author.lower()):
            if len(part) > 2:
                out.add(part)
    for name, town in conn.execute("SELECT name, town FROM lakes"):
        for src in (name or "", town or ""):
            # Block both spellings. "JerMar Lake" is written "jermar" by some
            # members and "jer mar" by others, so the camel-case split has to
            # be blocked alongside the original, not instead of it.
            spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", src)
            for variant in (src, spaced):
                for part in re.split(r"[^A-Za-z']+", variant.lower()):
                    if len(part) > 2:
                        out.add(part)
    conn.close()
    return frozenset(out)


def _tokens(text: str, blocked: frozenset) -> list[str]:
    text = re.sub(r"[^a-z0-9' ]", " ", text.lower())
    return [w for w in text.split()
            if len(w) > 2 and w not in STOP and w not in blocked
            and not _JUNK.search(w)]


def _phrases(text: str, blocked: frozenset) -> set[str]:
    ws = _tokens(text, blocked)
    out = set(ws)
    out.update(f"{ws[i]} {ws[i+1]}" for i in range(len(ws) - 1))
    return out


def mention_index(conn: sqlite3.Connection, db_path: str) -> dict:
    """Count, per lake and club-wide, how many reports contain each phrase."""
    blocked = _blocked(db_path)
    rows = conn.execute(
        "SELECT l.name AS lake, r.body FROM reports r"
        " JOIN trips t ON t.report_id = r.report_id"
        " JOIN lakes l ON l.lake_id = t.lake_id"
        " WHERE r.body IS NOT NULL AND t.lake_known = 1").fetchall()
    club: Counter = Counter()
    per_lake: dict[str, Counter] = {}
    lake_n: Counter = Counter()
    for r in rows:
        ph = _phrases(r["body"], blocked)
        club.update(ph)
        lake_n[r["lake"]] += 1
        per_lake.setdefault(r["lake"], Counter()).update(ph)
    return {"club": club, "per_lake": per_lake, "lake_n": lake_n,
            "total": len(rows)}


def distinctive_mentions(index: dict, lake: str, limit: int = 10,
                         min_reports: int = 6, min_share: float = 0.04,
                         min_lift: float = 0.35) -> list[dict]:
    """Phrases this lake's reports carry far more often than the club's.

    Scored by log-odds against the club baseline, then weighted by how many
    reports back the phrase so a lucky handful cannot outrank a real pattern.
    """
    counts = index["per_lake"].get(lake)
    if not counts:
        return []
    n = index["lake_n"][lake]
    club, total = index["club"], index["total"]

    scored = []
    for phrase, cnt in counts.items():
        if cnt < min_reports or cnt / n < min_share:
            continue
        lift = math.log(((cnt + 0.5) / (n + 1)) / ((club[phrase] + 0.5) / (total + 1)))
        if lift <= min_lift:
            continue
        scored.append({"phrase": phrase, "reports": int(cnt), "of": int(n),
                       "share": round(100 * cnt / n, 1),
                       "times_club": round(math.exp(lift), 1),
                       "_score": lift * math.log1p(cnt)})
    scored.sort(key=lambda d: -d["_score"])

    # Drop a phrase already covered by a stronger one - either contained in it
    # ("island" under "island point") or the same word in another number
    # ("battery" beside "batteries") - so the list reads as distinct
    # observations rather than variants of one.
    kept: list[dict] = []
    for d in scored:
        if any(d["phrase"] in k["phrase"] or k["phrase"] in d["phrase"]
               or _stem(d["phrase"]) == _stem(k["phrase"])
               for k in kept):
            continue
        d.pop("_score")
        kept.append(d)
        if len(kept) >= limit:
            break
    return kept


def _stem(phrase: str) -> str:
    """Crude singularisation, enough to collapse plural variants."""
    out = []
    for w in phrase.split():
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("es") and len(w) > 4 and w[-3] in "sxzh":
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        out.append(w)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# Narrated statistics
# --------------------------------------------------------------------------- #
def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


# Prior strength, in trips, pulling a month toward the lake's own average.
MONTH_SHRINK_K = 8.0
MIN_MONTH_TRIPS = 5


def _month_sentence(profile) -> str | None:
    """Rank months on a shrunk rate, not a raw one.

    A six-trip January can post the highest raw median at a lake fished two
    hundred times, and crowning it would be the same small-sample mistake the
    rest of the system is careful to avoid. Each month is pulled toward the
    lake's own overall rate in proportion to how little backs it.
    """
    months = [m for m in profile["by_month"]
              if m["n"] >= MIN_MONTH_TRIPS and m["median"]]
    if len(months) < 4:
        return None
    overall = profile["rate"]["median"] or 0.0
    for m in months:
        m["_adj"] = ((m["n"] * m["median"] + MONTH_SHRINK_K * overall)
                     / (m["n"] + MONTH_SHRINK_K))
    ranked = sorted(months, key=lambda m: -m["_adj"])
    best, worst = ranked[0], ranked[-1]
    runners = [m for m in ranked[1:3] if m["_adj"] > overall]
    also = (" " + " and ".join(MONTHS[m["m"] - 1] for m in runners) +
            (" also run" if len(runners) > 1 else " also runs") +
            " well.") if runners else ""
    return (f"Fishes best in {MONTHS[best['m'] - 1]} — {best['median']} fish an hour "
            f"across {best['n']} {_plural(best['n'], 'trip')} — and slowest in "
            f"{MONTHS[worst['m'] - 1]} at {worst['median']} over "
            f"{worst['n']}.{also}")


def _rate_sentence(profile) -> str:
    r, v = profile["rate"], profile["volume"]
    pct = ""
    if r["percentile"] is not None:
        where = ("near the top of the club" if r["percentile"] >= 80 else
                 "above average" if r["percentile"] >= 60 else
                 "about average" if r["percentile"] >= 40 else
                 "below average")
        pct = f", which puts it {where}"
    return (f"Across {v['scored']} {_plural(v['scored'], 'trip')} with a countable "
            f"catch, this lake runs {r['median']} fish an hour against a club median "
            f"of {r['club_median']}{pct}.")


def _fish_sentence(profile) -> str | None:
    f = profile["fish"]
    parts = []
    if f["median_fish_per_trip"]:
        parts.append(f"A typical trip brings {f['median_fish_per_trip']:.0f} fish")
    if f["best_lb"]:
        big = (f", and {f['over_5lb_rate']:.0f}% of the trips that mention a size "
               f"report a five-pounder" if f["over_5lb_rate"] else "")
        parts.append(f"the heaviest on record is {f['best_lb']} lb{big}")
    if not parts:
        return None
    s = "; ".join(parts) + "."
    if f["species"] and len(f["species"]) > 1 and f["species"][0]["pct"] < 90:
        others = [x for x in f["species"][1:3] if x["pct"] >= 5]
        if others:
            listed = " and ".join(f"{x['species'].replace('_', ' ')} {x['pct']:.0f}%"
                                  for x in others)
            s += f" It is not only a bass lake: {listed} of the fish members identify."
    return s


def _water_sentence(profile) -> str | None:
    w = profile["water"]
    bits = []
    if w["clarity_ft_median"] is not None:
        bits.append(f"clarity around {w['clarity_ft_median']} ft "
                    f"(mentioned in {w['clarity_ft_n']} reports)")
    if w["veg_mention_rate"]:
        top = w["vegetation"][0]["value"].replace("_", " ") if w["vegetation"] else None
        veg = f"vegetation comes up in {w['veg_mention_rate']:.0f}% of reports"
        if top and top != "grass generic":
            veg += f", most often {top}"
        bits.append(veg)
    if not bits:
        return None
    s = "Members who describe the water report " + "; ".join(bits) + "."
    if w["structure"]:
        names = [x["value"].replace("_", " ") for x in w["structure"][:3]]
        s += " The cover they name most is " + ", ".join(names) + "."
    return s


def _bait_sentence(profile) -> str | None:
    baits = profile["baits"]["overall"]
    if not baits:
        return None
    up = [b for b in baits if b["lift"] and b["lift"] >= 1.05][:3]
    down = [b for b in baits if b["lift"] and b["lift"] <= 0.92][-2:]
    parts = []
    if up:
        parts.append("above this lake's own baseline: " + ", ".join(
            f"{b['bait'].replace('_', ' ')} ({b['lift']:.2f}x over {b['n']} trips)"
            for b in up))
    if down:
        parts.append("below it: " + ", ".join(
            f"{b['bait'].replace('_', ' ')} ({b['lift']:.2f}x)" for b in down))
    if not parts:
        return None
    seasons = profile["baits"].get("by_season") or {}
    tail = ""
    if seasons:
        tail = (" By season, the leader is "
                + ", ".join(f"{s} {r[0]['bait'].replace('_', ' ')}"
                            for s, r in seasons.items() if r) + ".")
    return "Baits have run " + "; ".join(parts) + "." + tail


def _technique_sentence(profile) -> str | None:
    tech = profile["water"].get("technique") or []
    if not tech:
        return None
    names = [t["value"].replace("_", " ") for t in tech[:3]]
    return ("The presentations members write down most often are "
            + ", ".join(names) + ".")


def _caveat(profile) -> str | None:
    v = profile["volume"]
    if v["confidence"] in ("thin", "very thin"):
        return (f"Only {v['scored']} {_plural(v['scored'], 'trip')} here carry a "
                f"countable catch, so read all of this as a hint rather than a "
                f"measurement.")
    return None


def summarize(profile: dict, mentions: list[dict] | None = None) -> dict:
    """Assemble the summary for one lake."""
    paras = [s for s in (
        _rate_sentence(profile),
        _month_sentence(profile),
        _fish_sentence(profile),
        _water_sentence(profile),
        _bait_sentence(profile),
        _technique_sentence(profile),
    ) if s]

    mention_line = None
    if mentions:
        mention_line = ("Things members bring up here far more than at other club "
                        "lakes: " + ", ".join(m["phrase"] for m in mentions[:8]) + ".")

    return {
        "paragraphs": paras,
        "mentions": mentions or [],
        "mention_line": mention_line,
        "caveat": _caveat(profile),
    }
