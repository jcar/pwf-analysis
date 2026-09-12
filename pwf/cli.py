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


@app.command()
def lake(name: str):
    """Scorecard for one lake."""
    s = A.lake_scorecard(_db(), name)
    if "error" in s:
        console.print(f"[red]{s['error']}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]{s['lake']}[/bold] - {s['town'] or '?'}   "
                  f"{_fmt(s['acres'], 0)} acres, max {_fmt(s['max_depth_ft'], 0)} ft   "
                  f"cohort: {s['cohort'] or '?'}")
    console.print(f"{s['trips']} reports ({s['date_range'][0]} .. {s['date_range'][1]}), "
                  f"{s['scored_trips']} with a countable catch")
    console.print(f"catch rate {_fmt(s['fish_per_hour_median'])} fish/hr "
                  f"(club median {_fmt(s['club_median_fph'])})   "
                  f"best fish {_fmt(s['best_fish_lb'], 1)} lb")
    console.print(f"clarity median {_fmt(s['clarity_ft_median'], 1)} ft "
                  f"(n={s['clarity_n']})   vegetation mentioned in "
                  f"{s['veg_mention_rate']*100:.0f}% of reports")

    if not s["by_month"].empty:
        bm = s["by_month"]
        _table("By month", ["month", "trips", "fish/hr"],
               [[int(i), int(r.n), _fmt(r.fph)] for i, r in bm.iterrows()])
    tl = s["top_lures"]
    if not tl.empty:
        _table("Producing baits", ["bait", "trips", "fish/hr", "vs baseline", "conservative"],
               [[i, int(r.n_trips), _fmt(r.shrunk_fph), f"{r.lift:.2f}x",
                 f"{r.lift_lb:.2f}x"] for i, r in tl.head(12).iterrows()],
               caption="ranked by the conservative column (lower bound, so thin "
                       "cells sink). Association, not cause.")
    if len(s["vegetation"]):
        console.print("vegetation: " + ", ".join(
            f"{k} ({v})" for k, v in s["vegetation"].head(6).items()))
    if len(s["structure"]):
        console.print("cover: " + ", ".join(
            f"{k} ({v})" for k, v in s["structure"].head(8).items()))


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
               caption="Small samples by nature. Association, not cause.")

    ids = ", ".join(str(int(r)) for r in top["report_id"].head(8))
    console.print(f"[dim]closest matches: report ids {ids}[/dim]")


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
