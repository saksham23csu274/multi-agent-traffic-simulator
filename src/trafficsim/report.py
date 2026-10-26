"""Self-contained HTML reports: a single-run replay dashboard and a strategy comparison page."""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .orchestrator import RunResult

_EVENT_TYPES_FOR_REPORT = {
    "run_started", "run_finished", "run_failed", "run_timeout", "incident_start", "incident_end",
    "emergency_dispatched", "emergency_rerouted", "emergency_arrived", "emergency_unroutable",
    "priority_requested", "priority_approved", "priority_denied", "priority_cleared", "priority_expired",
    "agent_fault", "agent_replaced_by_fallback", "forced_phase_change", "congestion_start", "congestion_end",
}

_STYLE = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --seq-0: #86b6ef; --seq-1: #5598e7; --seq-2: #2a78d6; --seq-3: #1c5cab; --seq-4: #104281; --seq-5: #0d366b;
  --edge-empty: #e1e0d9; --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  --critical: #d03b3b; --good: #0ca30c; --line: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --seq-0: #184f95; --seq-1: #1c5cab; --seq-2: #256abf; --seq-3: #3987e5; --seq-4: #6da7ec; --seq-5: #b7d3f6;
    --edge-empty: #383835; --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --line: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --seq-0: #184f95; --seq-1: #1c5cab; --seq-2: #256abf; --seq-3: #3987e5; --seq-4: #6da7ec; --seq-5: #b7d3f6;
  --edge-empty: #383835; --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --line: #3987e5;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 32px 0 12px; }
.sub { color: var(--ink-2); margin: 0; } .muted { color: var(--muted); }
.note { color: var(--ink-2); font-size: 13px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-top: 20px; }
.tile .label { color: var(--ink-2); font-size: 12px; } .tile .value { font-size: 24px; font-weight: 600; }
.tile .unit { color: var(--muted); font-size: 13px; font-weight: 400; }
.replay { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 16px; }
@media (max-width: 820px) { .replay { grid-template-columns: 1fr; } }
svg { display: block; width: 100%; height: auto; }
.controls { display: flex; gap: 10px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.controls input[type=range] { flex: 1; min-width: 140px; }
button, select { font: inherit; color: var(--ink); background: var(--surface); border: 1px solid var(--axis);
  border-radius: 6px; padding: 4px 10px; cursor: pointer; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--ink-2); margin-top: 10px; align-items: center; }
.swatch { display: inline-block; width: 18px; height: 4px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }
.ramp { display: inline-flex; vertical-align: middle; margin: 0 4px; }
.ramp span { width: 14px; height: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; }
.scroll { max-height: 340px; overflow: auto; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
.chart-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.tooltip { position: fixed; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15); display: none; z-index: 10; white-space: nowrap; }
.pill { display: inline-block; padding: 0 6px; border-radius: 999px; border: 1px solid var(--axis); font-size: 11px; }
.ok { color: var(--good); } .bad { color: var(--critical); }
code { font-size: 12px; }
"""

_RUN_SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const tip = document.getElementById('tip');
const fmt = (v, d = 1) => v === null || v === undefined ? '—' : (typeof v === 'number' ? v.toLocaleString(undefined, {maximumFractionDigits: d}) : v);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function showTip(e, html) { tip.innerHTML = html; tip.style.display = 'block';
  const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }
function hideTip() { tip.style.display = 'none'; }

// ---------------------------------------------------------------- map replay
const NS = 'http://www.w3.org/2000/svg';
const nodes = Object.fromEntries(D.network.nodes.map(n => [n.id, n]));
const edges = D.edges.map(id => D.network.edges.find(e => e.id === id));
const xs = D.network.nodes.map(n => n.x), ys = D.network.nodes.map(n => n.y);
const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
const W = 600, PAD = 36;
const scale = (W - 2 * PAD) / Math.max(maxX - minX, maxY - minY, 1);
const H = Math.max(240, (maxY - minY) * scale + 2 * PAD);
const px = x => PAD + (x - minX) * scale, py = y => H - PAD - (y - minY) * scale;
const map = document.getElementById('map');
map.setAttribute('viewBox', `0 0 ${W} ${H}`);
const OFF = 4;
const edgeGeom = edges.map(e => {
  const a = nodes[e.from], b = nodes[e.to];
  let x1 = px(a.x), y1 = py(a.y), x2 = px(b.x), y2 = py(b.y);
  const len = Math.hypot(x2 - x1, y2 - y1) || 1, ux = (x2 - x1) / len, uy = (y2 - y1) / len;
  const ox = -uy * OFF, oy = ux * OFF, trim = 9;
  x1 += ox + ux * trim; y1 += oy + uy * trim; x2 += ox - ux * trim; y2 += oy - uy * trim;
  return {x1, y1, x2, y2};
});
const edgeEls = edgeGeom.map((g, i) => {
  const l = document.createElementNS(NS, 'line');
  l.setAttribute('x1', g.x1); l.setAttribute('y1', g.y1); l.setAttribute('x2', g.x2); l.setAttribute('y2', g.y2);
  l.setAttribute('stroke-width', 4); l.setAttribute('stroke-linecap', 'round');
  map.appendChild(l);
  const hit = document.createElementNS(NS, 'line');
  hit.setAttribute('x1', g.x1); hit.setAttribute('y1', g.y1); hit.setAttribute('x2', g.x2); hit.setAttribute('y2', g.y2);
  hit.setAttribute('stroke', 'transparent'); hit.setAttribute('stroke-width', 10);
  hit.addEventListener('mousemove', e => { const f = D.frames[cur];
    showTip(e, `<b>${esc(edges[i].id)}</b><br>occupancy ${Math.round(f.occ[i] * 100)}%<br>queue ${f.q[i]} veh${f.closed.includes(i) ? '<br><b>closed</b>' : ''}`); });
  hit.addEventListener('mouseleave', hideTip);
  map.appendChild(hit);
  return l;
});
const sigEls = {};
for (const n of D.network.nodes) {
  const g = document.createElementNS(NS, 'g');
  const c = document.createElementNS(NS, 'circle');
  c.setAttribute('cx', px(n.x)); c.setAttribute('cy', py(n.y)); c.setAttribute('r', n.signalized ? 8 : 4);
  c.setAttribute('fill', 'var(--surface)'); c.setAttribute('stroke', 'var(--axis)'); c.setAttribute('stroke-width', 1.5);
  g.appendChild(c);
  if (n.signalized) {
    const bar = document.createElementNS(NS, 'line');
    bar.setAttribute('stroke-width', 3); bar.setAttribute('stroke-linecap', 'round'); bar.setAttribute('stroke', 'var(--good)');
    g.appendChild(bar);
    sigEls[n.id] = {bar, c, x: px(n.x), y: py(n.y)};
    g.addEventListener('mousemove', e => { const s = D.frames[cur].sig[n.id];
      showTip(e, `<b>${esc(n.id)}</b><br>phase ${s ? esc(s[0]) : '—'} · ${s ? {g:'green',y:'yellow',r:'all-red'}[s[1]] : ''}`); });
    g.addEventListener('mouseleave', hideTip);
    g.addEventListener('click', () => { document.getElementById('inspect-node').value = n.id; renderInspector(); });
    g.style.cursor = 'pointer';
  }
  map.appendChild(g);
}
const evLayer = document.createElementNS(NS, 'g'); map.appendChild(evLayer);
const seqVars = ['--seq-0','--seq-1','--seq-2','--seq-3','--seq-4','--seq-5'];
function occColor(r) { if (r <= 0.001) return 'var(--edge-empty)'; return `var(${seqVars[Math.min(5, Math.floor(r * 6))]})`; }

let cur = 0, timer = null;
const slider = document.getElementById('slider'), tlabel = document.getElementById('tlabel');
slider.max = Math.max(0, D.frames.length - 1);
function render() {
  const f = D.frames[cur]; if (!f) return;
  tlabel.textContent = `t = ${fmt(f.t, 0)} s`;
  edgeEls.forEach((l, i) => {
    const closed = f.closed.includes(i);
    l.setAttribute('stroke', closed ? 'var(--critical)' : occColor(f.occ[i]));
    l.setAttribute('stroke-dasharray', closed ? '4 4' : '');
  });
  for (const [id, el] of Object.entries(sigEls)) {
    const s = f.sig[id];
    if (!s || s[1] !== 'g') { el.bar.setAttribute('stroke', 'transparent'); el.c.setAttribute('stroke-dasharray', '2 2'); continue; }
    el.c.setAttribute('stroke-dasharray', '');
    el.bar.setAttribute('stroke', 'var(--good)');
    const vertical = s[0] === 'NS';
    el.bar.setAttribute('x1', el.x - (vertical ? 0 : 6)); el.bar.setAttribute('x2', el.x + (vertical ? 0 : 6));
    el.bar.setAttribute('y1', el.y - (vertical ? 6 : 0)); el.bar.setAttribute('y2', el.y + (vertical ? 6 : 0));
  }
  evLayer.innerHTML = '';
  for (const [id, ei, p] of f.ev) {
    const g = edgeGeom[ei], x = g.x1 + (g.x2 - g.x1) * p, y = g.y1 + (g.y2 - g.y1) * p;
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 6);
    c.setAttribute('fill', 'var(--s2)'); c.setAttribute('stroke', 'var(--surface)'); c.setAttribute('stroke-width', 2);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', x + 9); t.setAttribute('y', y - 7); t.setAttribute('font-size', 11);
    t.setAttribute('fill', 'var(--ink)'); t.textContent = id;
    evLayer.appendChild(c); evLayer.appendChild(t);
  }
  renderNearbyEvents(f.t);
  renderInspector();
  moveCursors(f.t);
}
slider.addEventListener('input', () => { cur = +slider.value; render(); });
document.getElementById('play').addEventListener('click', e => {
  if (timer) { clearInterval(timer); timer = null; e.target.textContent = 'Play'; return; }
  e.target.textContent = 'Pause';
  timer = setInterval(() => { if (cur >= D.frames.length - 1) { clearInterval(timer); timer = null; e.target.textContent = 'Play'; return; }
    cur++; slider.value = cur; render(); }, 120);
});

// ---------------------------------------------------------------- inspector + events
const nodeSel = document.getElementById('inspect-node');
for (const n of D.network.nodes.filter(n => n.signalized)) { const o = document.createElement('option'); o.value = o.textContent = n.id; nodeSel.appendChild(o); }
nodeSel.addEventListener('change', renderInspector);
function renderInspector() {
  const body = document.getElementById('inspect-body');
  if (!D.decisions.length) { body.innerHTML = '<tr><td class="muted">Decision logging was disabled for this run.</td></tr>'; return; }
  const t = D.frames[cur] ? D.frames[cur].t : 0, node = nodeSel.value;
  const rows = D.decisions.filter(d => d.intersection_id === node && Math.abs(d.time_s - t) <= 30);
  body.innerHTML = rows.map(d => `<tr><td>${fmt(d.time_s,0)}</td><td>${esc(d.phase)} · ${fmt(d.phase_elapsed_s,0)}s</td>
    <td>${Object.entries(d.queues).map(([k,v]) => k + ':' + v).join(' ')}</td>
    <td>${esc(d.action)}${d.target_phase && d.action === 'request_phase' ? ' → ' + esc(d.target_phase) : ''}<br><span class="muted">${esc(d.reason_code)}</span></td>
    <td class="${d.accepted ? 'ok' : 'bad'}">${d.accepted ? '✓' : '✗'} ${esc(d.verdict)}${d.priority ? ' <span class="pill">priority</span>' : ''}${d.fallback ? ' <span class="pill">fallback</span>' : ''}${d.forced_change ? ' <span class="pill">forced</span>' : ''}</td></tr>`).join('')
    || '<tr><td colspan="5" class="muted">No decisions within ±30 s (signal in transition).</td></tr>';
}
const keyEvents = D.events.filter(e => !e.type.startsWith('congestion'));
function describe(e) {
  const skip = new Set(['time_s','type','source']);
  return Object.entries(e).filter(([k]) => !skip.has(k)).map(([k,v]) => `${k}=${Array.isArray(v) ? v.length + ' items' : v}`).join(', ');
}
function renderNearbyEvents(t) {
  const rows = keyEvents.filter(e => e.time_s <= t).slice(-8).reverse();
  document.getElementById('recent').innerHTML = rows.map(e => `<tr><td>${fmt(e.time_s,0)}</td><td>${esc(e.type)}</td><td class="muted">${esc(describe(e))}</td></tr>`).join('')
    || '<tr><td class="muted">No events yet.</td></tr>';
}
const typeSel = document.getElementById('event-type');
for (const t of [...new Set(D.events.map(e => e.type))].sort()) { const o = document.createElement('option'); o.value = o.textContent = t; typeSel.appendChild(o); }
function renderEvents() {
  const v = typeSel.value;
  const rows = D.events.filter(e => !v || e.type === v);
  document.getElementById('events').innerHTML = rows.slice(0, 1500).map(e => `<tr><td>${fmt(e.time_s,0)}</td><td>${esc(e.type)}</td><td>${esc(e.source)}</td><td class="muted">${esc(describe(e))}</td></tr>`).join('');
}
typeSel.addEventListener('change', renderEvents);

// ---------------------------------------------------------------- time-series charts
const cursors = [];
function lineChart(el, key, unit) {
  const data = D.timeseries; if (!data.length) return;
  const w = 480, h = 180, l = 44, r = 12, t = 10, b = 26;
  const xMax = data[data.length - 1].time_s || 1, yMax = Math.max(1, ...data.map(d => d[key]));
  const X = v => l + v / xMax * (w - l - r), Y = v => h - b - v / yMax * (h - t - b);
  const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  let s = '';
  for (let i = 0; i <= 4; i++) { const v = yMax * i / 4, y = Y(v);
    s += `<line x1="${l}" x2="${w - r}" y1="${y}" y2="${y}" stroke="var(--grid)" stroke-width="1"/>`;
    s += `<text x="${l - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="var(--muted)">${fmt(v, 0)}</text>`; }
  for (let i = 0; i <= 4; i++) { const v = xMax * i / 4;
    s += `<text x="${X(v)}" y="${h - 8}" text-anchor="middle" font-size="10" fill="var(--muted)">${fmt(v, 0)}s</text>`; }
  for (const e of D.events.filter(e => e.type === 'incident_start' || e.type === 'emergency_dispatched')) {
    s += `<line x1="${X(e.time_s)}" x2="${X(e.time_s)}" y1="${t}" y2="${h - b}" stroke="var(--axis)" stroke-dasharray="3 3"/>`;
  }
  s += `<polyline fill="none" stroke="var(--line)" stroke-width="2" stroke-linejoin="round" points="${data.map(d => X(d.time_s) + ',' + Y(d[key])).join(' ')}"/>`;
  s += `<line class="cursor" y1="${t}" y2="${h - b}" stroke="var(--ink-2)" stroke-width="1" opacity="0.6"/>`;
  s += `<line class="hover" y1="${t}" y2="${h - b}" stroke="var(--ink)" stroke-width="1" visibility="hidden"/><circle class="dot" r="4" fill="var(--line)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`;
  s += `<rect x="${l}" y="${t}" width="${w - l - r}" height="${h - t - b}" fill="transparent"/>`;
  svg.innerHTML = s; el.appendChild(svg);
  const hover = svg.querySelector('.hover'), dot = svg.querySelector('.dot'), rect = svg.querySelector('rect');
  rect.addEventListener('mousemove', e => {
    const box = svg.getBoundingClientRect(), vx = (e.clientX - box.left) / box.width * w;
    const tv = (vx - l) / (w - l - r) * xMax;
    let best = data[0]; for (const d of data) if (Math.abs(d.time_s - tv) < Math.abs(best.time_s - tv)) best = d;
    hover.setAttribute('x1', X(best.time_s)); hover.setAttribute('x2', X(best.time_s)); hover.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', X(best.time_s)); dot.setAttribute('cy', Y(best[key])); dot.setAttribute('visibility', 'visible');
    showTip(e, `t = ${fmt(best.time_s, 0)} s<br><b>${fmt(best[key])}</b> ${unit}`);
  });
  rect.addEventListener('mouseleave', () => { hover.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); hideTip(); });
  rect.addEventListener('click', e => { const box = svg.getBoundingClientRect(), vx = (e.clientX - box.left) / box.width * w;
    const tv = (vx - l) / (w - l - r) * xMax; let bi = 0; D.frames.forEach((f, i) => { if (Math.abs(f.t - tv) < Math.abs(D.frames[bi].t - tv)) bi = i; });
    cur = bi; slider.value = cur; render(); });
  cursors.push({line: svg.querySelector('.cursor'), X});
}
function moveCursors(t) { for (const c of cursors) { c.line.setAttribute('x1', c.X(t)); c.line.setAttribute('x2', c.X(t)); } }
lineChart(document.getElementById('c-queue'), 'queued_vehicles', 'queued vehicles');
lineChart(document.getElementById('c-net'), 'vehicles_in_network', 'vehicles in network');
lineChart(document.getElementById('c-thr'), 'throughput_vph', 'veh/h');
lineChart(document.getElementById('c-cong'), 'congested_edges', 'congested edges');
renderEvents();
render();
"""


def _esc(value: Any) -> str:
    return html.escape("—" if value is None else str(value))


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _json_for_script(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")


def _tile(label: str, value: Any, unit: str = "") -> str:
    unit_html = f' <span class="unit">{_esc(unit)}</span>' if unit and value is not None else ""
    return f'<div class="card tile"><div class="label">{_esc(label)}</div><div class="value">{_esc(_fmt(value))}{unit_html}</div></div>'


def _kv_table(rows: list[tuple[str, Any]]) -> str:
    body = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(_fmt(v, 3))}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def render_run_report(result: RunResult) -> str:
    s = result.summary
    tr, em, sysm = s["traffic"], s["emergency"], s["system"]
    edges_sorted = sorted(e["id"] for e in result.network["edges"])
    data = {
        "network": result.network,
        "edges": edges_sorted,
        "frames": result.metrics.frames,
        "timeseries": result.metrics.timeseries,
        "events": [e for e in result.events if e["type"] in _EVENT_TYPES_FOR_REPORT],
        "decisions": result.decisions,
    }
    tiles = "".join([
        _tile("Trips completed", tr["trips_completed"]),
        _tile("Mean travel time", tr["mean_travel_time_s"], "s"),
        _tile("Mean waiting time", tr["mean_waiting_time_s"], "s"),
        _tile("Throughput", tr["throughput_vph"], "veh/h"),
        _tile("Emergency response (mean)", em["mean_response_time_s"], "s"),
        _tile("Priority approved / requested", f'{em["priority_approved"]} / {em["priority_requests"]}'),
    ])
    ev_rows = "".join(
        f"<tr><td>{_esc(v['id'])}</td><td>{_esc(v['status'])}</td><td>{_esc(v['origin'])} → {_esc(v['destination'])}</td>"
        f"<td>{_esc(_fmt(v['dispatch_s']))}</td><td>{_esc(_fmt(v['arrival_s']))}</td><td>{_esc(_fmt(v['response_time_s']))}</td>"
        f"<td>{_esc(_fmt(v['stopped_time_s']))}</td><td>{_esc(v['route_changes'])}</td>"
        f"<td>{_esc(_fmt(v['route_length_m'], 0))}</td></tr>"
        for v in em["vehicles"]
    ) or '<tr><td colspan="9" class="muted">No emergency requests in this scenario.</td></tr>'
    inc_rows = "".join(
        f"<tr><td>{_esc(i['incident_id'])}</td><td>{_esc(i['kind'])}</td><td>{_esc(_fmt(i['baseline_queued_vehicles']))}</td>"
        f"<td>{_esc(_fmt(i['peak_queued_vehicles']))}</td><td>{_esc(_fmt(i['recovery_time_s']))}</td></tr>"
        for i in s["incidents"]
    ) or '<tr><td colspan="5" class="muted">No incidents in this scenario.</td></tr>'
    traffic_rows = [(k.replace("_", " "), v) for k, v in tr.items()]
    system_rows = [(k.replace("_", " "), v) for k, v in sysm.items() if k != "rejections_by_reason"]
    system_rows += [(f"rejected: {k}", v) for k, v in sysm["rejections_by_reason"].items()]
    m = result.manifest

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Traffic Run Report</title><style>{_STYLE}</style></head>
<body><main>
<h1>{_esc(m['scenario']['id'])} · {_esc(s['label'])}</h1>
<p class="sub">Run <code>{_esc(result.run_id)}</code> · status <b>{_esc(result.status)}</b> · seed {_esc(m['random_seed'])} ·
engine {_esc(m['engine'])} · v{_esc(m['software_version'])}</p>
<p class="note">Simulation output only — not a validation of real-world traffic or emergency performance.</p>
<div class="tiles">{tiles}</div>

<h2>Network replay</h2>
<div class="replay">
  <div class="card">
    <svg id="map" role="img" aria-label="Road network replay"></svg>
    <div class="controls"><button id="play">Play</button><input id="slider" type="range" min="0" value="0" aria-label="Simulation time"><span id="tlabel"></span></div>
    <div class="legend">
      <span>Edge occupancy <span class="ramp"><span style="background:var(--seq-0)"></span><span style="background:var(--seq-2)"></span><span style="background:var(--seq-3)"></span><span style="background:var(--seq-5)"></span></span> low → full</span>
      <span><span class="swatch" style="background:var(--critical)"></span>closed edge (dashed)</span>
      <span><span class="swatch" style="background:var(--good)"></span>green axis at a signal (dashed ring = yellow/all-red)</span>
      <span><span class="swatch" style="background:var(--s2);height:8px;width:8px;border-radius:50%"></span>emergency vehicle</span>
    </div>
  </div>
  <div class="card">
    <div class="chart-title">Decision inspector <select id="inspect-node" aria-label="Intersection"></select></div>
    <p class="note" style="margin:0 0 6px">Decisions within ±30 s of the replay time. Click a signal on the map to select it.</p>
    <div class="scroll" style="max-height:220px"><table><thead><tr><th>t (s)</th><th>Phase</th><th>Queues</th><th>Action</th><th>Verdict</th></tr></thead><tbody id="inspect-body"></tbody></table></div>
    <div class="chart-title" style="margin-top:12px">Latest events</div>
    <div class="scroll" style="max-height:200px"><table><tbody id="recent"></tbody></table></div>
  </div>
</div>

<h2>Time series</h2>
<p class="note">Dashed verticals mark incident starts and emergency dispatches. Click a chart to jump the replay.</p>
<div class="charts">
  <div class="card"><div class="chart-title">Queued vehicles</div><div id="c-queue"></div></div>
  <div class="card"><div class="chart-title">Vehicles in network</div><div id="c-net"></div></div>
  <div class="card"><div class="chart-title">Throughput, trailing 60 s (veh/h)</div><div id="c-thr"></div></div>
  <div class="card"><div class="chart-title">Congested edges</div><div id="c-cong"></div></div>
</div>

<h2>Emergency vehicles</h2>
<div class="card scroll"><table><thead><tr><th>ID</th><th>Status</th><th>Route</th><th>Dispatch (s)</th><th>Arrival (s)</th>
<th>Response (s)</th><th>Stopped (s)</th><th>Route changes</th><th>Length (m)</th></tr></thead><tbody>{ev_rows}</tbody></table>
<p class="note">Priority requests: {em['priority_requests']} · approved {em['priority_approved']} · denied {em['priority_denied']} ·
cleared {em['priority_cleared']} · expired {em['priority_expired']}</p></div>

<h2>Incidents</h2>
<div class="card scroll"><table><thead><tr><th>ID</th><th>Kind</th><th>Baseline queued</th><th>Peak queued</th><th>Recovery (s)</th></tr></thead><tbody>{inc_rows}</tbody></table></div>

<h2>Metrics</h2>
<div class="charts"><div class="card"><div class="chart-title">Traffic</div>{_kv_table(traffic_rows)}</div>
<div class="card"><div class="chart-title">System</div>{_kv_table(system_rows)}</div></div>

<h2>Event timeline</h2>
<div class="card"><div class="controls" style="margin:0 0 8px"><label>Type <select id="event-type"><option value="">All</option></select></label></div>
<div class="scroll"><table><thead><tr><th>t (s)</th><th>Type</th><th>Source</th><th>Details</th></tr></thead><tbody id="events"></tbody></table></div></div>
</main>
<div class="tooltip" id="tip"></div>
<script type="application/json" id="data">{_json_for_script(data)}</script>
<script>{_RUN_SCRIPT}</script>
</body></html>
"""


_COMPARE_SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const tip = document.getElementById('tip');
const fmt = (v, d = 1) => v === null || v === undefined ? '—' : v.toLocaleString(undefined, {maximumFractionDigits: d});
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const colors = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)'];
const labelColor = Object.fromEntries(D.labels.map((l, i) => [l, colors[i % colors.length]]));
const legend = document.getElementById('legend');
legend.innerHTML = D.labels.map(l => `<span><span class="swatch" style="background:${labelColor[l]};width:10px;height:10px;border-radius:2px"></span>${esc(l)}</span>`).join('');
function bars(el, metric) {
  const rows = D.labels.map(l => ({label: l, ...D.aggregate[l][metric.key]}));
  const w = 420, rowH = 30, l = 8, r = 70, t = 6, h = t + rows.length * rowH + 4;
  const max = Math.max(1e-9, ...rows.map(d => (d.mean ?? 0) + (d.std ?? 0)));
  const X = v => l + v / max * (w - l - r);
  let s = `<line x1="${l}" x2="${l}" y1="${t}" y2="${h - 4}" stroke="var(--axis)"/>`;
  rows.forEach((d, i) => {
    const y = t + i * rowH + 6, bh = rowH - 14;
    if (d.mean === null || d.mean === undefined) { s += `<text x="${l + 6}" y="${y + bh - 3}" font-size="11" fill="var(--muted)">no data</text>`; return; }
    const bw = Math.max(1, X(d.mean) - l);
    s += `<path d="M${l},${y} h${bw - 4} a4,4 0 0 1 4,4 v${bh - 8} a4,4 0 0 1 -4,4 h${-(bw - 4)} z" fill="${labelColor[d.label]}"/>`;
    if (d.std) s += `<line x1="${X(d.mean - d.std)}" x2="${X(d.mean + d.std)}" y1="${y + bh / 2}" y2="${y + bh / 2}" stroke="var(--ink-2)" stroke-width="1.5"/>`;
    s += `<text x="${X((d.mean ?? 0) + (d.std ?? 0)) + 6}" y="${y + bh - 3}" font-size="11" fill="var(--ink)">${fmt(d.mean)}</text>`;
    s += `<rect class="hit" data-i="${i}" x="0" y="${y - 4}" width="${w}" height="${rowH}" fill="transparent"/>`;
  });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.innerHTML = s; el.appendChild(svg);
  svg.querySelectorAll('.hit').forEach(hit => {
    const d = rows[+hit.dataset.i];
    hit.addEventListener('mousemove', e => { tip.innerHTML = `<b>${esc(d.label)}</b><br>mean ${fmt(d.mean, 2)} ${esc(metric.unit)}<br>std ${fmt(d.std, 2)} · n=${d.n}<br>min ${fmt(d.min, 2)} · max ${fmt(d.max, 2)}`;
      tip.style.display = 'block'; tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
    hit.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
  });
}
const grid = document.getElementById('bars');
for (const m of D.metrics) {
  const card = document.createElement('div'); card.className = 'card';
  card.innerHTML = `<div class="chart-title">${esc(m.title)} <span class="muted">(${esc(m.unit)}, ${m.better} is better)</span></div>`;
  grid.appendChild(card); bars(card, m);
}
"""

COMPARISON_METRICS = [
    ("traffic", "mean_travel_time_s", "Mean travel time", "s", "lower"),
    ("traffic", "mean_waiting_time_s", "Mean waiting time", "s", "lower"),
    ("traffic", "mean_time_loss_s", "Mean time loss", "s", "lower"),
    ("traffic", "mean_queued_vehicles", "Mean queued vehicles", "veh", "lower"),
    ("traffic", "throughput_vph", "Throughput", "veh/h", "higher"),
    ("traffic", "trips_unfinished", "Unfinished trips", "veh", "lower"),
    ("emergency", "mean_response_time_s", "Emergency response time", "s", "lower"),
    ("emergency", "mean_stopped_time_s", "Emergency stopped time", "s", "lower"),
    ("system", "forced_phase_changes", "Forced phase changes", "count", "lower"),
]


def render_comparison_report(labels: list[str], aggregate: dict[str, dict[str, dict[str, Any]]],
                             runs: list[dict[str, Any]], scenario_ids: list[str], warnings: list[str]) -> str:
    metrics = [{"key": f"{sec}.{key}", "title": title, "unit": unit, "better": better}
               for sec, key, title, unit, better in COMPARISON_METRICS]
    data = {"labels": labels, "aggregate": aggregate, "metrics": metrics}
    head = "".join(f"<th>{_esc(label)}</th>" for label in labels)
    body = ""
    for m in metrics:
        cells = ""
        for label in labels:
            agg = aggregate[label][m["key"]]
            cell = "—" if agg["mean"] is None else f"{agg['mean']:,.2f} ± {agg['std']:,.2f}"
            cells += f"<td>{_esc(cell)}</td>"
        body += f"<tr><th>{_esc(m['title'])} ({_esc(m['unit'])})</th>{cells}</tr>"
    run_rows = "".join(
        f"<tr><td>{_esc(r['label'])}</td><td>{_esc(r['seed'])}</td><td>{_esc(r['status'])}</td>"
        f"<td><a href=\"{_esc(r['run_id'])}/report.html\">{_esc(r['run_id'])}</a></td></tr>"
        for r in runs
    )
    warn_html = "".join(f'<p class="note bad">⚠ {_esc(w)}</p>' for w in warnings)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Comparison</title><style>{_STYLE}</style></head>
<body><main>
<h1>Strategy comparison</h1>
<p class="sub">Scenario {_esc(', '.join(scenario_ids))} · {len(runs)} runs · values are mean ± standard deviation across seeds.</p>
<p class="note">Simulation output only — not a validation of real-world traffic or emergency performance.</p>
{warn_html}
<div class="legend" id="legend" style="margin-top:16px"></div>
<h2>Key metrics</h2>
<div class="charts" id="bars"></div>
<h2>Table</h2>
<div class="card scroll"><table><thead><tr><th>Metric</th>{head}</tr></thead><tbody>{body}</tbody></table></div>
<h2>Runs</h2>
<div class="card scroll"><table><thead><tr><th>Label</th><th>Seed</th><th>Status</th><th>Run</th></tr></thead><tbody>{run_rows}</tbody></table></div>
</main>
<div class="tooltip" id="tip"></div>
<script type="application/json" id="data">{_json_for_script(data)}</script>
<script>{_COMPARE_SCRIPT}</script>
</body></html>
"""
