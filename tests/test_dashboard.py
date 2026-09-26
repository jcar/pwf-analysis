"""The published page: it must carry real data, stay small enough to ship, and
never carry a member's words or name."""
import json
import re

import pytest

from pwf.config import DB_PATH
from pwf.db import init

PAGE = None


def _page():
    global PAGE
    from pathlib import Path
    # docs/ is what GitHub Pages serves; dashboard/ is the old output path.
    p = next((q for q in (Path("docs/index.html"), Path("dashboard/index.html"))
              if q.exists()), None)
    if p is None:
        pytest.skip("dashboard not built - run `pwf dashboard`")
    if PAGE is None:
        PAGE = p.read_text(encoding="utf-8")
    return PAGE


def _payload(html):
    m = re.search(r"const D = (\{.*?\});\n", html, re.S)
    assert m, "embedded payload not found"
    return json.loads(m.group(1))


class TestPageIntegrity:
    def test_small_enough_to_publish(self):
        html = _page()
        assert len(html) < 2_000_000, f"page is {len(html):,} bytes"

    def test_payload_parses_and_is_populated(self):
        d = _payload(_page())
        assert d["profiles"], "no lake profiles embedded"
        assert d["lakes"] and d["heatmap"]["cells"]
        assert d["weekend"]["lakes"], "no weekend ranking embedded"

    def test_every_js_target_exists_in_the_markup(self):
        html = _page()
        used = set(re.findall(r'\$\("#([\w-]+)"\)', html)) | set(
            re.findall(r'getElementById\("([\w-]+)"\)', html))
        present = set(re.findall(r'id="([\w-]+)"', html))
        assert not (used - present)

    def test_theme_tokens_all_declared_on_bare_root(self):
        """A colour defined only inside a media or [data-theme] block never
        applies in the default un-stamped state - the classic unreadable page."""
        html = _page()
        used = set(re.findall(r"var\((--[\w-]+)\)", html))
        root = re.search(r"^:root\{(.*?)\}", html, re.S | re.M).group(1)
        declared = set(re.findall(r"(--[\w-]+)\s*:", root))
        assert not (used - declared)

    def test_both_dark_scopes_present(self):
        html = _page()
        assert "prefers-color-scheme: dark" in html
        assert ':root[data-theme="dark"]' in html
        assert "background:var(--ground)" in html


class TestNoMemberContent:
    """Aggregates only. The reports belong to the club's members; the patterns
    in them are fair to analyse, the words are not ours to republish."""

    def test_no_report_bodies(self):
        d = _payload(_page())
        blob = json.dumps(d)
        for key in ("body", "title", "author", "narrative_text"):
            assert f'"{key}":' not in blob, f"{key} leaked into the page"

    def test_no_member_names(self):
        if not DB_PATH.exists():
            pytest.skip("no database")
        conn = init(DB_PATH)
        names = [r[0] for r in conn.execute(
            "SELECT author FROM reports WHERE author IS NOT NULL"
            " GROUP BY author ORDER BY COUNT(*) DESC LIMIT 40")]
        html = _page()
        leaked = [n for n in names if n and len(n) > 6 and n in html]
        assert not leaked, f"member names in the published page: {leaked[:5]}"


class TestProfiles:
    def test_profiles_carry_their_samples(self):
        d = _payload(_page())
        for name, p in list(d["profiles"].items())[:25]:
            assert p["volume"]["reports"] > 0
            assert p["volume"]["confidence"] in {"good", "fair", "thin", "very thin"}
            # A share without a denominator is the thing to avoid.
            assert "clarity_ft_n" in p["water"]
            assert "weight_reports" in p["fish"]

    def test_every_listed_lake_can_be_opened(self):
        """Rows are clickable; a click must not land on a missing profile."""
        d = _payload(_page())
        profiles = set(d["profiles"])
        missing = [L["lake"] for L in d["lakes"] if L["lake"] not in profiles]
        assert not missing, f"listed but unopenable: {missing[:5]}"

    def test_weekend_picks_have_profiles(self):
        d = _payload(_page())
        profiles = set(d["profiles"])
        for L in d["weekend"]["lakes"]:
            assert L["lake"] in profiles

    def test_weekend_carries_no_stale_forecast(self):
        """The page is a static snapshot; a forecast baked in at publish time
        would read as current long after it stopped being true."""
        d = _payload(_page())
        for L in d["weekend"]["lakes"]:
            assert "forecast" not in L


class TestPlanner:
    """The page is now a booking tool with the archive beneath it. Both halves
    have to survive."""

    def test_planner_payload_present(self):
        d = _payload(_page())
        p = d.get("planner")
        assert p, "no planner payload"
        assert p["days"] and p["default_day"] in p["days"]
        day = p["days"][p["default_day"]]
        assert day["shortlist"] and day["briefs"]

    def test_every_shortlisted_lake_has_a_brief(self):
        d = _payload(_page())
        for key, day in d["planner"]["days"].items():
            for row in day["shortlist"]:
                assert row["lake"] in day["briefs"], f"{key}: {row['lake']}"

    def test_map_ships_with_the_page(self):
        """The basemap comes from tiles now, so the payload carries only what
        MapLibre cannot: the lakes, and the distances the rings stand for."""
        m = _payload(_page())["planner"]["map"]
        assert m["rings"] and m["lakes"] and m["gradient_ring"]
        assert all("miles" in r for r in m["rings"])
        for mark in m["lakes"]:
            assert 25.8 <= mark["lat"] <= 37.1, mark["lake"]
            assert -103.1 <= mark["lon"] <= -93.5, mark["lake"]

    def test_the_map_uses_real_tiles_from_keyless_providers(self):
        """This test used to assert the opposite, and the reversal is the point.

        The map drew its own geometry because the artifact host blocks tile
        servers outright. Served from GitHub Pages there is no such policy, so
        it is a real slippy map - and for ten-to-fifty-acre private ponds the
        satellite layer is the one that tells you something before you book.

        All three providers must stay keyless: an API key in a public repo is a
        credential leak, and a billing-backed key is one someone else can spend.
        """
        html = _page()
        for host in ("server.arcgisonline.com", "tiles.openfreemap.org"):
            assert host in html, f"{host} basemap missing"
        assert "cdnjs.cloudflare.com/ajax/libs/maplibre-gl/6.11.2" in html, \
            "MapLibre must be pinned, not floating"
        for keyed in ("maps.googleapis.com", "api.mapbox.com",
                      "api.maptiler.com", "access_token=", "&key=", "apikey"):
            assert keyed not in html, f"{keyed} implies an API key in a public repo"

    def test_attribution_is_present_for_every_basemap(self):
        """Required by OSM's and Esri's terms, and it is other people's work."""
        html = _page()
        # OpenFreeMap's style ships its own OpenStreetMap credit; the inline
        # satellite style has to carry Esri's itself.
        for credit in ("Esri", "Maxar", "Earthstar"):
            assert credit in html, f"missing attribution: {credit}"

    def test_unconfirmed_locations_are_marked_not_hidden(self):
        """A lake whose town the club's directions cannot confirm still ranks -
        its catch data is sound - but the drive it implies must carry the
        caveat, because that and the weather join are the only figures resting
        on the guess."""
        html = _page()
        d = _payload(html)["planner"]
        flagged = {r["lake"] for day in d["days"].values()
                   for r in day["shortlist"] if r.get("geo_uncertain")}
        unsure_marks = {m["lake"] for m in d["map"]["lakes"] if m.get("unsure")}
        # Whatever is flagged in the shortlist must also be flagged on the map,
        # or the two surfaces would disagree about the same lake.
        assert flagged <= unsure_marks
        # And the page must actually render the caveat rather than drop it.
        assert "UNSURE_NOTE" in html and "mp-unsure" in html
        assert "location unconfirmed" in html

    def test_flagged_lakes_keep_their_ranking(self):
        """The flag is a note about geography, never a demotion.

        Ranking is on shrunk lift, not raw rate, so the check is that the
        published order is exactly what the recommender produced - adding the
        caveat must not have reordered, dropped or rescored anything.
        """
        from datetime import date

        from pwf.recommend import recommend

        d = _payload(_page())["planner"]
        conn = init(DB_PATH)
        for day, payload in d["days"].items():
            rec = recommend(conn, when=date.fromisoformat(day), max_miles=200,
                            limit=12, with_forecast=False)
            assert [r["lake"] for r in payload["shortlist"]] == \
                [r["lake"] for r in rec["lakes"]]
            assert [r["expected_fph"] for r in payload["shortlist"]] == \
                [r["expected_fph"] for r in rec["lakes"]]

    def test_archive_survives_below_the_planner(self):
        html = _page()
        for marker in ("The archive behind it", "Bait by month", "The lakes",
                       "How to read this"):
            assert marker in html
        # the planner must come first in the document
        assert html.index('id="planner"') < html.index("The archive behind it")

    def test_citations_link_to_the_club_site(self):
        d = _payload(_page())
        assert d["planner"]["report_url"].startswith(
            "https://www.privatewaterfishing.com/forums/view_report/")
        day = d["planner"]["days"][d["planner"]["default_day"]]
        cited = sum(len(v) for b in day["briefs"].values()
                    for v in b["citations"].values())
        assert cited > 0, "no receipts shipped"

    def test_evidence_drawers_are_native_details(self):
        """`<details>` so the evidence opens without JavaScript and is
        keyboard-reachable."""
        html = _page()
        assert 'el("details", "ev")' in html or "<details" in html

    def test_theme_is_the_bass_palette(self):
        html = _page()
        assert "#f4f2e9" in html and "#7a5f1c" in html, "light palette missing"
        assert "#141811" in html and "#d4ae4a" in html, "dark palette missing"
        assert "family=Fraunces" in html


class TestPageActuallyRuns:
    """`node --check` only parses, and an earlier version of this test only ran
    whatever happened to be inside <script> — which passed while the entire
    planner sat in the <style> block being silently parsed as CSS, so the page
    rendered nothing. These assert the code is in the right block, that it runs,
    and that it actually builds the planner."""

    def test_planner_code_is_in_the_script_block_not_the_stylesheet(self):
        html = _page()
        style_lo, style_hi = html.find("<style>"), html.find("</style>")
        script_lo = html.find("<script>")
        pos = html.find("const P = D.planner")
        assert pos > 0, "planner code missing entirely"
        assert not (style_lo < pos < style_hi), (
            "planner JavaScript is inside <style> — it will be parsed as CSS "
            "and silently do nothing")
        assert pos > script_lo, "planner code sits before the script block"

    def test_every_render_function_reaches_the_script_block(self):
        html = _page()
        script = html[html.find("<script>"):]
        for fn in ("drawMap", "drawScatter", "drawShortlist", "drawBrief",
                   "drawPlanner", "selectLake", "citeTable"):
            assert f"function {fn}" in script, f"{fn} not in the script block"

    def _run_js(self, tail: str):
        """Execute the page's real script against the DOM stub, plus `tail`."""
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if not shutil.which("node"):
            pytest.skip("node not available")
        stub = Path("tests/support/domstub.js")
        if not stub.exists():
            pytest.skip("dom stub missing")
        m = re.search(r"(?s)<script>(.*)</script>", _page())
        assert m, "no script block"
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                         encoding="utf-8") as f:
            f.write(stub.read_text() + "\n" + m.group(1) + "\n" + tail)
            path = f.name
        try:
            return subprocess.run(["node", path], capture_output=True,
                                  text=True, timeout=120)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_hover_links_the_map_scatter_and_table(self):
        """Pointing at a lake in one panel must light it up in the others.

        The map says which direction and how far, the scatter says whether the
        extra drive is worth it, the table carries the numbers - they are one
        instrument only if they are linked. This executes the real hover
        handler rather than grepping for it: an earlier version of the runtime
        stub returned [] from querySelectorAll, which would have let a hover
        that highlighted nothing pass silently.
        """
        r = self._run_js("""
          const tagged = globalThis.__made.filter(n => n.attrs["data-lake"]);
          if (tagged.length < 3) throw new Error("nothing carries data-lake");
          const name = tagged[0].attrs["data-lake"];
          const mine = tagged.filter(n => n.attrs["data-lake"] === name);
          // The scatter circle and the table row carry data-lake. The map's
          // markers are Leaflet objects, not DOM nodes, so they are checked
          // separately below - that difference is exactly what made hovering
          // the table leave the map untouched.
          if (mine.length < 2)
            throw new Error(`only ${mine.length} DOM panel(s) tag ${name}`);
          tagged[0].dispatch("mouseenter");
          const lit = mine.filter(n => n._classes.has("is-hot")).length;
          if (lit !== mine.length)
            throw new Error(`hovering lit ${lit} of ${mine.length} panels`);
          const strays = tagged.filter(n => n.attrs["data-lake"] !== name
                                       && n._classes.has("is-hot"));
          if (strays.length) throw new Error("hover leaked to other lakes");
          // GL features are not DOM nodes, so the map is checked through the
          // filter that drives its highlight layer.
          const hot = globalThis.__gl.filters["lakes-hot"];
          if (!hot || hot[2] !== name)
            throw new Error("hover did not reach the map: " + JSON.stringify(hot));
          tagged[0].dispatch("mouseleave");
          if (globalThis.__made.some(n => n._classes.has("is-hot")))
            throw new Error("hover never cleared");
          if (globalThis.__gl.filters["lakes-hot"][2] === name)
            throw new Error("map stayed highlighted after leave");
          console.log("linked", mine.length + 1, "panels for", name);
        """)
        assert r.returncode == 0, f"linked hover broken:\n{r.stderr[:1500]}"
        assert "linked" in r.stdout

    def test_map_carries_the_whole_club_with_a_drive_for_each(self):
        """The map is the primary surface, so it shows every placed lake - not
        just this week's twelve - and each needs a drive distance.

        Taking `miles` from the ranking gave it only to the 132 lakes with
        enough history; the other 34 had none, so they passed every drive
        filter and a "within sixty miles" view showed lakes 200 miles out.
        """
        d = _payload(_page())["planner"]
        lakes = d["map"]["lakes"]
        assert len(lakes) > 120, "map is not carrying the whole club"
        # Leaflet plots real coordinates, so every mark needs them and they
        # must land inside Texas/Oklahoma.
        for l in lakes:
            assert 25.8 <= l["lat"] <= 37.1, f'{l["lake"]} at {l["lat"]}'
            assert -103.1 <= l["lon"] <= -93.5, f'{l["lake"]} at {l["lon"]}'
        missing = [l["lake"] for l in lakes if l.get("miles") is None]
        assert not missing, f"no drive distance for {missing[:5]}"
        unranked = [l for l in lakes if l.get("fph") is None]
        assert unranked, "some lakes should be too sparse to rank"

    def test_map_filters_actually_change_what_is_plotted(self):
        """The controls are the query, not a view preference, so this drives
        them against a MapLibre stub and counts the features that survive.

        Counting GeoJSON features rather than marker objects is the whole point
        of the GL rewrite: one source, data-driven paint, no per-marker state.
        """
        r = self._run_js("""
          const G = globalThis.__gl;
          const n = () => { drawMap(); return G.sources.lakes.data.features.length; };
          mapFilters.miles = 300; mapFilters.trips = 0; mapFilters.price = 0;
          mapFilters.q = ""; const wide = n();
          if (wide < 100) throw new Error("map is not carrying the club: " + wide);
          mapFilters.miles = 60;
          if (!(n() < wide)) throw new Error("drive filter did nothing");
          mapFilters.miles = 300; mapFilters.trips = 100;
          if (!(n() < wide)) throw new Error("trips filter did nothing");
          mapFilters.trips = 0; mapFilters.price = 90;
          if (!(n() < wide)) throw new Error("price filter did nothing");
          mapFilters.price = 0; mapFilters.q = "coal";
          if (!(n() < wide)) throw new Error("search did not narrow the map");
          mapFilters.q = ""; n();
          // Too little history to rank is drawn hollow, never as average.
          const hollow = G.sources.lakes.data.features
            .filter(f => f.properties.fph == null).length;
          if (!hollow) throw new Error("no lake drawn as too-sparse-to-rank");
          if (!G.sources.rings || !G.sources.gradring)
            throw new Error("drive rings and the 80-mile line are not both drawn");
          for (const id of ["lakes", "lakes-hot", "lakes-sel", "lakes-label"])
            if (!G.layers.some(l => l.id === id))
              throw new Error("missing layer " + id);
          console.log("controls ok", wide, hollow);
        """)
        assert r.returncode == 0, f"map controls broken:\n{r.stderr[:1500]}"
        assert "controls ok" in r.stdout

    def test_map_and_plan_modes_share_one_selection(self):
        r = self._run_js("""
          selectLake("Acker Lake");
          setMode("plan");
          if (selLake !== "Acker Lake") throw new Error("mode switch lost the lake");
          setMode("map");
          if (selLake !== "Acker Lake") throw new Error("mode switch lost the lake");
          if (globalThis.__gl.resizes < 1)
            throw new Error("map never resized after a mode change");
          console.log("modes ok");
        """)
        assert r.returncode == 0, f"modes broken:\n{r.stderr[:1200]}"
        assert "modes ok" in r.stdout

    def test_the_view_is_restorable_and_shareable(self):
        """Coming back from a lake used to dump you at the top of the page with
        the map wherever it happened to be."""
        r = self._run_js("""
          mapFilters.miles = 120; mapFilters.q = "lake";
          pushView({}, { replace: true });
          const hash = globalThis.location.hash;
          if (!/mi=120/.test(hash) || !/q=lake/.test(hash))
            throw new Error("filters are not in the URL: " + hash);
          const parsed = parseHash(hash);
          if (parsed.filters.miles !== 120 || parsed.filters.q !== "lake")
            throw new Error("hash does not round-trip");
          const snap = snapshot();
          if (!snap.map || snap.map.zoom == null)
            throw new Error("snapshot carries no viewport");
          // and a restore puts it back
          mapFilters.miles = 300;
          applyView(parsed);
          if (mapFilters.miles !== 120)
            throw new Error("applyView did not restore the filters");
          console.log("view state ok", hash.slice(0, 40));
        """)
        assert r.returncode == 0, f"view state broken:\n{r.stderr[:1500]}"
        assert "view state ok" in r.stdout

    def test_render_paths_execute_without_error(self):
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if not shutil.which("node"):
            pytest.skip("node not available")
        stub = Path("tests/support/domstub.js")
        if not stub.exists():
            pytest.skip("dom stub missing")

        html = _page()
        m = re.search(r"(?s)<script>(.*)</script>", html)
        assert m, "no script block"
        src = (stub.read_text() + "\n" + m.group(1)
               + "\nif (globalThis.__made.length < 50) "
                 "{ throw new Error('render produced almost nothing'); }"
               + "\nconsole.log('ok', globalThis.__made.length);")
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                         encoding="utf-8") as f:
            f.write(src)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True,
                               timeout=120)
            assert r.returncode == 0, f"page JS threw at runtime:\n{r.stderr[:2000]}"
            assert "ok" in r.stdout
        finally:
            Path(path).unlink(missing_ok=True)
