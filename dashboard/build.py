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
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@400;500;600&family=Source+Sans+3:wght@400;500;600&display=swap">
<style>
:root{
  color-scheme: light;
  --ground:#f4f2e9; --surface:#fbfaf4; --surface-2:#eae7d9; --surface-3:#ddd9c7;
  --ink:#161c12; --ink-2:#4d5745; --ink-3:#767f6b;
  --rule:#d8d4c2; --rule-strong:#bdb8a2;
  --accent:#7a5f1c; --accent-soft:#efe9d5; --lateral:#20281a;
  --d4:#b23434; --d3:#dd6b6b; --d2:#eda3a3; --d1:#f7d6d6;
  --dmid:#eceeea;
  --u1:#cde2fb; --u2:#86b6ef; --u3:#3987e5; --u4:#1c5cab;
  --on-dark:#ffffff; --on-light:#10201c;
  --good:#0ca30c; --warn:#fab219;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --ground:#141811; --surface:#1b2018; --surface-2:#232a1f; --surface-3:#2d3528;
    --ink:#eef0e6; --ink-2:#9aa691; --ink-3:#7a8571;
    --rule:#2b3327; --rule-strong:#3d4636;
    --accent:#d4ae4a; --accent-soft:#252d1c; --lateral:#c3cbb6;
    --d4:#e88585; --d3:#cf5a5a; --d2:#a83a3a; --d1:#7d2828;
    --dmid:#2b302c;
    --u1:#1b3f6b; --u2:#1c5cab; --u3:#3987e5; --u4:#86b6ef;
    --on-dark:#0d100e; --on-light:#eef2ee;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --ground:#141811; --surface:#1b2018; --surface-2:#232a1f; --surface-3:#2d3528;
  --ink:#eef0e6; --ink-2:#9aa691; --ink-3:#7a8571;
  --rule:#2b3327; --rule-strong:#3d4636;
  --accent:#d4ae4a; --accent-soft:#252d1c; --lateral:#c3cbb6;
  --d4:#e88585; --d3:#cf5a5a; --d2:#a83a3a; --d1:#7d2828;
  --dmid:#2b302c;
  --u1:#1b3f6b; --u2:#1c5cab; --u3:#3987e5; --u4:#86b6ef;
  --on-dark:#0d100e; --on-light:#eef2ee;
}

/* --- the bathymetric device: contour field and the lateral line ---------- */
.contours{position:absolute; inset:0; pointer-events:none; opacity:.5}
.contours path{fill:none; stroke:var(--rule-strong); stroke-width:1}
.lateral{height:9px; margin:0; border:0; background:var(--lateral);
  clip-path:polygon(0 40%,4% 20%,9% 55%,14% 25%,20% 60%,26% 22%,32% 58%,38% 28%,
    45% 62%,52% 24%,58% 56%,65% 26%,71% 60%,78% 22%,84% 58%,90% 28%,96% 54%,
    100% 34%,100% 66%,96% 82%,90% 48%,84% 78%,78% 44%,71% 80%,65% 46%,58% 76%,
    52% 44%,45% 80%,38% 48%,32% 78%,26% 44%,20% 80%,14% 46%,9% 76%,4% 44%,0 70%);
  opacity:.55; margin:38px 0 30px}

*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Source Sans 3", ui-sans-serif, system-ui, sans-serif;
  font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1120px; margin:0 auto; padding-inline:20px; padding-block:0 72px}
h1,h2,h3{font-family:Fraunces, "Iowan Old Style", Georgia, serif; text-wrap:balance; margin:0}
h1{font-size:clamp(28px,4.6vw,44px); font-weight:700; letter-spacing:-.015em; line-height:1.1}
h2{font-size:20px; font-weight:600; letter-spacing:-.005em}
h3{font-size:15px; font-weight:600}
.num{font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums}
.eyebrow{
  font-size:11px; font-weight:600; letter-spacing:.12em; text-transform:uppercase;
  color:var(--ink-3); margin:0 0 10px
}

/* ---- masthead ---- */
header.top{position:relative; border-bottom:1px solid var(--rule-strong);
  padding-block:44px 26px; margin-bottom:30px; overflow:hidden}
header.top > *{position:relative}

/* --- planner --------------------------------------------------------------- */
.daybar{display:flex; flex-wrap:wrap; gap:10px 14px; align-items:center;
  margin:20px 0 6px}
.daybtn{font:inherit; font-size:14px; padding:7px 16px; cursor:pointer;
  background:var(--surface); color:var(--ink-2); border:1px solid var(--rule-strong);
  border-radius:2px}
.daybtn[aria-pressed="true"]{background:var(--lateral); color:var(--ground);
  border-color:var(--lateral); font-weight:600}
.daybtn:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.wx{font-size:13.5px; color:var(--ink-2); font-family:"IBM Plex Mono",monospace}
.wx b{color:var(--ink)}

.plan-grid{display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:26px;
  align-items:start}
@media (max-width:980px){ .plan-grid{grid-template-columns:1fr} }

.maprail{display:grid; gap:18px}
.mapbox{border:1px solid var(--rule); background:var(--surface); padding:10px}
.mapbox svg{display:block; width:100%; height:auto}
.mp-state{fill:var(--surface-2); stroke:var(--rule-strong); stroke-width:1}
.mp-ring{fill:none; stroke:var(--rule-strong); stroke-width:1; stroke-dasharray:3 5}
.mp-ringlab{fill:var(--ink-3); font:500 10px "IBM Plex Mono",monospace}
.mp-city{fill:var(--ink-3); font:500 10px "Source Sans 3",sans-serif}
.mp-citydot{fill:var(--ink-3)}
.mp-home{fill:var(--accent)}
.mp-lake{fill:var(--ink-3); opacity:.42}
.mp-pick{stroke:var(--surface); stroke-width:1.2; cursor:pointer}
.mp-lab{fill:var(--ink); font:600 10.5px "Source Sans 3",sans-serif;
  paint-order:stroke; stroke:var(--surface); stroke-width:3px}
.mp-sel{fill:none; stroke:var(--accent); stroke-width:2.5}
.mp-leg{fill:var(--ink-3); font:500 10px "IBM Plex Mono",monospace}
.mp-line{stroke:var(--accent); stroke-width:1.2; stroke-dasharray:2 3; opacity:.8}

.scat{border:1px solid var(--rule); background:var(--surface); padding:10px}
.scat svg{display:block; width:100%; height:auto}
.sc-ax{stroke:var(--rule-strong); stroke-width:1}
.sc-gr{stroke:var(--rule); stroke-width:1}
.sc-lab{fill:var(--ink-3); font:500 10px "IBM Plex Mono",monospace}
.sc-dot{fill:var(--ink-3); opacity:.35}
.sc-pick{cursor:pointer; stroke:var(--surface); stroke-width:1}
.sc-sel{fill:none; stroke:var(--accent); stroke-width:2.5}
.sc-name{fill:var(--ink); font:600 10px "Source Sans 3",sans-serif;
  paint-order:stroke; stroke:var(--surface); stroke-width:3px}

table.short{border-collapse:collapse; width:100%; background:var(--surface);
  border:1px solid var(--rule)}
table.short th{font:600 11px "Source Sans 3",sans-serif; letter-spacing:.07em;
  text-transform:uppercase; color:var(--ink-3); text-align:right; padding:9px 11px;
  border-bottom:1px solid var(--rule-strong); background:var(--surface-2);
  cursor:pointer; user-select:none; white-space:nowrap}
table.short th:first-child{text-align:left}
table.short th[aria-sort]{color:var(--accent)}
table.short td{padding:8px 11px; text-align:right; font-size:13.5px;
  border-bottom:1px solid var(--rule); font-variant-numeric:tabular-nums;
  font-family:"IBM Plex Mono",monospace; white-space:nowrap}
table.short td:first-child{text-align:left; font-family:"Source Sans 3",sans-serif}
table.short tbody tr{cursor:pointer}
table.short tbody tr:hover td{background:var(--surface-2)}
table.short tbody tr.is-sel td{background:var(--accent-soft)}
table.short tbody tr.is-sel td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
.rk{color:var(--ink-3); font-family:"IBM Plex Mono",monospace; font-size:12px}

.brief{border:1px solid var(--rule-strong); background:var(--surface);
  margin-top:26px}
.brief-hd{padding:20px 22px 16px; border-bottom:1px solid var(--rule);
  background:var(--surface-2)}
.brief-hd h3{font-family:Fraunces,Georgia,serif; font-size:24px; font-weight:600;
  margin:0 0 5px}
.brief-hd .sub{font-size:13px; color:var(--ink-2);
  font-family:"IBM Plex Mono",monospace}
.brief-body{padding:20px 22px 22px; display:grid; gap:22px}
.bsec > h4{font:600 11px "Source Sans 3",sans-serif; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-3); margin:0 0 9px}
.bstat{display:flex; flex-wrap:wrap; gap:8px 26px; align-items:baseline}
.bstat .v{font-family:"IBM Plex Mono",monospace; font-size:27px; font-weight:600}
.bstat .k{font-size:12.5px; color:var(--ink-3)}
.bline{font-size:14.5px; line-height:1.6; margin:8px 0 0; max-width:70ch}
.bnote{font-size:13.5px; line-height:1.55; color:var(--ink); margin:8px 0 0;
  padding:9px 13px; background:var(--accent-soft); border-left:3px solid var(--accent);
  max-width:74ch}
.pitem{display:grid; grid-template-columns:1fr auto auto; gap:3px 12px;
  padding:8px 0; border-bottom:1px solid var(--rule); align-items:center}
.pitem:last-child{border-bottom:none}
.pitem .nm{font-size:14.5px; font-weight:500}
.pitem .d{font-family:"IBM Plex Mono",monospace; font-size:13.5px; font-weight:600}
.pitem .m{font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--ink-3)}
.pitem .sub{grid-column:1/-1; font-size:12.5px; color:var(--ink-2)}
.skip{font-size:13.5px; color:var(--ink-2)}

details.ev{margin-top:7px; font-size:12.5px}
details.ev summary{cursor:pointer; color:var(--accent); font-weight:600;
  list-style:none; display:inline-flex; gap:5px; align-items:center}
details.ev summary::-webkit-details-marker{display:none}
details.ev summary::before{content:"▸"; font-size:10px}
details.ev[open] summary::before{content:"▾"}
details.ev summary:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.evbody{margin-top:8px; padding:11px 13px; background:var(--surface-2);
  border-left:2px solid var(--rule-strong); color:var(--ink-2); line-height:1.55}
.evbody table{border-collapse:collapse; margin-top:7px; font-size:12px}
.evbody td{padding:2px 10px 2px 0; font-family:"IBM Plex Mono",monospace}
.evbody a{color:var(--accent)}
.archive-head{display:flex; align-items:baseline; justify-content:space-between;
  gap:16px; flex-wrap:wrap; margin:10px 0 20px}
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

/* ---- contour field in the masthead ---- */
(function contours() {
  const svg = document.getElementById("contours");
  if (!svg) return;
  const W = 1200, H = 220;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  let d = "";
  // Nested closed contours, the way a lake basin reads on a chart.
  for (let i = 0; i < 9; i++) {
    const k = i / 9, amp = 16 + i * 5, y = H * 0.52 + (i - 4) * 15;
    let pts = "";
    for (let x = -40; x <= W + 40; x += 24) {
      const t = x / W * Math.PI * 2;
      pts += `${x},${(y + Math.sin(t * 1.6 + k * 5) * amp
        + Math.sin(t * 3.1 + k * 2) * amp * 0.35).toFixed(1)} `;
    }
    d += "M" + pts.trim().split(" ").join("L") + " ";
  }
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  svg.append(path);
})();

/* ---- the planner ---- */
const P = D.planner || {};
let planDay = P.default_day;
let selLake = null;

function svgEl(tag, attrs, text) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const k in (attrs || {})) n.setAttribute(k, attrs[k]);
  if (text !== undefined) n.textContent = text;
  return n;
}
function dayData() { return (P.days || {})[planDay] || {}; }
function rateColor(v, max) {
  const ramp = ["--u1", "--u2", "--u3", "--u4"];
  const i = Math.min(ramp.length - 1, Math.floor((v / (max || 1)) * ramp.length));
  return "var(" + ramp[Math.max(0, i)] + ")";
}

function drawMap() {
  const m = P.map, host = $("#mapbox");
  if (!m || !host) return;
  host.textContent = "";
  const day = dayData();
  const picks = new Map((day.shortlist || []).map((r, i) => [r.lake, { ...r, rank: i + 1 }]));
  const max = Math.max(...(day.shortlist || []).map(r => r.expected_fph || 0), 1);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${m.width} ${m.height}`, role: "img",
    "aria-label": "Club lakes and drive distance from Dallas",
  });
  m.states.forEach(st => svg.append(svgEl("path", { d: st.d, class: "mp-state" })));
  m.rings.forEach(r => {
    svg.append(svgEl("path", { d: r.d, class: "mp-ring" }));
    svg.append(svgEl("text", {
      x: r.label_x + 4, y: r.label_y + 11, class: "mp-ringlab",
    }, `${r.miles} mi`));
  });
  m.cities.forEach(c => {
    if (c.home) return;
    svg.append(svgEl("circle", { cx: c.x, cy: c.y, r: 2, class: "mp-citydot" }));
    svg.append(svgEl("text", { x: c.x + 5, y: c.y + 3.5, class: "mp-city" }, c.name));
  });
  // every lake, so the shortlist is seen in context
  m.lakes.forEach(l => {
    if (picks.has(l.lake)) return;
    // Node.append() returns undefined, so the title has to be attached to the
    // circle before the circle goes into the document.
    const dot = svgEl("circle", { cx: l.x, cy: l.y, r: 2.6, class: "mp-lake" });
    dot.append(svgEl("title", {}, l.lake));
    svg.append(dot);
  });
  const home = m.home;
  svg.append(svgEl("circle", { cx: home.x, cy: home.y, r: 4.5, class: "mp-home" }));
  svg.append(svgEl("text", { x: home.x + 7, y: home.y + 4, class: "mp-city" }, "Dallas"));

  m.lakes.forEach(l => {
    const pick = picks.get(l.lake);
    if (!pick) return;
    if (selLake === l.lake) {
      svg.append(svgEl("line", {
        x1: home.x, y1: home.y, x2: l.x, y2: l.y, class: "mp-line",
      }));
    }
    const c = svgEl("circle", {
      cx: l.x, cy: l.y, r: 6.5, class: "mp-pick",
      fill: rateColor(pick.expected_fph, max),
      "data-lake": l.lake,
    });
    c.append(svgEl("title", {},
      `${l.lake} — ${fmt(pick.expected_fph)} fish/hr, ${Math.round(pick.miles)} mi`));
    c.addEventListener("click", () => selectLake(l.lake));
    svg.append(c);
    if (selLake === l.lake)
      svg.append(svgEl("circle", { cx: l.x, cy: l.y, r: 10, class: "mp-sel" }));
    svg.append(svgEl("text", { x: l.x + 9, y: l.y + 3.5, class: "mp-lab" },
      String(pick.rank)));
  });
  svg.append(svgEl("text", { x: 8, y: m.height - 8, class: "mp-leg" },
    "rings = drive distance · numbers = rank · deeper blue = better"));
  host.append(svg);
}

function drawScatter() {
  const host = $("#scat");
  const day = dayData();
  const rows = (day.shortlist || []).filter(r => r.miles != null);
  if (!host || !rows.length) return;
  host.textContent = "";
  const W = 340, H = 260, L = 44, B = 34, T = 14, R = 12;
  const maxMi = Math.max(...rows.map(r => r.miles), 60) * 1.08;
  const maxF = Math.max(...rows.map(r => r.expected_fph), 1) * 1.12;
  const x = v => L + (v / maxMi) * (W - L - R);
  const y = v => H - B - (v / maxF) * (H - B - T);
  const svg = svgEl("svg", {
    viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Expected catch rate against drive distance",
  });
  [0, 0.25, 0.5, 0.75, 1].forEach(f => {
    svg.append(svgEl("line", {
      x1: L, x2: W - R, y1: y(maxF * f), y2: y(maxF * f), class: "sc-gr",
    }));
    svg.append(svgEl("text", { x: L - 6, y: y(maxF * f) + 3.5, class: "sc-lab",
      "text-anchor": "end" }, (maxF * f).toFixed(0)));
  });
  svg.append(svgEl("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "sc-ax" }));
  [0, 60, 120, 180].filter(v => v <= maxMi).forEach(v => {
    svg.append(svgEl("text", { x: x(v), y: H - B + 15, class: "sc-lab",
      "text-anchor": "middle" }, String(v)));
  });
  svg.append(svgEl("text", { x: (L + W - R) / 2, y: H - 6, class: "sc-lab",
    "text-anchor": "middle" }, "drive, miles"));
  svg.append(svgEl("text", { x: 10, y: 11, class: "sc-lab" }, "fish/hr"));

  const max = Math.max(...rows.map(r => r.expected_fph || 0), 1);
  rows.forEach(r => {
    const c = svgEl("circle", {
      cx: x(r.miles), cy: y(r.expected_fph), r: 6, class: "sc-pick",
      fill: rateColor(r.expected_fph, max), "data-lake": r.lake,
    });
    c.append(svgEl("title", {},
      `${r.lake} — ${fmt(r.expected_fph)} fish/hr, ${Math.round(r.miles)} mi`));
    c.addEventListener("click", () => selectLake(r.lake));
    svg.append(c);
    if (selLake === r.lake) {
      svg.append(svgEl("circle", {
        cx: x(r.miles), cy: y(r.expected_fph), r: 10, class: "sc-sel" }));
      svg.append(svgEl("text", {
        x: x(r.miles) + 12, y: y(r.expected_fph) + 3.5, class: "sc-name" }, r.lake));
    }
  });
  host.append(svg);
}

let shortSort = { key: "score", dir: -1 };
function drawShortlist() {
  const t = $("#short"), day = dayData();
  const rows = (day.shortlist || []).map((r, i) => ({ ...r, rank: i + 1 }));
  if (!t || !rows.length) return;
  t.textContent = "";
  const cols = [
    ["lake", "Lake"], ["expected_fph", "Fish/hr"], ["miles", "Drive"],
    ["day_rate", "$/day"], ["n_total", "Trips"], ["band", "Spread"],
    ["bust", "Bust"],
  ];
  const head = t.createTHead().insertRow();
  cols.forEach(([key, label]) => {
    const th = el("th", null, label);
    th.dataset.key = key;
    if (shortSort.key === key)
      th.setAttribute("aria-sort", shortSort.dir === 1 ? "ascending" : "descending");
    th.addEventListener("click", () => {
      shortSort = { key, dir: shortSort.key === key ? -shortSort.dir
        : (key === "lake" ? 1 : -1) };
      drawShortlist();
    });
    head.append(th);
  });
  const val = (r, k) => k === "band" ? ((r.consistency || {}).band || "")
    : k === "bust" ? ((r.consistency || {}).bust_rate ?? -1) : r[k];
  rows.sort((a, b) => {
    const x = val(a, shortSort.key), y = val(b, shortSort.key);
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * shortSort.dir;
  });
  const tb = t.createTBody();
  rows.forEach(r => {
    const cs = r.consistency || {};
    const tr = tb.insertRow();
    if (selLake === r.lake) tr.className = "is-sel";
    tr.addEventListener("click", () => selectLake(r.lake));
    const c0 = tr.insertCell();
    c0.append(el("span", "rk", "#" + r.rank + "  "), document.createTextNode(r.lake));
    [fmt(r.expected_fph), r.miles == null ? "–" : Math.round(r.miles) + " mi",
     r.day_rate ? "$" + Math.round(r.day_rate) : "–", r.n_total,
     cs.band || "–", cs.bust_rate == null ? "–" : Math.round(cs.bust_rate) + "%"]
      .forEach(v => tr.insertCell().textContent = v);
  });
}

function ev(summaryText, bodyNode) {
  const d = el("details", "ev");
  d.append(el("summary", null, summaryText));
  const b = el("div", "evbody");
  b.append(bodyNode);
  d.append(b);
  return d;
}
function citeTable(cites) {
  const wrap = el("div");
  if (!cites || !cites.length) {
    wrap.append(el("div", null, "No individual trips recorded for this one."));
    return wrap;
  }
  wrap.append(el("div", null,
    `The ${cites.length} most recent trips this rests on — each opens the member's `
    + `report on the club site:`));
  const t = el("table");
  cites.forEach(([id, when, fish]) => {
    const tr = el("tr");
    const a = el("a", null, "report " + id);
    a.href = (P.report_url || "") + id;
    a.target = "_blank";
    a.rel = "noopener";
    const c1 = el("td"); c1.append(a);
    tr.append(c1, el("td", null, when),
      el("td", null, fish == null ? "no count" : fish + " fish"));
    t.append(tr);
  });
  wrap.append(t);
  return wrap;
}

function drawBrief() {
  const host = $("#brief"), day = dayData();
  if (!host) return;
  const b = (day.briefs || {})[selLake];
  host.textContent = "";
  if (!b) return;
  const prof = (D.profiles || {})[selLake] || {};
  const f = prof.facts || {}, ex = b.expected, exp = b.expect, plan = b.plan;

  const hd = el("div", "brief-hd");
  hd.append(el("h3", null, b.lake));
  const bits = [];
  if (f.miles != null) bits.push(`${f.miles} mi from Dallas`);
  if (f.day_rate) bits.push(`$${f.day_rate}/day`);
  if (f.acres) bits.push(`${f.acres} acres`);
  if (f.max_depth_ft) bits.push(`max ${f.max_depth_ft} ft`);
  if (f.boat_type) bits.push(f.boat_type);
  hd.append(el("div", "sub", `${b.weekday} ${b.date}  ·  ` + bits.join("  ·  ")));
  host.append(hd);

  const body = el("div", "brief-body");

  // ---- expect ----
  const s1 = el("div", "bsec");
  s1.append(el("h4", null, "What to expect"));
  const st = el("div", "bstat");
  [[fmt(ex.fph) + " fish/hr", `expected for ${ex.month_name} (club ${ex.club_month_mean})`],
   [exp.typical_fish ?? "–", "fish on a typical day"],
   [exp.worst_decile ?? "–", "fish/hr on the slowest day in ten"],
   [(exp.bust_rate ?? "–") + "%", `came back with 2 or fewer (club ${Math.round(exp.club_bust_rate)}%)`]
  ].forEach(([v, k]) => {
    const d = el("div");
    d.append(el("div", "v", String(v)), el("div", "k", k));
    st.append(d);
  });
  s1.append(st);
  const monthRows = (prof.by_month || []).filter(m => m.n);
  s1.append(ev(`Where ${fmt(ex.fph)} comes from`, (() => {
    const w = el("div");
    w.append(el("div", null,
      `Blended from this lake's ${ex.n_total} scored trips, weighted toward recent `
      + `years and shrunk toward the club mean by how little backs it. Basis: `
      + `${ex.basis === "lake-month" ? `its own ${ex.month_name} record (${ex.n_basis} trips)`
        : "its year-round average, scaled by the club's seasonal shape"}. `
      + `Backtested across six held-out years, a lake's history predicts its next `
      + `season at about r=0.65.`));
    if (monthRows.length) w.append(bars(monthRows, "month", "median", "n"));
    return w;
  })()));
  if (exp.sentence) s1.append(el("p", "bline", exp.sentence));
  s1.append(ev("How reliable is that?", el("div", null, exp.caveat)));
  body.append(s1);

  // ---- conditions ----
  const cond = b.conditions || {};
  if (cond.forecast) {
    const s2 = el("div", "bsec");
    const fc = cond.forecast;
    s2.append(el("h4", null, "Conditions that day"));
    s2.append(el("p", "bline",
      `${Math.round(fc.temp_max_f)}°F high · ${Math.round(fc.wind_max_mph)} mph `
      + `· ${fc.cloud_pct}% cloud · ${fc.pressure_trend || "steady"} pressure`));
    if (cond.note) s2.append(el("p", "bnote", cond.note));
    s2.append(ev("Why the forecast is not in the ranking", el("div", null,
      "Measured inside each lake-month, the largest weather effect in this archive "
      + "— calm against windy — is about 10% with a confidence interval that "
      + "includes zero. Cloud is 9%, pressure 7%, moon 3%. Lake and month separate "
      + "lakes threefold. So conditions are shown to plan the day around, not to "
      + "pick the lake.")));
    body.append(s2);
  }

  // ---- the plan ----
  const pres = plan.presentation || {};
  const s3 = el("div", "bsec");
  s3.append(el("h4", null, "How to fish it"));
  if (pres.lead) s3.append(el("p", "bline", pres.lead + "."));
  (pres.use || []).forEach(u => {
    const row = el("div", "pitem");
    row.append(el("div", "nm", u.label));
    const d = el("div", "d", `${u.diff >= 0 ? "+" : ""}${u.diff.toFixed(2)} fish/hr`);
    d.style.color = "var(--u4)";
    row.append(d, el("div", "m", `${u.years_agreeing}/${u.years} yrs`));
    if (u.here) {
      const against = u.here.diff < 0 ? " — against the club pattern here" : "";
      row.append(el("div", "sub",
        `at this lake ${u.here.diff >= 0 ? "+" : ""}${u.here.diff.toFixed(2)} over `
        + `${u.here.trips} trips${against}`));
    }
    s3.append(row);
  });
  if ((pres.avoid || []).length)
    s3.append(el("p", "skip", "Leave alone: " + pres.avoid
      .map(a => `${a.label} (${a.diff.toFixed(2)})`).join(", ")));
  s3.append(ev("What 'holds up' means", el("div", null,
    "Each presentation is compared against the other trips that named about as many "
    + "baits, because trips describing more tackle catch more fish and would "
    + "otherwise flatter everything at once. The years column counts how many "
    + "separate years agree with the pooled result — two techniques clear the "
    + "pooled interval and then flip sign in half the years, so they are not "
    + "promoted.")));
  body.append(s3);

  // ---- baits ----
  const baits = plan.baits || {};
  const s4 = el("div", "bsec");
  s4.append(el("h4", null, "What to tie on"));
  s4.append(el("p", "bline", (baits.lead || "") + "."));
  ["backed", "suggestive"].forEach(key => {
    (baits[key] || []).slice(0, 3).forEach(e => {
      const row = el("div", "pitem");
      row.append(el("div", "nm", baitName(e.bait) + (e.club_unstable ? " †" : "")));
      const d = el("div", "d", `${e.diff >= 0 ? "+" : ""}${e.diff.toFixed(2)} fish/hr`);
      d.style.color = e.lo > 0 ? "var(--u4)" : "var(--ink-2)";
      row.append(d, el("div", "m", `${e.trips} trips`));
      row.append(el("div", "sub",
        `95% interval ${e.lo.toFixed(2)} to ${e.hi.toFixed(2)}`
        + (e.club_unstable
          ? " · † club-wide this bait does not hold its sign year to year" : "")));
      row.append(ev(`The ${(b.citations[e.bait] || []).length} trips behind this`,
        citeTable(b.citations[e.bait])));
      s4.append(row);
    });
  });
  if ((baits.below || []).length)
    s4.append(el("p", "skip", "Measurably behind here: " + baits.below.slice(0, 3)
      .map(e => `${baitName(e.bait)} (${e.diff.toFixed(2)})`).join(", ")));
  body.append(s4);

  // ---- where ----
  if ((plan.where || []).length) {
    const s5 = el("div", "bsec");
    s5.append(el("h4", null, "Where they fish it"));
    s5.append(el("p", "bline", "Members name " + plan.where
      .map(w => `${w.value.replace(/_/g, " ")} (${w.n})`).join(", ") + "."));
    if ((plan.vegetation || []).length)
      s5.append(el("p", "skip", "Growth: " + plan.vegetation
        .map(v => `${v.value.replace(/_/g, " ")} (${v.n})`).join(", ")));
    body.append(s5);
  }

  const s6 = el("div", "bsec");
  s6.append(el("h4", null, "Which slot"));
  s6.append(el("p", "bline", plan.slot_note));
  body.append(s6);

  const more = el("p", "skip");
  const a = el("a", null, "Full profile for " + b.lake + " →");
  a.href = "#lake/" + encodeURIComponent(b.lake);
  a.style.color = "var(--accent)";
  more.append(a);
  body.append(more);

  host.append(body);
}

function selectLake(name) {
  selLake = name;
  drawMap(); drawScatter(); drawShortlist(); drawBrief();
  const el_ = $("#brief");
  if (el_) el_.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function drawDaybar() {
  const bar = $("#daybar");
  if (!bar || !P.days) return;
  bar.textContent = "";
  Object.keys(P.days).forEach(key => {
    const d = P.days[key];
    const b = el("button", "daybtn", `${d.weekday} ${key.slice(5)}`);
    b.type = "button";
    b.id = "day-" + key;
    b.setAttribute("aria-pressed", String(key === planDay));
    b.addEventListener("click", () => {
      planDay = key;
      const sl = dayData().shortlist || [];
      if (!sl.some(r => r.lake === selLake)) selLake = sl.length ? sl[0].lake : null;
      drawPlanner();
    });
    bar.append(b);
  });
}

function drawPlanner() {
  if (!P.days) return;
  const day = dayData();
  drawDaybar();
  const note = $("#plan-note");
  if (note) note.innerHTML =
    `Ranked on what each lake has actually produced in <b>${day.month_name}</b>, `
    + `within <b>${day.max_miles} miles</b>, out of <b>${day.considered}</b> lakes. `
    + `The club averages ${day.club_month_mean} fish an hour this month. Pick a lake `
    + `on the map, the plot or the table — everything below it opens onto the trips `
    + `it came from.`;
  const wx = $("#wx");
  const top = (day.briefs || {})[selLake] || Object.values(day.briefs || {})[0];
  const fc = top && top.conditions ? top.conditions.forecast : null;
  if (wx && fc) wx.innerHTML =
    `Forecast around Dallas: <b>${Math.round(fc.temp_max_f)}°F</b>, `
    + `<b>${Math.round(fc.wind_max_mph)} mph</b>, ${fc.cloud_pct}% cloud`;
  drawMap(); drawScatter(); drawShortlist(); drawBrief();
}

if (P.days) {
  const first = dayData().shortlist || [];
  selLake = first.length ? first[0].lake : null;
  drawPlanner();
}

/* ---- weekend panel ---- 
.wk{display:grid; grid-template-columns:repeat(auto-fit,minmax(232px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule)}
.wk-card{background:var(--surface); padding:15px 16px 14px; cursor:pointer;
  display:flex; flex-direction:column; gap:3px}
.wk-card:hover{background:var(--surface-2)}
.wk-card .rank{font-size:11px; letter-spacing:.1em; color:var(--ink-3);
  text-transform:uppercase}
.wk-card .nm{font-family:Fraunces,"Iowan Old Style",Georgia,serif; font-weight:600; font-size:16px}
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
.summary{margin:0 0 30px; max-width:78ch}
.summary h3{font-size:13px; font-weight:600; letter-spacing:.1em;
  text-transform:uppercase; color:var(--ink-3); font-family:"Source Sans 3",sans-serif;
  margin-bottom:12px}
.summary p{margin:0 0 12px; font-size:15.5px; line-height:1.62; color:var(--ink)}
.summary .mentions{font-size:14px; color:var(--ink-2); border-left:3px solid var(--accent);
  padding:10px 0 10px 14px; background:var(--accent-soft); margin-top:4px}
.summary .mentions b{color:var(--ink); font-weight:600}
.summary .caveat-line{font-size:13.5px; color:var(--ink-2); margin-top:12px;
  padding-top:10px; border-top:1px solid var(--rule)}
.expect{border:1px solid var(--rule); background:var(--surface); padding:14px 16px;
  margin:0 0 26px}
.expect .s{font-size:15px; line-height:1.6; margin:0 0 8px}
.expect .figs{display:flex; flex-wrap:wrap; gap:6px 20px; font-size:12.5px;
  color:var(--ink-3); font-family:"IBM Plex Mono",monospace}
.expect .figs b{color:var(--ink-2); font-weight:600}
.expect .cav{font-size:12px; color:var(--ink-3); margin:9px 0 0; line-height:1.5}
.tech-yrs{font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--ink-3)}
.ev{display:grid; gap:16px}
.ev-group{border:1px solid var(--rule); background:var(--surface)}
.ev-group.is-backed{border-color:var(--accent); box-shadow:inset 3px 0 0 var(--accent)}
.ev-group.is-below{box-shadow:inset 3px 0 0 var(--d3)}
.ev-head{display:flex; align-items:baseline; justify-content:space-between;
  gap:12px; padding:10px 14px; border-bottom:1px solid var(--rule);
  background:var(--surface-2)}
.ev-head .t{font-size:12px; font-weight:600; letter-spacing:.07em;
  text-transform:uppercase; color:var(--ink-2)}
.ev-head .c{font-size:12px; color:var(--ink-3)}
.ev-row{display:grid; grid-template-columns:1fr auto auto; gap:4px 12px;
  padding:9px 14px; border-bottom:1px solid var(--rule); align-items:center}
.ev-row:last-child{border-bottom:none}
.ev-row .nm{font-size:14px; font-weight:500}
.ev-row .d{font-family:"IBM Plex Mono",monospace; font-size:13.5px;
  font-variant-numeric:tabular-nums; font-weight:600}
.ev-row .n{font-family:"IBM Plex Mono",monospace; font-size:12px; color:var(--ink-3)}
.ev-row .ci{grid-column:1/-1; display:flex; align-items:center; gap:9px;
  font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--ink-3)}
.ci-track{position:relative; flex:1; height:9px; background:var(--surface-3);
  min-width:90px}
.ci-track .zero{position:absolute; top:-2px; bottom:-2px; width:1px;
  background:var(--rule-strong)}
.ci-track .span{position:absolute; top:2px; height:5px; border-radius:3px}
.ci-track .pt{position:absolute; top:0; width:3px; height:9px; background:var(--ink)}
.ev-row .dt{grid-column:1/-1; font-size:12.5px; color:var(--ink-2); margin-top:2px}
.ev-lead{font-size:15.5px; line-height:1.6; margin:0 0 6px}
.ev-note{font-size:12.5px; color:var(--ink-3); margin:0 0 14px; max-width:74ch}
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
  <svg class="contours" id="contours" aria-hidden="true"></svg>
  <p class="eyebrow">Private Water Fishing &middot; member report archive</p>
  <h1>Private Water Pattern Book</h1>
  <p class="lede">Thirteen thousand member reports, read by rule and joined to the
  weather each trip was fished under, pointed at one question: which lake is worth
  booking, and what goes in the boat. Every figure below opens onto the trips it
  came from.</p>
  <p class="provenance" id="prov"></p>
</header>

<div id="index">

<section id="planner">
  <div class="daybar" id="daybar"></div>
  <p class="wx" id="wx"></p>
  <p class="note" id="plan-note"></p>

  <div class="plan-grid">
    <div>
      <div style="overflow-x:auto"><table class="short" id="short"></table></div>
      <div class="brief" id="brief"></div>
    </div>
    <div class="maprail">
      <div class="mapbox" id="mapbox"></div>
      <div class="scat" id="scat"></div>
    </div>
  </div>
</section>

<hr class="lateral">

<div class="archive-head">
  <h2>The archive behind it</h2>
  <span class="tn">every number above comes from here</span>
</div>

<div class="kpis" id="kpis"></div>
<p class="caveat" id="caveat"></p>

<section>
  <div class="shead"><h2 id="wk-title">Ranked for the weekend</h2></div>
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

const SUPPORT_LABEL = {
  backed: ["Backed by the data", "is-backed"],
  suggestive: ["Leaning that way, not proven", ""],
  unproven: ["Thrown here, but not separated from the rest", ""],
  below: ["Below the lake's other baits", "is-below"],
  thin: ["Too few trips to say", ""],
};

function ciBar(e, scale) {
  const wrap = el("div", "ci");
  const track = el("div", "ci-track");
  const pos = v => ((v + scale) / (2 * scale)) * 100;
  const zero = el("div", "zero"); zero.style.left = pos(0) + "%";
  const span = el("div", "span");
  const lo = Math.max(-scale, e.lo), hi = Math.min(scale, e.hi);
  span.style.left = pos(lo) + "%";
  span.style.width = Math.max(1.5, pos(hi) - pos(lo)) + "%";
  span.style.background = e.lo > 0 ? "var(--u3)" : e.hi < 0 ? "var(--d3)" : "var(--surface-3)";
  span.style.outline = "1px solid var(--rule-strong)";
  const pt = el("div", "pt"); pt.style.left = pos(e.diff) + "%";
  track.append(span, zero, pt);
  wrap.append(el("span", null, `${e.lo >= 0 ? "+" : ""}${e.lo.toFixed(2)}`));
  wrap.append(track);
  wrap.append(el("span", null, `${e.hi >= 0 ? "+" : ""}${e.hi.toFixed(2)}`));
  return wrap;
}

function baitEvidence(baits) {
  const rec = baits.recommendation || {};
  const ev = baits.evidence || [];
  const box = el("div", "p-block");
  box.append(el("h3", null, "What to throw"));
  if (rec.lead) box.append(el("p", "ev-lead", rec.lead + "."));
  box.append(el("p", "ev-note",
    `${rec.n_compared || ev.length} baits compared. Each is measured against the ` +
    `other baits on trips that named about as many, because trips listing more ` +
    `baits catch more fish and would otherwise flatter every bait at once. The ` +
    `bar shows the 95% interval; where it crosses zero, the archive cannot tell ` +
    `that bait apart from the rest.`));

  const scale = Math.max(1, ...ev.filter(e => e.hi != null)
    .map(e => Math.max(Math.abs(e.lo), Math.abs(e.hi))));
  const wrap = el("div", "ev");
  ["backed", "suggestive", "unproven", "below", "thin"].forEach(key => {
    const group = rec[key] || [];
    if (!group.length) return;
    const [label, cls] = SUPPORT_LABEL[key];
    const g = el("div", "ev-group" + (cls ? " " + cls : ""));
    const head = el("div", "ev-head");
    head.append(el("div", "t", label), el("div", "c", group.length + " of " + ev.length));
    g.append(head);
    group.forEach(e => {
      const row = el("div", "ev-row");
      row.append(el("div", "nm", baitName(e.bait)));
      const d = el("div", "d", e.diff == null ? "–"
        : `${e.diff >= 0 ? "+" : ""}${e.diff.toFixed(2)} fish/hr`);
      d.style.color = e.lo > 0 ? "var(--u4)" : e.hi < 0 ? "var(--d4)" : "var(--ink-2)";
      row.append(d);
      row.append(el("div", "n", `${e.trips} trips · ${e.share}%`));
      if (e.club_unstable) {
        const f = el("div", "dt",
          "† club-wide this bait does not hold its sign from year to year — a " +
          "caveat on the club average, not on this lake's own trips");
        f.style.color = "var(--ink-3)";
        row.append(f);
      }
      if (e.lo != null) row.append(ciBar(e, scale));
      const dt = e.detail || {};
      const bits = [];
      if ((dt.subtypes || []).length)
        bits.push("mostly " + dt.subtypes.slice(0, 3)
          .map(x => `${x.value.replace(/_/g, " ")} (${x.n})`).join(", "));
      if (dt.by_season && Object.keys(dt.by_season).length) {
        const best = Object.entries(dt.by_season)
          .sort((a, b) => (b[1].rate || 0) - (a[1].rate || 0))[0];
        bits.push(`strongest in ${best[0]} (${best[1].rate} fish/hr over ${best[1].n} trips)`);
      }
      if (bits.length) row.append(el("div", "dt", bits.join(" · ")));
      g.append(row);
    });
    wrap.append(g);
  });
  box.append(wrap);
  return box;
}

function whatToExpect(cons) {
  const box = el("div", "p-block");
  box.append(el("h3", null, "What to expect"));
  const card = el("div", "expect");
  card.append(el("p", "s", cons.sentence));
  const figs = el("div", "figs");
  figs.innerHTML =
    `volatility <b>${cons.cv}</b> (${cons.band})` +
    ` · best day in ten <b>${cons.best_decile}</b> fish/hr` +
    ` · worst <b>${cons.worst_decile}</b>` +
    ` · over <b>${cons.trips}</b> trips`;
  card.append(figs);
  card.append(el("p", "cav",
    "Spread is history, not a forecast: a lake's volatility in past years " +
    "predicts the next year's at only about r=0.20, against r=0.65 for its " +
    "catch rate. Bust rate also largely restates the average — good lakes " +
    "blank less — so volatility is the figure that adds something the rate " +
    "does not already carry."));
  box.append(card);
  return box;
}

const TECH_LABEL = {
  backed: ["Holds up across the archive", "is-backed"],
  suggestive: ["Leaning that way", ""],
  unproven: ["Not separated from the rest", ""],
  unstable: ["Significant on paper, inconsistent year to year", ""],
  below: ["Behind the alternatives", "is-below"],
};

function techniqueEvidence(tech) {
  const club = (D.technique_club || {}).effects || [];
  if (!club.length) return null;
  const sum = (D.technique_club || {}).summary || {};
  const local = {};
  (tech.lake || []).forEach(e => { local[e.technique] = e; });

  const box = el("div", "p-block");
  box.append(el("h3", null, "How you fish it"));
  if (sum.lead) box.append(el("p", "ev-lead", sum.lead + "."));
  box.append(el("p", "ev-note",
    "Presentation, measured across the whole archive and matched the same way " +
    "as baits. The years column counts how many separate years agree with the " +
    "pooled result — trips cluster within seasons, so a pooled interval runs " +
    "narrow, and anything marked inconsistent clears it and then flips sign in " +
    "half the years it appears in. Where this lake has enough of its own trips, " +
    "its figure sits beside the club's."));

  const scale = Math.max(1, ...club.map(e => Math.max(Math.abs(e.lo), Math.abs(e.hi))));
  const wrap = el("div", "ev");
  ["backed", "suggestive", "unproven", "unstable", "below"].forEach(key => {
    const group = club.filter(e => e.support === key);
    if (!group.length) return;
    const [label, cls] = TECH_LABEL[key];
    const g = el("div", "ev-group" + (cls ? " " + cls : ""));
    const head = el("div", "ev-head");
    head.append(el("div", "t", label), el("div", "c", group.length + " of " + club.length));
    g.append(head);
    group.forEach(e => {
      const row = el("div", "ev-row");
      row.append(el("div", "nm", e.label));
      const d = el("div", "d", `${e.diff >= 0 ? "+" : ""}${e.diff.toFixed(2)} fish/hr`);
      d.style.color = e.lo > 0 ? "var(--u4)" : e.hi < 0 ? "var(--d4)" : "var(--ink-2)";
      row.append(d);
      row.append(el("div", "n", `${e.trips} trips`));
      row.append(ciBar(e, scale));
      const here = local[e.technique];
      const bits = [];
      if (e.years) bits.push(`${e.years_agreeing} of ${e.years} years agree`);
      if (here) bits.push(`here: ${here.diff >= 0 ? "+" : ""}${here.diff.toFixed(2)} ` +
                          `over ${here.trips} trips`);
      if (bits.length) row.append(el("div", "dt", bits.join(" · ")));
      g.append(row);
    });
    wrap.append(g);
  });
  box.append(wrap);
  return box;
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

  const summ = p.summary || {};
  if (summ.paragraphs && summ.paragraphs.length) {
    const box = el("div", "summary");
    box.append(el("h3", null, "What members are saying"));
    summ.paragraphs.forEach(t => box.append(el("p", null, t)));
    if (summ.mentions && summ.mentions.length) {
      const m = el("div", "mentions");
      m.innerHTML = "Brought up here far more than at other club lakes: " +
        summ.mentions.map(x =>
          `<b>${x.phrase}</b> <span title="${x.reports} of ${x.of} reports">` +
          `(${x.reports})</span>`).join(", ") +
        ". Counted across reports, never quoted from one.";
      box.append(m);
    }
    if (summ.caveat) box.append(el("div", "caveat-line", summ.caveat));
    host.append(box);
  }

  const cons = p.consistency || {};
  if (cons.sentence) host.append(whatToExpect(cons));

  const baits = p.baits || {};
  if ((baits.evidence || []).length) host.append(baitEvidence(baits));

  const techBlock = techniqueEvidence(p.technique || {});
  if (techBlock) host.append(techBlock);

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
