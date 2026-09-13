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
