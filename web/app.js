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
map.addSource("cut", { type: "geojson", data: empty });
map.addSource("blocked", { type: "geojson", data: empty });
map.addSource("choke", { type: "geojson", data: empty });

map.addLayer({ id: "boundary", type: "fill", source: "boundary", paint: { "fill-color": "#6b7280", "fill-opacity": 0.18 } });
map.addLayer({ id: "nb-fill", type: "fill", source: "nb", paint: {
  "fill-color": ["match", ["get", "status"], "red", COLORS.red, "amber", COLORS.amber, "green", COLORS.green, COLORS.not_assessed],
  // stronger red where more homes could be cut off; classification itself is unchanged
  "fill-opacity": ["match", ["get", "status"],
    "red", ["interpolate", ["linear"], ["get", "worst_cut"], 30, 0.22, 150, 0.5, 400, 0.78],
    "amber", 0.28, "green", 0.2, 0.12] } });
map.addLayer({ id: "nb-line", type: "line", source: "nb", paint: {
  "line-color": ["match", ["get", "status"], "red", COLORS.red, "amber", COLORS.amber, "green", COLORS.green, "#9aa3ad"],
  "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 3.5, 0.6],
  "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 1, 0.6] } });
map.addLayer({ id: "roads", type: "line", source: "roads", paint: {
  "line-color": ["case", ["get", "way_out"], "#e8edf2", "#7f95ab"],
  "line-width": ["interpolate", ["linear"], ["zoom"], 11, ["case", ["get", "way_out"], 1.4, 0.4],
                 16, ["case", ["get", "way_out"], 4, 1.8]] } });
map.addLayer({ id: "cut", type: "line", source: "cut", filter: ["==", ["get", "nid"], -1],
  paint: { "line-color": "#ff3b30", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 5] } });
map.addLayer({ id: "blocked", type: "fill", source: "blocked", filter: ["==", ["get", "nid"], -1],
  paint: { "fill-color": "#ffffff", "fill-opacity": 0.35 } });
map.addLayer({ id: "choke", type: "circle", source: "choke", paint: {
  "circle-color": "#ffffff", "circle-stroke-color": "#ff3b30", "circle-stroke-width": 2,
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 4, 16, 9] } });

let current = null, scanData = null, selected = null;

function panelHtml(p) {
  const src = `Home count: the higher of OpenStreetMap (${p.homes_osm}) and Microsoft (${p.homes_ms}) building footprints.`;
  let body;
  if (p.status === "not_assessed")
    body = `<div class="cut">Not assessed: too close to the edge of our road data to judge fairly.</div>`;
  else if (p.worst_cut > 0)
    body = `<div class="cut">If this road area is blocked, <b>${p.worst_cut}</b> could lose their way out to a major road.</div>
            <div class="src">Choke point shown on the map (white circle). Streets that would lose their way out are in bright red.</div>`;
  else
    body = `<div class="cut">No single blocked road area cuts these homes off from a major road.</div>`;
  return `<div class="big">${p.homes} homes in this neighbourhood</div>${body}
          <div class="src">Connects to major roads at ${p.gateways} point${p.gateways === 1 ? "" : "s"}.</div>
          <div class="src">${src}</div>`;
}

function select(nid) {
  if (selected !== null) map.setFeatureState({ source: "nb", id: selected }, { selected: false });
  selected = nid;
  const f = scanData.neighbourhoods.features.find((f) => f.id === nid);
  const panel = document.getElementById("panel");
  if (!f) { panel.classList.add("hidden"); updateChokeFilter(); return; }
  map.setFeatureState({ source: "nb", id: nid }, { selected: true });
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
    ${f.properties.homes} homes could lose their way out</li>`).join("") || "<li>None</li>";
  ol.querySelectorAll("li[data-nid]").forEach((li) => (li.onclick = () => select(+li.dataset.nid)));
}

async function loadArea(name) {
  current = name;
  document.querySelectorAll("#areas button").forEach((b) => b.classList.toggle("on", b.dataset.area === name));
  const [scan, roads, boundary] = await Promise.all(
    ["scan", "roads", "boundary"].map((k) => fetch(`/api/${name}/${k}`).then((r) => r.json())));
  if (current !== name) return;
  scanData = scan;
  map.getSource("roads").setData(roads);
  map.getSource("boundary").setData(boundary);
  map.getSource("nb").setData(scan.neighbourhoods);
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

map.on("click", "nb-fill", (e) => select(e.features[0].id));
map.on("click", "choke", (e) => select(e.features[0].properties.nid));
map.on("mouseenter", "nb-fill", () => (map.getCanvas().style.cursor = "pointer"));
map.on("mouseleave", "nb-fill", () => (map.getCanvas().style.cursor = ""));

// deep links: ?area=fredericton&nid=99 opens an area with a neighbourhood selected
const q = new URLSearchParams(location.search);
await loadArea(areas[q.get("area")] ? q.get("area") : "tantallon");
if (q.get("nid")) select(+q.get("nid"));
window.__app = { map, select, loadArea };   // for debugging / scripted demo
