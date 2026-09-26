import * as maplibregl from "/vendor/maplibre-gl-6.11.2/maplibre-gl.mjs";

const OFM_DARK = "https://tiles.openfreemap.org/styles/dark";
// Plain dark map used when the basemap can't be reached (e.g. no internet at the venue).
const OFFLINE_STYLE = { version: 8, sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b0d10" } }] };
const COLORS = { red: "#e0524a", amber: "#e0a526", green: "#3fb27f", not_assessed: "#6b7280" };
const SHOW_TOP_CHOKES = 5;

async function pickStyle() {
  if (new URLSearchParams(location.search).get("basemap") === "off") return OFFLINE_STYLE;  // rehearse offline demo
  try {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 4000);
    const r = await fetch(OFM_DARK, { signal: ctl.signal }); clearTimeout(t);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch { return OFFLINE_STYLE; }
}

const areas = await (await fetch("/api/areas")).json();
const map = new maplibregl.Map({ container: "map", style: await pickStyle(), center: areas.tantallon.center,
  zoom: areas.tantallon.zoom, attributionControl: { compact: false } });
map.addControl(new maplibregl.NavigationControl(), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
await new Promise((r) => map.once("load", r));

const empty = { type: "FeatureCollection", features: [] };
const OSM = "© OpenStreetMap contributors";
map.addSource("boundary", { type: "geojson", data: empty });
map.addSource("roads", { type: "geojson", data: empty, attribution: OSM });
map.addSource("nb", { type: "geojson", data: empty,
  attribution: "Building footprints © Microsoft (ODbL); © OpenStreetMap contributors" });
map.addSource("streets", { type: "geojson", data: empty });
map.addSource("cut", { type: "geojson", data: empty });
map.addSource("blocked", { type: "geojson", data: empty });
map.addSource("choke", { type: "geojson", data: empty });

map.addLayer({ id: "boundary", type: "fill", source: "boundary", paint: { "fill-color": "#6b7280", "fill-opacity": 0.18 } });
// invisible click targets (the neighbourhood's area); status is drawn on the street lines below
map.addLayer({ id: "nb-fill", type: "fill", source: "nb", paint: { "fill-color": "#000", "fill-opacity": 0 } });
map.addLayer({ id: "roads", type: "line", source: "roads", paint: {
  "line-color": ["case", ["get", "way_out"], "#e8edf2", "#4b5663"],
  "line-width": ["interpolate", ["linear"], ["zoom"], 11, ["case", ["get", "way_out"], 1.4, 0.3],
                 16, ["case", ["get", "way_out"], 4, 1.2]] } });
const SEL = ["boolean", ["feature-state", "selected"], false];
map.addLayer({ id: "streets", type: "line", source: "streets", layout: { "line-cap": "round", "line-join": "round" },
  paint: {
    "line-color": ["match", ["get", "status"], "red", COLORS.red, "amber", COLORS.amber, "green", COLORS.green, COLORS.not_assessed],
    "line-width": ["interpolate", ["linear"], ["zoom"], 11, ["case", SEL, 2.2, 1.0], 16, ["case", SEL, 5, 2.6]],
    // red streets more opaque where more buildings could be cut off; classification itself is unchanged
    "line-opacity": ["case", SEL, 1, ["match", ["get", "status"],
      "red", ["interpolate", ["linear"], ["get", "worst_cut"], 30, 0.6, 200, 0.95], "not_assessed", 0.55, 0.85]] } });
map.addLayer({ id: "cut", type: "line", source: "cut", filter: ["==", ["get", "nid"], -1],
  paint: { "line-color": "#ff3b30", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 5] } });
map.addLayer({ id: "blocked", type: "fill", source: "blocked", filter: ["==", ["get", "nid"], -1],
  paint: { "fill-color": "#ffffff", "fill-opacity": 0.35 } });
map.addLayer({ id: "choke", type: "circle", source: "choke", paint: {
  "circle-color": "#ffffff", "circle-stroke-color": "#ff3b30", "circle-stroke-width": 2,
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 4, 16, 9] } });

// mitigation test layers: proposed road, and the neighbourhood's new worst case with that road
map.addSource("proposal", { type: "geojson", data: empty });
map.addSource("mit-blocked", { type: "geojson", data: empty });
map.addSource("mit-cut", { type: "geojson", data: empty });
map.addLayer({ id: "mit-cut", type: "line", source: "mit-cut",
  paint: { "line-color": "#ffb020", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 5] } });
map.addLayer({ id: "mit-blocked", type: "fill", source: "mit-blocked",
  paint: { "fill-color": "#35c3ff", "fill-opacity": 0.35 } });
map.addLayer({ id: "proposal-line", type: "line", source: "proposal", filter: ["==", ["geometry-type"], "LineString"],
  paint: { "line-color": "#35c3ff", "line-width": 4, "line-dasharray": [2, 1.2] } });
map.addLayer({ id: "proposal-pts", type: "circle", source: "proposal", filter: ["==", ["geometry-type"], "Point"],
  paint: { "circle-color": "#35c3ff", "circle-radius": 6, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });

let current = null, scanData = null, selected = null;
let drawing = false, clicks = [];

function panelHtml(p) {
  const src = `Count: the higher of OpenStreetMap (${p.homes_osm}) and Microsoft (${p.homes_ms}) building footprints.`;
  let body;
  if (p.status === "not_assessed")
    body = `<div class="cut">Not assessed: too close to the edge of our road data to judge fairly.</div>`;
  else if (p.worst_cut > 0)
    body = `<div class="cut">If this road area is blocked, <b>${p.worst_cut}</b> could lose their way out to a major road.</div>
            <div class="src">Choke point shown on the map (white circle). Streets that would lose their way out are in bright red.</div>`;
  else
    body = `<div class="cut">No single blocked road area cuts these buildings off from a major road.</div>`;
  return `<div class="big">${p.homes} mapped buildings in this neighbourhood</div>${body}
          <div class="src">Connects to major roads at ${p.gateways} point${p.gateways === 1 ? "" : "s"}.</div>
          <div class="src">${src}</div>`;
}

function select(nid) {
  if (selected !== null) map.setFeatureState({ source: "streets", id: selected }, { selected: false });
  selected = nid;
  const f = scanData.neighbourhoods.features.find((f) => f.id === nid);
  const panel = document.getElementById("panel");
  if (!f) { panel.classList.add("hidden"); updateChokeFilter(); return; }
  map.setFeatureState({ source: "streets", id: nid }, { selected: true });
  panel.className = `card ${f.properties.status}`;
  panel.innerHTML = panelHtml(f.properties);
  map.setFilter("cut", ["==", ["get", "nid"], nid]);
  map.setFilter("blocked", ["==", ["get", "nid"], nid]);
  updateChokeFilter();
  const b = new maplibregl.LngLatBounds();
  const add = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(add));
  add(f.geometry.coordinates);
  map.fitBounds(b, { padding: { top: 60, bottom: 60, left: 380, right: 60 }, maxZoom: 16, duration: 900 });
}

function updateChokeFilter() {
  // only the top-ranked choke points (and the selected one) are drawn, to avoid a wall of markers
  map.setFilter("choke", ["any", ["all", ["!=", ["get", "rank"], null], ["<=", ["get", "rank"], SHOW_TOP_CHOKES]],
                          ["==", ["get", "nid"], selected ?? -1]]);
}

function renderRanking() {
  const ol = document.getElementById("ranking");
  const top = scanData.neighbourhoods.features.filter((f) => f.properties.rank !== null)
    .sort((a, b) => a.properties.rank - b.properties.rank).slice(0, 8);
  ol.innerHTML = top.map((f) => `<li data-nid="${f.id}"><span class="n">${f.properties.worst_cut}</span> of
    ${f.properties.homes} mapped buildings could lose their way out</li>`).join("") || "<li>None</li>";
  ol.querySelectorAll("li[data-nid]").forEach((li) => (li.onclick = () => select(+li.dataset.nid)));
}

async function loadArea(name) {
  current = name;
  if (typeof clearMitigation === "function") clearMitigation();
  document.querySelectorAll("#areas button").forEach((b) => b.classList.toggle("on", b.dataset.area === name));
  const [scan, roads, boundary] = await Promise.all(
    ["scan", "roads", "boundary"].map((k) => fetch(`/api/${name}/${k}`).then((r) => r.json())));
  if (current !== name) return;
  scanData = scan;
  map.getSource("roads").setData(roads);
  map.getSource("boundary").setData(boundary);
  map.getSource("nb").setData(scan.neighbourhoods);
  map.getSource("streets").setData(scan.streets);
  map.getSource("cut").setData(scan.cut_roads);
  map.getSource("blocked").setData(scan.blocked);
  map.getSource("choke").setData(scan.chokepoints);
  selected = null;
  document.getElementById("panel").classList.add("hidden");
  map.setFilter("cut", ["==", ["get", "nid"], -1]);
  map.setFilter("blocked", ["==", ["get", "nid"], -1]);
  updateChokeFilter();
  renderRanking();
  map.jumpTo({ center: areas[name].center, zoom: areas[name].zoom });
}

document.getElementById("areas").innerHTML = Object.entries(areas)
  .map(([k, v]) => `<button data-area="${k}">${v.label}</button>`).join("");
document.querySelectorAll("#areas button").forEach((b) => (b.onclick = () => loadArea(b.dataset.area)));

// ---------- mitigation test ----------
const fc = (features) => ({ type: "FeatureCollection", features });
const pt = (ll) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: ll } });

function clearMitigation() {
  drawing = false; clicks = [];
  ["proposal", "mit-blocked", "mit-cut"].forEach((s) => map.getSource(s).setData(empty));
  document.getElementById("mitig").classList.add("hidden");
  document.getElementById("hint").classList.add("hidden");
  document.getElementById("clearBtn").classList.add("hidden");
  document.getElementById("drawBtn").classList.remove("on");
  map.getCanvas().style.cursor = "";
}

function startDrawing() {
  clearMitigation();
  drawing = true;
  document.getElementById("drawBtn").classList.add("on");
  document.getElementById("hint").classList.remove("hidden");
  document.getElementById("clearBtn").classList.remove("hidden");
  map.getCanvas().style.cursor = "crosshair";
}

function mitigHtml(r) {
  if (!r.ok) return `<div class="cut">${r.message}</div>`;
  const b = r.before, a = r.after;
  const after = a ? (a.worst_cut > 0
      ? `With this road, the largest single choke point in the neighbourhood cuts off <b>${a.worst_cut}</b> (shown in blue).`
      : `With this road, no single blocked road area cuts these buildings off.`) : "";
  return `<div class="big">${r.regained} of ${b.worst_cut} mapped buildings regain a separate way out</div>
    <div class="cut">Before: if this road area is blocked, ${b.worst_cut} of ${b.homes} mapped buildings could lose
      their way out to a major road.</div>
    <div class="cut">${after}</div>
    <div class="src">Proposed road: ${r.length_m.toLocaleString()} m, straight line between the nearest existing road points.</div>`;
}

async function runMitigation() {
  drawing = false;
  map.getCanvas().style.cursor = "";
  document.getElementById("drawBtn").classList.remove("on");
  document.getElementById("hint").classList.add("hidden");
  const box = document.getElementById("mitig");
  box.className = "card mitig"; box.innerHTML = "<div class='src'>Recalculating…</div>";
  box.scrollIntoView({ block: "nearest" });
  let r;
  try {
    const resp = await fetch(`/api/${current}/mitigate`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a: clicks[0], b: clicks[1] }) });
    if (!resp.ok) throw new Error(`server replied ${resp.status}`);
    r = await resp.json();
  } catch (err) {
    console.error("mitigation request failed", err);
    r = { ok: false, message: `Couldn't reach the analysis server (${err.message}). Is scripts/serve.py running?` };
  }
  box.innerHTML = mitigHtml(r);
  box.scrollIntoView({ block: "nearest" });
  box.dataset.state = r.ok ? "done" : "error";   // used by the scripted demo check
  if (!r.ok) { map.getSource("proposal").setData(fc(clicks.map(pt))); return; }
  map.getSource("proposal").setData(fc([r.road, pt(r.road.geometry.coordinates[0]), pt(r.road.geometry.coordinates[1])]));
  if (r.after_geo) {
    map.getSource("mit-blocked").setData(r.after_geo.blocked);
    map.getSource("mit-cut").setData(r.after_geo.cut_roads);
  }
  if (selected !== r.before.nid) select(r.before.nid);
}

map.on("click", (e) => {
  if (!drawing) return;
  clicks.push([e.lngLat.lng, e.lngLat.lat]);
  map.getSource("proposal").setData(fc(clicks.map(pt)));
  if (clicks.length === 2) runMitigation();
});
document.getElementById("drawBtn").onclick = startDrawing;
document.getElementById("clearBtn").onclick = clearMitigation;

map.on("click", "nb-fill", (e) => { if (!drawing) select(e.features[0].id); });
map.on("click", "choke", (e) => { if (!drawing) select(e.features[0].properties.nid); });
map.on("mouseenter", "nb-fill", () => (map.getCanvas().style.cursor = "pointer"));
map.on("mouseleave", "nb-fill", () => (map.getCanvas().style.cursor = ""));

// deep links: ?area=fredericton&nid=99 opens an area with a neighbourhood selected
const q = new URLSearchParams(location.search);
await loadArea(areas[q.get("area")] ? q.get("area") : "tantallon");
if (q.get("nid")) select(+q.get("nid"));
// scripted demo / backup: &road=lonA,latA,lonB,latB runs the same mitigation path as two map clicks
if (q.get("road")) {
  const v = q.get("road").split(",").map(Number);
  if (v.length === 4 && v.every(Number.isFinite)) { clicks = [[v[0], v[1]], [v[2], v[3]]]; runMitigation(); }
}
window.__app = { map, select, loadArea };   // for debugging / scripted demo
