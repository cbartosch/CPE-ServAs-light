#!/usr/bin/env python3
"""Generate the control tower as a standalone drill-down HTML page.

    PYTHONPATH=src python3 scripts/generate_control_tower_html.py
    PYTHONPATH=src python3 scripts/generate_control_tower_html.py --count 120 --seed 7

Why a single file
-----------------
It opens from a USB stick. No Docker, no Streamlit, no pip, no server. Given how
much of this project has been spent on a build that would not complete, a
deliverable that cannot fail to start is worth having.

**Zero external requests.** No CDN script, no webfont, no remote image. Charts are
inline SVG computed in `html_charts`, styles are inline, and the only http links
are citations a person may click. A test asserts there is no loadable external
resource, because a CDN tag is precisely what fails on a network that blocks
outbound traffic.

Drill levels
------------
    overview            KPI tiles and one card per panel
    #/panel/<key>       the panel in full, plus its data-contract requirements
    #/incident/<id>     plant chain, dispatch, and the effort ledger line by line
    #/contract          every field, its source system and its status

Navigation is hash-based, so browser back and forward work and any level can be
linked. Provenance travels with the data: every drill level shows the same
computed, assumed or synthetic chip as the overview, because a number that loses
its caveat on the way down is worse than one that never had it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.benchmarks import citation  # noqa: E402
from lpr_cpe_demo.dashboard import build  # noqa: E402
from lpr_cpe_demo.effort import assumptions, simulate_resolution  # noqa: E402
from lpr_cpe_demo.fault_generator import generate_faults  # noqa: E402
from lpr_cpe_demo.html_charts import (ACCENTS, donut, esc,  # noqa: E402
                                      grouped_bars, lines, stacked_bars, table)
from lpr_cpe_demo.plant import chain_for  # noqa: E402
from lpr_cpe_demo.telemetry import DATA_CONTRACT, contract_summary  # noqa: E402

OUT = ROOT / "docs" / "control_tower.html"

PROV_LABEL = {"computed": "computed from the model",
              "assumed": "stated assumption",
              "synthetic": "shape only, no data source"}

CSS = """
:root{--bg0:#020617;--bg1:#0F172A;--bg2:#1E1B4B;--card:rgba(255,255,255,.08);
--edge:rgba(255,255,255,.10);--ink:#F1F5F9;--muted:#94A3B8;--cyan:#22D3EE;
--amber:#FBBF24;--red:#FB7185;--green:#34D399;--violet:#A78BFA;--blue:#60A5FA}
*{box-sizing:border-box}
body{margin:0;padding:22px;color:var(--ink);font:14px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif;background:linear-gradient(160deg,var(--bg0) 0%,
var(--bg1) 55%,var(--bg2) 100%);background-attachment:fixed;min-height:100vh}
.wrap{max-width:1320px;margin:0 auto}
h1{font-size:1.45rem;margin:0}h2{font-size:1.05rem;margin:0 0 2px}
h3{font-size:.95rem;margin:0 0 2px}
p{margin:.35rem 0 0}
a{color:var(--cyan)}
.card{background:var(--card);border:1px solid var(--edge);border-radius:14px;
padding:14px 17px;margin-bottom:12px;backdrop-filter:blur(6px)}
.note{color:var(--muted);font-size:.8rem;line-height:1.45;margin-top:6px}
.prov{display:inline-block;font-size:.66rem;letter-spacing:.05em;
text-transform:uppercase;padding:2px 8px;border-radius:5px;border:1px solid
currentColor;margin-bottom:7px}
.prov.computed{color:var(--green)}.prov.assumed{color:var(--amber)}
.prov.synthetic{color:var(--red)}
.grid{display:grid;gap:12px}
.g5{grid-template-columns:repeat(auto-fit,minmax(184px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(430px,1fr))}
.kpi .v{font-size:1.7rem;font-weight:600;color:var(--cyan);line-height:1.1}
.kpi .l{font-size:.72rem;color:var(--muted);text-transform:uppercase;
letter-spacing:.05em}
.kpi .d{font-size:.75rem;color:var(--muted);margin-top:5px}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.badge{font-size:.72rem;padding:3px 10px;border-radius:999px;
border:1px solid var(--edge);background:rgba(255,255,255,.06)}
.badge.caveat{border-color:var(--amber);color:var(--amber)}
table{width:100%;border-collapse:collapse;margin-top:8px;font-size:.83rem}
th{text-align:left;color:var(--muted);font-weight:600;padding:6px 9px;
border-bottom:1px solid var(--edge);white-space:nowrap}
td{padding:6px 9px;border-bottom:1px solid rgba(255,255,255,.05);
vertical-align:middle}
tr.drill{cursor:pointer}
tr.drill:hover,tr.drill:focus{background:rgba(34,211,238,.10);outline:none}
tr.drill td:first-child{color:var(--cyan)}
.chart{display:block;margin-top:6px}
.crumb{font-size:.8rem;color:var(--muted);margin-bottom:12px}
.crumb a{text-decoration:none}
.back{display:inline-block;margin-bottom:12px;padding:5px 12px;border-radius:8px;
border:1px solid var(--edge);background:rgba(255,255,255,.06);color:var(--ink);
cursor:pointer;font-size:.8rem}
.back:hover{background:rgba(34,211,238,.14)}
.panelcard{cursor:pointer}
.panelcard:hover{border-color:var(--cyan)}
.more{color:var(--cyan);font-size:.78rem;margin-top:8px}
.tag{font-size:.7rem;padding:1px 7px;border-radius:4px;border:1px solid
currentColor}
.tag.in_flow{color:var(--green)}.tag.modelled{color:var(--amber)}
.tag.missing{color:var(--red)}
.foot{color:var(--muted);font-size:.75rem;margin-top:18px;line-height:1.5}
.hide{display:none}
"""

JS = """
const DATA = window.__CT__;
const app = document.getElementById('app');

function crumbs(parts){
  return '<div class="crumb">' + parts.map((p,i)=>
    i===parts.length-1 ? '<span>'+p.t+'</span>'
                       : '<a href="'+p.h+'">'+p.t+'</a> &rsaquo; ').join('') + '</div>';
}
function prov(p){ return '<span class="prov '+p+'">'+DATA.provLabel[p]+'</span>'; }

function overview(){
  let h = crumbs([{t:'Overview'}]);
  h += DATA.hero;
  h += '<div class="grid g5">' + DATA.kpiTiles + '</div>';
  h += '<div class="grid g2">';
  for(const p of DATA.panels){
    h += '<div class="card panelcard" data-panel="'+p.key+'" tabindex="0" role="link">'
       + prov(p.provenance) + '<h2>'+p.title+'</h2>'
       + (p.preview||'') + '<p class="note">'+p.note+'</p>'
       + '<div class="more">Drill in &rarr;</div></div>';
  }
  h += '</div>';
  h += '<div class="card panelcard" data-panel="__contract__" tabindex="0" role="link">'
     + prov('computed') + '<h2>Data contract</h2><p class="note">'+DATA.contractNote+'</p>'
     + '<div class="more">See every field and its source system &rarr;</div></div>';
  h += DATA.foot;
  app.innerHTML = h;
}

function panel(key){
  if(key==='__contract__'){ return contract(); }
  const p = DATA.panels.find(x=>x.key===key);
  if(!p){ return overview(); }
  let h = crumbs([{t:'Overview',h:'#/'},{t:p.title}]);
  h += '<button class="back" onclick="location.hash=\\'#/\\'">&larr; Overview</button>';
  h += '<div class="card">'+prov(p.provenance)+'<h2>'+p.title+'</h2>'
     + (p.chart||'') + (p.table||'') + '<p class="note">'+p.note+'</p></div>';
  if(p.requirements){
    h += '<div class="card"><h3>What this panel needs</h3>'+p.requirements+'</div>';
  }
  app.innerHTML = h;
}

function incident(id){
  const inc = DATA.incidents[id];
  if(!inc){ return overview(); }
  let h = crumbs([{t:'Overview',h:'#/'},
                  {t:'Hotspots',h:'#/panel/hotspots'},{t:id}]);
  h += '<button class="back" onclick="location.hash=\\'#/panel/hotspots\\'">'
     + '&larr; Hotspots</button>';
  h += inc.body;
  app.innerHTML = h;
}

function contract(){
  let h = crumbs([{t:'Overview',h:'#/'},{t:'Data contract'}]);
  h += '<button class="back" onclick="location.hash=\\'#/\\'">&larr; Overview</button>';
  h += DATA.contract;
  app.innerHTML = h;
}

function route(){
  const hash = location.hash || '#/';
  const m = hash.match(/^#\\/(panel|incident)\\/(.+)$/);
  if(!m){ overview(); }
  else if(m[1]==='panel'){ panel(decodeURIComponent(m[2])); }
  else { incident(decodeURIComponent(m[2])); }
  window.scrollTo(0,0);
}

document.addEventListener('click', e=>{
  const row = e.target.closest('[data-incident]');
  if(row){ location.hash = '#/incident/'+encodeURIComponent(row.dataset.incident); return; }
  const card = e.target.closest('[data-panel]');
  if(card){ location.hash = '#/panel/'+encodeURIComponent(card.dataset.panel); }
});
document.addEventListener('keydown', e=>{
  if(e.key!=='Enter') return;
  const t = e.target;
  if(t.dataset && t.dataset.incident){ location.hash='#/incident/'+encodeURIComponent(t.dataset.incident); }
  else if(t.dataset && t.dataset.panel){ location.hash='#/panel/'+encodeURIComponent(t.dataset.panel); }
});
window.addEventListener('hashchange', route);
route();
"""


def _kpi_tiles(kpis) -> str:
    return "".join(
        f'<div class="card kpi"><div class="l">{esc(k["label"])}</div>'
        f'<div class="v">{esc(k["value"])}</div>'
        f'<div class="d">{esc(k["description"])}</div></div>'
        for k in kpis)


def _hero(dash) -> str:
    chips = "".join(
        f'<span class="badge{" caveat" if b.get("type") == "caveat" else ""}">'
        f'{esc(b["label"])}</span>' for b in dash.badges)
    return (f'<div class="card"><h1>{esc(dash.title)}</h1>'
            f'<p class="note">{esc(dash.subtitle)}</p>'
            f'<div class="badges">{chips}</div></div>')


def _requirements_table(panel_key: str) -> str:
    panel = next((p for p in DATA_CONTRACT if p.panel == panel_key), None)
    if panel is None:
        return ""
    rows = [(r.field, r.source_system, r.grain,
             f'<span class="tag {r.availability}">{r.availability.replace("_", " ")}</span>',
             r.note or "-") for r in panel.requirements]
    return (f'<p class="note">Refresh {esc(panel.refresh)} &middot; '
            f'{esc(panel.status)}</p>'
            + table(["field", "source system", "grain", "status", "note"], rows))


def _incident_body(fault) -> str:
    ledger = simulate_resolution(incident_id=fault.fault_id, site_id=fault.site_id,
                                 technology=fault.technology,
                                 true_domain=fault.true_domain)
    chain = chain_for(fault.site_id, fault.technology)
    chain_rows = [(e.kind, e.element_id, e.serves_households, e.crew_type,
                   "delimiter, MR raised here" if e.is_delimiter else "")
                  for e in chain]
    ledger_rows = [(r["step"], r["role"], r["minutes"], f'{r["cost_usd"]:,.2f}',
                    r["note"] or "-") for r in ledger.as_rows()]
    facts = [
        ("Municipio", fault.municipio), ("Archetype", fault.archetype),
        ("Technology", fault.technology), ("True domain", fault.true_domain),
        ("Reported by", fault.household_id),
        ("Worked at", f"{fault.intervention_id} ({fault.intervention_kind})"),
        ("Households affected", fault.households_affected),
        ("Crew", f"{fault.crew_type} boots from {fault.base_name}"),
        ("Travel each way", f"{fault.travel_minutes} min"),
        ("Ferry required", "yes" if fault.requires_ferry else "no"),
        ("Fits one shift", "yes" if fault.same_day_feasible else "no"),
        ("Benchmark per dispatch", f"{fault.benchmark_per_dispatch_usd:,.2f} USD"),
        ("Inside benchmark scope", "yes" if fault.benchmark_in_scope else
         "no, ferry and overnight are outside the published range"),
    ]
    return (
        f'<div class="card"><span class="prov computed">computed from the model</span>'
        f'<h2>{esc(fault.fault_id)} &middot; {esc(fault.municipio)}</h2>'
        f'<p class="note">The intervention point is where the crew works, which for '
        f'a tap or ODP fault is not the address that reported it.</p>'
        + table(["fact", "value"], facts) + '</div>'
        f'<div class="grid g2">'
        f'<div class="card"><h3>Plant chain</h3>'
        + table(["element", "identifier", "households", "crew", ""], chain_rows)
        + '</div>'
        f'<div class="card"><h3>Cost</h3>'
        f'<div class="kpi"><div class="l">Resolved</div>'
        f'<div class="v">{ledger.total_cost:,.0f} USD</div>'
        f'<div class="d">{ledger.total_minutes} min, '
        f'{ledger.truck_rolls} truck roll(s)</div></div>'
        f'<div class="kpi" style="margin-top:10px"><div class="l">If misdispatched'
        f'</div><div class="v" style="color:var(--red)">'
        f'{fault.misdispatch_cost_usd:,.0f} USD</div>'
        f'<div class="d">a wasted visit by the wrong crew plus a handover, before '
        f'the correct visit still happens</div></div></div></div>'
        f'<div class="card"><h3>Effort ledger</h3>'
        + table(["step", "role", "minutes", "cost USD", "note"], ledger_rows)
        + f'<p class="note">Every rate and duration is assumed. '
          f'{esc(assumptions()["basis"])}</p></div>')


def build_html(count: int, seed: int) -> str:
    dash = build(count=count, seed=seed)
    faults = generate_faults(count, seed=seed)
    by_id = {f.fault_id: f for f in faults}

    panels = []
    for block in dash.blocks:
        if block.key == "data_contract":
            continue
        entry = {"key": block.key, "title": block.title,
                 "provenance": block.provenance, "note": esc(block.note),
                 "preview": "", "chart": "", "table": "",
                 "requirements": _requirements_table(block.key)}

        if block.key == "incident_root_cause_mix":
            chart = donut(block.data, label="Incident root-cause mix")
            entry["preview"] = chart
            entry["chart"] = chart
            entry["table"] = table(["bucket", "share %"],
                                   [(d["name"], f'{d["value"]:.1f}') for d in block.data])
        elif block.key == "automation_funnel":
            chart = stacked_bars(block.data, label="Autonomy by stage")
            entry["preview"] = chart
            entry["chart"] = chart
            entry["table"] = table(["stage", "autonomous %", "human %", "source"],
                                   [(d["stage"],
                                     "n/a" if d["autonomous_pct"] is None else d["autonomous_pct"],
                                     "n/a" if d["human_pct"] is None else d["human_pct"],
                                     d.get("source", "")) for d in block.data])
        elif block.key == "cost_by_archetype":
            cats = [d["archetype"] for d in block.data]
            chart = grouped_bars(cats, [
                {"name": "mean cost to resolve", "color": ACCENTS["blue"],
                 "values": [d["mean_cost"] for d in block.data]},
                {"name": "benchmark wasted visit", "color": ACCENTS["red"],
                 "values": [d.get("mean_wasted_visit") for d in block.data]}],
                unit=" (USD)", label="Cost per incident by archetype")
            entry["preview"] = chart
            entry["chart"] = chart
            entry["table"] = table(
                ["archetype", "incidents", "dispatched", "mean cost", "wasted visit"],
                [(d["archetype"], d["incidents"], d["dispatched"],
                  f'{d["mean_cost"]:,.0f}',
                  "n/a" if d.get("mean_wasted_visit") is None
                  else f'{d["mean_wasted_visit"]:,.0f}') for d in block.data])
        elif block.key == "service_health_by_layer":
            chart = lines([d["time"] for d in block.data],
                          [{"name": n, "color": ACCENTS[c],
                            "values": [d[n] for d in block.data]}
                           for n, c in (("HFC", "cyan"), ("PON", "blue"),
                                        ("Core", "green"), ("WiFi", "amber"))],
                          y_min=85, y_max=100, label="Service health by layer")
            entry["preview"] = chart
            entry["chart"] = chart
        elif block.key == "hotspots":
            rows = [(h["id"], h["area"], h["technology"], h["severity"],
                     h["subscribers_impacted"], h["root_cause"],
                     h["eta_to_restore"], f'{h["cost_usd"]:,.0f}')
                    for h in block.data]
            ids = [h["id"] for h in block.data]
            # map the intervention id back to its fault so the row can drill
            id_to_fault = {f.intervention_id: f.fault_id for f in faults}
            entry["table"] = table(
                ["intervention", "municipio", "tech", "severity", "hh",
                 "root cause", "eta", "cost USD"], rows,
                drill_attr="incident",
                drill_values=[id_to_fault.get(i, "") for i in ids])
            entry["preview"] = (
                '<p class="note">' +
                "<br>".join(f'{esc(h["id"])} &middot; {esc(h["area"])} &middot; '
                            f'{h["subscribers_impacted"]} hh'
                            for h in block.data[:3]) + "</p>")
        elif block.key == "closed_loop_confidence":
            guards = block.data["guardrails"]
            entry["table"] = table(["guardrail", "score %", "rests on"],
                                   [(g["name"], g["score_pct"], g["basis"])
                                    for g in guards])
            entry["preview"] = (f'<div class="kpi"><div class="l">Overall</div>'
                                f'<div class="v">'
                                f'{block.data["overall_confidence_pct"]}%</div></div>')
        elif block.key == "playbook_backlog":
            entry["table"] = table(["playbook", "success %", "risk", "action"],
                                   [(p["name"], p["success_pct"], p["risk"],
                                     p["action"]) for p in block.data])
        elif block.key == "agent_status":
            entry["table"] = table(["metric", "value"],
                                   [(d["metric"], d["value"]) for d in block.data])
            headline = next((d["value"] for d in block.data
                             if d["metric"] == "provider"), "")
            entry["preview"] = (f'<div class="kpi"><div class="l">provider</div>'
                                f'<div class="v">{esc(headline)}</div></div>')
        elif block.key == "kpis":
            continue
        panels.append(entry)

    contract_rows = []
    for panel in DATA_CONTRACT:
        for req in panel.requirements:
            contract_rows.append((
                panel.panel, req.field, req.source_system, req.grain,
                f'<span class="tag {req.availability}">'
                f'{req.availability.replace("_", " ")}</span>', req.note or "-"))
    summary = contract_summary()
    contract_html = (
        f'<div class="card"><span class="prov computed">computed from the model</span>'
        f'<h2>Data contract</h2><p class="note">'
        f'{summary["fields"]} fields across {summary["panels"]} panels: '
        f'{summary["by_availability"].get("in_flow", 0)} available from the workflow '
        f'today, {summary["by_availability"].get("modelled", 0)} on modelled inputs, '
        f'{summary["by_availability"].get("missing", 0)} needing a source system that '
        f'is not wired. A panel marked blocked is not a caveat: the named system is '
        f'the work item that closes it.</p>'
        + table(["panel", "field", "source system", "grain", "status", "note"],
                contract_rows) + '</div>')

    incidents = {fid: {"body": _incident_body(f)} for fid, f in by_id.items()}
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    foot = (f'<div class="foot">Generated {generated} from seed {seed} with '
            f'{count} synthetic incidents, so this file reproduces exactly. '
            f'Every rate, duration, plant ratio and hub location is assumed; see '
            f'the data contract. Truck-roll cost is externally sourced: '
            f'{esc(citation())} '
            f'No external requests: charts are inline SVG and there is no script '
            f'or font loaded from a network.</div>')

    payload = {
        "hero": _hero(dash),
        "kpiTiles": _kpi_tiles(dash.block("kpis").data),
        "panels": panels,
        "contract": contract_html,
        "contractNote": esc(
            f'{summary["by_availability"].get("in_flow", 0)} of '
            f'{summary["fields"]} fields are available from the workflow today. '
            f'{len(summary["missing_source_systems"])} source systems would close '
            f'the rest.'),
        "provLabel": PROV_LABEL,
        "foot": foot,
        "incidents": incidents,
    }

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(dash.title)}</title>"
        f"<style>{CSS}</style></head><body><div class=\"wrap\">"
        '<div id="app"></div></div>'
        f'<script id="ct-data" type="application/json">'
        f'{json.dumps(payload)}</script>'
        f"<script>window.__CT__=JSON.parse("
        f"document.getElementById('ct-data').textContent);{JS}</script>"
        "</body></html>\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260817)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(args.count, args.seed), encoding="utf-8")
    size = len(out.read_bytes())
    print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} "
          f"({size:,} bytes, {args.count} incidents, seed {args.seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
