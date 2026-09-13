# pwf-analysis

Turns the Private Water Fishing club's member report archive into something you can
actually query, so you can work out what produces on small, clear, grassy Texas water.

**No LLM anywhere in the pipeline.** Every figure comes from rules, regex and
arithmetic that run offline in minutes, cost nothing, and give the same answer every
time. Re-running after a rule change is free, which is what makes tuning the lure
taxonomy practical.

## What it does

1. **Crawls** the public report pages once (13,672 reports, 2010–2026) and caches the
   raw HTML, so no later step ever needs the network again.
2. **Parses** two page shapes: the structured reports (2019+, which *may* carry
   `Lures Used` and `Total Fish/Sizes` fields — those are optional and about 58% of
   all reports fill them in) and the legacy narrative-only ones.
3. **Attributes lakes from the listing index**, which carries `Property : <Lake>,
   <Town>` back to mid-2012 — years before the detail pages gained the field.
4. **Extracts by rule**: a lure taxonomy of ~230 surface forms, catch counts and
   weights, and narrative patterns for clarity, water temperature, depth, vegetation,
   cover, technique and time of day.
5. **Enriches** every trip with Open-Meteo historical weather — temperature, wind,
   cloud, precipitation, and mean sea-level pressure with its 24/48-hour trend —
   plus locally computed moon phase and day length.
6. **Analyses** with shrunk catch rates ranked on a conservative lower bound, so a
   bait that went well on four trips cannot outrank one that went well on four hundred.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/pwf crawl      # once, ~2 hours, resumable
.venv/bin/pwf build      # parse + apply rules, a few minutes, repeatable
.venv/bin/pwf enrich     # geocode lakes, backfill weather
```

Then:

```bash
pwf coverage                        # what fraction of reports supports each dimension
pwf lakes --cohort small_clear_grassy
pwf lake "Northeast Lake"           # scorecard
pwf baits --cohort small_clear_grassy --month 4 --pressure falling
pwf plan --lake "JerMar Lake" --date 2026-09-19
pwf compare "China Lake,Kickapoo Lake"
pwf review                          # lure strings the taxonomy missed
pwf geo-verify                      # check coordinates against the club's own directions
pwf geo-review                      # settle the lakes no evidence can resolve
pwf sql "SELECT ..."                # escape hatch; `pwf schema` prints the tables
pwf dashboard                       # build the aggregate page
```

## The two coverage tiers

Members record what they caught and what they threw far more reliably than they record
the water. Measured on a 200-report sample:

Measured across all 13,672 reports:

| Available on most trips | Only when a member wrote it down |
|---|---|
| a written narrative (99%) | time of day (59%) |
| bait named, field or narrative (86%) | cover/structure (54%) |
| lake identified (89%) | technique (36%) |
| bait matched to the taxonomy (92% of the 58% that name one) | vegetation (33%) |
| countable catch (56%) | water clarity (25%) |
| exact reservation date (58%) | depth fished (15%) |
| weather, pressure + trend, wind, cloud — every trip with a lake and a date | water temperature (13%) |

Three of those deserve emphasis.

**Catch rates cover 2018–2026, not the full sixteen years.** A rate needs both a fish
count and a half- or full-day window, and both live in the structured field block that
only appears from about 2018. So every fish-per-hour figure rests on **7,613 trips**,
not on all 13,672 reports. The 2010–2017 reports are not wasted — they supply baits,
vegetation and cover descriptions, and lake profiles — but they carry no rate.

**Only 56% of reports give a countable catch**, which is the same constraint seen from
the other side, and is the real denominator behind every rate.

**The structured fields are optional**: roughly 58% of reports fill in `Lures Used`,
which is why the narrative scan matters — together they name a bait on 86% of trips.

This is also why the weather join earns its place: it supplies exactly the conditions
the narratives leave out, for every trip that has a lake and a date. `pwf coverage`
prints the live numbers, and the test suite asserts floors so a rule edit cannot
quietly lose recall.

## Where each lake actually is

The club publishes a town, not a coordinate, and town names repeat inside Texas —
82 of the club's 111 towns have more than one Texas or Oklahoma match. Picking the
most populous one is backwards for lakes on rural ranches: it put Walnut Springs in
a town of 27,864 near San Antonio when the club's lake is in Bosque County,
population 811, 170 miles north.

Four passes resolve this, each preferred over the next because it needs nobody:

1. **The club's own directions.** Every live property page carries a "General
   Directions" line — *"2 hours and 30 minutes east of Downtown Dallas … 1 hour east
   of Tyler"*. Those are statements about the lake rather than about the name, and
   two or three of them triangulate a town to within a few miles. **41 lakes.**
2. **A verified same-town sibling.** A retired lake in Crockett is in the same
   Crockett as the live property whose page proves where Crockett is. **13 lakes.**
3. **The club's published region**, then town population.
4. **`pwf geo-review`** for what is left — 29 retired properties with no page and an
   ambiguous name. It shows every candidate town with its county, population, drive
   and compass direction from Dallas, plus anything members wrote that hints at the
   location, and writes the answer to `data/lake_coords.csv`.

`pwf geo-verify` audits the result: **82 of 84 checkable lakes now agree with their
own property page**, against 58 before. The pass caught ten real errors, including
Hickory Creek Ranch (411 reports) sitting 12 miles from Dallas when its page says two
and a half hours, and the five Heartland 10-10 Ranch lakes placed northwest of Dallas
when the club says 150 miles east.

Only rows marked `confirmed` in `data/lake_coords.csv` act as overrides. The file
also holds a dump of every current coordinate for review, and treating those dumped
rows as corrections used to pin each lake to whatever the geocoder guessed first,
silently turning later fixes into no-ops.

A lake that stays unresolved is still ranked — its catch data is unaffected — but the
page marks its drive distance as approximate, because that and the weather join are
the only figures resting on the guess.

## Honest limits

Observational data with real confounds. Popular baits get thrown more, and under
different conditions, than rare ones. Better anglers write more reports. Only ~3% of
reports admit a blank day, which is not a believable rate — the archive is
survivorship-biased toward good days. Everything here is association, not cause.

Tackle advice does not replicate per lake: split a lake's history in half and its own
bait effects agree at r = −0.02. Pooled by lake size it does, at r = +0.39, so that is
the finest grain the archive supports. Lake choice is the one thing that replicates
strongly (r = +0.70).

Weather backfill is rate-limited by Open-Meteo's free tier, which meters by request
weight; a full backfill takes more than one hourly budget. `pwf enrich` is resumable
and waits for the bucket to refill, so re-running it simply continues.

## Layout

```
pwf/
  crawl.py      polite resumable crawler (listing, reports, lake pages)
  parse_*.py    HTML -> rows for each page shape
  rules/        lures.yaml taxonomy, patterns.py regexes, fish.py catch parser
  geo/weather/astro.py   enrichment
  analysis.py   shrinkage, lift, cohorts, similarity matching
  cli.py        the commands above
dashboard/      aggregate page builder
tests/          fixtures + rule precision tests + coverage floors
```

Run `pytest` to check everything.
