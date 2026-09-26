import * as maplibregl from "/vendor/maplibre-gl-6.11.2/maplibre-gl.mjs";

const OFM_DARK = "https://tiles.openfreemap.org/styles/dark";
// Plain dark map used when the basemap can't be reached (e.g. no internet at the venue).
const OFFLINE_STYLE = { version: 8, sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#0b0d10" } }] };
const COLORS = { red: "#e0524a", amber: "#e0a526", green: "#3fb27f", not_assessed: "#6b7280" };
// Motion only acknowledges USER input (camera framing, settling headline numbers, one attention ring). Off for
// prefers-reduced-motion, ?motion=off, self-tests (unless &motion=on) or __app.motion(false). Never drives state.
const QS = new URLSearchParams(location.search);
let MOTION = QS.get("motion") === "on" ||
  (QS.get("motion") !== "off" && !QS.get("selftest") && !matchMedia("(prefers-reduced-motion: reduce)").matches);
const dur = (ms) => (MOTION ? ms : 0);
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
const style = await pickStyle();
const stB = document.getElementById("stBasemap");
stB.className = `st ${style === OFFLINE_STYLE ? "off" : "on"}`;
stB.textContent = style === OFFLINE_STYLE ? "Basemap off (offline mode)" : "Basemap online";
const map = new maplibregl.Map({ container: "map", style, center: areas.tantallon.center,
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

// Mapped water (OSM water/riverbank/reservoir): geographic context only, never used by any calculation. Subdued and
// desaturated so the flood scenario's supplied inundation (bright blue, drawn above) is always distinguishable.
map.addSource("water", { type: "geojson", data: empty, attribution: OSM });
map.addLayer({ id: "water", type: "fill", source: "water", paint: { "fill-color": "#1a2c3d", "fill-opacity": 0.95 } });
map.addLayer({ id: "water-line", type: "line", source: "water", paint: { "line-color": "#2a4258", "line-width": 0.6 } });
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
// 3D view (presentation only): the same polygons and category colours, extruded to one fixed illustrative height.
// Placed below the road layers so roads, choke points, the proposed connection and hazard lines stay readable on top.
const BLD_HEIGHT_M = 14;         // illustrative, identical for every mapped building (real heights are not available)
const BLD_COLOR_3D = ["match", BLD_CAT, "cut", "#ff7a45", "inside", "#c084fc", "retain", "#4fb3a0", "#5a6573"];
map.addLayer({ id: "bld-3d", type: "fill-extrusion", source: "bld", minzoom: 12, layout: { visibility: "none" },
  paint: { "fill-extrusion-color": BLD_COLOR_3D, "fill-extrusion-height": BLD_HEIGHT_M, "fill-extrusion-base": 0,
           "fill-extrusion-opacity": 0.92, "fill-extrusion-vertical-gradient": true } }, "roads");
// a lower, stronger light than the default so walls and roofs shade differently (depth cue); affects extrusions only
map.setLight({ anchor: "viewport", color: "#ffffff", intensity: 0.6, position: [1.2, 200, 35] });

const SEL = ["boolean", ["feature-state", "selected"], false];
map.addLayer({ id: "streets", type: "line", source: "streets", layout: { "line-cap": "round", "line-join": "round" },
  paint: {
    "line-color": ["case", SEL, "#7d5250",   // selected: muted; its stranded streets are drawn bright red on top (cut)
      ["match", ["get", "status"], "red", COLORS.red, "amber", COLORS.amber, "green", COLORS.green, COLORS.not_assessed]],
    "line-width": ["interpolate", ["linear"], ["zoom"], 11, ["case", SEL, 2.2, 1.0], 16, ["case", SEL, 5, 2.6]],
    // red streets more opaque where more buildings could be cut off; classification itself is unchanged
    "line-opacity": ["case", SEL, 1, ["match", ["get", "status"],
      "red", ["interpolate", ["linear"], ["get", "worst_cut"], 30, 0.6, 200, 0.95], "not_assessed", 0.55, 0.85]] } });
map.addLayer({ id: "cut", type: "line", source: "cut", filter: ["==", ["get", "nid"], -1],
  layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#ff3b30", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 6.5] } });
// Selected worst sampled blockage = the engine's own 50 m-radius disc from the scan response (no geometry computed here).
// Drawn above the road layers: a dark gap so the road portions inside it read as unavailable, a hatch that marks the
// area as blocked, and a dashed boundary. Buildings (2D and 3D) are drawn below, so they never hide it.
{
  const n = 16, px = new Uint8Array(n * n * 4);                    // diagonal hatch tile, generated locally (offline)
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const on = (x + y) % 8 < 2, i = (y * n + x) * 4;
    px[i] = px[i + 1] = px[i + 2] = 255; px[i + 3] = on ? 150 : 0;
  }
  map.addImage("hatch", { width: n, height: n, data: px });
}
map.addLayer({ id: "blocked", type: "fill", source: "blocked", filter: ["==", ["get", "nid"], -1],
  paint: { "fill-color": "#07090c", "fill-opacity": 0.82 } });
map.addLayer({ id: "blocked-hatch", type: "fill", source: "blocked", filter: ["==", ["get", "nid"], -1],
  paint: { "fill-pattern": "hatch", "fill-opacity": 0.55 } });
map.addLayer({ id: "blocked-edge", type: "line", source: "blocked", filter: ["==", ["get", "nid"], -1],
  paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 16, 4],
           "line-dasharray": [2, 1.2] } });
// choke markers: the top-ranked ones stay as entry points; the selected one shrinks to a centre dot inside its disc
const CHOKE_R = (sel) => ["interpolate", ["linear"], ["zoom"], 11, ["case", sel, 2, 4], 16, ["case", sel, 3.5, 9]];
map.addLayer({ id: "choke", type: "circle", source: "choke", paint: {
  "circle-color": "#ffffff", "circle-stroke-color": "#ff3b30", "circle-stroke-width": 2,
  "circle-radius": CHOKE_R(false) } });
// Blockage the user placed (probe): geometry comes from the server (the same 50 m circle evaluate_block used, and the
// streets it strands). Cyan edge = "you placed it"; the scan's worst sampled blockage keeps the white edge.
map.addSource("probe", { type: "geojson", data: empty });
map.addSource("probe-preview", { type: "geojson", data: empty });   // drag preview only: never analysed
map.addSource("blk-hit", { type: "geojson", data: empty });          // grab handle at the displayed blockage centre
const KIND = (k) => ["==", ["get", "kind"], k];
map.addLayer({ id: "probe-cut", type: "line", source: "probe", filter: KIND("cut"), layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#ff3b30", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 6.5] } });
map.addLayer({ id: "probe-gap", type: "fill", source: "probe", filter: KIND("disc"), paint: { "fill-color": "#07090c", "fill-opacity": 0.82 } });
map.addLayer({ id: "probe-hatch", type: "fill", source: "probe", filter: KIND("disc"), paint: { "fill-pattern": "hatch", "fill-opacity": 0.55 } });
map.addLayer({ id: "probe-edge", type: "line", source: "probe", filter: KIND("disc"),
  paint: { "line-color": "#7fdcff", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 16, 4], "line-dasharray": [2, 1.2] } });
map.addLayer({ id: "probe-dot", type: "circle", source: "probe", filter: KIND("centre"),
  paint: { "circle-color": "#7fdcff", "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2, 16, 3.5] } });
map.addLayer({ id: "pv-gap", type: "fill", source: "probe-preview", paint: { "fill-color": "#07090c", "fill-opacity": 0.7 } });
map.addLayer({ id: "pv-hatch", type: "fill", source: "probe-preview", paint: { "fill-pattern": "hatch", "fill-opacity": 0.45 } });
map.addLayer({ id: "pv-edge", type: "line", source: "probe-preview",
  paint: { "line-color": "#7fdcff", "line-width": 2, "line-opacity": 0.9, "line-dasharray": [1, 1] } });
map.addLayer({ id: "blk-hit", type: "circle", source: "blk-hit",
  paint: { "circle-radius": 20, "circle-color": "#ffffff", "circle-opacity": 0.01 } });
const PROBE_LAYERS = ["probe-cut", "probe-gap", "probe-hatch", "probe-edge", "probe-dot", "pv-gap", "pv-hatch", "pv-edge", "blk-hit"];
const BLOCKED_LAYERS = ["blocked", "blocked-hatch", "blocked-edge"];
const setBlockedFilter = (nid) => BLOCKED_LAYERS.forEach((l) => map.setFilter(l, ["==", ["get", "nid"], nid]));

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
  paint: { "fill-color": "#3b82f6", "fill-opacity": 0.55 } }, "bld-fill");
map.addLayer({ id: "fl-water-line", type: "line", source: "fl-water", layout: { visibility: "none" },
  paint: { "line-color": "#93c5fd", "line-width": 1.2, "line-opacity": 0.9 } }, "bld-fill");
map.addLayer({ id: "fl-cut", type: "line", source: "fl-cut", layout: { visibility: "none" },
  paint: { "line-color": "#ff7a45", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 4.5] } });
map.addLayer({ id: "fl-roads", type: "line", source: "fl-roads", layout: { visibility: "none", "line-cap": "round" },
  paint: { "line-color": "#22d3ee", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2, 16, 6] } });
const FLOOD_LAYERS = ["fl-cover", "fl-water", "fl-water-line", "fl-cut", "fl-roads"];
const SCAN_OVERLAYS = ["choke", "blocked", "blocked-hatch", "blocked-edge", "cut", ...PROBE_LAYERS];   // hidden in scenario modes
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

// ---------- analytics panel building blocks: display only, every number is an audited API field ----------
const N = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString());
const pairTxt = (o, m) => `OSM ${N(o)} · Microsoft ${N(m)}`;
const INDEP = `<div class="indep">OpenStreetMap and Microsoft are independent footprint estimates, never added together.</div>`;
const metric = (v, label, cls = "", sub = "", s = null) => `<div class="m ${cls}">
  <div class="mv"${s ? ` data-k="${s.k}" data-v="${s.v}" data-d="${s.d || 0}" data-u="${s.u || ""}"` : ""}>${v}</div>
  <div class="ml">${label}</div>${sub ? `
  <div class="msub">${sub}</div>` : ""}</div>`;
// two independent estimates side by side, each bar scaled to the larger of the two (never summed)
function srcBars(o, m, head) {
  const mx = Math.max(o, m, 1), row = (l, v) => `<div class="sb"><span class="sbl">${l}</span>
    <span class="sbt"><i style="width:${(v / mx) * 100}%"></i></span><span class="sbn">${N(v)}</span></div>`;
  return `<div class="blk"><div class="bh">${head}</div>${row("OpenStreetMap", o)}${row("Microsoft", m)}${INDEP}</div>`;
}
// status distribution per source: one stacked bar per source (each is 100% of that source) + a small table
function distBlock(head, rows, c, indep = true) {
  const bar = (src) => {
    const tot = rows.reduce((a, r) => a + c[r.key][src], 0) || 1;
    return `<div class="dist">${rows.map((r) => c[r.key][src]
      ? `<i class="${r.cls}" style="width:${(c[r.key][src] / tot) * 100}%"></i>` : "").join("")}</div>`;
  };
  return `<div class="blk"><div class="bh">${head}</div>
    <div class="dsrc"><span>OSM</span>${bar("osm")}</div><div class="dsrc"><span>Microsoft</span>${bar("ms")}</div>
    <table class="dt"><tr><th></th><th>OSM</th><th>Microsoft</th></tr>${rows.map((r) =>
      `<tr><td><span class="k ${r.cls}"></span>${r.label}</td><td>${N(c[r.key].osm)}</td><td>${N(c[r.key].ms)}</td></tr>`).join("")}</table>
    ${indep ? INDEP : ""}</div>`;
}
const STATUS_TXT = { red: "One blocked road area cuts off 30+ mapped buildings",
  amber: "One blocked road area cuts off 1–29 mapped buildings",
  green: "None of the sampled blockages cuts anyone off", not_assessed: "Too close to the edge of our road data to judge fairly" };
const STATUS_TAG = { red: "RED", amber: "AMBER", green: "GREEN", not_assessed: "NOT ASSESSED" };

function panelHtml(p) {
  const na = p.status === "not_assessed";
  const affected = na
    ? metric("—", "affected: not assessed", "na")
    : metric(N(p.worst_cut), "lose access if the worst sampled blockage occurs", p.worst_cut > 0 ? "cut" : "",
             pairTxt(p.worst_cut_osm, p.worst_cut_ms), { k: "nb-cut", v: p.worst_cut });
  return `<div class="kicker">Access vulnerability</div>
    <div class="stag ${p.status}"><b>${STATUS_TAG[p.status]}</b> ${STATUS_TXT[p.status]}</div>
    <div class="mgrid3">
      ${metric(N(p.homes), "mapped buildings in this neighbourhood", "", pairTxt(p.homes_osm, p.homes_ms))}
      ${affected}
      ${metric(N(p.gateways), `connection${p.gateways === 1 ? "" : "s"} to major roads`)}
    </div>
    ${!na && p.worst_cut > 0 ? `<div class="causal">
      <div><span class="sw blk"></span><span><b>Blocked road area</b> (hatched circle, 100 m across): roads inside it are unavailable</span></div>
      <div><span class="sw rd"></span><span><b>Streets in bright red</b> lose their way out: every route to a major road passes through it</span></div>
      <div><span class="sw bo"></span><span><b>Orange mapped buildings</b> on those streets lose access; teal ones keep it</span></div>
      <div class="fine">The worst of the sampled blockages, not an absolute worst case. Drag the hatched circle along
        the roads to test a blockage you choose.</div></div>` : ""}
    ${srcBars(p.homes_osm, p.homes_ms, "Mapped buildings: source comparison")}`;
}

function select(nid) {
  clearProbe();                            // a placed blockage belongs to one neighbourhood; never carried over
  if (floodOn) exitFlood(false);           // selecting a neighbourhood returns to the vulnerability view
  if (fireOn) exitFire(false);
  if (selected !== null) map.setFeatureState({ source: "streets", id: selected }, { selected: false });
  selected = nid;
  const f = scanData.neighbourhoods.features.find((f) => f.id === nid);
  const panel = document.getElementById("panel");
  if (!f) { panel.classList.add("hidden"); map.setPaintProperty("streets", "line-opacity", STREET_OPACITY); updateChokeFilter(); syncMode(); return; }
  map.setFeatureState({ source: "streets", id: nid }, { selected: true });
  map.setPaintProperty("streets", "line-opacity", ["case", SEL, 0.95, 0.3]);   // other streets recede while selected
  panel.className = `card ${f.properties.status}`;
  panel.innerHTML = panelHtml(f.properties) + `<div id="bldInfo"></div>`;
  settleIn(panel);
  showBuildings(nid, f.properties);
  map.setFilter("cut", ["==", ["get", "nid"], nid]);
  setBlockedFilter(nid);
  renderBlockage();
  if (f.properties.status !== "not_assessed") loadProbeRoads(current, nid);
  const b = new maplibregl.LngLatBounds();
  const add = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(add));
  add(f.geometry.coordinates);
  if (view === "3d") frame3d(nid, dur(800));
  else map.fitBounds(b, { padding: 60, maxZoom: 16, duration: dur(800), bearing: map.getBearing() });
  const ch = scanData.chokepoints.features.find((x) => x.properties.nid === nid);
  if (ch) attentionAfterMove(ch.geometry.coordinates);   // one ring once the camera has arrived
  syncMode();
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
               : probeShown() && probe.area === bldShown.area ? probe.data.ids[bldShown.src]
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
  const s = bldCats.sources, p = bldCats.props;
  const cnt = (k) => ({ osm: s.osm[k].length, ms: s.ms[k].length });
  const btn = (src) => `<button data-src="${src}" class="${src === bldShown.src ? "on" : ""}">${SRC_LABEL[src]} (${src === "osm" ? p.homes_osm : p.homes_ms})</button>`;
  el.innerHTML = `${bldCats.choke ? distBlock("Under the worst sampled blockage", [
      { cls: "cut", label: "Lose access", key: "cut" },
      { cls: "inside", label: "Inside the blocked area", key: "inside" },
      { cls: "retain", label: "Retain access", key: "retain" }], { cut: cnt("cut"), inside: cnt("inside"), retain: cnt("retain") }, false) : ""}
    <div class="bldsrc">Footprints on the map: ${btn("osm")}${btn("ms")}</div>
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
  renderBuildingInfo();                        // the counts come from the API: show them before the footprints finish loading
  // default to the source that gives the headline count (the higher of the two), unless the viewer picked one
  const src = bldPinned || (props.homes_ms > props.homes_osm ? "ms" : "osm");
  if (bldShown.src !== src || bldShown.area !== area) await loadBuildings(area, src);
  applyBuildingCats();
}

function updateChokeFilter() {
  // only the top-ranked choke points (and the selected one) are drawn, to avoid a wall of markers
  const probing = probeShown();
  map.setFilter("choke", ["all", ["any", ["all", ["!=", ["get", "rank"], null], ["<=", ["get", "rank"], SHOW_TOP_CHOKES]],
                                  ["==", ["get", "nid"], selected ?? -1]],
                          ["!=", ["get", "nid"], probing ? selected : -2]]);
  map.setPaintProperty("choke", "circle-radius", CHOKE_R(["==", ["get", "nid"], selected ?? -1]));
}

function renderOverview() {
  const el = $("overview"), c = scanData.summary.counts, n = (k) => c[k] || 0;
  const total = n("red") + n("amber") + n("green") + n("not_assessed"), assessed = total - n("not_assessed");
  const ranked = scanData.neighbourhoods.features.filter((f) => f.properties.rank !== null)
    .sort((a, b) => a.properties.rank - b.properties.rank);
  const lead = ranked.length ? ranked[0].properties : null;
  const seg = ["red", "amber", "green", "not_assessed"].map((k) => n(k)
    ? `<i class="s-${k}" style="width:${(n(k) / (total || 1)) * 100}%"></i>` : "").join("");
  const leg = [["red", "30+ cut off"], ["amber", "1–29 cut off"], ["green", "none cut off"], ["not_assessed", "not assessed"]]
    .map(([k, l]) => `<div><span class="k s-${k}"></span><b>${n(k)}</b> ${l}</div>`).join("");
  const top = ranked.slice(0, 5).map((f) => {
    const q = f.properties;
    return `<button class="toprow" data-nid="${f.id}"><span class="tr">#${q.rank}</span>
      <span class="tb"><i style="width:${(q.worst_cut / Math.max(q.homes, 1)) * 100}%"></i></span>
      <span class="tn"><b>${N(q.worst_cut)}</b> of ${N(q.homes)}</span></button>`;
  }).join("");
  el.innerHTML = `<div class="kicker">Area overview</div>
    <div class="big">${areas[current].label}</div>
    <div class="mgrid2">
      ${metric(N(total), "neighbourhoods of 30+ mapped buildings")}
      ${metric(N(assessed), "assessed", "", `${N(n("not_assessed"))} not assessed (edge of road data)`)}
    </div>
    <div class="blk"><div class="bh">Vulnerability status</div><div class="dist tall">${seg}</div><div class="leg">${leg}</div></div>
    ${lead ? `<div class="blk"><div class="bh">Largest sampled blockage impact</div>
      ${metric(N(lead.worst_cut), `mapped buildings cut off by one blocked road area (of ${N(lead.homes)} in that neighbourhood)`,
               "cut", pairTxt(lead.worst_cut_osm, lead.worst_cut_ms))}</div>` : ""}
    <div class="blk"><div class="bh">Most vulnerable neighbourhoods</div>
      <div class="fine">Mapped buildings cut off by the worst sampled blockage, of the neighbourhood total. Click to open.</div>
      ${top || `<div class="fine">None.</div>`}</div>`;
  el.querySelectorAll(".toprow").forEach((b) => (b.onclick = () => select(+b.dataset.nid)));
}

async function loadArea(name) {
  if (floodOn) exitFlood(false);          // switching areas always clears the flood scenario
  if (fireOn) exitFire(false);            // ...and the fire scenario
  // clear the old area's building categories and footprints NOW, not when the new footprints arrive
  bldCats = null; bldPinned = null;
  map.removeFeatureState({ source: "bld" }); bldStateN = 0;
  bldGen++; bldAppliedNs = null;                 // any in-flight footprint load for the old area becomes stale
  map.getSource("bld").setData(empty); bldShown = { area: null, src: null, ready: false };
  map.getSource("water").setData(empty);
  current = name;
  syncMode();
  if (typeof clearMitigation === "function") clearMitigation();
  document.querySelectorAll("#areas button").forEach((b) => b.classList.toggle("on", b.dataset.area === name));
  const [scan, roads, boundary] = await Promise.all(
    ["scan", "roads", "boundary"].map((k) => fetch(`/api/${name}/${k}`).then((r) => r.json())));
  if (current !== name) return;
  scanData = scan;
  loadBuildings(name, "osm");   // subtle background footprints; loads after the roads, never blocks them
  fetch(`/api/${name}/water`).then((r) => r.json())
    .then((w) => { if (current === name) map.getSource("water").setData(w); }).catch(() => {});   // context only
  map.getSource("roads").setData(roads);
  map.getSource("boundary").setData(boundary);
  map.getSource("nb").setData(scan.neighbourhoods);
  map.getSource("streets").setData(scan.streets);
  map.getSource("cut").setData(scan.cut_roads);
  map.getSource("blocked").setData(scan.blocked);
  map.getSource("choke").setData(scan.chokepoints);
  selected = null;
  map.setPaintProperty("streets", "line-opacity", STREET_OPACITY);
  document.getElementById("panel").classList.add("hidden");
  map.setFilter("cut", ["==", ["get", "nid"], -1]);
  setBlockedFilter(-1);
  renderBlockage();
  renderOverview();
  renderSummary();
  syncMode();
  for (const k in shownNum) delete shownNum[k];          // numbers never "settle" across areas
  attention(null);                                       // no ring carried across areas
  if (firstFrame) { firstFrame = false; map.jumpTo({ center: areas[name].center, zoom: areas[name].zoom }); }
  else map.flyTo({ center: areas[name].center, zoom: areas[name].zoom, duration: dur(900) });
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
  clearProbe();
  mitGen++; mitKey = null;
  drawing = false; clicks = [];
  setProposal([]);
  ["mit-blocked", "mit-cut"].forEach((s) => map.getSource(s).setData(empty));
  document.getElementById("mitig").classList.add("hidden");
  document.getElementById("hint").classList.add("hidden");
  document.getElementById("clearBtn").classList.add("hidden");
  document.getElementById("drawBtn").classList.remove("on");
  map.getCanvas().style.cursor = "";
  if (current) syncMode();
}

function startDrawing() {
  if (floodOn || fireOn) return;           // the road test belongs to the vulnerability view, not a scenario mode
  clearMitigation();
  drawing = true;
  document.getElementById("drawBtn").classList.add("on");
  document.getElementById("hint").classList.remove("hidden");
  document.getElementById("clearBtn").classList.remove("hidden");
  map.getCanvas().style.cursor = "crosshair";
  syncMode();
}

function mitigHtml(r) {
  if (!r.ok) return `<div class="kicker">Mitigation test</div><div class="cut">${r.message}</div>`;
  const b = r.before, a = r.after;
  const road = `<div class="conn"><b>${N(r.length_m)} m</b> conceptual straight-line connection
    <div class="fine">Construction feasibility not assessed. Each end joins the nearest existing road junction or road end.</div></div>`;
  if (r.unavailable) return `<div class="kicker">Mitigation test</div><div class="big">Result unavailable</div>
    ${metric(N(b.worst_cut), "lose access under the original worst sampled blockage", "cut", pairTxt(r.before_cut_src?.osm, r.before_cut_src?.ms))}
    <div class="cut">${r.message}</div>${road}`;
  const w = (v) => `${(v / Math.max(b.worst_cut, 1)) * 100}%`;
  const residual = a.worst_cut > 0
    ? metric(N(a.worst_cut), "mapped buildings affected by the worst sampled blockage with the connection (can be a different road area; shown in blue)",
             "cut", pairTxt(a.worst_cut_src?.osm, a.worst_cut_src?.ms))
    : metric("0", "none of the sampled blockages cuts these mapped buildings off with the connection", "retain");
  return `<div class="kicker">Mitigation test</div>
    <div class="big">${N(r.regained)} of ${N(b.worst_cut)} regain access under this blockage</div>
    <div class="ba">
      <div class="bacol">${metric(N(b.worst_cut), "BEFORE: lose access under this blockage", "cut", pairTxt(r.before_cut_src.osm, r.before_cut_src.ms))}</div>
      <div class="baarrow">→</div>
      <div class="bacol">${metric(N(r.same_block_cut), "AFTER: remain without access under this blockage", r.same_block_cut > 0 ? "cut" : "retain",
                                  pairTxt(r.same_block_cut_src.osm, r.same_block_cut_src.ms), { k: "mit-after", v: r.same_block_cut })}</div>
    </div>
    <div class="babars">
      <div class="dsrc"><span>Before</span><div class="dist"><i class="cut" style="width:100%"></i></div></div>
      <div class="dsrc"><span>After</span><div class="dist"><i class="cut" style="width:${w(r.same_block_cut)}"></i><i class="retain" style="width:${w(r.regained)}"></i></div></div>
    </div>
    ${metric(N(r.regained), "regain access under this same blockage", "retain", pairTxt(r.regained_src.osm, r.regained_src.ms))}
    <div class="blk resid"><div class="bh">Residual vulnerability</div>${residual}
      <div class="fine">A separate result: the new worst sampled blockage for the same ${N(b.homes)} mapped buildings.
        With the connection, the worst sampled blockage cuts off ${N(a.worst_cut)}.</div></div>
    ${road}`;
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
  if (r.ok && !r.unavailable) settleIn(box, { "mit-after": r.before.worst_cut });   // e.g. 234 -> 1
  box.scrollIntoView({ block: "nearest" });
  box.dataset.state = r.ok ? "done" : "error";   // used by the scripted checks
  if (!r.ok) { setProposal(pair.map(pt)); return; }
  setProposal([r.road, pt(r.road.geometry.coordinates[0]), pt(r.road.geometry.coordinates[1])]);
  if (r.after_geo && !r.unavailable) {
    map.getSource("mit-blocked").setData(r.after_geo.blocked);
    map.getSource("mit-cut").setData(r.after_geo.cut_roads);
  }
  if (selected !== r.before.nid) select(r.before.nid);
  syncMode();
}

map.on("click", (e) => {
  if (!drawing) return;
  clicks.push([e.lngLat.lng, e.lngLat.lat]);
  setProposal(clicks.map(pt));
  syncMode();
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
  return `<div class="kicker">Flood scenario</div>
    <div class="nopredict">This is not a flood prediction.</div>
    <div class="fine">Supplied river level ${s.gauge_m.toFixed(2)} m (gauge)</div>
    <div class="wkey"><span><span class="sw inund"></span>Supplied inundation (this scenario)</span>
      <span><span class="sw water"></span>Mapped water (context only)</span></div>
    <div class="mgrid2">
      ${metric(`${s.gauge_m.toFixed(2)} m`, "supplied gauge level (CGVD28, station 01AK003)", "flood")}
      ${metric(`~${s.water_cgvd2013_m.toFixed(2)} m`, "project CGVD2013 conversion", "flood", `offset ${s.offset_m} m`)}
      ${metric(`${s.roads_affected_km} km`, "road portions affected", "froad", "", { k: "fl-km", v: s.roads_affected_km, d: 2, u: " km" })}
      ${metric(N(Math.max(c.lose_access.osm, c.lose_access.ms)), "outside the inundation, lose access", "cut", pairTxt(c.lose_access.osm, c.lose_access.ms),
               { k: "fl-cut", v: Math.max(c.lose_access.osm, c.lose_access.ms) })}
    </div>
    ${distBlock("Mapped buildings by status", [
      { cls: "inside", label: "Centre inside supplied inundation", key: "inside" },
      { cls: "cut", label: "Outside inundation, loses access", key: "lose_access" },
      { cls: "retain", label: "Retains access", key: "keep_access" }], c)}
    <details class="src"><summary>Model assumptions</summary><ul class="assume">
      <li>The river level is your input; the water is a flat surface at ${s.water_cgvd2013_m.toFixed(2)} m (CGVD2013)
        connected to the river channel. No hydraulic flow, river slope, flood defences or drainage.</li>
      <li>Gauge height converted with ${s.offset_m} m (NRCan conversion grid). Consistent with 2008 observations but not
        proven; historical datum conversions carry some uncertainty.</li>
      <li>Terrain is the 2024 NRCan HRDEM survey, which may not match 2008 ground (e.g. later regrading).</li>
      <li>Elevation data covers the river corridor only (dashed outline); roads outside it are treated as dry.</li>
      <li>Bridges are treated as passable.</li>
      <li>Buildings are classified by their centre; buildings at the water's edge may partly overlap it. Access counts cover
        assessed neighbourhoods of 30+ mapped buildings (as in the vulnerability scan); "centre inside" covers every
        mapped building in the water area. The vulnerability classification is not changed.</li></ul></details>`;
}

function renderFloodKey() {
  const el = $("floodBld");
  if (!el || !floodData) return;
  const btn = (src) => `<button data-src="${src}" class="${src === bldShown.src ? "on" : ""}">${SRC_LABEL[src]}</button>`;
  el.innerHTML = `<div class="bldsrc">Footprints on the map: ${btn("osm")}${btn("ms")}</div>`;
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
  settleIn(out);
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
    $("floodCtl").classList.remove("hidden");
    syncMode();
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
  ["fl-water", "fl-roads", "fl-cut"].forEach((l) => map.getSource(l).setData(empty));
  FLOOD_LAYERS.forEach((l) => map.setLayoutProperty(l, "visibility", "none"));
  SCAN_OVERLAYS.forEach((l) => map.setLayoutProperty(l, "visibility", "visible"));
  map.setPaintProperty("streets", "line-opacity", STREET_OPACITY);
  $("drawBtn").disabled = false;
  $("floodCtl").classList.add("hidden");
  syncMode();
  $("floodOut").innerHTML = ""; delete $("floodOut").dataset.state;
  delete shownNum["fl-km"]; delete shownNum["fl-cut"];
  const saved = floodSavedBld; floodSavedBld = null;
  if (restoreSelection && saved) {               // restore the pre-flood footprint source and the viewer's pin
    bldPinned = saved.pinned;
    if (saved.src && bldShown.src !== saved.src) loadBuildings(current, saved.src);   // applies categories on arrival
  }
  applyBuildingCats();                           // no-op until the (possibly restored) source is ready
  const sel = floodSavedSel; floodSavedSel = null;
  if (restoreSelection && sel !== null) select(sel);
}

$("gauge").oninput = (e) => updateGaugeReadout(e.target.value);
$("gauge").onchange = (e) => floodOn && enterFlood(e.target.value);  // on release; an explicit level supersedes older inits
document.querySelectorAll("#floodCtl .presets button").forEach((b) => (b.onclick = () => enterFlood(b.dataset.g)));

// ---------- fire scenario (Tantallon): road access under a SUPPLIED affected area; no fire-spread prediction ----------
const km = (m) => `${(Math.round(m / 10) / 100).toFixed(2)} km`;   // nearest 10 m first: (0.955).toFixed(2) is "0.95"
const stat = (cls, label, c) => `<div class="fs ${cls}"><span class="n">${Math.max(c.osm, c.ms).toLocaleString()}</span>
  <span class="l">${label}</span><span class="src">OSM ${c.osm.toLocaleString()} · Microsoft ${c.ms.toLocaleString()}</span></div>`;
const FIRE_KEY = `<div class="firekey">
  <div><span class="k zone"></span>Supplied affected area</div>
  <div><span class="k road"></span>Road portions within the supplied affected area</div>
  <div><span class="k cut"></span>Outside the area but loses access (buildings and roads)</div>
  <div><span class="k inside"></span>Building centre inside the supplied area</div>
  <div><span class="k retain"></span>Retains access</div></div>`;

function fireHtml(s) {
  const c = s.counts, hist = s.kind === "historical";
  const head = hist
    ? `<div class="kicker">2023 mapped burned-area perimeter</div><div class="big">Mapped 2023 fire perimeter</div>
       <div class="mgrid2">
         ${metric(`${s.perimeter.mapped_ha} ha`, "published NBAC area", "fire", `fire starting ${s.perimeter.start_date}`)}
         ${metric(`${s.roads_affected_km} km`, "road portions within the mapped area", "froad-f", "", { k: "fi-km", v: s.roads_affected_km, d: 2, u: " km" })}
       </div>`
    : `<div class="kicker">Supplied affected area</div><div class="big">Supplied hypothetical affected area</div>
       <div class="mgrid2">
         ${metric(`${s.radius_m.toLocaleString()} m`, "supplied affected radius", "fire", `${s.zone_ha} ha · your input, not a predicted fire extent`)}
         ${metric(`${s.roads_affected_km} km`, "road portions within the supplied affected area", "froad-f", "", { k: "fi-km", v: s.roads_affected_km, d: 2, u: " km" })}
       </div>`;
  const ents = hist
    ? `<div class="fnote">Neither Westwood Hills entrance lies inside the mapped perimeter (about
       ${s.westwood_entrances.map((e) => e.distance_m).sort((a, b) => a - b).map(km).join(" and ")} away).</div>
       <div class="fine">Model result using the retrospective mapped perimeter as a supplied affected area. NBAC is a
         retrospective burned-area outline, not a time-resolved record of how the fire progressed on May 28.</div>` : "";
  return `${head}
    <div class="nopredict">This tool does not predict fire spread.</div>
    ${distBlock("Mapped buildings by status", [
      { cls: "inside", label: "Centre inside the area", key: "inside" },
      { cls: "cut", label: "Outside the area, loses access", key: "lose_access" },
      { cls: "retain", label: "Retains access", key: "keep_access" }], c)}
    ${ents}
    ${FIRE_KEY}
    <details class="src"><summary>How this is counted</summary>
      Roads are treated as impassable only within the supplied area; no wind, weather, fire behaviour, traffic or
      evacuation time is modelled. Buildings are classified by their centre. Access counts cover assessed
      neighbourhoods of 30+ mapped buildings (as in the vulnerability scan); the centre-inside count covers every
      mapped building in the area.${hist ? ` Area: the published NBAC figure (${s.perimeter.mapped_ha} ha)
      is measured on the curved Earth; this tool measures the same outline on its flat map as ${s.zone_ha} ha
      (about 0.1% larger from map distortion this far from New Brunswick). The outline is unchanged.` : ""}</details>`;
}

function renderFireKey() {
  const el = $("fireBld");
  if (!el || !fireData) return;
  const btn = (src) => `<button data-src="${src}" class="${src === bldShown.src ? "on" : ""}">${SRC_LABEL[src]}</button>`;
  el.innerHTML = `<div class="bldsrc">Footprints on the map: ${btn("osm")}${btn("ms")}</div>`;
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
  settleIn(out);
  out.dataset.state = "done";
  syncMode();
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
  syncMode();
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
  $("fireCtl").classList.add("hidden");
  syncMode();
  $("fireOut").innerHTML = ""; delete $("fireOut").dataset.state;
  delete shownNum["fi-km"];
  const saved = fireSavedBld; fireSavedBld = null;
  if (restoreSelection && saved) {
    bldPinned = saved.pinned;
    if (saved.src && bldShown.src !== saved.src) loadBuildings(current, saved.src);
  }
  applyBuildingCats();
  const sel = fireSavedSel; fireSavedSel = null;
  if (restoreSelection && sel !== null) select(sel);
}


// ---------- motion helpers (presentation only) ----------
// Headline settling: the element already contains the FINAL text; if motion is on and a previous value for the same
// headline is known, the text counts from it to the final value over ~380 ms. A newer render of the same headline
// (or removal of the element) cancels the older count immediately; a timer guarantees the final text even if frames stall.
const shownNum = {}, settleTok = {};
let firstFrame = true;
function settleIn(root, seeds = {}) {
  root.querySelectorAll(".mv[data-k]").forEach((el) => {
    const k = el.dataset.k, to = +el.dataset.v, dec = +el.dataset.d || 0, unit = el.dataset.u || "";
    const from = k in seeds ? seeds[k] : shownNum[k];
    shownNum[k] = to;
    const tok = (settleTok[k] = (settleTok[k] || 0) + 1);
    if (!MOTION || from === undefined || from === null || !Number.isFinite(from) || from === to) return;
    const fmt = (v) => (dec ? v.toFixed(dec) : Math.round(v).toLocaleString()) + unit, final = el.textContent;
    const t0 = performance.now(), D = 380;
    const live = () => settleTok[k] === tok && el.isConnected;
    const step = (now) => {
      if (!live()) return;
      const p = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - p, 3);
      el.textContent = p < 1 ? fmt(from + (to - from) * e) : final;
      if (p < 1) requestAnimationFrame(step);
    };
    el.textContent = fmt(from);
    requestAnimationFrame(step);
    setTimeout(() => { if (live()) el.textContent = final; }, D + 150);
  });
}
// One-shot attention ring (~650 ms, CSS), lying on the ground plane; never repeats, never loops.
let attnMarker = null, attnTok = 0;
function attention(ll) {
  attnTok++;
  if (attnMarker) { attnMarker.remove(); attnMarker = null; }
  if (!MOTION || !ll) return;
  const el = document.createElement("div");
  el.className = "attn-ring";
  const m = new maplibregl.Marker({ element: el, pitchAlignment: "map", rotationAlignment: "map" }).setLngLat(ll).addTo(map);
  attnMarker = m;
  const done = () => { if (attnMarker === m) { m.remove(); attnMarker = null; } };
  el.addEventListener("animationend", done, { once: true });
  setTimeout(done, 750);                               // fallback if animationend never fires
}
function attentionAfterMove(ll) {   // after the camera arrives (moveend), unless something newer happened
  const tok = ++attnTok;
  if (!MOTION) return;
  map.once("moveend", () => { if (tok === attnTok) attention(ll); });
}

// ---------- user-placed blockage (probe): drag the circle along the roads, release to test ----------
// Drag = visual only (local snap preview, no request, no state change). Release = ONE request. Every drop, drag start,
// reset, selection change, area switch, scenario entry and mitigation start bumps probeGen; a response is applied only
// if it is still the newest request for the same area + neighbourhood in vulnerability mode.
let probe = null, probeGen = 0, probeState = "none", probeMsg = "", drag = null;
let probeRoads = null;       // {area, nid, data}: the server's eligible roads for the selected neighbourhood (preview only)
let previewN = 0;            // features currently in the preview source (mirrors setPreview)
function setPreview(data) { previewN = data.features.length; map.getSource("probe-preview").setData(data); }
// fetched on selection (never during a drag); the preview suggests only positions the server will accept
async function loadProbeRoads(area, nid) {
  probeRoads = null;
  try {
    const r = await fetch(`/api/${area}/nb/${nid}/probe-roads`);
    if (!r.ok) return;
    const data = await r.json();
    if (current === area && selected === nid) probeRoads = { area, nid, data };
  } catch { /* preview falls back to the neighbourhood's own streets (a subset of the eligible set) */ }
}
const PROBE_SNAP_M = 60;                              // same tolerance as the server (egress/probe.py SNAP_TOL_M)
function probeShown() { return !!(probe && probe.area === current && probe.nid === selected && !floodOn && !fireOn); }
function selProps() {
  const f = scanData && selected !== null && scanData.neighbourhoods.features.find((x) => x.id === selected);
  return f ? f.properties : null;
}
function canProbe() {
  const p = selProps();
  return !!(p && p.status !== "not_assessed" && !floodOn && !fireOn && !drawing && proposalCount === 0);
}
// local metric frame for the preview (display only; the server does the authoritative snap in the analysis CRS)
function localFrame(lat0) { const kx = 111320 * Math.cos((lat0 * Math.PI) / 180), ky = 110540; return { kx, ky }; }
function snapPreview(ll) {
  if (!drag) return null;
  const { kx, ky } = drag.frame, px = (ll.lng - drag.o[0]) * kx, py = (ll.lat - drag.o[1]) * ky;
  let best = null, bd = Infinity;
  for (const [ax, ay, bx, by] of drag.segs) {
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
    const qx = ax + t * dx, qy = ay + t * dy, d = Math.hypot(px - qx, py - qy);
    if (d < bd) { bd = d; best = [qx, qy]; }
  }
  return best && { ll: [drag.o[0] + best[0] / kx, drag.o[1] + best[1] / ky], d: bd };
}
function discAt(ll) {   // preview circle, 50 m radius (drawn only; the analysed circle comes from the server)
  const { kx, ky } = localFrame(ll[1]), ring = [];
  for (let k = 0; k <= 64; k++) { const a = (k / 64) * 2 * Math.PI; ring.push([ll[0] + (50 * Math.cos(a)) / kx, ll[1] + (50 * Math.sin(a)) / ky]); }
  return fc([{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } }]);
}
function blockageCentre() {   // centre of the blockage currently shown for the selected neighbourhood
  if (probeShown()) return probe.data.centre;
  const c = scanData && scanData.chokepoints.features.find((x) => x.properties.nid === selected);
  return c ? c.geometry.coordinates : null;
}
function renderBlockage() {
  const shown = probeShown(), nid = selected ?? -1;
  map.getSource("probe").setData(shown ? probe.data.geo : empty);
  setBlockedFilter(shown ? -1 : nid);
  map.setFilter("cut", ["==", ["get", "nid"], shown ? -1 : nid]);
  updateChokeFilter();
  const c = !drag && canProbe() ? blockageCentre() : null;
  map.getSource("blk-hit").setData(c ? fc([pt(c)]) : empty);
  renderProbeCard();
}
function renderProbeCard() {
  const el = $("probeCard"), badge = $("blkBadge"), p = selProps();
  const vis = !!p && !floodOn && !fireOn && (probeState !== "none" || probeShown());
  badge.classList.toggle("hidden", !p || floodOn || fireOn || p.status === "not_assessed" || proposalCount > 0);
  badge.className = badge.className.replace(/ ?probe-on/, "") + (probeShown() || drag ? " probe-on" : "");
  badge.textContent = drag ? (drag.far ? "Too far from a road: release to cancel" : "Release to test this blockage")
    : probeState === "pending" ? "Testing…" : probeShown() ? "Map shows: blockage you placed" : "Map shows: worst sampled blockage";
  el.classList.toggle("hidden", !vis);
  el.dataset.state = probeState;
  if (!vis) { el.innerHTML = ""; return; }
  const worst = `<div class="fine">Worst sampled blockage for this neighbourhood (scan finding): <b>${N(p.worst_cut)}</b>
    <span class="src">(${pairTxt(p.worst_cut_osm, p.worst_cut_ms)})</span></div>`;
  const reset = `<button id="probeReset" class="probe-reset">Reset to worst sampled blockage</button>`;
  let body;
  if (probeState === "dragging") body = `<div class="big">Release to test this blockage</div>
    <div class="fine">Nothing is recalculated until you release. The circle stays on the roads (fixed 100 m across).</div>`;
  else if (probeState === "pending") body = `<div class="big">Testing…</div><div class="fine">One calculation for the blockage you placed.</div>`;
  else if (probeShown()) {
    const d = probe.data, c = d.counts;
    body = `<div class="mgrid2">
        ${metric(N(d.cut), "mapped buildings lose access if this road area is blocked", d.cut > 0 ? "cut" : "retain", pairTxt(d.cut_osm, d.cut_ms),
                 { k: "probe-cut", v: d.cut })}
        ${metric(N(Math.max(c.inside.osm, c.inside.ms)), "centre inside the blocked area", "inside", pairTxt(c.inside.osm, c.inside.ms))}
      </div>
      ${distBlock("Mapped buildings under the blockage you placed", [
        { cls: "cut", label: "Lose access", key: "cut" }, { cls: "inside", label: "Inside the blocked area", key: "inside" },
        { cls: "retain", label: "Retain access", key: "retain" }], c, false)}
      ${d.cut > p.worst_cut ? `<div class="fine">Higher than the worst sampled blockage: the scan tests points every 50 m,
        and this position falls between them.</div>` : ""}`;
  } else body = "";
  el.innerHTML = `<div class="kicker">Blockage you placed</div>
    ${probeMsg ? `<div class="pmsg">${probeMsg}</div>` : ""}${body}${worst}${reset}
    <div class="fine">Your test only: it does not change the scan, the ranking or the neighbourhood's classification.</div>`;
  $("probeReset").onclick = () => clearProbe();
  if (probeState === "done" && probeShown()) settleIn(el, { "probe-cut": shownNum["probe-cut"] ?? p.worst_cut });   // e.g. 234 -> 47
}
function endDragListeners() {
  if (!drag) return;
  map.off("mousemove", onProbeMove); document.removeEventListener("mouseup", onProbeUp, true);
  document.removeEventListener("keydown", onProbeKey, true);
  map.dragPan.enable(); map.getCanvas().style.cursor = "";
}
function clearProbe() {       // reset to the worst sampled blockage; invalidates any drag or pending request
  probeGen++;
  endDragListeners(); drag = null;
  setPreview(empty);          // always: also covers a pending calculation (no drag active)
  const had = probe !== null;
  probe = null; probeState = "none"; probeMsg = "";
  delete shownNum["probe-cut"];
  if (!scanData) return;
  renderBlockage();
  if (had) applyBuildingCats();
}
function onProbeKey(e) { if (e.key === "Escape") onProbeUp(null); }
function onProbeMove(e) {
  if (!drag || drag.area !== current || drag.nid !== selected || !canProbe()) return onProbeUp(null);
  drag.cursor = [e.lngLat.lng, e.lngLat.lat];          // the raw cursor: what is sent on release
  const s = snapPreview(e.lngLat);
  drag.far = !s || s.d > PROBE_SNAP_M;
  if (!drag.far) drag.pos = s.ll;                      // preview suggestion only
  setPreview(discAt(drag.pos));
  renderProbeCard();
}
function onProbeUp(e) {
  if (!drag) return;
  const d = drag;
  endDragListeners(); drag = null;
  const valid = d.area === current && d.nid === selected && canProbe();
  if (!valid) { setPreview(empty); probeState = probeShown() ? "done" : "none"; renderBlockage(); return; }
  if (e === null || !d.moved || !d.cursor) {           // cancelled (Esc) or a click without a drag: nothing to test
    setPreview(empty); probeMsg = ""; probeState = probeShown() ? "done" : "none";
    renderBlockage(); return;
  }
  // the server is the single authority: it receives the RAW cursor and decides eligibility, tolerance and the centre
  runProbe(d.cursor, d.far ? null : d.pos);
}
function startProbeDrag(e) {
  if (drag || !canProbe()) return;
  const c = blockageCentre();
  if (!c) return;
  e.preventDefault();
  probeGen++;                                          // a drag supersedes any calculation still in flight
  const f = scanData.neighbourhoods.features.find((x) => x.id === selected);
  const street = scanData.streets.features.find((x) => x.id === selected || x.properties.nid === selected);
  const b = new maplibregl.LngLatBounds(); const add = (q) => (typeof q[0] === "number" ? b.extend(q) : q.forEach(add));
  add(f.geometry.coordinates);
  const o = [b.getCenter().lng, b.getCenter().lat], frame = localFrame(o[1]), pad = 150;
  const [x0, y0, x1, y1] = [(b.getWest() - o[0]) * frame.kx - pad, (b.getSouth() - o[1]) * frame.ky - pad,
                            (b.getEast() - o[0]) * frame.kx + pad, (b.getNorth() - o[1]) * frame.ky + pad];
  const segs = [], addLine = (line) => { for (let k = 1; k < line.length; k++) {
    const ax = (line[k - 1][0] - o[0]) * frame.kx, ay = (line[k - 1][1] - o[1]) * frame.ky;
    const bx = (line[k][0] - o[0]) * frame.kx, by = (line[k][1] - o[1]) * frame.ky;
    if (Math.max(ax, bx) >= x0 && Math.min(ax, bx) <= x1 && Math.max(ay, by) >= y0 && Math.min(ay, by) <= y1) segs.push([ax, ay, bx, by]);
  } };
  const addGeom = (g) => g.type === "LineString" ? addLine(g.coordinates) : g.type === "MultiLineString" ? g.coordinates.forEach(addLine) : null;
  if (probeRoads && probeRoads.area === current && probeRoads.nid === selected) probeRoads.data.features.forEach((r) => addGeom(r.geometry));
  else if (street) addGeom(street.geometry);           // fallback: own streets only (never wider than the server's set)
  drag = { area: current, nid: selected, pos: c, cursor: null, far: false, moved: false, o, frame, segs };
  probeState = "dragging"; probeMsg = "";
  map.dragPan.disable(); map.getCanvas().style.cursor = "grabbing";
  map.getSource("blk-hit").setData(empty);
  setPreview(discAt(c));
  map.on("mousemove", onProbeMove);
  map.once("mousemove", () => { if (drag) drag.moved = true; });
  document.addEventListener("mouseup", onProbeUp, true);
  document.addEventListener("keydown", onProbeKey, true);
  renderProbeCard();
}
async function runProbe(ll, previewAt) {          // ll = raw release point; previewAt = suggested spot to show meanwhile
  const gen = ++probeGen, area = current, nid = selected;
  const valid = () => gen === probeGen && current === area && selected === nid && !floodOn && !fireOn;
  probeState = "pending"; probeMsg = "";
  setPreview(previewAt ? discAt(previewAt) : empty);
  renderProbeCard();
  let d;
  try {
    const r = await fetch(`/api/${area}/nb/${nid}/probe`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lon: ll[0], lat: ll[1] }) });
    if (!r.ok) throw new Error(`server replied ${r.status}`);
    d = await r.json();
  } catch (err) { d = { ok: false, message: `Couldn't test this blockage (${err.message}).` }; }
  if (!valid()) return;                                // superseded: touch nothing (clearProbe already cleared)
  setPreview(empty);                                   // the authoritative circle comes from the response
  if (!d.ok) { probeMsg = `${d.message} The blockage went back to where it was.`; probeState = probeShown() ? "done" : "rejected"; renderBlockage(); return; }
  probe = { area, nid, data: d }; probeState = "done";
  renderBlockage();
  attention(d.centre);
  applyBuildingCats();
}
for (const l of ["blk-hit", "blocked", "probe-gap"]) {
  map.on("mousedown", l, (e) => startProbeDrag(e));
  map.on("mouseenter", l, () => { if (!drag && canProbe()) map.getCanvas().style.cursor = "grab"; });
  map.on("mouseleave", l, () => { if (!drag) map.getCanvas().style.cursor = ""; });
}

// ---------- command-centre shell: scenario tabs, mode indicator, context line, status bar ----------
const MODE_LABEL = { vuln: "VULNERABILITY", mit: "MITIGATION", flood: "FLOOD SCENARIO", fire: "FIRE SCENARIO" };
function syncMode() {
  const mode = floodOn ? "flood" : fireOn ? "fire" : (drawing || proposalCount > 0) ? "mit" : "vuln";
  const chip = $("ctxMode");
  chip.className = `chip mode-${mode}`; chip.textContent = MODE_LABEL[mode];
  $("ctxArea").textContent = current ? areas[current].label : "";
  document.querySelectorAll("#modes button").forEach((b) => {
    b.classList.toggle("on", b.dataset.mode === (mode === "mit" ? "vuln" : mode));
    if (b.dataset.mode === "flood") b.classList.toggle("hidden", current !== "fredericton");   // flood: Fredericton only
    if (b.dataset.mode === "fire") b.classList.toggle("hidden", current !== "tantallon");      // fire: Tantallon only
  });
  $("vulnBox").classList.toggle("hidden", floodOn || fireOn);
  $("floodBox").classList.toggle("hidden", !floodOn);
  $("fireBox").classList.toggle("hidden", !fireOn);
  $("overview").classList.toggle("hidden", floodOn || fireOn || selected !== null);
  $("anaCtx").textContent =
    fireOn && fireMode === "hyp" && !fireCentre ? "Click the map to place the supplied affected area."
    : !floodOn && !fireOn && selected === null && !drawing ? "Select a neighbourhood on the map or from the list."
    : "";
}
function renderSummary() {
  const c = scanData.summary.counts, n = (k) => c[k] || 0;
  $("stSummary").innerHTML = `<b>${areas[current].label}</b> · neighbourhoods of 30+ mapped buildings:
    <span class="dot red"></span>${n("red")} cut off 30+ <span class="dot amber"></span>${n("amber")} cut off 1–29
    <span class="dot green"></span>${n("green")} none <span class="dot grey"></span>${n("not_assessed")} not assessed`;
}
document.querySelectorAll("#modes button").forEach((b) => (b.onclick = () => {
  const m = b.dataset.mode;
  if (m === "vuln") { if (floodOn) exitFlood(); if (fireOn) exitFire(); }
  else if (m === "flood") { if (fireOn) exitFire(false); if (!floodOn) enterFlood(); }
  else if (m === "fire") { if (floodOn) exitFlood(false); if (!fireOn) enterFire(); }
}));
$("resetView").onclick = () => current && map.flyTo({ center: areas[current].center, zoom: areas[current].zoom,
                                                        pitch: view === "3d" ? PITCH_3D : 0, bearing: view === "3d" ? BEARING_3D : 0, duration: dur(800) });

// ---------- 2D / 3D: two views of the SAME current result. Only the camera and the building layer change: no request,
// no recalculation, and no change to scenario, selection, source, proposed connection or parameters.
const PITCH_3D = 57, BEARING_3D = 30;
let view = "2d";
// 3D framing of one neighbourhood: closer than the flat fit, tilted and rotated so walls face the viewer
function frame3d(nid, duration = 1200) {
  const f = scanData && scanData.neighbourhoods.features.find((x) => x.id === nid);
  if (!f) return false;
  const b = new maplibregl.LngLatBounds();
  const add = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(add));
  add(f.geometry.coordinates);
  const cam = map.cameraForBounds(b, { padding: 40, bearing: BEARING_3D, maxZoom: 16.5 });
  if (!cam) return false;
  const opts = { center: cam.center, zoom: Math.min(cam.zoom + 1.2, 16.8), bearing: BEARING_3D, pitch: PITCH_3D };
  if (duration) map.easeTo({ ...opts, duration }); else map.jumpTo(opts);
  return true;
}
// back to 2D: the same flat, north-up framing that selecting a neighbourhood gives in 2D
function frame2d(nid, duration = 900) {
  const f = scanData && scanData.neighbourhoods.features.find((x) => x.id === nid);
  if (!f) return false;
  const b = new maplibregl.LngLatBounds();
  const add = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(add));
  add(f.geometry.coordinates);
  const cam = map.cameraForBounds(b, { padding: 60, bearing: 0, maxZoom: 16 });
  if (!cam) return false;
  const opts = { center: cam.center, zoom: cam.zoom, bearing: 0, pitch: 0 };
  if (duration) map.easeTo({ ...opts, duration }); else map.jumpTo(opts);
  return true;
}
function setView(v, animate = true) {
  view = v === "3d" ? "3d" : "2d";
  const is3d = view === "3d";
  map.setLayoutProperty("bld-3d", "visibility", is3d ? "visible" : "none");
  ["bld-fill", "bld-line"].forEach((l) => map.setLayoutProperty(l, "visibility", is3d ? "none" : "visible"));
  const framed = selected !== null && (is3d ? frame3d(selected, animate ? dur(900) : 0) : frame2d(selected, animate ? dur(800) : 0));
  if (!framed) {
    const cam = { pitch: is3d ? PITCH_3D : 0, bearing: is3d ? BEARING_3D : 0 };
    if (animate && MOTION) map.easeTo({ ...cam, duration: 800 }); else map.jumpTo(cam);
  }
  document.querySelectorAll("#viewCtl button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  $("viewNote").classList.toggle("hidden", !is3d);
}
document.querySelectorAll("#viewCtl button").forEach((b) => (b.onclick = () => setView(b.dataset.view)));
document.querySelectorAll("#fireModes button").forEach((b) => (b.onclick = () => fireOn && setFireMode(b.dataset.mode)));
$("fireRadius").oninput = (e) => ($("fireRadiusVal").textContent = `${(+e.target.value).toLocaleString()} m`);
$("fireRadius").onchange = () => fireOn && fireMode === "hyp" && runFire();   // on release
map.on("click", (e) => {
  if (!fireOn || fireMode !== "hyp") return;
  fireCentre = [+e.lngLat.lng.toFixed(6), +e.lngLat.lat.toFixed(6)];
  syncMode();
  runFire();
});

map.on("click", "nb-fill", (e) => { if (!drawing && !floodOn && !fireOn && !drag && e.features[0].id !== selected) select(e.features[0].id); });
map.on("click", "choke", (e) => { if (!drawing && !floodOn && !fireOn) select(e.features[0].properties.nid); });
map.on("mouseenter", "nb-fill", () => (map.getCanvas().style.cursor = "pointer"));
map.on("mouseleave", "nb-fill", () => (map.getCanvas().style.cursor = ""));

// deep links: ?area=fredericton&nid=99 opens an area with a neighbourhood selected
const q = new URLSearchParams(location.search);
await loadArea(areas[q.get("area")] ? q.get("area") : "tantallon");
if (q.get("view") === "3d") setView("3d", false);   // before &nid: an instant camera change would cancel its zoom
if (q.get("nid")) select(+q.get("nid"));
// scripted demo / backup: &road=lonA,latA,lonB,latB runs the same mitigation path as two map clicks
if (q.get("road")) {
  const v = q.get("road").split(",").map(Number);
  if (v.length === 4 && v.every(Number.isFinite)) { clicks = [[v[0], v[1]], [v[2], v[3]]]; runMitigation(); }
}
// scenario deep links (demo backup): &mode=flood[&gauge=8.36] on Fredericton; &mode=fire&fire=hist|hyp[&c=lon,lat&r=500] on Tantallon
if (q.get("mode") === "flood" && current === "fredericton") {
  const g = Number(q.get("gauge"));
  enterFlood(q.get("gauge") && g >= +$("gauge").min && g <= +$("gauge").max ? g : undefined);
} else if (q.get("mode") === "fire" && current === "tantallon") {
  const c = (q.get("c") || "").split(",").map(Number), r = Number(q.get("r"));
  if (r >= +$("fireRadius").min && r <= +$("fireRadius").max) { $("fireRadius").value = r; $("fireRadiusVal").textContent = `${r.toLocaleString()} m`; }
  if (c.length === 2 && c.every(Number.isFinite)) fireCentre = c;
  enterFire(q.get("fire") === "hist" ? "hist" : "hyp");
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
  motion: (on) => { MOTION = !!on; if (!MOTION) attention(null); return MOTION; },
  settleText: (k) => { const el = document.querySelector(`.mv[data-k="${k}"]`); return el ? el.textContent : null; },
  attnRings: () => document.querySelectorAll(".attn-ring").length,
  async fps(ms = 2000, orbit = true) {   // frames rendered during a slow camera orbit (performance check in Chrome)
    let n = 0; const count = () => n++;
    map.on("render", count);
    if (orbit) map.easeTo({ bearing: map.getBearing() + 60, duration: ms, easing: (t) => t });
    await new Promise((r) => setTimeout(r, ms));
    map.off("render", count);
    return Math.round((n * 1000) / ms);
  },
  selectedChoke() {   // the selected neighbourhood's choke point, as served by the scan (test/diagnostic only)
    const f = scanData && scanData.chokepoints.features.find((c) => c.properties.nid === selected);
    return f ? f.geometry.coordinates : null;
  },
  blockedFilter: () => map.getFilter("blocked"),
  probeDrop: (lon, lat) => runProbe([lon, lat], [lon, lat]),
  probeDragMove: (lon, lat) => { if (drag) { drag.moved = true; onProbeMove({ lngLat: { lng: lon, lat } }); } },
  previewFeatures: async () => (await map.getSource("probe-preview").getData()).features.length,
  previewN: () => previewN,
  probeDragStart() { const c = blockageCentre(); if (c) startProbeDrag({ preventDefault() {}, lngLat: { lng: c[0], lat: c[1] } }); return !!drag; },
  probeDragEnd: (cancel) => onProbeUp(cancel ? null : {}),
  probeReset: () => clearProbe(),
  probeInfo: () => ({ shown: probeShown(), state: probeState, gen: probeGen, dragging: !!drag, msg: probeMsg,
    centre: probe ? probe.data.centre : null, cut: probe ? [probe.data.cut_osm, probe.data.cut_ms] : null,
    card: $("probeCard").textContent.replace(/\s+/g, " ").trim(), badge: $("blkBadge").textContent,
    blocked: map.getFilter("blocked"), cut_filter: map.getFilter("cut"), dragPan: map.dragPan.isEnabled(),
    probeFeatures: probeShown() ? probe.data.geo.features.length : 0, counts: probe ? probe.data.counts : null }),
  topNid: () => { const f = scanData.neighbourhoods.features.find((x) => x.properties.rank === 1); return f ? f.id : null; },
  view: (v, animate = true) => setView(v, animate), viewState: () => ({ view, pitch: map.getPitch(), bearing: map.getBearing(),
    vis3d: map.getLayoutProperty("bld-3d", "visibility"), vis2d: map.getLayoutProperty("bld-fill", "visibility"),
    noteHidden: $("viewNote").classList.contains("hidden") }),
  fireState: () => ({ on: fireOn, mode: fireMode, area: current, cardState: $("fireOut").dataset.state || null,
    cardText: $("fireOut").textContent.replace(/\s+/g, " ").trim(), bldStates: bldStateN,
    boxHidden: document.querySelector('#modes [data-mode="fire"]').classList.contains("hidden") }),
  floodState: () => ({ on: floodOn, area: current, cardState: $("floodOut").dataset.state || null,
    cardText: $("floodOut").textContent.replace(/\s+/g, " ").trim(), bldStates: bldStateN,
    boxHidden: document.querySelector('#modes [data-mode="flood"]').classList.contains("hidden"), coverFeatures,
    bldSrc: bldShown.src, bldReady: bldShown.ready, bldPinned }),
  state() {
    const box = document.getElementById("mitig");
    return { area: current, cardHidden: box.classList.contains("hidden"), cardState: box.dataset.state || null,
             cardText: box.textContent.replace(/\s+/g, " ").trim(), proposalFeatures: proposalCount,
             clearVisible: !document.getElementById("clearBtn").classList.contains("hidden") };
  },
};
if (["1", "flood", "fire", "3d", "demo", "probe", "motion"].includes(q.get("selftest"))) import("/selftest.js");   // explicit test URLs only
