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
    p = Path("dashboard/index.html")
    if not p.exists():
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
        m = _payload(_page())["planner"]["map"]
        assert m["states"] and m["rings"] and m["lakes"]
        for mark in m["lakes"]:
            assert 0 <= mark["x"] <= m["width"]
            assert 0 <= mark["y"] <= m["height"]

    def test_no_tile_or_external_map_dependency(self):
        """A tile map would fail silently under the artifact's content policy,
        so the map must be self-contained geometry."""
        html = _page()
        for host in ("tile.openstreetmap", "maps.googleapis", "api.mapbox",
                     "leaflet", "unpkg.com"):
            assert host not in html.lower(), f"{host} would be blocked"

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
          // map circle + scatter circle + table row: all three, or the panels
          // are not actually linked.
          if (mine.length < 3)
            throw new Error(`only ${mine.length} panel(s) tag ${name}`);
          tagged[0].dispatch("mouseenter");
          const lit = mine.filter(n => n._classes.has("is-hot")).length;
          if (lit !== mine.length)
            throw new Error(`hovering lit ${lit} of ${mine.length} panels`);
          const strays = tagged.filter(n => n.attrs["data-lake"] !== name
                                       && n._classes.has("is-hot"));
          if (strays.length) throw new Error("hover leaked to other lakes");
          tagged[0].dispatch("mouseleave");
          if (globalThis.__made.some(n => n._classes.has("is-hot")))
            throw new Error("hover never cleared");
          console.log("linked", mine.length, "panels for", name);
        """)
        assert r.returncode == 0, f"linked hover broken:\n{r.stderr[:1500]}"
        assert "linked" in r.stdout

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
