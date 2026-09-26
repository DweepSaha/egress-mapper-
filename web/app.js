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
// Mapped building footprints (display only). One source at a time (OSM or Microsoft), feature id = engine building
// id, category set via feature-state so the same source/colour rule can later drive a fill-extrusion (3D) layer.
map.addSource("bld", { type: "geojson", data: empty });
const BLD_CAT = ["feature-state", "cat"];
const BLD_COLOR = ["match", BLD_CAT, "cut", "#ff7a45", "inside", "#c084fc", "retain", "#4fb3a0", "#3b4452"];
const BLD_OPACITY = ["match", BLD_CAT, "cut", 0.95, "inside", 0.95, "retain", 0.6, 0.35];
map.addLayer({ id: "bld-fill", type: "fill", source: "bld", minzoom: 12,
  paint: { "fill-color": BLD_COLOR, "fill-opacity": BLD_OPACITY } }, "roads");
map.addLayer({ id: "bld-line", type: "line", source: "bld", minzoom: 14,
  paint: { "line-color": BLD_COLOR, "line-width": 0.6,
           "line-opacity": ["match", BLD_CAT, "cut", 1, "inside", 1, 0] } }, "roads");

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

// flood scenario layers (Fredericton only; hidden unless the flood scenario is active)
for (const s of ["fl-water", "fl-roads", "fl-cut", "fl-cover"]) map.addSource(s, { type: "geojson", data: empty });
map.addLayer({ id: "fl-cover", type: "line", source: "fl-cover", layout: { visibility: "none" },
  paint: { "line-color": "#93c5fd", "line-width": 1.2, "line-dasharray": [3, 2], "line-opacity": 0.7 } }, "bld-fill");
map.addLayer({ id: "fl-water", type: "fill", source: "fl-water", layout: { visibility: "none" },
  paint: { "fill-color": "#2563eb", "fill-opacity": 0.4 } }, "bld-fill");
map.addLayer({ id: "fl-cut", type: "line", source: "fl-cut", layout: { visibility: "none" },
  paint: { "line-color": "#ff7a45", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 4.5] } });
map.addLayer({ id: "fl-roads", type: "line", source: "fl-roads", layout: { visibility: "none", "line-cap": "round" },
  paint: { "line-color": "#22d3ee", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2, 16, 6] } });
const FLOOD_LAYERS = ["fl-cover", "fl-water", "fl-cut", "fl-roads"];
const SCAN_OVERLAYS = ["choke", "blocked", "cut"];   // hidden while the flood scenario is shown, restored after
const STREET_OPACITY = map.getPaintProperty("streets", "line-opacity");
// fire scenario layers (Tantallon only; hidden unless the fire scenario is active)
for (const s of ["fi-zone", "fi-roads", "fi-cut"]) map.addSource(s, { type: "geojson", data: empty });
map.addLayer({ id: "fi-zone", type: "fill", source: "fi-zone", layout: { visibility: "none" },
  paint: { "fill-color": "#ef4444", "fill-opacity": 0.06 } }, "bld-fill");
map.addLayer({ id: "fi-zone-line", type: "line", source: "fi-zone", layout: { visibility: "none" },
  paint: { "line-color": "#f87171", "line-width": 2.5, "line-dasharray": [3, 1.5] } });
map.addLayer({ id: "fi-cut", type: "line", source: "fi-cut", layout: { visibility: "none" },
  paint: { "line-color": "#ff7a45", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 4.5] } });
map.addLayer({ id: "fi-roads", type: "line", source: "fi-roads", layout: { visibility: "none", "line-cap": "round" },
  paint: { "line-color": "#fde047", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2, 16, 6] } });
const FIRE_LAYERS = ["fi-zone", "fi-zone-line", "fi-cut", "fi-roads"];
let fireOn = false, fireGen = 0, fireData = null, fireMode = "hyp", fireCentre = null, fireSavedSel = null, fireSavedBld = null;

let current = null, scanData = null, selected = null;
let drawing = false, clicks = [];
let floodOn = false, floodGen = 0, floodData = null, floodInfo = null, floodSavedSel = null, floodSavedBld = null;
let bldStateN = 0, coverFeatures = 0, floodAct = 0, coverInstalled = false;
let bldGen = 0, bldAppliedNs = null;
// Displayed footprint ids are namespaced per (area, source) so a category id from one source/area can never match a
// polygon from another, even if MapLibre finishes processing sources out of order. Server ids and counts unchanged.
const BLD_NS = (area, src) => ((area === "fredericton" ? 2 : 0) + (src === "ms" ? 1 : 0)) * 1e7;
const bldTest = { completeDelays: [] };         // test-only: delay the post-processing step to simulate a slow worker
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));
// Resolves once MapLibre has finished processing THIS update of the bld source. sourcedata events don't identify which
// setData they complete, so after each completion event we check the ids of the polygons MapLibre actually holds:
// they must be in this update's namespace (or none loaded yet, e.g. zoomed out below the footprint layer).
function bldProcessed(ns, gen) {
  return new Promise((res) => {
    const done = () => { map.off("sourcedata", onData); map.off("idle", check); res(); };
    const check = () => {
      if (gen !== bldGen) return done();                                 // superseded: stop listening
      if (!map.isSourceLoaded("bld")) return;                            // tiles still (re)loading
      const f = map.querySourceFeatures("bld");
      if (!f.every((x) => x.id >= ns && x.id < ns + 1e7)) return;       // an earlier update's polygons still loaded
      done();
    };
    const onData = (e) => { if (e.sourceId === "bld") check(); };
    map.on("sourcedata", onData);
    map.on("idle", check);                     // also re-check once rendering has settled (no fixed timeout)
  });
}

function panelHtml(p) {
  const src = `Count: the higher of OpenStreetMap (${p.homes_osm}) and Microsoft (${p.homes_ms}) building footprints.`;
  let body;
  if (p.status === "not_assessed")
    body = `<div class="cut">Not assessed: too close to the edge of our road data to judge fairly.</div>`;
  else if (p.worst_cut > 0)
    body = `<div class="cut">If this road area is blocked, <b>${p.worst_cut}</b> could lose their way out to a major road.</div>
            <div class="src">Choke point shown on the map (white circle). Streets that would lose their way out are in bright red.</div>`;
  else
    body = `<div class="cut">None of the sampled blockages cuts these buildings off from a major road.</div>`;
  return `<div class="big">${p.homes} mapped buildings in this neighbourhood</div>${body}
          <div class="src">Connects to major roads at ${p.gateways} point${p.gateways === 1 ? "" : "s"}.</div>
          <div class="src">${src}</div>`;
}

function select(nid) {
  if (floodOn) exitFlood(false);           // selecting a neighbourhood returns to the vulnerability view
  if (fireOn) exitFire(false);
  if (selected !== null) map.setFeatureState({ source: "streets", id: selected }, { selected: false });
  selected = nid;
  const f = scanData.neighbourhoods.features.find((f) => f.id === nid);
  const panel = document.getElementById("panel");
  if (!f) { panel.classList.add("hidden"); updateChokeFilter(); return; }
  map.setFeatureState({ source: "streets", id: nid }, { selected: true });
  panel.className = `card ${f.properties.status}`;
  panel.innerHTML = panelHtml(f.properties) + `<div id="bldInfo"></div>`;
  showBuildings(nid, f.properties);
  map.setFilter("cut", ["==", ["get", "nid"], nid]);
  map.setFilter("blocked", ["==", ["get", "nid"], nid]);
  updateChokeFilter();
  const b = new maplibregl.LngLatBounds();
  const add = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(add));
  add(f.geometry.coordinates);
  map.fitBounds(b, { padding: { top: 60, bottom: 60, left: 380, right: 60 }, maxZoom: 16, duration: 900 });
}

// ---------- mapped building footprints ----------
const SRC_LABEL = { osm: "OpenStreetMap", ms: "Microsoft" };
let bldShown = { area: null, src: null, ready: false }, bldCats = null, bldPinned = null;

async function loadBuildings(area, src) {
  if (bldShown.area === area && bldShown.src === src) return;
  const gen = ++bldGen;
  bldShown = { area, src, ready: false, gen, ns: BLD_NS(area, src) };   // styling disabled until processed
  map.removeFeatureState({ source: "bld" }); bldStateN = 0;
  const data = await (await fetch(`/api/${area}/buildings/${src}`)).json();
  if (gen !== bldGen) return;                                       // superseded before processing began
  const ns = BLD_NS(area, src);
  for (const f of data.features) f.id += ns;
  const processed = bldProcessed(ns, gen);
  map.getSource("bld").setData(data);          // returning from setData does NOT mean the polygons are replaced
  await processed;                             // ...wait until MapLibre holds THIS update's polygons
  const d = bldTest.completeDelays.shift(); if (d) await sleepMs(d);
  if (gen !== bldGen || bldShown.area !== area || bldShown.src !== src || current !== area) return;   // stale
  bldShown.ready = true;
  applyBuildingCats();                         // re-reads the CURRENT scenario (flood or selection) at apply time
}

function applyBuildingCats() {
  map.removeFeatureState({ source: "bld" });
  bldStateN = 0;
  if (!bldShown.ready) return;                 // never paint one source's ids onto the other source's polygons
  // the flood scenario and the selected-neighbourhood view never mix: one or the other drives the categories
  const scen = floodOn ? floodData : fireOn ? fireData : null;     // a scenario mode, if active, owns the categories
  const cats = (floodOn || fireOn) ? (scen && scen.area === bldShown.area ? scen.ids[bldShown.src] : null)
                       : (bldCats && bldCats.area === bldShown.area ? bldCats.sources[bldShown.src] : null);
  if (!cats) return;
  const ns = bldShown.ns;
  for (const cat of ["retain", "cut", "inside"]) for (const id of cats[cat]) {
    map.setFeatureState({ source: "bld", id: id + ns }, { cat }); bldStateN++;
  }
  bldAppliedNs = ns;
  if (floodOn) renderFloodKey(); else if (fireOn) renderFireKey(); else renderBuildingInfo();
}

function renderBuildingInfo() {
  const el = document.getElementById("bldInfo");
  if (!el || !bldCats) return;
  const s = bldCats.sources[bldShown.src], p = bldCats.props;
  const btn = (src) => `<button data-src="${src}" class="${src === bldShown.src ? "on" : ""}">${SRC_LABEL[src]} (${src === "osm" ? p.homes_osm : p.homes_ms})</button>`;
  el.innerHTML = `<div class="bldsrc">Footprints shown: ${btn("osm")}${btn("ms")}</div>
    ${bldCats.choke ? `<div class="bldkey"><span class="k cut"></span>lose access (${s.cut.length})
      <span class="k inside"></span>inside the blocked area (${s.inside.length})
      <span class="k retain"></span>keep access (${s.retain.length})</div>` : ""}
    ${bldCats.matches_scan === false ? `<div class="src">Note: building display does not match the scan counts.</div>` : ""}`;
  el.querySelectorAll("button[data-src]").forEach((b) => (b.onclick = () => {
    bldPinned = b.dataset.src; loadBuildings(bldShown.area, bldPinned).then(renderBuildingInfo);
  }));
}

async function showBuildings(nid, props) {
  const area = current;
  const cats = await (await fetch(`/api/${area}/nb/${nid}/buildings`)).json();
  if (area !== current || nid !== selected) return;
  bldCats = { ...cats, area, props };
  // default to the source that gives the headline count (the higher of the two), unless the viewer picked one
  const src = bldPinned || (props.homes_ms > props.homes_osm ? "ms" : "osm");
  if (bldShown.src !== src || bldShown.area !== area) await loadBuildings(area, src);
  applyBuildingCats();
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
  if (floodOn) exitFlood(false);          // switching areas always clears the flood scenario
  if (fireOn) exitFire(false);            // ...and the fire scenario
  // clear the old area's building categories and footprints NOW, not when the new footprints arrive
  bldCats = null; bldPinned = null;
  map.removeFeatureState({ source: "bld" }); bldStateN = 0;
  bldGen++; bldAppliedNs = null;                 // any in-flight footprint load for the old area becomes stale
  map.getSource("bld").setData(empty); bldShown = { area: null, src: null, ready: false };
  current = name;
  document.getElementById("floodBox").classList.toggle("hidden", name !== "fredericton");
  document.getElementById("fireBox").classList.toggle("hidden", name !== "tantallon");
  if (typeof clearMitigation === "function") clearMitigation();
  document.querySelectorAll("#areas button").forEach((b) => b.classList.toggle("on", b.dataset.area === name));
  const [scan, roads, boundary] = await Promise.all(
    ["scan", "roads", "boundary"].map((k) => fetch(`/api/${name}/${k}`).then((r) => r.json())));
  if (current !== name) return;
  scanData = scan;
  loadBuildings(name, "osm");   // subtle background footprints; loads after the roads, never blocks them
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

// Every mitigation request carries a generation number. Clear, area switch and starting a new proposal bump it, so a
// late response from an older request can never update the map or the panel.
let mitGen = 0, mitKey = null, proposalCount = 0;
function setProposal(features) { proposalCount = features.length; map.getSource("proposal").setData(fc(features)); }

function clearMitigation() {
  mitGen++; mitKey = null;
  drawing = false; clicks = [];
  setProposal([]);
  ["mit-blocked", "mit-cut"].forEach((s) => map.getSource(s).setData(empty));
  document.getElementById("mitig").classList.add("hidden");
  document.getElementById("hint").classList.add("hidden");
  document.getElementById("clearBtn").classList.add("hidden");
  document.getElementById("drawBtn").classList.remove("on");
  map.getCanvas().style.cursor = "";
}

function startDrawing() {
  if (floodOn || fireOn) return;           // the road test belongs to the vulnerability view, not a scenario mode
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
  const road = `<div class="src">Proposed road: ${r.length_m.toLocaleString()} m between the nearest existing road
    junctions or road ends. Conceptual straight-line connection; construction feasibility not assessed.</div>`;
  const beforeTxt = `<div class="cut">Before: if this road area is blocked, ${b.worst_cut} of ${b.homes} mapped buildings
    could lose their way out to a major road.</div>`;
  if (r.unavailable) return `<div class="big">Result unavailable</div>${beforeTxt}<div class="cut">${r.message}</div>${road}`;
  const after = a.worst_cut > 0
    ? `For these same mapped buildings, the worst sampled blockage with the road cuts off <b>${a.worst_cut}</b> (shown in blue).`
    : `For these same mapped buildings, none of the sampled blockages cuts them off with the road.`;
  return `<div class="big">${r.regained} of ${b.worst_cut} mapped buildings regain access under this blockage</div>
    ${beforeTxt}<div class="cut">${after}</div>${road}`;
}

async function runMitigation() {
  const gen = ++mitGen, area = current, pair = clicks.slice(0, 2), key = JSON.stringify(pair);
  mitKey = key;
  const stillCurrent = () => gen === mitGen && area === current && key === mitKey;
  drawing = false;
  map.getCanvas().style.cursor = "";
  document.getElementById("drawBtn").classList.remove("on");
  document.getElementById("hint").classList.add("hidden");
  document.getElementById("clearBtn").classList.remove("hidden");   // Clear available for drawn AND deep-linked proposals
  const box = document.getElementById("mitig");
  box.className = "card mitig"; box.innerHTML = "<div class='src'>Recalculating…</div>";
  box.dataset.state = "pending";
  box.scrollIntoView({ block: "nearest" });
  let r;
  try {
    const resp = await fetch(`/api/${area}/mitigate`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a: pair[0], b: pair[1] }) });
    if (!resp.ok) throw new Error(`server replied ${resp.status}`);
    r = await resp.json();
  } catch (err) {
    if (!stillCurrent()) return;
    console.error("mitigation request failed", err);
    r = { ok: false, message: `Couldn't reach the analysis server (${err.message}). Is scripts/serve.py running?` };
  }
  if (!stillCurrent()) return;   // superseded by Clear, an area switch or a newer proposal: touch nothing
  box.innerHTML = mitigHtml(r);
  box.scrollIntoView({ block: "nearest" });
  box.dataset.state = r.ok ? "done" : "error";   // used by the scripted checks
  if (!r.ok) { setProposal(pair.map(pt)); return; }
  setProposal([r.road, pt(r.road.geometry.coordinates[0]), pt(r.road.geometry.coordinates[1])]);
  if (r.after_geo && !r.unavailable) {
    map.getSource("mit-blocked").setData(r.after_geo.blocked);
    map.getSource("mit-cut").setData(r.after_geo.cut_roads);
  }
  if (selected !== r.before.nid) select(r.before.nid);
}

map.on("click", (e) => {
  if (!drawing) return;
  clicks.push([e.lngLat.lng, e.lngLat.lat]);
  setProposal(clicks.map(pt));
  if (clicks.length === 2) runMitigation();
});
document.getElementById("drawBtn").onclick = startDrawing;
document.getElementById("clearBtn").onclick = clearMitigation;

// ---------- flood scenario (Fredericton): road access under a USER-SUPPLIED river level ----------
const $ = (id) => document.getElementById(id);
const fmt = (c) => `${Math.max(c.osm, c.ms).toLocaleString()} <span class="src">(OSM ${c.osm.toLocaleString()} · Microsoft ${c.ms.toLocaleString()})</span>`;

function updateGaugeReadout(g) {
  const off = floodInfo ? floodInfo.offset_m : -0.489;
  $("gaugeVal").textContent = `${(+g).toFixed(2)} m gauge height`;
  $("gaugeElev").textContent = `compared with the elevation model as ${(+g + off).toFixed(2)} m (CGVD2013)`;
}

function floodHtml(s) {
  const c = s.counts;
  return `<div class="big">Supplied river level ${s.gauge_m.toFixed(2)} m (gauge)</div>
    <div class="cut">Roads affected under this scenario: <b>${s.roads_affected_km} km</b> (cyan).</div>
    <div class="cut">Mapped buildings that lose access: <b>${fmt(c.lose_access)}</b> — outside the water area, but every
      route to a major road crosses it (orange).</div>
    <div class="cut">Mapped buildings with the building centre inside the supplied inundation area: <b>${fmt(c.inside)}</b> (violet).</div>
    <div class="cut">Mapped buildings that keep access: ${fmt(c.keep_access)} (teal).</div>
    <div class="src">Building status is classified by its centre; buildings along the water's edge may partially overlap
      the inundation area. Access counts cover assessed neighbourhoods of 30+ mapped buildings (as in the vulnerability
      scan); the "centre inside" count covers every mapped building in the water area.</div>
    <div class="src">This is not a flood prediction. The river level is your input; the water is a flat surface at
      ${s.water_cgvd2013_m.toFixed(2)} m (CGVD2013) connected to the river channel — no river slope, flood defences or
      drainage. Elevation data covers the river corridor only (dashed outline); roads outside it are treated as dry.
      Bridges are treated as passable. Gauge height is converted with ${s.offset_m} m (NRCan conversion grid); this
      offset is consistent with 2008 observations but not proven, and historical datum conversions carry some
      uncertainty. The terrain is a 2024 survey, so it may not match 2008 ground (e.g. later regrading) when used with
      the 2008 reference. The vulnerability classification is not changed by this scenario.</div>`;
}

function renderFloodKey() {
  const el = $("floodBld");
  if (!el || !floodData) return;
  const btn = (src) => `<button data-src="${src}" class="${src === bldShown.src ? "on" : ""}">${SRC_LABEL[src]}</button>`;
  el.innerHTML = `<div class="bldsrc">Footprints shown: ${btn("osm")}${btn("ms")}</div>`;
  el.querySelectorAll("button[data-src]").forEach((b) => (b.onclick = () => {
    bldPinned = b.dataset.src; loadBuildings(current, bldPinned).then(renderFloodKey);
  }));
}

async function runFlood(g) {
  const gen = ++floodGen, area = current;
  const out = $("floodOut");
  out.dataset.state = "pending";
  out.innerHTML = `<div class="src">Calculating supplied river level ${(+g).toFixed(2)} m…</div>`;
  let s;
  try {
    const r = await fetch(`/api/fredericton/flood?gauge=${(+g).toFixed(2)}`);
    if (!r.ok) throw new Error(`server replied ${r.status}`);
    s = await r.json();
  } catch (err) {
    if (gen !== floodGen || !floodOn || area !== current) return;
    out.dataset.state = "error";
    out.innerHTML = `<div class="cut">Couldn't calculate this scenario (${err.message}).</div>`;
    return;
  }
  if (gen !== floodGen || !floodOn || area !== current) return;   // superseded: touch nothing
  floodData = { ...s, area };
  map.getSource("fl-water").setData(s.water);
  map.getSource("fl-roads").setData(s.roads_affected);
  map.getSource("fl-cut").setData(s.cut_roads);
  out.innerHTML = floodHtml(s) + `<div id="floodBld"></div>`;
  out.dataset.state = "done";
  const src = bldPinned || (s.counts.lose_access.ms > s.counts.lose_access.osm ? "ms" : "osm");
  if (bldShown.src !== src) await loadBuildings(current, src); else applyBuildingCats();
  if (gen === floodGen && floodOn) applyBuildingCats();
}

async function enterFlood(g) {
  if (current !== "fredericton") return;
  // every enable / disable / explicit level bumps floodAct, so an older initialization that resumes after an await
  // (e.g. a slow /flood/info) exits without touching controls, coverage, the slider or the calculation
  const act = ++floodAct, area = current;
  const want = g !== undefined ? (+g).toFixed(2) : $("gauge").value;
  if (!floodOn) {
    clearMitigation();
    floodSavedSel = selected;
    floodSavedBld = { src: bldShown.src, pinned: bldPinned };   // restored exactly on exit
    if (selected !== null) map.setFeatureState({ source: "streets", id: selected }, { selected: false });
    selected = null;
    $("panel").classList.add("hidden");
    floodOn = true;
    SCAN_OVERLAYS.forEach((l) => map.setLayoutProperty(l, "visibility", "none"));
    map.setPaintProperty("streets", "line-opacity", 0.25);
    FLOOD_LAYERS.forEach((l) => map.setLayoutProperty(l, "visibility", "visible"));
    $("drawBtn").disabled = true;
    $("floodOnBox").checked = true;
    $("floodCtl").classList.remove("hidden");
    applyBuildingCats();
  }
  const valid = () => act === floodAct && floodOn && current === area;
  if (!coverInstalled) {                        // coverage outline, once per activation
    let info = floodInfo;
    if (!info) {
      info = await (await fetch("/api/fredericton/flood/info")).json();
      if (!valid()) return;                     // obsolete initialization: no state or UI mutation
      floodInfo = info;
    }
    map.getSource("fl-cover").setData(info.coverage);
    coverFeatures = info.coverage.features.length; coverInstalled = true;
  }
  if (!valid()) return;
  $("gauge").value = want;
  updateGaugeReadout(want);
  return runFlood(want);
}

function exitFlood(restoreSelection = true) {
  floodGen++; floodAct++;                       // invalidate pending scenario requests AND initializations
  floodOn = false; floodData = null; coverInstalled = false;
  FLOOD_LAYERS.filter((l) => l !== "fl-cover").forEach((l) => map.getSource(l).setData(empty));
  FLOOD_LAYERS.forEach((l) => map.setLayoutProperty(l, "visibility", "none"));
  SCAN_OVERLAYS.forEach((l) => map.setLayoutProperty(l, "visibility", "visible"));
  map.setPaintProperty("streets", "line-opacity", STREET_OPACITY);
  $("drawBtn").disabled = false;
  $("floodOnBox").checked = false;
  $("floodCtl").classList.add("hidden");
  $("floodOut").innerHTML = ""; delete $("floodOut").dataset.state;
  const saved = floodSavedBld; floodSavedBld = null;
  if (restoreSelection && saved) {               // restore the pre-flood footprint source and the viewer's pin
    bldPinned = saved.pinned;
    if (saved.src && bldShown.src !== saved.src) loadBuildings(current, saved.src);   // applies categories on arrival
  }
  applyBuildingCats();                           // no-op until the (possibly restored) source is ready
  const sel = floodSavedSel; floodSavedSel = null;
  if (restoreSelection && sel !== null) select(sel);
}

$("floodOnBox").onchange = (e) => (e.target.checked ? enterFlood() : exitFlood());
$("gauge").oninput = (e) => updateGaugeReadout(e.target.value);
$("gauge").onchange = (e) => floodOn && enterFlood(e.target.value);  // on release; an explicit level supersedes older inits
document.querySelectorAll("#floodCtl .presets button").forEach((b) => (b.onclick = () => enterFlood(b.dataset.g)));

// ---------- fire scenario (Tantallon): road access under a SUPPLIED affected area; no fire-spread prediction ----------
const km = (m) => `${(m / 1000).toFixed(2)} km`;
const stat = (cls, label, c) => `<div class="fs ${cls}"><span class="n">${Math.max(c.osm, c.ms).toLocaleString()}</span>
  <span class="l">${label}</span><span class="src">OSM ${c.osm.toLocaleString()} · Microsoft ${c.ms.toLocaleString()}</span></div>`;
const FIRE_KEY = `<div class="firekey">
  <div><span class="k zone"></span>Supplied affected area</div>
  <div><span class="k road"></span>Road portions within the supplied affected area</div>
  <div><span class="k cut"></span>Outside the area but loses access (buildings and roads)</div>
  <div><span class="k inside"></span>Building centre inside the supplied area</div>
  <div><span class="k retain"></span>Retains access</div></div>`;

function fireHtml(s) {
  const c = s.counts;
  const head = s.kind === "historical"
    ? `<div class="big">Mapped 2023 fire perimeter</div>
       <div class="src">Published NBAC area ${s.perimeter.mapped_ha} ha · fire starting ${s.perimeter.start_date}</div>`
    : `<div class="big">Supplied hypothetical affected area</div>
       <div class="src">Radius ${s.radius_m.toLocaleString()} m (${s.zone_ha} ha) · your input, not a predicted fire extent</div>`;
  const ents = s.kind === "historical"
    ? `<div class="fnote">Westwood Hills entrances: outside the perimeter, about
       ${s.westwood_entrances.map((e) => e.distance_m).sort((a, b) => a - b).map(km).join(" and ")} away.</div>` : "";
  return `${head}
    <div class="fstats">
      <div class="fs road"><span class="n">${s.roads_affected_km} km</span>
        <span class="l">road portions within the supplied affected area</span></div>
      ${stat("cut", "outside the area, lose access", c.lose_access)}
      ${stat("inside", "centre inside the area", c.inside)}
      ${stat("retain", "retain access", c.keep_access)}
    </div>
    ${ents}
    <div class="nopredict">This tool does not predict fire spread.</div>
    ${FIRE_KEY}
    <details class="src"><summary>How this is counted</summary>
      Roads are treated as impassable only within the supplied area; no wind, weather, fire behaviour, traffic or
      evacuation time is modelled. Buildings are classified by their centre. Access counts cover assessed
      neighbourhoods of 30+ mapped buildings (as in the vulnerability scan); the centre-inside count covers every
      mapped building in the area.${s.kind === "historical" ? ` Area: the published NBAC figure (${s.perimeter.mapped_ha} ha)
      is measured on the curved Earth; this tool measures the same outline on its flat map as ${s.zone_ha} ha
      (about 0.1% larger from map distortion this far from New Brunswick). The outline is unchanged.` : ""}</details>`;
}

function renderFireKey() {
  const el = $("fireBld");
  if (!el || !fireData) return;
  const btn = (src) => `<button data-src="${src}" class="${src === bldShown.src ? "on" : ""}">${SRC_LABEL[src]}</button>`;
  el.innerHTML = `<div class="bldsrc">Footprints shown: ${btn("osm")}${btn("ms")}</div>`;
  el.querySelectorAll("button[data-src]").forEach((b) => (b.onclick = () => {
    bldPinned = b.dataset.src; loadBuildings(current, bldPinned).then(renderFireKey);
  }));
}

async function runFire() {
  const gen = ++fireGen, area = current, mode = fireMode;
  const out = $("fireOut");
  if (mode === "hyp" && !fireCentre) { out.innerHTML = ""; delete out.dataset.state; return; }
  const radius = +$("fireRadius").value;
  const url = mode === "hist" ? "/api/tantallon/fire/historical"
    : `/api/tantallon/fire/hypothetical?lon=${fireCentre[0]}&lat=${fireCentre[1]}&radius=${radius}`;
  out.dataset.state = "pending";
  out.innerHTML = `<div class="src">Calculating…</div>`;
  let s;
  try {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`server replied ${r.status}`);
    s = await r.json();
  } catch (err) {
    if (gen !== fireGen || !fireOn || area !== current) return;
    out.dataset.state = "error"; out.innerHTML = `<div class="cut">Couldn't calculate this scenario (${err.message}).</div>`;
    return;
  }
  if (gen !== fireGen || !fireOn || area !== current || mode !== fireMode) return;   // superseded: touch nothing
  fireData = { ...s, area };
  map.getSource("fi-zone").setData(s.zone);
  map.getSource("fi-roads").setData(s.roads_affected);
  map.getSource("fi-cut").setData(s.cut_roads);
  out.innerHTML = fireHtml(s) + `<div id="fireBld"></div>`;
  out.dataset.state = "done";
  const src = bldPinned || (s.counts.lose_access.ms > s.counts.lose_access.osm ? "ms" : "osm");
  if (bldShown.src !== src) loadBuildings(current, src); else applyBuildingCats();
}

function setFireMode(mode) {
  fireMode = mode;
  document.querySelectorAll("#fireModes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("fireHyp").classList.toggle("hidden", mode !== "hyp");
  fireGen++; fireData = null;                                   // a new mode supersedes any pending calculation
  ["fi-zone", "fi-roads", "fi-cut"].forEach((l) => map.getSource(l).setData(empty));
  applyBuildingCats();
  map.getCanvas().style.cursor = fireOn && mode === "hyp" ? "crosshair" : "";
  if (fireOn) runFire();
}

function enterFire(mode) {
  if (current !== "tantallon") return;
  if (!fireOn) {
    clearMitigation();
    fireSavedSel = selected;
    fireSavedBld = { src: bldShown.src, pinned: bldPinned };   // restored exactly on exit
    if (selected !== null) map.setFeatureState({ source: "streets", id: selected }, { selected: false });
    selected = null;
    $("panel").classList.add("hidden");
    fireOn = true;
    SCAN_OVERLAYS.forEach((l) => map.setLayoutProperty(l, "visibility", "none"));
    map.setPaintProperty("streets", "line-opacity", 0.25);
    FIRE_LAYERS.forEach((l) => map.setLayoutProperty(l, "visibility", "visible"));
    $("drawBtn").disabled = true;
    $("fireOnBox").checked = true;
    $("fireCtl").classList.remove("hidden");
  }
  setFireMode(mode || fireMode);
}

function exitFire(restoreSelection = true) {
  fireGen++;                                    // invalidate any pending scenario request
  fireOn = false; fireData = null; fireCentre = null;
  ["fi-zone", "fi-roads", "fi-cut"].forEach((l) => map.getSource(l).setData(empty));
  FIRE_LAYERS.forEach((l) => map.setLayoutProperty(l, "visibility", "none"));
  SCAN_OVERLAYS.forEach((l) => map.setLayoutProperty(l, "visibility", "visible"));
  map.setPaintProperty("streets", "line-opacity", STREET_OPACITY);
  map.getCanvas().style.cursor = "";
  $("drawBtn").disabled = false;
  $("fireOnBox").checked = false;
  $("fireCtl").classList.add("hidden");
  $("fireOut").innerHTML = ""; delete $("fireOut").dataset.state;
  const saved = fireSavedBld; fireSavedBld = null;
  if (restoreSelection && saved) {
    bldPinned = saved.pinned;
    if (saved.src && bldShown.src !== saved.src) loadBuildings(current, saved.src);
  }
  applyBuildingCats();
  const sel = fireSavedSel; fireSavedSel = null;
  if (restoreSelection && sel !== null) select(sel);
}

$("fireOnBox").onchange = (e) => (e.target.checked ? enterFire() : exitFire());
document.querySelectorAll("#fireModes button").forEach((b) => (b.onclick = () => fireOn && setFireMode(b.dataset.mode)));
$("fireRadius").oninput = (e) => ($("fireRadiusVal").textContent = `${(+e.target.value).toLocaleString()} m`);
$("fireRadius").onchange = () => fireOn && fireMode === "hyp" && runFire();   // on release
map.on("click", (e) => {
  if (!fireOn || fireMode !== "hyp") return;
  fireCentre = [+e.lngLat.lng.toFixed(6), +e.lngLat.lat.toFixed(6)];
  runFire();
});

map.on("click", "nb-fill", (e) => { if (!drawing && !floodOn && !fireOn) select(e.features[0].id); });
map.on("click", "choke", (e) => { if (!drawing && !floodOn && !fireOn) select(e.features[0].properties.nid); });
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
window.__app = {   // for debugging, scripted demo and the ?selftest=1 checks
  bldTest, reapply: () => applyBuildingCats(),
  resetFloodInfo() { floodInfo = null; coverInstalled = false; coverFeatures = 0; },   // test-only: fresh first activation
  gaugeValue: () => $("gauge").value,
  bldCheck() {   // what MapLibre actually holds: loaded polygons' namespaces and their category states
    const feats = map.querySourceFeatures("bld");
    const byNs = {}, wrong = [];
    const expect = floodOn ? (floodData ? floodData.ids[bldShown.src] : null) : (bldCats ? bldCats.sources[bldShown.src] : null);
    const expCat = new Map();
    if (expect) for (const c of ["retain", "cut", "inside"]) for (const id of expect[c]) expCat.set(id, c);
    const seen = new Set();
    for (const f of feats) {
      if (seen.has(f.id)) continue; seen.add(f.id);
      const ns = Math.floor(f.id / 1e7) * 1e7;
      byNs[ns] = (byNs[ns] || 0) + 1;
      const st = map.getFeatureState({ source: "bld", id: f.id }).cat;
      if (st && (ns !== bldShown.ns || expCat.get(f.id - ns) !== st)) wrong.push({ id: f.id, ns, st });
    }
    return { src: bldShown.src, ready: bldShown.ready, ns: bldShown.ns, appliedNs: bldAppliedNs, states: bldStateN,
             loadedByNs: byNs, loaded: seen.size, wrongStates: wrong.length, wrongSample: wrong.slice(0, 3) };
  },
  map, select, loadArea, clear: clearMitigation,
  propose(a, b) { clearMitigation(); clicks = [a, b]; return runMitigation(); },
  flood: (g) => enterFlood(g), unflood: () => exitFlood(),
  snapshot() {   // map/UI state used to check that leaving the flood scenario restores the exact baseline
    const vis = Object.fromEntries(map.getStyle().layers.map((l) => [l.id, map.getLayoutProperty(l.id, "visibility") ?? "visible"]));
    return JSON.stringify({ vis, streetsOpacity: map.getPaintProperty("streets", "line-opacity"),
      filters: SCAN_OVERLAYS.map((l) => map.getFilter(l)), selected, panelHidden: $("panel").classList.contains("hidden"),
      panelText: $("panel").textContent.replace(/\s+/g, " ").trim(), drawDisabled: $("drawBtn").disabled,
      floodCtlHidden: $("floodCtl").classList.contains("hidden"), bldStates: bldStateN, floodOn,
      bldSrc: bldShown.src, bldPinned });
  },
  fire(mode, centre, radius) {   // test hook: enter the fire scenario (optionally at a centre/radius)
    if (radius) { $("fireRadius").value = radius; $("fireRadiusVal").textContent = `${radius} m`; }
    if (centre) fireCentre = centre;
    enterFire(mode);
  },
  unfire: () => exitFire(),
  fireState: () => ({ on: fireOn, mode: fireMode, area: current, cardState: $("fireOut").dataset.state || null,
    cardText: $("fireOut").textContent.replace(/\s+/g, " ").trim(), bldStates: bldStateN,
    boxHidden: $("fireBox").classList.contains("hidden") }),
  floodState: () => ({ on: floodOn, area: current, cardState: $("floodOut").dataset.state || null,
    cardText: $("floodOut").textContent.replace(/\s+/g, " ").trim(), bldStates: bldStateN,
    boxHidden: $("floodBox").classList.contains("hidden"), coverFeatures,
    bldSrc: bldShown.src, bldReady: bldShown.ready, bldPinned }),
  state() {
    const box = document.getElementById("mitig");
    return { area: current, cardHidden: box.classList.contains("hidden"), cardState: box.dataset.state || null,
             cardText: box.textContent.replace(/\s+/g, " ").trim(), proposalFeatures: proposalCount,
             clearVisible: !document.getElementById("clearBtn").classList.contains("hidden") };
  },
};
if (["1", "flood", "fire"].includes(q.get("selftest"))) import("/selftest.js");   // explicit test URLs only
