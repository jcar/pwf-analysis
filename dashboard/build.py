"""Render the aggregate dashboard as a standalone HTML page."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from .data import BAIT_LABELS, collect

ROOT = Path(__file__).resolve().parent.parent

COHORT_LABELS = {
    "small_clear_grassy": "Small, clear, grassy",
    "small_grassy": "Small and grassy",
    "small_other": "Small, other",
    "larger_grassy": "Larger, grassy",
    "larger_open": "Larger, open",
}
TREND_LABELS = {"falling": "Falling pressure", "steady": "Steady pressure",
                "rising": "Rising pressure",
                "clear_sky": "Clear sky", "partly": "Partly cloudy",
                "overcast": "Overcast"}


def build_dashboard(conn: sqlite3.Connection, out: str) -> Path:
    payload = collect(conn)
    payload["bait_labels"] = BAIT_LABELS
    payload["cohort_labels"] = COHORT_LABELS
    payload["trend_labels"] = TREND_LABELS
    payload["generated"] = date.today().isoformat()

    path = ROOT / out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PAGE.replace("__DATA__", json.dumps(payload)), encoding="utf-8")
    return path


PAGE = r"""<title>Private Water Pattern Book</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bitter:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Source+Sans+3:wght@400;500;600&display=swap">
<style>
:root{
  color-scheme: light;
  --ground:#f7f8f6; --surface:#ffffff; --surface-2:#eef1ed; --surface-3:#e4e9e4;
  --ink:#10201c; --ink-2:#54635e; --ink-3:#8a968f;
  --rule:#dbe1db; --rule-strong:#c3ccc4;
  --accent:#1f6b5c; --accent-soft:#e2efea;
  --d4:#b23434; --d3:#dd6b6b; --d2:#eda3a3; --d1:#f7d6d6;
  --dmid:#eceeea;
  --u1:#cde2fb; --u2:#86b6ef; --u3:#3987e5; --u4:#1c5cab;
  --on-dark:#ffffff; --on-light:#10201c;
  --good:#0ca30c; --warn:#fab219;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --ground:#101310; --surface:#171b18; --surface-2:#1f241f; --surface-3:#272d28;
    --ink:#eef2ee; --ink-2:#a5b1a8; --ink-3:#727e75;
    --rule:#2a312b; --rule-strong:#3a433c;
    --accent:#5cc0a6; --accent-soft:#16302a;
    --d4:#e88585; --d3:#cf5a5a; --d2:#a83a3a; --d1:#7d2828;
    --dmid:#2b302c;
    --u1:#1b3f6b; --u2:#1c5cab; --u3:#3987e5; --u4:#86b6ef;
    --on-dark:#0d100e; --on-light:#eef2ee;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --ground:#101310; --surface:#171b18; --surface-2:#1f241f; --surface-3:#272d28;
  --ink:#eef2ee; --ink-2:#a5b1a8; --ink-3:#727e75;
  --rule:#2a312b; --rule-strong:#3a433c;
  --accent:#5cc0a6; --accent-soft:#16302a;
  --d4:#e88585; --d3:#cf5a5a; --d2:#a83a3a; --d1:#7d2828;
  --dmid:#2b302c;
  --u1:#1b3f6b; --u2:#1c5cab; --u3:#3987e5; --u4:#86b6ef;
  --on-dark:#0d100e; --on-light:#eef2ee;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Source Sans 3", ui-sans-serif, system-ui, sans-serif;
  font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1120px; margin:0 auto; padding-inline:20px; padding-block:0 72px}
h1,h2,h3{font-family:Bitter, Georgia, serif; text-wrap:balance; margin:0}
h1{font-size:clamp(28px,4.6vw,44px); font-weight:700; letter-spacing:-.015em; line-height:1.1}
h2{font-size:20px; font-weight:600; letter-spacing:-.005em}
h3{font-size:15px; font-weight:600}
.num{font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums}
.eyebrow{
  font-size:11px; font-weight:600; letter-spacing:.12em; text-transform:uppercase;
  color:var(--ink-3); margin:0 0 10px
}

/* ---- masthead ---- */
header.top{border-bottom:1px solid var(--rule-strong); padding-block:40px 26px; margin-bottom:34px}
.lede{color:var(--ink-2); max-width:62ch; margin:14px 0 0; font-size:16.5px}
.provenance{
  display:flex; flex-wrap:wrap; gap:6px 20px; margin-top:20px;
  font-size:13px; color:var(--ink-3)
}
.provenance b{color:var(--ink-2); font-weight:600}

/* ---- kpi ---- */
.kpis{display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); margin-bottom:44px}
.kpi{background:var(--surface); padding:18px 18px 16px}
.kpi .v{font-family:"IBM Plex Mono",monospace; font-size:27px; font-weight:600;
  line-height:1.1; letter-spacing:-.02em}
.kpi .k{font-size:12px; color:var(--ink-3); margin-top:5px; letter-spacing:.02em}
.caveat{margin:14px 0 40px; padding:12px 15px; background:var(--accent-soft);
  border-left:3px solid var(--accent); font-size:13.5px; color:var(--ink-2);
  max-width:78ch}

section{margin-bottom:48px}
.shead{display:flex; align-items:baseline; justify-content:space-between;
  gap:16px; flex-wrap:wrap; margin-bottom:6px}
.note{color:var(--ink-2); font-size:14px; max-width:70ch; margin:0 0 18px}

/* ---- coverage ---- */
.tiers{display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:26px}
.tier h3{margin-bottom:3px}
.tier .sub{font-size:12.5px; color:var(--ink-3); margin-bottom:14px}
.cov{display:grid; grid-template-columns:1fr auto; gap:5px 12px; align-items:center}
.cov .lab{font-size:13.5px; color:var(--ink-2)}
.cov .bar{grid-column:1/-1; height:5px; background:var(--surface-3); position:relative;
  margin:-2px 0 7px}
.cov .bar i{position:absolute; inset:0 auto 0 0; background:var(--accent); display:block}
.cov .pc{font-size:12.5px; color:var(--ink-3)}

/* ---- heatmap ---- */
.hm-scroll{overflow-x:auto; padding-bottom:4px}
table.hm{border-collapse:separate; border-spacing:2px; min-width:660px}
table.hm th{font-weight:600; font-size:12px; color:var(--ink-3); padding:0 0 5px;
  text-align:center; letter-spacing:.03em}
table.hm th.rowh{text-align:left; padding-right:12px; color:var(--ink-2);
  font-size:13.5px; white-space:nowrap; font-weight:500}
table.hm td{width:52px; height:34px; text-align:center; font-size:12.5px;
  font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums;
  border-radius:3px; cursor:default}
td.void{background:repeating-linear-gradient(45deg,transparent,transparent 4px,
  var(--surface-3) 4px,var(--surface-3) 5px); color:transparent}
.legend{display:flex; align-items:center; gap:9px; margin-top:16px; flex-wrap:wrap;
  font-size:12.5px; color:var(--ink-3)}
.legend .sw{display:flex; gap:2px}
.legend .sw i{width:26px; height:11px; display:block; border-radius:2px}

/* ---- condition panels ---- */
.panels{display:grid; grid-template-columns:repeat(auto-fit,minmax(258px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule)}
.panel{background:var(--surface); padding:17px 17px 15px}
.panel .ph{display:flex; align-items:baseline; justify-content:space-between; gap:10px}
.panel .pn{font-size:12px; color:var(--ink-3)}
.panel .pv{font-family:"IBM Plex Mono",monospace; font-size:21px; font-weight:600}
.panel ol{list-style:none; margin:13px 0 0; padding:0; display:grid; gap:6px}
.panel li{display:grid; grid-template-columns:1fr auto auto; gap:9px; align-items:center;
  font-size:13.5px}
.chip{font-family:"IBM Plex Mono",monospace; font-size:11.5px; padding:1px 6px;
  border-radius:3px; font-weight:500}
.tn{font-size:11.5px; color:var(--ink-3); font-family:"IBM Plex Mono",monospace}

/* ---- cohorts ---- */
.cohorts{display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:16px}
.cohort{border:1px solid var(--rule); background:var(--surface); padding:16px}
.cohort.is-focus{border-color:var(--accent); box-shadow:inset 3px 0 0 var(--accent)}
.cohort .meta{font-size:12.5px; color:var(--ink-3); margin:3px 0 12px}
.cohort ul{list-style:none; margin:0; padding:0; display:grid; gap:5px; font-size:13.5px}
.cohort li{display:flex; justify-content:space-between; gap:10px; align-items:center}

/* ---- table ---- */
.tbl-scroll{overflow-x:auto; border:1px solid var(--rule)}
table.lakes{border-collapse:collapse; width:100%; min-width:720px; background:var(--surface)}
table.lakes th{
  text-align:right; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--ink-3); font-weight:600; padding:10px 13px; border-bottom:1px solid var(--rule-strong);
  white-space:nowrap; cursor:pointer; user-select:none; background:var(--surface-2)
}
table.lakes th:first-child, table.lakes td:first-child{text-align:left}
table.lakes th[aria-sort]{color:var(--accent)}
table.lakes td{padding:8px 13px; text-align:right; font-size:13.5px;
  border-bottom:1px solid var(--rule); font-variant-numeric:tabular-nums;
  font-family:"IBM Plex Mono",monospace}
table.lakes td:first-child{font-family:"Source Sans 3",sans-serif; white-space:nowrap}
table.lakes tbody tr:hover td{background:var(--surface-2)}
.town{color:var(--ink-3); font-size:12px}
.tag{display:inline-block; font-size:11px; padding:1px 7px; border-radius:10px;
  background:var(--surface-3); color:var(--ink-2); white-space:nowrap;
  font-family:"Source Sans 3",sans-serif}
.tag.focus{background:var(--accent-soft); color:var(--accent); font-weight:600}

/* ---- weekend panel ---- */
.wk{display:grid; grid-template-columns:repeat(auto-fit,minmax(232px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule)}
.wk-card{background:var(--surface); padding:15px 16px 14px; cursor:pointer;
  display:flex; flex-direction:column; gap:3px}
.wk-card:hover{background:var(--surface-2)}
.wk-card .rank{font-size:11px; letter-spacing:.1em; color:var(--ink-3);
  text-transform:uppercase}
.wk-card .nm{font-family:Bitter,Georgia,serif; font-weight:600; font-size:16px}
.wk-card .rate{font-family:"IBM Plex Mono",monospace; font-size:22px; font-weight:600;
  line-height:1.15}
.wk-card .sub{font-size:12.5px; color:var(--ink-3)}
.wk-card .baits{font-size:12.5px; color:var(--ink-2); margin-top:5px}

/* ---- lake profile view ---- */
#profile{display:none}
body.profile-open #index{display:none}
body.profile-open #profile{display:block}
.back{background:none; border:1px solid var(--rule-strong); color:var(--ink-2);
  font:inherit; font-size:13px; padding:5px 12px; cursor:pointer; border-radius:2px}
.back:hover{background:var(--surface-2); color:var(--ink)}
.back:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.p-head{border-bottom:1px solid var(--rule-strong); padding-block:26px 20px;
  margin-bottom:28px}
.p-head h2{font-size:clamp(24px,3.6vw,34px); font-weight:700; letter-spacing:-.015em;
  margin:14px 0 8px}
.facts{display:flex; flex-wrap:wrap; gap:5px 18px; font-size:13.5px; color:var(--ink-2)}
.facts b{color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums}
.p-lead{display:flex; flex-wrap:wrap; gap:26px; margin-top:18px}
.p-stat .v{font-family:"IBM Plex Mono",monospace; font-size:26px; font-weight:600;
  line-height:1.1}
.p-stat .k{font-size:12px; color:var(--ink-3); margin-top:3px}
.p-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(288px,1fr)); gap:30px}
.p-block h3{margin-bottom:4px}
.p-block .cap{font-size:12.5px; color:var(--ink-3); margin:0 0 12px}
.bars{display:grid; grid-template-columns:auto 1fr auto; gap:3px 9px; align-items:center;
  font-size:13px}
.bars .lb{color:var(--ink-2); white-space:nowrap}
.bars .tr{background:var(--surface-3); height:13px; position:relative}
.bars .tr i{position:absolute; inset:0 auto 0 0; display:block}
.bars .vl{font-family:"IBM Plex Mono",monospace; font-size:12.5px;
  font-variant-numeric:tabular-nums; color:var(--ink-2)}
.kv{display:grid; grid-template-columns:1fr auto; gap:4px 12px; font-size:13.5px}
.kv .k{color:var(--ink-2)}
.kv .v{font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums;
  color:var(--ink)}
.pill-row{display:flex; flex-wrap:wrap; gap:6px; margin-top:4px}
.pill{font-size:12px; padding:2px 9px; border-radius:11px; background:var(--surface-3);
  color:var(--ink-2)}
.pill b{color:var(--ink); font-weight:600}
.rules{font-size:12.5px; color:var(--ink-3); margin-top:22px; padding-top:16px;
  border-top:1px solid var(--rule); max-width:74ch}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:var(--surface-2)}

footer{border-top:1px solid var(--rule-strong); padding-top:24px; color:var(--ink-3);
  font-size:13px; max-width:74ch}
footer h3{color:var(--ink-2); margin-bottom:7px}
footer p{margin:0 0 11px}
@media (max-width:560px){ .kpi .v{font-size:23px} }
</style>

<div class="wrap">
<header class="top">
  <p class="eyebrow">Private Water Fishing &middot; member report archive</p>
  <h1>Private Water Pattern Book</h1>
  <p class="lede">Every fishing report the club's members have written, read by rule
  and joined to the weather each trip was actually fished under. Built to answer one
  question: on small, clear, grassy water, what actually works?</p>
  <p class="provenance" id="prov"></p>
</header>

<div id="index">
<div class="kpis" id="kpis"></div>
<p class="caveat" id="caveat"></p>

<section>
  <div class="shead"><h2 id="wk-title">This weekend</h2></div>
  <p class="note" id="wk-note"></p>
  <div class="wk" id="weekend"></div>
</section>

<section>
  <div class="shead"><h2>What the archive will tell you</h2></div>
  <p class="note">Members write down what they caught and what they threw far more
  reliably than they write down the water. Everything on the left is available on
  almost every trip; everything on the right only exists when somebody mentioned it.
  Figures drawn from the right-hand list carry their sample size everywhere they appear.</p>
  <div class="tiers">
    <div class="tier"><h3>Recorded almost every trip</h3>
      <p class="sub">Structured fields, plus weather joined by lake and date</p>
      <div class="cov" id="cov-full"></div></div>
    <div class="tier"><h3>Only when a member wrote it</h3>
      <p class="sub">Pulled from the narrative by pattern matching</p>
      <div class="cov" id="cov-part"></div></div>
  </div>
</section>

<section>
  <div class="shead"><h2>Bait by month</h2><span class="tn" id="hm-n"></span></div>
  <p class="note">Each cell compares a bait's catch rate against that month's own
  baseline, so seasonal swings in the fishing don't masquerade as bait performance.
  Rates are pulled toward the baseline in proportion to how thin the cell is.
  Hatched cells are months where that bait was named on too few trips to score.</p>
  <div class="hm-scroll"><table class="hm" id="hm"></table></div>
  <div class="legend">
    <span>Worse than the month's baseline</span>
    <span class="sw"><i style="background:var(--d4)"></i><i style="background:var(--d3)"></i><i style="background:var(--d2)"></i><i style="background:var(--d1)"></i><i style="background:var(--dmid)"></i><i style="background:var(--u1)"></i><i style="background:var(--u2)"></i><i style="background:var(--u3)"></i><i style="background:var(--u4)"></i></span>
    <span>Better</span>
  </div>
</section>

<section>
  <div class="shead"><h2>When the barometer moves</h2></div>
  <p class="note">Trips grouped by the 24-hour pressure change at the lake on the day
  they were fished. A front is the one condition anglers plan around, and it is on
  record for every trip whether or not the member mentioned the weather. Restricted
  to <span id="exact-n" class="num"></span> trips whose exact date is known from a
  reservation &mdash; older reports carry a date estimated from when they were
  posted, and a one-day error ruins a pressure reading.</p>
  <div class="panels" id="pressure"></div>
</section>

<section>
  <div class="shead"><h2>Under the sky you get</h2></div>
  <p class="note">The same split by cloud cover.</p>
  <div class="panels" id="clouds"></div>
</section>

<section>
  <div class="shead"><h2>Water types</h2></div>
  <p class="note">Lakes grouped by acreage, how clear members report the water, and how
  often they mention vegetation. Any single report rarely describes the water, but a
  lake with two hundred reports accumulates enough mentions to type it.</p>
  <div class="cohorts" id="cohorts"></div>
</section>

<section>
  <div class="shead"><h2>The lakes</h2><span class="tn">click a column to sort</span></div>
  <p class="note">Lakes with at least fifteen reports. Catch rate is the median across
  trips with a countable catch, normalised to fish per hour on the water.</p>
  <div class="tbl-scroll"><table class="lakes" id="lakes"></table></div>
</section>

</div><!-- /#index -->

<div id="profile"></div>

<footer>
  <h3>How to read this</h3>
  <p>This is observational data, not an experiment. Popular baits get thrown more
  often, and under different conditions, than rare ones; better anglers write more
  reports; and only about three percent of reports admit a blank day, which is not a
  believable rate. Everything here describes an association between what someone threw
  and what they caught. None of it establishes cause.</p>
  <p>Catch rates are shrunk toward the baseline of whatever slice they sit in, and
  ranked on the conservative end of the estimate, so a bait that went well on four
  trips does not outrank one that went well on four hundred. Sample sizes are printed
  beside every figure for exactly this reason.</p>
  <p>Built from public report pages by a rule-based pipeline: no model reads the
  reports, and re-running it produces the same numbers. This page shows aggregates
  only &mdash; no member names and no report text.</p>
  <p id="gen" class="num"></p>
</footer>
</div>

<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c;
  if (x !== undefined) n.textContent = x; return n; };
const baitName = b => D.bait_labels[b] || b;
const fmt = (v, n = 2) => (v === null || v === undefined) ? "–" : Number(v).toFixed(n);

/* ---- masthead + kpis ---- */
const h = D.headline;
$("#prov").innerHTML =
  `<span><b>${h.reports.toLocaleString()}</b> reports</span>` +
  `<span><b>${h.lakes}</b> lakes</span>` +
  `<span><b>${h.first || "?"}</b> to <b>${h.last || "?"}</b></span>` +
  `<span><b>${fmt(h.lake_known_pct, 1)}%</b> matched to a lake</span>`;
$("#gen").textContent = "Generated " + D.generated;
$("#caveat").innerHTML =
  `The archive runs from <b>${h.first}</b>, but a catch <i>rate</i> needs both a fish ` +
  `count and a half- or full-day window, and those fields only appear on reports from ` +
  `about <b>${h.scored_from}</b> onward. Every rate on this page therefore rests on ` +
  `<b>${h.scored.toLocaleString()}</b> trips from ${h.scored_from}–${h.scored_to}, not on all ` +
  `${h.reports.toLocaleString()} reports. The older reports still contribute the baits ` +
  `people threw and how they described the water.`;

[["reports", h.reports.toLocaleString(), "reports read"],
 ["lakes", h.lakes, "lakes in the club"],
 ["scored", h.scored.toLocaleString(), "trips with a countable catch"],
 ["fph", fmt(h.median_fph), "median fish per hour"],
 ["best", h.best_lb ? fmt(h.best_lb, 1) + " lb" : "–", "heaviest fish reported"]
].forEach(([, v, k]) => {
  const d = el("div", "kpi"); d.append(el("div", "v", v), el("div", "k", k));
  $("#kpis").append(d);
});

/* ---- coverage ---- */
function coverage(target, rows) {
  const box = $(target);
  rows.forEach(r => {
    box.append(el("div", "lab", r.dimension), el("div", "pc", fmt(r.pct, 0) + "%"));
    const bar = el("div", "bar"), fill = el("i");
    fill.style.width = Math.min(100, r.pct) + "%";
    bar.append(fill); box.append(bar);
  });
}
coverage("#cov-full", D.coverage.filter(r => r.tier === "full"));
coverage("#cov-part", D.coverage.filter(r => r.tier === "partial"));

/* ---- heatmap ---- */
const STEPS = [
  [0.55, "--d4"], [0.72, "--d3"], [0.86, "--d2"], [0.95, "--d1"],
  [1.05, "--dmid"], [1.16, "--u1"], [1.32, "--u2"], [1.55, "--u3"], [Infinity, "--u4"]
];
const DARKSTEP = { "--d4": 1, "--u4": 1 };
function cellColor(lift) { for (const [hi, v] of STEPS) if (lift < hi) return v; return "--u4"; }

(function heatmap() {
  const t = $("#hm"), hm = D.heatmap;
  const byKey = new Map(hm.cells.map(c => [c.bait + "|" + c.month, c]));
  const head = t.insertRow();
  head.append(el("th", "rowh", ""));
  hm.months.forEach(m => head.append(el("th", null, m)));
  let scored = 0;
  hm.baits.forEach(b => {
    const row = t.insertRow();
    row.append(el("th", "rowh", baitName(b)));
    for (let m = 1; m <= 12; m++) {
      const c = byKey.get(b + "|" + m), td = row.insertCell();
      if (!c) { td.className = "void"; td.textContent = "·";
        td.title = baitName(b) + " — fewer than " + hm.min_cell + " trips this month";
        continue; }
      scored++;
      const tok = cellColor(c.lift);
      td.style.background = "var(" + tok + ")";
      td.style.color = DARKSTEP[tok] ? "var(--on-dark)" : "var(--on-light)";
      td.textContent = c.lift.toFixed(2);
      td.title = `${baitName(b)} in ${hm.months[m - 1]}\n` +
        `${c.lift.toFixed(2)}x the month baseline\n` +
        `${fmt(c.fph)} fish/hr across ${c.n} trips`;
    }
  });
  $("#hm-n").textContent = scored + " scored cells";
})();

/* ---- condition panels ---- */
function panels(target, rows, labels) {
  const box = $(target);
  if (!rows.length) { box.append(el("div", "panel", "Not enough data yet.")); return; }
  rows.forEach(r => {
    const p = el("div", "panel");
    const head = el("div", "ph");
    head.append(el("div", "pv", fmt(r.median_fph)), el("div", "pn", r.n + " trips"));
    p.append(el("h3", null, labels[r.value] || r.value), head);
    const note = el("div", "pn", "median fish/hr"); note.style.marginTop = "2px";
    p.append(note);
    const ol = el("ol");
    r.top.forEach(b => {
      const li = el("li");
      const chip = el("span", "chip", b.lift.toFixed(2) + "x");
      const tok = cellColor(b.lift);
      chip.style.background = "var(" + tok + ")";
      chip.style.color = DARKSTEP[tok] ? "var(--on-dark)" : "var(--on-light)";
      li.append(el("span", null, baitName(b.bait)), chip, el("span", "tn", "n=" + b.n));
      ol.append(li);
    });
    p.append(ol); box.append(p);
  });
}
const exn = document.getElementById("exact-n");
if (exn) exn.textContent = (D.exact_trips || 0).toLocaleString();
panels("#pressure", D.pressure, D.trend_labels);
panels("#clouds", D.clouds, D.trend_labels);

/* ---- cohorts ---- */
(function cohorts() {
  const box = $("#cohorts");
  D.cohorts.forEach(c => {
    const d = el("div", "cohort" + (c.cohort === "small_clear_grassy" ? " is-focus" : ""));
    d.append(el("h3", null, D.cohort_labels[c.cohort] || c.cohort));
    d.append(el("div", "meta",
      `${c.lakes} lakes · ${c.trips} trips · median ${fmt(c.median_acres, 0)} acres · ${fmt(c.median_fph)} fish/hr`));
    const ul = el("ul");
    c.top.forEach(b => {
      const li = el("li");
      li.append(el("span", null, baitName(b.bait)),
                el("span", "tn", b.lift.toFixed(2) + "x  n=" + b.n));
      ul.append(li);
    });
    d.append(ul); box.append(d);
  });
})();

/* ---- weekend panel ---- */
(function weekend() {
  const w = D.weekend || {};
  const box = $("#weekend");
  if (!w.lakes || !w.lakes.length) { $("#wk-title").remove(); return; }
  $("#wk-title").textContent = "Best bets for " + w.date;
  $("#wk-note").innerHTML =
    `Ranked by the catch rate each lake has actually produced in ${w.month_name}, ` +
    `within ${w.max_miles} miles, out of ${w.considered} lakes. Backtested on held-out ` +
    `years, a lake's own history predicts its next season at about r=0.65 — which is ` +
    `why the ranking rests on that and not on the forecast. Measured inside each ` +
    `lake-month, the largest weather effect in this archive is around 10% with a ` +
    `confidence interval that includes zero, while lake and month separate lakes ` +
    `threefold. Club ${w.month_name} average is ${w.club_month_mean} fish/hr.`;
  w.lakes.slice(0, 8).forEach((L, i) => {
    const c = el("div", "wk-card");
    c.append(el("div", "rank", "#" + (i + 1)));
    c.append(el("div", "nm", L.lake));
    c.append(el("div", "rate", fmt(L.expected_fph) + " fish/hr"));
    const bits = [];
    if (L.miles != null) bits.push(Math.round(L.miles) + " mi");
    if (L.day_rate) bits.push("$" + Math.round(L.day_rate));
    bits.push(L.n_total + " trips");
    bits.push(L.basis === "lake-month" ? "this month" : "annual avg");
    c.append(el("div", "sub", bits.join(" · ")));
    if (L.top_baits && L.top_baits.length)
      c.append(el("div", "baits", L.top_baits.map(b => baitName(b.bait)).join(", ")));
    c.addEventListener("click", () => openLake(L.lake));
    box.append(c);
  });
})();

/* ---- lake profile ---- */
const RAMP = ["--u1", "--u2", "--u3", "--u4"];
function rampFor(v, max) {
  if (!max || v == null) return "--surface-3";
  const i = Math.min(RAMP.length - 1, Math.floor((v / max) * RAMP.length));
  return RAMP[Math.max(0, i)];
}
function bars(rows, labelKey, valueKey, nKey) {
  const box = el("div", "bars");
  const max = Math.max(...rows.map(r => r[valueKey] || 0), 0.0001);
  rows.forEach(r => {
    box.append(el("div", "lb", r[labelKey]));
    const tr = el("div", "tr"), fill = el("i");
    fill.style.width = Math.max(2, 100 * (r[valueKey] || 0) / max) + "%";
    fill.style.background = "var(" + rampFor(r[valueKey], max) + ")";
    tr.append(fill);
    box.append(tr);
    box.append(el("div", "vl", fmt(r[valueKey]) + (nKey ? `  n=${r[nKey]}` : "")));
  });
  return box;
}
function block(title, cap, node) {
  const b = el("div", "p-block");
  b.append(el("h3", null, title));
  if (cap) b.append(el("p", "cap", cap));
  if (node) b.append(node);
  return b;
}
function kv(pairs) {
  const box = el("div", "kv");
  pairs.forEach(([k, v]) => {
    if (v === null || v === undefined || v === "") return;
    box.append(el("div", "k", k), el("div", "v", v));
  });
  return box;
}
function pills(items) {
  const row = el("div", "pill-row");
  items.forEach(it => {
    const s = el("span", "pill");
    s.innerHTML = `${it.value.replace(/_/g, " ")} <b>${it.n}</b>`;
    row.append(s);
  });
  return row;
}

function renderProfile(name) {
  const p = D.profiles[name];
  const host = $("#profile");
  host.textContent = "";
  if (!p) { host.append(el("p", null, "No profile for " + name)); return; }
  const f = p.facts, v = p.volume, r = p.rate, fish = p.fish, w = p.water;

  const head = el("div", "p-head");
  const back = el("button", "back", "\u2190  All lakes");
  back.addEventListener("click", () => closeLake());
  head.append(back);
  head.append(el("h2", null, p.lake));
  const facts = el("div", "facts");
  const bits = [];
  if (f.town) bits.push(["", f.town]);
  if (f.acres) bits.push(["", `<b>${f.acres}</b> acres`]);
  if (f.max_depth_ft) bits.push(["", `max <b>${f.max_depth_ft}</b> ft`]);
  if (f.miles != null) bits.push(["", `<b>${f.miles}</b> mi from Dallas`]);
  if (f.day_rate) bits.push(["", `<b>$${f.day_rate}</b> / day`]);
  if (f.cohort) bits.push(["", f.cohort.replace(/_/g, " ")]);
  if (f.membership_tier) bits.push(["", f.membership_tier]);
  facts.innerHTML = bits.map(b => `<span>${b[1]}</span>`).join("");
  head.append(facts);

  const lead = el("div", "p-lead");
  [[fmt(r.median) + " fish/hr", `median catch rate (club ${fmt(r.club_median)})`],
   [v.scored, `trips with a countable catch, of ${v.reports} reports`],
   [fish.best_lb ? fmt(fish.best_lb, 1) + " lb" : "\u2013", "best fish reported"],
   [r.percentile != null ? Math.round(r.percentile) + "th" : "\u2013",
    "percentile among club lakes"]
  ].forEach(([val, lab]) => {
    const st = el("div", "p-stat");
    st.append(el("div", "v", val), el("div", "k", lab));
    lead.append(st);
  });
  head.append(lead);
  host.append(head);

  const grid = el("div", "p-grid");

  if (p.by_month.length)
    grid.append(block("By month", `${v.first} to ${v.last}`,
      bars(p.by_month, "month", "median", "n")));

  if (p.by_slot.length)
    grid.append(block("By booking slot",
      "comparable because all-day effort is measured from the data, not assumed",
      bars(p.by_slot.map(s => ({ ...s, label: s.slot.replace("_", " ") })),
           "label", "median", "n")));

  if (p.by_year.length > 2)
    grid.append(block("Recent years", "is it holding up?",
      bars(p.by_year.map(y => ({ ...y, label: String(y.year) })),
           "label", "median", "n")));

  if (p.baits.overall.length) {
    const t = el("div", "bars");
    p.baits.overall.forEach(b => {
      t.append(el("div", "lb", baitName(b.bait)));
      const tr = el("div", "tr"), fill = el("i");
      const tok = cellColor(b.lift);
      fill.style.width = Math.min(100, Math.max(3, b.lift * 55)) + "%";
      fill.style.background = "var(" + tok + ")";
      tr.append(fill); t.append(tr);
      t.append(el("div", "vl", `${b.lift.toFixed(2)}x  n=${b.n}`));
    });
    const seasons = Object.entries(p.baits.by_season)
      .map(([s, rows]) => `${s}: ${baitName(rows[0].bait)}`).join(" · ");
    grid.append(block("Producing baits",
      "against this lake's own baseline" + (seasons ? " — best by season: " + seasons : ""),
      t));
  }

  grid.append(block("The water",
    `clarity and temperature only where a member wrote them down`,
    (() => {
      const box = el("div");
      box.append(kv([
        ["clarity", w.clarity_ft_median != null
          ? `${w.clarity_ft_median} ft (n=${w.clarity_ft_n})` : "not stated"],
        ["water temp", w.water_temp_f_median != null
          ? `${w.water_temp_f_median}\u00b0F (n=${w.water_temp_n})` : "not stated"],
        ["depth fished", w.depth_median_ft != null
          ? `${w.depth_median_ft} ft (n=${w.depth_n})` : "not stated"],
        ["vegetation mentioned", w.veg_mention_rate != null
          ? `${w.veg_mention_rate}% of reports` : "\u2013"],
      ]));
      if (w.vegetation.length) { box.append(el("div", "cap", "growth")); box.append(pills(w.vegetation)); }
      if (w.structure.length) { box.append(el("div", "cap", "cover")); box.append(pills(w.structure)); }
      if (w.technique.length) { box.append(el("div", "cap", "techniques")); box.append(pills(w.technique)); }
      return box;
    })()));

  grid.append(block("The fish",
    fish.species_named_on ? `species named on ${fish.species_named_on} reports` : "",
    (() => {
      const box = el("div");
      box.append(kv([
        ["typical trip", fish.median_fish_per_trip != null
          ? fish.median_fish_per_trip + " fish" : "\u2013"],
        ["best fish", fish.best_lb ? fmt(fish.best_lb, 1) + " lb" : "\u2013"],
        ["trips with a 5 lb+", fish.over_5lb_rate != null
          ? `${fish.over_5lb_rate}% (n=${fish.weight_reports})` : "\u2013"],
      ]));
      if (fish.species.length) {
        box.append(el("div", "cap", "species"));
        box.append(pills(fish.species.map(x =>
          ({ value: x.species, n: x.pct + "%" }))));
      }
      if (fish.weight_bands.length) {
        box.append(el("div", "cap", "sizes reported"));
        box.append(pills(fish.weight_bands.map(b =>
          ({ value: b.value, n: b.pct + "%" }))));
      }
      return box;
    })()));

  const cond = p.conditions || {};
  if (cond.typical) {
    grid.append(block("Typically fished in",
      `what this lake's ${cond.weather_n} dated trips actually met — context, not prediction`,
      kv([["air temp", cond.typical.temp_max_f + "\u00b0F"],
          ["wind", cond.typical.wind_mph + " mph"],
          ["cloud", cond.typical.cloud_pct + "%"]])));
  }

  host.append(grid);
  if (f.harvest_rules) host.append(el("p", "rules", f.harvest_rules));
  if (v.confidence === "thin" || v.confidence === "very thin")
    host.append(el("p", "rules",
      `Only ${v.scored} trips here carry a countable catch, so treat every rate on ` +
      `this page as a hint rather than a measurement.`));
}

function openLake(name) {
  if (!D.profiles[name]) return;
  location.hash = "lake/" + encodeURIComponent(name);
}
function closeLake() { location.hash = ""; }
function route() {
  const m = /^#lake\/(.+)$/.exec(location.hash || "");
  if (m) {
    renderProfile(decodeURIComponent(m[1]));
    document.body.classList.add("profile-open");
    window.scrollTo(0, 0);
  } else {
    document.body.classList.remove("profile-open");
  }
}
window.addEventListener("hashchange", route);

/* ---- lake table ---- */
(function lakes() {
  const cols = [["lake", "Lake", "s"], ["trips", "Reports", "n"], ["acres", "Acres", "n"],
    ["depth", "Max ft", "n"], ["fph", "Fish/hr", "n"], ["best", "Best lb", "n"],
    ["clarity", "Clarity ft", "n"], ["rate", "$/day", "n"], ["cohort", "Water type", "s"]];
  const t = $("#lakes");
  const thead = t.createTHead().insertRow();
  cols.forEach(([key, label]) => {
    const th = el("th", null, label);
    th.addEventListener("click", () => sortBy(key));
    th.dataset.key = key; thead.append(th);
  });
  const tb = t.createTBody();
  let state = { key: "trips", dir: -1 };

  function draw() {
    tb.textContent = "";
    const rows = D.lakes.slice().sort((a, b) => {
      const x = a[state.key], y = b[state.key];
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * state.dir;
    });
    rows.forEach(r => {
      const tr = tb.insertRow();
      if (D.profiles[r.lake]) {
        tr.className = "clickable";
        tr.addEventListener("click", () => openLake(r.lake));
      }
      const c0 = tr.insertCell();
      c0.append(el("div", null, r.lake));
      if (r.town) c0.append(el("div", "town", r.town));
      [r.trips, fmt(r.acres, 0), fmt(r.depth, 0), fmt(r.fph), fmt(r.best, 1),
       fmt(r.clarity, 1), r.rate ? "$" + fmt(r.rate, 0) : "–"]
        .forEach(v => tr.insertCell().textContent = v);
      const tc = tr.insertCell();
      const tag = el("span", "tag" + (r.cohort === "small_clear_grassy" ? " focus" : ""),
                     D.cohort_labels[r.cohort] || "–");
      tc.append(tag);
    });
    thead.querySelectorAll("th").forEach(th => {
      if (th.dataset.key === state.key) th.setAttribute("aria-sort",
        state.dir === 1 ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
  }
  function sortBy(key) {
    state = { key, dir: state.key === key ? -state.dir : (key === "lake" ? 1 : -1) };
    draw();
  }
  draw();
})();

route();
</script>
"""
