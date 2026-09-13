"""Command line interface. Runs offline against SQLite; no API keys anywhere."""
from __future__ import annotations

from datetime import date, datetime

import typer
from rich.console import Console
from rich.table import Table

from . import analysis as A
from . import build as B
from . import crawl as CR
from . import geo, weather
from .config import DB_PATH
from .db import init
from .rules.extract import extract_all

app = typer.Typer(add_completion=False, help=__doc__)
console = Console()


def _db():
    return init(DB_PATH)


def _table(title: str, cols: list[str], rows: list[list], caption: str | None = None):
    t = Table(title=title, caption=caption, header_style="bold")
    for c in cols:
        t.add_column(c, justify="right" if c not in cols[:1] else "left")
    for r in rows:
        t.add_row(*["" if v is None else str(v) for v in r])
    console.print(t)


def _fmt(v, nd=2):
    if v is None:
        return "-"
    try:
        if v != v:  # NaN
            return "-"
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
@app.command()
def crawl(index: bool = typer.Option(False, help="Crawl listing pages only"),
          reports: bool = typer.Option(False, help="Crawl report pages only"),
          lakes: bool = typer.Option(False, help="Crawl lake property pages only"),
          limit: int = typer.Option(None, help="Stop after N new pages"),
          refresh: bool = typer.Option(False, help="Re-fetch pages already cached")):
    """Harvest the site. Resumable - re-running picks up where it stopped."""
    conn = _db()
    do_all = not (index or reports or lakes)
    if index or do_all:
        console.print("[bold]listing index[/bold]")
        console.print(CR.crawl_index(conn, refresh=refresh, limit=limit))
    if reports or do_all:
        console.print("[bold]report pages[/bold]")
        console.print(CR.crawl_reports(conn, refresh=refresh, limit=limit))
    if lakes or do_all:
        console.print("[bold]lake pages[/bold]")
        console.print(CR.crawl_lakes(conn, B.lake_variant_map(conn), refresh=refresh))


@app.command()
def build(skip_lakes: bool = typer.Option(False, help="Skip lake page parsing")):
    """Parse cached HTML and apply the rule layer. Offline, repeatable."""
    conn = _db()
    console.print(f"index rows   : {B.build_index(conn)}")
    kept, skipped = B.build_reports(conn)
    console.print(f"reports      : {kept} parsed, {skipped} missing-id stubs")
    console.print(f"lakes        : {B.build_lakes(conn)}")
    if not skip_lakes:
        console.print(f"lake details : {B.build_lake_details(conn)}")
    console.print(f"trips        : {B.build_trips(conn)}")
    console.print(f"rules        : {extract_all(conn)}")
    df = A.assign_cohorts(conn)
    if not df.empty:
        console.print(f"cohorts      : {dict(df['cohort'].value_counts())}")


@app.command()
def enrich(force: bool = typer.Option(False, help="Re-geocode lakes")):
    """Geocode lakes and backfill weather, pressure trend, moon and daylight."""
    conn = _db()
    console.print(f"geocode : {geo.geocode_lakes(conn, force=force)}")
    console.print(f"weather : {weather.backfill(conn, progress=console.print)}")


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
@app.command()
def coverage():
    """What fraction of reports supports each dimension."""
    df = A.coverage(_db())
    if df.empty:
        console.print("[yellow]No coverage stats - run `pwf build` first.[/yellow]")
        return
    _table("Coverage by dimension",
           ["dimension", "tier", "n", "of", "%"],
           [[r.dimension, r.tier, r.n_with, r.n_total, f"{r.pct:.1f}%"]
            for r in df.itertuples()],
           caption="full tier = available on essentially every trip; "
                   "partial = only when a member wrote it down")


@app.command()
def lakes(cohort: str = typer.Option(None), min_trips: int = typer.Option(20),
          limit: int = typer.Option(30)):
    """List lakes with their size, cohort and catch rate."""
    conn = _db()
    df = A.trips_frame(conn)
    df = df[df["lake_known"] == 1]
    if cohort:
        df = df[df["cohort"] == cohort]
    g = df.groupby("lake").agg(
        trips=("report_id", "size"), acres=("acres", "first"),
        cohort=("cohort", "first"), fph=("fish_per_hour", "median"),
        best=("max_weight_lb", "max"))
    g = g[g["trips"] >= min_trips].sort_values("trips", ascending=False).head(limit)
    _table(f"Lakes ({len(g)} shown)", ["lake", "trips", "acres", "cohort", "fish/hr", "best lb"],
           [[i, r.trips, _fmt(r.acres, 0), r.cohort, _fmt(r.fph), _fmt(r.best, 1)]
            for i, r in g.iterrows()])


_SUPPORT_STYLE = {
    "backed": ("bold green", "Backed by the data"),
    "suggestive": ("yellow", "Leaning that way, not proven"),
    "unproven": ("dim", "Thrown here, but not separated from the rest"),
    "below": ("red", "Below the lake's other baits"),
    "thin": ("dim", "Too few trips to say"),
}


def _render_baits(baits: dict) -> None:
    """Group baits by how much the archive supports them, with the interval."""
    ev = baits.get("evidence") or []
    rec = baits.get("recommendation") or {}
    if not ev:
        return

    console.print()
    console.rule("[bold]What to throw[/bold]", style="dim")
    if rec.get("lead"):
        console.print(f"[bold]{rec['lead']}.[/bold]")
    console.print(
        f"[dim]{rec.get('n_compared', len(ev))} baits compared. Each is measured "
        f"against the other baits on trips that named about as many, because "
        f"trips listing more baits catch more fish and would otherwise flatter "
        f"every bait at once.[/dim]\n")

    for key in ("backed", "suggestive", "unproven", "below", "thin"):
        group = rec.get(key) or []
        if not group:
            continue
        style, label = _SUPPORT_STYLE[key]
        rows = []
        flagged = False
        for e in group[:8]:
            ci = (f"[{e['lo']:+.2f}, {e['hi']:+.2f}]"
                  if e["lo"] is not None else "-")
            diff = f"{e['diff']:+.2f}" if e["diff"] is not None else "-"
            name = e["bait"].replace("_", " ")
            if e.get("club_unstable"):
                name += " †"
                flagged = True
            rows.append([name, e["trips"], f"{e['share']:.0f}%",
                         _fmt(e["rate"]), diff, ci])
        _table(label, ["bait", "trips", "share", "fish/hr", "vs others", "95% CI"],
               rows,
               caption="† club-wide this bait cannot hold its sign from year to "
                       "year. That is a caveat on the club average, not on this "
                       "lake's own trips, which are counted here."
                       if flagged else None)
        # Supporting detail for the ones worth acting on.
        for e in group[:3]:
            d = e.get("detail") or {}
            bits = []
            if d.get("subtypes"):
                bits.append("mostly " + ", ".join(
                    f"{x['value'].replace('_',' ')} ({x['n']})" for x in d["subtypes"][:3]))
            if d.get("by_season"):
                best = max(d["by_season"].items(), key=lambda kv: kv[1]["rate"] or 0)
                bits.append(f"strongest in {best[0]} ({best[1]['rate']} fish/hr "
                            f"over {best[1]['n']} trips)")
            if d.get("colors"):
                bits.append("colours named: " + ", ".join(
                    x["value"] for x in d["colors"][:3]))
            if bits:
                console.print(f"   [dim]{e['bait'].replace('_',' ')}: "
                              f"{'; '.join(bits)}[/dim]")

    seasons = baits.get("by_season") or {}
    if seasons:
        line = "  ·  ".join(f"{sea}: {rows[0]['bait'].replace('_',' ')} ({rows[0]['n']})"
                            for sea, rows in seasons.items() if rows)
        if line:
            console.print(f"\n[dim]Plain season leaders (thin samples, unstratified) "
                          f"- {line}[/dim]")
    console.rule(style="dim")


def _render_technique(tech: dict) -> None:
    """Club-wide presentation effects, with this lake's own beside them."""
    club = tech.get("club") or []
    if not club:
        return
    from .technique import summary as _tsummary
    s = _tsummary(club)
    local = {e["technique"]: e for e in (tech.get("lake") or [])}

    console.print()
    console.rule("[bold]How you fish it[/bold]", style="dim")
    console.print(f"[bold]{s['lead']}.[/bold]")
    rows = []
    for key in ("backed", "suggestive", "below", "unstable"):
        for e in s.get(key) or []:
            here = local.get(e["technique"])
            rows.append([
                e["label"][:19], e["trips"], f"{e['diff']:+.2f}",
                f"{e['lo']:+.2f} to {e['hi']:+.2f}",
                f"{e['years_agreeing']}/{e['years']}" if e["years"] else "-",
                key,
                f"{here['diff']:+.2f} n={here['trips']}" if here else "-",
            ])
    if rows:
        _table("Presentation, club-wide",
               ["technique", "trips", "vs others", "95% CI", "yrs", "support",
                "here"],
               rows,
               caption="'years' counts how many separate years agree with the "
                       "pooled sign. Trips cluster within seasons, so a pooled "
                       "interval runs narrow - anything marked unstable clears "
                       "it and then flips sign in half the years it appears in.")
    console.rule(style="dim")


def _render_consistency(cons: dict) -> None:
    if not cons or not cons.get("sentence"):
        return
    from .consistency import CAVEAT
    console.print(f"\n[bold]what to expect[/bold]  {cons['sentence']}", width=88)
    console.print(
        f"[dim]volatility {cons['cv']} ({cons['band']}); best one day in ten "
        f"{cons['best_decile']} fish/hr, worst {cons['worst_decile']}. "
        f"{CAVEAT}[/dim]", width=88)


@app.command()
def techniques(lake: str = typer.Option(None, help="Scope to one lake"),
               min_trips: int = typer.Option(None)):
    """How you fish it: presentation effects across the archive."""
    from .technique import (lake_technique_effects, summary,
                            technique_effects)

    conn = _db()
    trips, lures, tags = (A.trips_frame(conn), A.lures_frame(conn),
                          A.tags_frame(conn))
    if lake:
        sel = trips[trips["lake"].fillna("").str.lower() == lake.lower()]
        if sel.empty:
            console.print(f"[red]No trips for {lake!r}.[/red]")
            raise typer.Exit(1)
        ids = set(sel["report_id"])
        ev = lake_technique_effects(
            sel, tags[tags["report_id"].isin(ids)],
            lures[lures["report_id"].isin(ids)])
        title = f"Presentation at {sel['lake'].iloc[0]}"
        note = ("per-lake samples are thin and are not year-checked; read them "
                "as local colour beside the club-wide table")
    else:
        ev = technique_effects(trips, tags, lures, min_trips=min_trips)
        title = "Presentation, club-wide"
        note = ("'years' counts how many separate years agree with the pooled "
                "sign; unstable means the interval excludes zero but the sign "
                "does not hold")
    if not ev:
        console.print("[yellow]Not enough technique data for that slice.[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]{summary(ev)['lead']}.[/bold]")
    _table(title,
           ["technique", "trips", "vs others", "95% CI", "yrs", "support"],
           [[e["label"][:20], e["trips"], f"{e['diff']:+.2f}",
             f"{e['lo']:+.2f} to {e['hi']:+.2f}",
             f"{e['years_agreeing']}/{e['years']}" if e["years"] else "-",
             e["support"]] for e in ev],
           caption=note)


@app.command()
def lake(name: str, season: str = typer.Option(None, help="Show baits for one season")):
    """Full profile for one lake - everything worth knowing before a trip."""
    from .config import DB_PATH
    from .profile import lake_profile
    from .summarize import mention_index

    from .baits import club_stability
    from .consistency import club_bust_rate, lake_consistency
    from .technique import technique_effects

    conn = _db()
    trips, lures = A.trips_frame(conn), A.lures_frame(conn)
    cons = lake_consistency(trips)
    cons["__club_bust__"] = club_bust_rate(trips)
    p = lake_profile(conn, name, trips=trips, lures=lures,
                     mentions=mention_index(conn, str(DB_PATH)),
                     club_technique=technique_effects(trips, A.tags_frame(conn), lures),
                     consistency=cons, bait_stability=club_stability(trips, lures))
    if "error" in p:
        console.print(f"[red]{p['error']}[/red]  Try `pwf lakes`.")
        raise typer.Exit(1)

    f, v, r = p["facts"], p["volume"], p["rate"]
    console.print(f"\n[bold]{p['lake']}[/bold]" + (f" - {f['town']}" if f["town"] else ""))

    bits = []
    if f["acres"]:
        bits.append(f"{f['acres']:.0f} acres")
    if f["max_depth_ft"]:
        bits.append(f"max {f['max_depth_ft']:.0f} ft")
    if f["miles"] is not None:
        bits.append(f"{f['miles']:.0f} mi from Dallas")
    if f["day_rate"]:
        half = f" / ${f['half_day_rate']:.0f} half" if f["half_day_rate"] else ""
        bits.append(f"${f['day_rate']:.0f} day{half}")
    if f["cohort"]:
        bits.append(f["cohort"].replace("_", " "))
    if f["membership_tier"]:
        bits.append(f["membership_tier"])
    console.print("  " + "  ·  ".join(bits))
    if f["boat_type"]:
        console.print(f"  boat: {f['boat_type']}")

    console.print(
        f"\n{v['reports']} reports ({v['first']} .. {v['last']}), "
        f"{v['scored']} with a countable catch  "
        f"[dim]confidence: {v['confidence']}[/dim]")
    pct = f", {r['percentile']:.0f}th percentile of club lakes" if r["percentile"] else ""
    console.print(
        f"catch rate [bold]{_fmt(r['median'])}[/bold] fish/hr median "
        f"(club {_fmt(r['club_median'])}){pct}")

    fish = p["fish"]
    console.print(
        f"typical trip {_fmt(fish['median_fish_per_trip'], 0)} fish  ·  "
        f"best fish {_fmt(fish['best_lb'], 1)} lb  ·  "
        f"{_fmt(fish['over_5lb_rate'], 0)}% of trips reporting a size had a 5 lb+ "
        f"[dim](n={fish['weight_reports']})[/dim]")

    summ = p.get("summary") or {}
    if summ.get("paragraphs"):
        console.print()
        console.rule("[bold]What members are saying[/bold]", style="dim")
        for para in summ["paragraphs"]:
            console.print(para, width=88)
            console.print()
        if summ.get("mention_line"):
            console.print(f"[italic]{summ['mention_line']}[/italic]", width=88)
        if summ.get("caveat"):
            console.print(f"[yellow]{summ['caveat']}[/yellow]", width=88)
        console.rule(style="dim")

    months = [m for m in p["by_month"] if m["n"]]
    if months:
        best = sorted(months, key=lambda m: -(m["median"] or 0))[:3]
        _table("By month", ["month", "trips", "fish/hr"],
               [[m["month"], m["n"], _fmt(m["median"])] for m in months],
               caption="best: " + ", ".join(f"{m['month']} ({_fmt(m['median'])})"
                                            for m in best))
    if p["by_slot"]:
        _table("By booking slot", ["slot", "trips", "fish/hr"],
               [[r_["slot"], r_["n"], _fmt(r_["median"])] for r_ in p["by_slot"]],
               caption="comparable because all-day effort is measured, not assumed")

    yrs = p["by_year"][-6:]
    if len(yrs) > 2:
        _table("Recent years", ["year", "trips", "fish/hr"],
               [[y["year"], y["n"], _fmt(y["median"])] for y in yrs])

    baits = p["baits"]
    if season:
        chosen = baits["by_season"].get(season) or []
        if chosen:
            _table(f"Producing baits - {season}",
                   ["bait", "trips", "fish/hr", "vs lake baseline"],
                   [[b["bait"], b["n"], _fmt(b["fph"]), f"{b['lift']:.2f}x"]
                    for b in chosen[:10]],
                   caption="season slices are too thin to match on trip detail, "
                           "so these are plain comparisons - read them loosely.")
    else:
        _render_baits(baits)

    _render_technique(p.get("technique") or {})
    _render_consistency(p.get("consistency") or {})

    w = p["water"]
    console.print(
        f"\n[bold]water[/bold]  clarity {_fmt(w['clarity_ft_median'], 1)} ft "
        f"[dim](n={w['clarity_ft_n']})[/dim]  ·  "
        f"temp {_fmt(w['water_temp_f_median'], 0)}F [dim](n={w['water_temp_n']})[/dim]  ·  "
        f"vegetation mentioned in {_fmt(w['veg_mention_rate'], 0)}% of reports")
    if w["vegetation"]:
        console.print("  growth: " + ", ".join(
            f"{x['value'].replace('_',' ')} {x['n']}" for x in w["vegetation"][:5]))
    if w["structure"]:
        console.print("  cover: " + ", ".join(
            f"{x['value'].replace('_',' ')} {x['n']}" for x in w["structure"][:6]))
    if w["technique"]:
        console.print("  techniques: " + ", ".join(
            f"{x['value'].replace('_',' ')} {x['n']}" for x in w["technique"][:6]))

    if fish["species"]:
        console.print("\n[bold]fish[/bold]  " + ", ".join(
            f"{x['species'].replace('_',' ')} {x['pct']:.0f}%" for x in fish["species"][:5])
            + f"  [dim](named on {fish['species_named_on']} reports)[/dim]")
    if fish["weight_bands"]:
        console.print("  sizes: " + ", ".join(
            f"{b['value']} {b['pct']:.0f}%" for b in fish["weight_bands"]))

    cond = p["conditions"]
    if cond.get("typical"):
        t = cond["typical"]
        console.print(
            f"\n[bold]typically fished in[/bold]  {_fmt(t['temp_max_f'],0)}F, "
            f"{_fmt(t['wind_mph'],0)} mph wind, {_fmt(t['cloud_pct'],0)}% cloud "
            f"[dim](n={cond['weather_n']})[/dim]")
    if f["harvest_rules"]:
        console.print(f"\n[dim]{f['harvest_rules']}[/dim]")


@app.command()
def weekend(when: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: next Saturday)"),
            miles: float = typer.Option(200, help="Max straight-line miles from Dallas"),
            limit: int = typer.Option(15),
            cohort: str = typer.Option(None, help="Restrict to one water type"),
            weight_conditions: bool = typer.Option(
                False, help="Apply measured weather multipliers (all inside noise)"),
            no_forecast: bool = typer.Option(False, help="Skip the forecast lookup")):
    """Rank lakes for a day - which trip is the best use of the drive."""
    from datetime import date as _date

    from .recommend import recommend

    conn = _db()
    target = _date.fromisoformat(when) if when else None
    out = recommend(conn, when=target, max_miles=miles, limit=limit, cohort=cohort,
                    weight_conditions=weight_conditions,
                    with_forecast=not no_forecast)
    if out.get("error") or not out["lakes"]:
        console.print("[yellow]Nothing to rank - run `pwf build` first.[/yellow]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold]{out['date']}[/bold] ({out['month_name']})  ·  within {miles:.0f} mi  "
        f"·  {out['considered']} lakes considered  ·  club {out['month_name']} average "
        f"{out['club_month_mean']} fish/hr")

    # Keep the table narrow enough not to wrap lake names in a normal terminal.
    basis_short = {"lake-month": "month", "lake-year": "annual", "club": "club"}
    cols = ["lake", "mi", "fish/hr", "n", "from", "$", "spread", "bust"]
    rows = []
    for L in out["lakes"]:
        cs = L.get("consistency") or {}
        rows.append([
            L["lake"][:22],
            f"{L['miles']:.0f}" if L["miles"] is not None else "-",
            _fmt(L["expected_fph"]),
            f"{L['n_total']}{'*' if L['confidence'] in ('thin','very thin') else ''}",
            basis_short.get(L["basis"], L["basis"]),
            f"{L['day_rate']:.0f}" if L["day_rate"] else "-",
            cs.get("band") or "-",
            f"{cs['bust_rate']:.0f}%" if cs.get("bust_rate") is not None else "-",
        ])
    _table(f"Best bets for {out['date']}", cols, rows,
           caption="expected catch rate for this lake in this month, backtested at "
                   "r~0.65 on held-out years. 'from' = month means the lake has "
                   "data for this month; annual means its year-round average "
                   "stands in. * marks a thin sample. 'spread' and 'bust' are "
                   "history, not forecast, and do not affect the order.")

    top = out["lakes"][0]
    if top["top_baits"]:
        console.print(f"[bold]{top['lake']}[/bold] baits: " + ", ".join(
            f"{b['bait']} ({b['n']} trips, {b['lift']:.2f}x)" for b in top["top_baits"]))

    if out.get("club_bust_rate") is not None:
        from .consistency import CAVEAT
        console.print(
            f"\n[dim]'bust' is the share of trips that came back with 2 fish or "
            f"fewer; club-wide that is {out['club_bust_rate']:.0f}%. {CAVEAT}[/dim]")

    if out["forecast_available"]:
        console.print(
            "\n[dim]The forecast is shown, not scored. Measured within lake-month, "
            "the largest weather effect in the archive - calm vs windy - is about 10% "
            "with a confidence interval that includes zero. Lake and month separate "
            "lakes by 3x. Use --weight-conditions to apply the small multipliers "
            "anyway.[/dim]")
    if out["weighted_by_conditions"]:
        console.print("[yellow]Weather multipliers applied - all sit inside noise.[/yellow]")


@app.command()
def calibrate():
    """Show the measured effort constants and how far they move the rates."""
    from .analysis import calibrate_effort, effort_hours

    conn = _db()
    stats = calibrate_effort(conn)
    hours = effort_hours(conn)
    console.print(f"effort hours per slot: {hours}  [dim]({stats['source']})[/dim]")
    if stats["ratio"]:
        console.print(
            f"all-day trips catch {stats['ratio']:.2f}x a half-day trip "
            f"(n={stats['n_all_day']} vs {stats['n_half']}), so all-day effort is "
            f"{hours['ALL_DAY']} hours - not 8.")
    row = conn.execute(
        "SELECT note FROM calibration WHERE key='all_day_hours'").fetchone()
    if row:
        console.print(f"[dim]{row[0]}[/dim]")
    res = conn.execute(
        "SELECT time_slot, COUNT(*), AVG(fish_per_hour) FROM trips"
        " WHERE fish_per_hour IS NOT NULL GROUP BY time_slot").fetchall()
    if res:
        means = [r[2] for r in res]
        spread = (max(means) - min(means)) / min(means)
        _table("Calibrated slot means", ["slot", "trips", "fish/hr"],
               [[r[0], r[1], _fmt(r[2])] for r in res],
               caption=f"spread {spread:.1%} - these should be close, or every "
                       "between-lake comparison inherits the bias")


@app.command()
def baits(lake: str = typer.Option(None), cohort: str = typer.Option(None),
          month: int = typer.Option(None), season: str = typer.Option(None),
          pressure: str = typer.Option(None, help="rising|steady|falling"),
          clarity: str = typer.Option(None, help="murky|stained|clear"),
          max_acres: float = typer.Option(None), wind: str = typer.Option(None),
          level: str = typer.Option("category", help="category|subtype"),
          exact_dates: bool = typer.Option(
              False, help="Only trips with an exact reservation date"),
          min_n: int = typer.Option(3)):
    """Rank baits within a slice of the archive."""
    conn = _db()
    df = A.trips_frame(conn)
    desc = []
    if lake:
        df = df[df["lake"].str.lower() == lake.lower()]; desc.append(f"lake={lake}")
    if cohort:
        df = df[df["cohort"] == cohort]; desc.append(f"cohort={cohort}")
    if month:
        df = df[df["month"] == month]; desc.append(f"month={month}")
    if season:
        df = df[df["season"] == season]; desc.append(f"season={season}")
    if pressure:
        df = df[df["pressure_trend"] == pressure]; desc.append(f"pressure={pressure}")
    if clarity:
        df = df[df["clarity_band"] == clarity]; desc.append(f"clarity={clarity}")
    if wind:
        df = df[df["wind_band"] == wind]; desc.append(f"wind={wind}")
    if max_acres:
        df = df[df["acres"] <= max_acres]; desc.append(f"acres<={max_acres:g}")
    if exact_dates or pressure:
        # Pressure is a same-day reading; an estimated date makes it noise.
        df = df[df["trip_date_source"] == "reservation"]
        if "exact dates" not in desc:
            desc.append("exact dates")

    if df.empty:
        console.print("[yellow]No trips match that slice.[/yellow]")
        return
    out = A.lure_lift(df, A.lures_frame(conn), level=level, min_n=min_n)
    if out.empty:
        console.print(f"[yellow]Slice has {len(df)} trips but no bait cell "
                      f"reached n>={min_n}.[/yellow]")
        return
    scored = int(out["scored_trips"].iloc[0])
    _table("Baits: " + (", ".join(desc) or "whole archive"),
           ["bait", "trips", "fish/hr", "vs baseline", "conservative"],
           [[i, int(r.n_trips), _fmt(r.shrunk_fph), f"{r.lift:.2f}x", f"{r.lift_lb:.2f}x"]
            for i, r in out.iterrows()],
           caption=f"{scored} scored trips in slice; baseline "
                   f"{_fmt(out['baseline_fph'].iloc[0])} fish/hr. Ranked by the "
                   "conservative column, which penalises thin cells. "
                   "Association, not cause.")


@app.command()
def plan(lake: str = typer.Option(..., help="Lake name"),
         when: str = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)")):
    """Match an upcoming forecast against comparable historical trips."""
    conn = _db()
    target_date = date.fromisoformat(when) if when else date.today()

    row = conn.execute(
        "SELECT lake_id, name, lat, lon, cohort FROM lakes WHERE lower(name)=?",
        (lake.lower(),)).fetchone()
    if row is None:
        console.print(f"[red]Unknown lake {lake!r}. Try `pwf lakes`.[/red]")
        raise typer.Exit(1)
    if row["lat"] is None:
        console.print("[red]Lake has no coordinates - run `pwf enrich`.[/red]")
        raise typer.Exit(1)

    fc = weather.forecast(row["lat"], row["lon"])
    day = fc.get(target_date.isoformat())
    if day is None:
        console.print(f"[yellow]No forecast for {target_date} "
                      f"(available: {min(fc)} .. {max(fc)}). Using month only.[/yellow]")
        day = {}

    console.print(f"\n[bold]{row['name']}[/bold] on {target_date}")
    if day:
        console.print(
            f"forecast: high {_fmt(day.get('temp_max_f'),0)}F, wind "
            f"{_fmt(day.get('wind_max_mph'),0)} mph, cloud {day.get('cloud_pct')}%, "
            f"pressure {_fmt(day.get('pressure_hpa'),1)} hPa "
            f"({day.get('pressure_trend')}, {_fmt(day.get('pressure_delta_24h'),1)} 24h), "
            f"sunrise {day.get('sunrise')}")

    target = {"month": target_date.month,
              "temp_max_f": day.get("temp_max_f"),
              "wind_max_mph": day.get("wind_max_mph"),
              "cloud_pct": day.get("cloud_pct"),
              "pressure_delta_24h": day.get("pressure_delta_24h")}

    trips = A.trips_frame(conn)
    sim = A.similar_trips(trips, target, lake=row["name"])
    scope = f"on {row['name']}"
    if len(sim) < 12 and row["cohort"]:
        sim = A.similar_trips(trips, target, cohort=row["cohort"])
        scope = f"across the {row['cohort']} cohort (too few on this lake)"
    if sim.empty:
        console.print("[yellow]No comparable historical trips.[/yellow]")
        return

    top = sim.head(40)
    console.print(f"matched {len(top)} comparable trips {scope}\n")
    out = A.lure_lift(top, A.lures_frame(conn), min_n=2)
    if out.empty:
        console.print("[yellow]No bait reached n>=2 among the matches.[/yellow]")
    else:
        _table("What produced under similar conditions",
               ["bait", "trips", "fish/hr", "vs baseline", "conservative"],
               [[i, int(r.n_trips), _fmt(r.shrunk_fph), f"{r.lift:.2f}x",
                 f"{r.lift_lb:.2f}x"] for i, r in out.head(10).iterrows()],
               caption=f"Matched on {len(top)} trips, so the conservative column "
                       "will sit below 1.00 across the board - that is the "
                       "sample size talking, not the baits. Read the order, not "
                       "the absolute values. Association, not cause.")

    ids = ", ".join(str(int(r)) for r in top["report_id"].head(8))
    console.print(f"[dim]closest matches: report ids {ids}[/dim]")


@app.command()
def brief(lake: str = typer.Option(..., help="Lake name"),
          when: str = typer.Option(None, "--date", help="YYYY-MM-DD"),
          evidence: bool = typer.Option(False, help="Print the cited reports")):
    """The plan for one lake on one day, with the evidence behind it."""
    from datetime import date as _date

    from .brief import next_weekend, report_url, trip_brief

    conn = _db()
    target = _date.fromisoformat(when) if when else next_weekend()[0]

    # One forecast call covers every grid cell the club occupies.
    fc = {}
    row = conn.execute("SELECT lat, lon FROM lakes WHERE lower(name)=?",
                       (lake.lower(),)).fetchone()
    if row and row["lat"] is not None:
        from .recommend import fetch_forecast
        from .weather import grid_key
        try:
            cell = grid_key(row["lat"], row["lon"])
            fc = fetch_forecast([cell]).get(cell, {}).get(target.isoformat(), {})
        except Exception:
            fc = {}
    b = trip_brief(conn, lake, target, forecast=fc)
    if "error" in b:
        console.print(f"[red]{b['error']}[/red]  Try `pwf lakes`.")
        raise typer.Exit(1)

    f, ex, exp = b["facts"], b["expected"], b["expect"]
    console.print(f"\n[bold]{b['lake']}[/bold] — {b['weekday']} {b['date']}")
    bits = []
    if f["miles"] is not None:
        bits.append(f"{f['miles']:.0f} mi from Dallas")
    if f["day_rate"]:
        bits.append(f"${f['day_rate']:.0f}/day")
    if f["acres"]:
        bits.append(f"{f['acres']:.0f} acres")
    if f["cohort"]:
        bits.append(f["cohort"].replace("_", " "))
    console.print("  " + "  ·  ".join(bits))

    console.rule("[bold]Expect[/bold]", style="dim")
    console.print(
        f"[bold]{_fmt(ex['fph'])} fish/hr[/bold] expected for {ex['month_name']} "
        f"(club average {ex['club_month_mean']}), from "
        f"{'this lake in this month' if ex['basis'] == 'lake-month' else 'its year-round average'}"
        f" over {ex['n_total']} scored trips.")
    if exp.get("sentence"):
        console.print(exp["sentence"], width=88)
    console.print(f"[dim]{exp['caveat']}[/dim]", width=88)

    cond = b["conditions"]
    if cond.get("forecast"):
        fc = cond["forecast"]
        console.rule("[bold]Conditions[/bold]", style="dim")
        console.print(
            f"{_fmt(fc.get('temp_max_f'), 0)}°F high · "
            f"{_fmt(fc.get('wind_max_mph'), 0)} mph · "
            f"{fc.get('cloud_pct')}% cloud · {fc.get('pressure_trend') or '?'} pressure")
        if cond.get("note"):
            console.print(f"[yellow]{cond['note']}[/yellow]", width=88)
        console.print("[dim]Shown to plan around, not scored: measured weather "
                      "effects in this archive sit inside noise.[/dim]", width=88)

    plan = b["plan"]
    pres = plan["presentation"]
    console.rule("[bold]What to throw[/bold]", style="dim")

    band = plan.get("size_band") or {}
    if band.get("use") or band.get("avoid"):
        console.print(
            f"[bold]For {band['label']}[/bold] — {band['lakes']} club lakes, "
            f"{band['trips']} trips, averaging {band['mean_fph']} fish/hr.")
        if band.get("use"):
            for e in band["use"]:
                console.print(
                    f"  · [bold]{e['value'].replace('_', ' ')}[/bold]  "
                    f"{e['diff']:+.2f} fish/hr [{e['lo']:+.2f}, {e['hi']:+.2f}] "
                    f"over {e['trips']} trips")
        if band.get("avoid"):
            console.print("  Costs you here: " + ", ".join(
                f"{e['value'].replace('_', ' ')} ({e['diff']:+.2f})"
                for e in band["avoid"]))
        console.print(f"[dim]{band['caveat']}[/dim]\n", width=88)

    console.print(
        "[dim]Everything in this section is measured across the whole archive "
        "and checked year by year. A single lake's own tackle numbers do not "
        "survive the same test - see 'at this lake' below.[/dim]", width=88)

    if pres.get("use"):
        console.print("\n[bold]Presentation[/bold] — it measures larger than bait choice.")
        for u in pres["use"]:
            console.print(
                f"  · [bold]{u['label']}[/bold]  {u['diff']:+.2f} fish/hr "
                f"[{u['lo']:+.2f}, {u['hi']:+.2f}] over {u['trips']} trips, "
                f"{u['years_agreeing']}/{u['years']} years agree")
    if pres.get("avoid"):
        console.print("  Behind the alternatives: " + ", ".join(
            f"{a['label']} ({a['diff']:+.2f})" for a in pres["avoid"]))

    cb = plan.get("club_baits") or {}
    if cb.get("use") or cb.get("avoid"):
        console.print("\n[bold]Bait family[/bold]")
        for e in cb.get("use", []):
            console.print(
                f"  · [bold]{e['bait'].replace('_', ' ')}[/bold]  {e['diff']:+.2f} "
                f"fish/hr [{e['lo']:+.2f}, {e['hi']:+.2f}] over {e['trips']} trips")
        if cb.get("avoid"):
            console.print("  Behind the alternatives: " + ", ".join(
                f"{e['bait'].replace('_', ' ')} ({e['diff']:+.2f})"
                for e in cb["avoid"]))

    here = plan.get("here") or {}
    if here.get("share"):
        console.rule(f"[bold]At {b['lake']}[/bold]", style="dim")
        console.print("[dim]What members actually throw here. Descriptive: this "
                      "lake's trips say what people tie on, not which bait "
                      "works better.[/dim]", width=88)
        console.print("  thrown on: " + ", ".join(
            f"{x['bait'].replace('_', ' ')} {x['share']}%" for x in here["share"][:6]))
        if here.get("subtypes"):
            console.print("  versions named: " + ", ".join(
                f"{x['value'].replace('_', ' ')} ({x['n']})"
                for x in here["subtypes"][:5]))
        if here.get("techniques"):
            console.print("  presentations named: " + ", ".join(
                f"{x['value'].replace('_', ' ')} ({x['n']})"
                for x in here["techniques"][:5]))
        for u in pres.get("use", []):
            if u.get("here"):
                h = u["here"]
                console.print(
                    f"  [dim]{u['label']} measured here: {h['diff']:+.2f} over "
                    f"{h['trips']} trips [{h['lo']:+.2f}, {h['hi']:+.2f}] — "
                    f"context only, see below[/dim]")
        if plan.get("lake_reliability"):
            console.print(f"\n[yellow]{plan['lake_reliability']}[/yellow]", width=88)

    if plan.get("where"):
        console.print("\n[bold]Where[/bold] — members name " + ", ".join(
            f"{w['value'].replace('_', ' ')} ({w['n']})" for w in plan["where"]))
    if plan.get("vegetation"):
        console.print("  growth: " + ", ".join(
            f"{v['value'].replace('_', ' ')} ({v['n']})" for v in plan["vegetation"]))
    console.print(f"\n[dim]{plan['slot_note']}[/dim]", width=88)

    if evidence:
        console.rule("[bold]The receipts[/bold]", style="dim")
        for bait, cites in b["citations"].items():
            if not cites:
                continue
            console.print(f"[bold]{bait.replace('_', ' ')}[/bold] — most recent trips:")
            for rid, when_, fish in cites[:6]:
                console.print(f"   {when_}  {str(fish) + ' fish' if fish is not None else 'no count':<10} "
                              f"[dim]{report_url(rid)}[/dim]")
    else:
        n = sum(len(v) for v in b["citations"].values())
        console.print(f"\n[dim]{n} trips cited behind these numbers — "
                      f"add --evidence for the links.[/dim]")


@app.command()
def compare(lakes_csv: str = typer.Argument(..., help="Comma-separated lake names")):
    """Compare lakes side by side."""
    conn = _db()
    df = A.trips_frame(conn)
    names = [n.strip().lower() for n in lakes_csv.split(",")]
    sel = df[df["lake"].str.lower().isin(names)]
    if sel.empty:
        console.print("[red]No matching lakes.[/red]")
        raise typer.Exit(1)
    g = sel.groupby("lake").agg(
        trips=("report_id", "size"), acres=("acres", "first"),
        fph=("fish_per_hour", "median"), best=("max_weight_lb", "max"),
        clarity=("clarity_ft", "median"), rate=("day_rate", "first"))
    _table("Lake comparison",
           ["lake", "trips", "acres", "fish/hr", "best lb", "clarity ft", "$/day"],
           [[i, r.trips, _fmt(r.acres, 0), _fmt(r.fph), _fmt(r.best, 1),
             _fmt(r.clarity, 1), _fmt(r.rate, 0)] for i, r in g.iterrows()])


@app.command()
def review(limit: int = typer.Option(40)):
    """Lure strings the taxonomy did not recognise, most frequent first."""
    conn = _db()
    rows = conn.execute(
        "SELECT raw, n FROM lure_review ORDER BY n DESC, raw LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        console.print("[green]Review queue is empty.[/green]")
        return
    _table("Unmatched lure strings", ["raw", "count"],
           [[r["raw"][:70], r["n"]] for r in rows],
           caption="Add recurring ones to pwf/rules/lures.yaml, then re-run `pwf build`.")


@app.command()
def schema():
    """Print the database schema for use with `pwf sql`."""
    conn = _db()
    for (sql,) in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
            " ORDER BY name"):
        console.print(sql + ";\n")


@app.command()
def sql(query: str):
    """Run arbitrary SQL against the database."""
    conn = _db()
    try:
        cur = conn.execute(query)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    rows = cur.fetchall()
    if not rows:
        console.print("[dim](no rows)[/dim]")
        return
    cols = [d[0] for d in cur.description]
    _table(f"{len(rows)} rows", cols,
           [[r[c] for c in cols] for r in rows[:200]],
           caption="showing first 200" if len(rows) > 200 else None)


@app.command()
def dashboard(out: str = typer.Option("dashboard/index.html")):
    """Build the aggregate dashboard page."""
    from dashboard.build import build_dashboard
    path = build_dashboard(_db(), out)
    console.print(f"[green]wrote {path}[/green]")


if __name__ == "__main__":
    app()
