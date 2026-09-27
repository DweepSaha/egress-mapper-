// Landing page: a slowly rotating globe with our own road data, then a flight into the chosen study area and a hand-off
// to the map (/?area=...). Optional entry only: any URL with a query string opens the map directly (see index.html).
// No analysis here; no numbers; the map page owns all state.
import * as maplibregl from "/vendor/maplibre-gl-6.11.2/maplibre-gl.mjs";

const OFM_DARK = "https://tiles.openfreemap.org/styles/dark";
const OFFLINE = { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#05070a" } }] };
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const START = { center: [-72, 38], zoom: innerHeight > 800 ? 1.9 : 1.5, bearing: 0, pitch: 0 };
const FLIGHT_MS = 5200;
const empty = { type: "FeatureCollection", features: [] };

// Default: our own data on a dark globe (deterministic, offline, no tile downloads during the spin and flight).
// ?basemap=on adds the online dark basemap when reachable; any failure falls back to our own data.
async function pickStyle() {
  if (new URLSearchParams(location.search).get("basemap") !== "on") return OFFLINE;
  try {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 3000);
    const r = await fetch(OFM_DARK, { signal: ctl.signal }); clearTimeout(t);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch { return OFFLINE; }                      // offline: the globe still renders from our own data
}

// faint graticule so the sphere reads even with no basemap
function graticule() {
  const f = [];
  for (let lon = -180; lon < 180; lon += 20) {
    const c = []; for (let lat = -80; lat <= 80; lat += 4) c.push([lon, lat]);
    f.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: c } });
  }
  for (let lat = -60; lat <= 60; lat += 20) {
    const c = []; for (let lon = -180; lon <= 180; lon += 4) c.push([lon, lat]);
    f.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: c } });
  }
  return { type: "FeatureCollection", features: f };
}

const areasP = fetch("/api/areas").then((r) => r.json()).catch(() => null);
let map = null;
// ---------- slow rotation (stops for good on any interaction or a selection)
let spinning = !REDUCED, last = null;
function spin(t) {
  if (!spinning || !map) return;
  if (last !== null) { const c = map.getCenter(); map.jumpTo({ center: [c.lng + (t - last) * 0.004, c.lat] }); }
  last = t; requestAnimationFrame(spin);
}
const stopSpin = () => { spinning = false; last = null; };
// The text, buttons and skip link never wait for the map: a slow or unreachable basemap must not blank the page.
const mapReady = (async () => {
map = new maplibregl.Map({ container: "globe", style: await pickStyle(), ...START, attributionControl: false,
                           renderWorldCopies: false });
await new Promise((r) => map.once("load", r));
map.setProjection({ type: "globe" });            // globe below z11, easing to mercator by z12 (MapLibre built-in)
try { map.setSky({ "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 6, 1, 9, 0] }); } catch { /* optional */ }
map.addSource("grat", { type: "geojson", data: graticule() });
map.addLayer({ id: "grat", type: "line", source: "grat", paint: { "line-color": "#2a4258", "line-width": 0.8, "line-opacity": 0.9 } });
map.addSource("egress-roads", { type: "geojson", data: empty, attribution: "© OpenStreetMap contributors" });
// glow: a wide blurred halo under a thin bright core; ways out (major roads) slightly brighter
map.addLayer({ id: "roads-glow", type: "line", source: "egress-roads", layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": "#35c3ff", "line-opacity": ["interpolate", ["linear"], ["zoom"], 2, 0.5, 10, 0.25],
           "line-width": ["interpolate", ["linear"], ["zoom"], 2, 3, 8, 5, 13, 6], "line-blur": 3 } });
map.addLayer({ id: "roads-core", type: "line", source: "egress-roads", layout: { "line-cap": "round", "line-join": "round" },
  paint: { "line-color": ["case", ["get", "way_out"], "#e6f7ff", "#9fdcf5"],
           "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.6, 10, 1, 14, ["case", ["get", "way_out"], 2.2, 0.9]] } });
// our road data for both study areas (already small; drawn whole)
Promise.all(["tantallon", "fredericton"].map((a) => fetch(`/api/${a}/roads`).then((r) => r.json()).catch(() => empty)))
  .then((fcs) => map.getSource("egress-roads").setData({ type: "FeatureCollection", features: fcs.flatMap((f) => f.features) }));
// the two study areas are a few pixels wide at globe zoom: a soft glowing dot at each (fades out as roads take over)
map.addSource("sites", { type: "geojson", data: empty });
map.addLayer({ id: "sites-glow", type: "circle", source: "sites", paint: { "circle-color": "#35c3ff", "circle-blur": 1,
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 14, 6, 22, 9, 0], "circle-opacity": 0.55 } });
map.addLayer({ id: "sites-core", type: "circle", source: "sites", paint: { "circle-color": "#e6f7ff",
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2.5, 6, 3.5, 9, 0] } });
areasP.then((areas) => areas && map.getSource("sites").setData({ type: "FeatureCollection", features: Object.values(areas)
  .map((a) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: a.center } })) }));
map.on("mousedown", stopSpin); map.on("touchstart", stopSpin); map.on("wheel", stopSpin);
if (spinning && !chosen) requestAnimationFrame(spin);
return map;
})().catch(() => null);

// ---------- entrance choreography (restrained; once)
const intro = () => anime.timeline({ easing: "easeOutCubic" })
  .add({ targets: ".mark", opacity: [0, 1], translateY: [14, 0], duration: 700 })
  .add({ targets: ".line", opacity: [0, 1], translateY: [10, 0], duration: 600 }, "-=350")
  .add({ targets: [".sub", ".choose"], opacity: [0, 1], duration: 500 }, "-=300")
  .add({ targets: ".loc", opacity: [0, 1], translateX: [-12, 0], delay: anime.stagger(110), duration: 500 }, "-=250")
  .add({ targets: ".skip", opacity: [0, 1], duration: 400 }, "-=200");
const showAll = () => document.querySelectorAll(".mark,.line,.sub,.choose,.loc,.skip").forEach((e) => { e.style.opacity = 1; e.style.transform = "none"; });
if (REDUCED) showAll(); else { intro(); setTimeout(showAll, 3200); }   // guarantee: controls are always usable

// ---------- selection -> flight -> hand-off. One selection only; the map page owns everything after.
let chosen = null, flightTimer = null, navigated = false;
const HANDLERS = ["dragPan", "scrollZoom", "boxZoom", "dragRotate", "keyboard", "doubleClickZoom", "touchZoomRotate"];
function go(area) {
  if (navigated || chosen !== area) return;             // exactly one navigation per selection
  navigated = true;
  location.assign(`/?area=${encodeURIComponent(area)}&from=welcome`);
}
async function choose(area) {
  if (chosen) return;                                   // a second click during the flight is ignored
  chosen = area;
  document.querySelectorAll(".loc").forEach((b) => (b.disabled = true));
  const areas = await areasP;
  const m = await Promise.race([mapReady, new Promise((r) => setTimeout(() => r(null), 3000))]);
  const a = areas && areas[area];
  if (!a || !m || REDUCED) return go(area);             // no flight without camera target / map, or with reduced motion
  stopSpin();
  HANDLERS.forEach((h) => map[h] && map[h].disable());
  anime({ targets: "#intro", opacity: [1, 0], duration: 450, easing: "easeInCubic" });   // opacity only: #intro keeps its centring transform
  const done = () => {                                  // fade to the map's background, then navigate
    if (chosen !== area) return;
    clearTimeout(flightTimer); flightTimer = null;
    anime({ targets: "#veil", opacity: [0, 1], duration: 380, easing: "linear", complete: () => go(area) });
    setTimeout(() => go(area), 480);                    // even if animation frames stall (background tab)
  };
  map.once("moveend", done);
  flightTimer = setTimeout(done, FLIGHT_MS + 1500);    // never stranded if moveend does not arrive
  map.flyTo({ center: a.center, zoom: a.zoom, bearing: 0, pitch: 0, duration: FLIGHT_MS, curve: 1.5, essential: true });
}
document.querySelectorAll(".loc").forEach((b) => (b.onclick = () => choose(b.dataset.area)));
addEventListener("keydown", (e) => { if (e.key === "Escape" && !chosen) location.assign("/?map"); });

// Back button restores this page from the browser cache in its last (veiled, mid-flight) state: reset it fully.
addEventListener("pageshow", (e) => {
  if (!e.persisted) return;
  chosen = null; navigated = false; clearTimeout(flightTimer); flightTimer = null;
  if (map) { map.stop(); map.jumpTo(START); HANDLERS.forEach((h) => map[h] && map[h].enable()); }
  document.getElementById("veil").style.opacity = 0;
  document.getElementById("intro").style.opacity = 1;
  document.querySelectorAll(".loc").forEach((b) => (b.disabled = false));
  if (!REDUCED && map) { spinning = true; requestAnimationFrame(spin); }
});

// diagnostic: ?autotest=<area> runs the selection automatically (headless flow check)
const auto = new URLSearchParams(location.search).get("autotest");
if (auto) setTimeout(() => choose(auto), 800);

window.__welcome = {   // diagnostics: frames rendered over ms (globe spin or an ongoing flight)
  async fps(ms = 2000) {
    let n = 0; const c = () => n++; map.on("render", c);
    await new Promise((r) => setTimeout(r, ms)); map.off("render", c); return Math.round((n * 1000) / ms);
  },
  state: () => ({ chosen, spinning, zoom: map && map.getZoom(), projection: map && map.getProjection()?.type }),
  choose, get map() { return map; },
};
