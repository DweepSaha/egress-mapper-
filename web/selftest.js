// Self-test for mitigation request handling. Loaded only with ?selftest=1 (never in normal use).
// Delays chosen /mitigate responses AFTER the server replies, so responses genuinely arrive out of order.
// Results are written to <pre id="selftest"> as JSON.
const app = window.__app;
// scenario layers are shown/hidden by their opacity TARGET (MapLibre transitions ease towards it)
const off = (l) => Object.values(app.fadeState(l)).every((v) => v === 0);
const on = (l) => Object.values(app.fadeState(l)).some((v) => v > 0);
const W = [[-63.87399, 44.72806], [-63.85501, 44.70479]];          // exact Westwood demo proposal (unchanged)
const ENT = [[-63.855646, 44.704433], [-63.852344, 44.706056]];    // joins the two entrance junctions (quick reply)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const realFetch = window.fetch.bind(window);
const delays = [];
const arrivals = [];
const floodDelays = [];   // delays (ms) applied, in order, to /flood?gauge= responses
const infoDelays = [];    // ... to /flood/info responses
const bldDelays = [];     // ... to /buildings/ footprint responses
const fireDelays = [];    // ... to /fire/ scenario responses
const probeDelays = [];   // ... to /probe responses (user-placed blockage)
const probeBodies = [];   // request bodies sent to /probe (the raw release point)
let apiCalls = 0;
const urlLog = [];        // every request URL, in order (xarea suite)         // every /api/ request (the 3D suite asserts that toggling 2D/3D makes none)
window.fetch = async (url, opts) => {
  if (String(url).includes("/api/")) { apiCalls++; urlLog.push(String(url)); }
  for (const [needle, q] of [["/flood/info", infoDelays], ["/buildings/", bldDelays]]) {
    if (String(url).includes(needle)) {
      const d = q.length ? q.shift() : 0;
      const resp = await realFetch(url, opts);
      await sleep(d);
      return resp;
    }
  }
  if (String(url).includes("/probe") && !String(url).includes("/probe-roads")) {
    probeBodies.push(JSON.parse(opts.body));
    const d = probeDelays.length ? probeDelays.shift() : 0;
    const resp = await realFetch(url, opts);
    await sleep(d);
    arrivals.push("probe " + JSON.parse(opts.body).lon.toFixed(5));
    return resp;
  }
  if (String(url).includes("/fire/")) {
    const d = fireDelays.length ? fireDelays.shift() : 0;
    const resp = await realFetch(url, opts);
    await sleep(d);
    arrivals.push(String(url).includes("historical") ? "fire hist" : "fire r=" + String(url).split("radius=")[1]);
    return resp;
  }
  if (String(url).includes("/flood?gauge=")) {
    const d = floodDelays.length ? floodDelays.shift() : 0;
    const resp = await realFetch(url, opts);
    await sleep(d);
    arrivals.push("flood " + String(url).split("gauge=")[1]);
    return resp;
  }
  if (!String(url).includes("/mitigate")) return realFetch(url, opts);
  const tag = JSON.parse(opts.body).a[0] === W[0][0] ? "westwood" : "entrance";
  const d = delays.length ? delays.shift() : 0;
  const resp = await realFetch(url, opts);
  await sleep(d);
  arrivals.push(tag);
  return resp;
};
const out = [];
const record = (name, pass, detail) => out.push({ name, pass, detail });

async function floodSuite() {
  const waitDone = async () => { for (let i = 0; i < 150 && app.floodState().cardState !== "done"; i++) await sleep(200); };
  await app.loadArea("fredericton");
  const waitBld = async (src) => { for (let i = 0; i < 450; i++) { const f = app.floodState(); if (f.bldSrc === src && f.bldReady) return; await sleep(200); } };
  await waitBld("osm");
  // F-init (Codex): flood(8.36) with a slow info response -> disable -> flood(6.50) completes -> old init released.
  // The old continuation must not restore 8.36 or change anything.
  app.resetFloodInfo(); infoDelays.push(2500);
  const pOld = app.flood(8.36); await sleep(100); app.unflood();
  const pNew = app.flood(6.5); await pNew; await waitDone();
  const beforeRelease = app.floodState();
  await pOld; await sleep(800);
  const afterRelease = app.floodState();
  record("F-init overlapping initialization: old continuation is inert", afterRelease.on && Number(app.gaugeValue()) === 6.5 &&
         afterRelease.cardText.includes("6.50 m (gauge)") && !afterRelease.cardText.includes("8.36 m (gauge)") &&
         afterRelease.coverFeatures > 0 && afterRelease.cardText === beforeRelease.cardText,
         { slider: app.gaugeValue(), card: afterRelease.cardText.slice(0, 60), cover: afterRelease.coverFeatures });
  app.unflood(); await waitBld("osm");

  // F-worker (Codex): delayed and reordered MapLibre source completion. Microsoft ids must never colour OSM polygons.
  await app.flood(8.36); await waitDone(); await waitBld("osm");
  const w0 = app.bldCheck();
  app.bldTest.completeDelays.push(2500);                            // (a) Microsoft completion is slow
  document.querySelector('#floodBld button[data-src="ms"]').click(); await sleep(900);
  app.reapply();                                                     // try to apply categories mid-replacement
  const wMid = app.bldCheck();
  await waitBld("ms"); await sleep(300);
  const wMs = app.bldCheck();
  app.bldTest.completeDelays.push(2500, 0);                         // (b) reorder: slow OSM, then fast Microsoft...
  document.querySelector('#floodBld button[data-src="osm"]').click(); await sleep(150);
  document.querySelector('#floodBld button[data-src="ms"]').click();
  const pend = [];                                                   // sample while processing is pending
  for (let i = 0; i < 6; i++) { await sleep(500); app.reapply(); pend.push(app.bldCheck()); }
  await waitBld("ms"); await sleep(3000);                            // ...then the stale OSM completion arrives last
  const wEnd = app.bldCheck();
  const pendOk = pend.every((c) => c.wrongStates === 0 && (c.ready ? c.appliedNs === c.ns : c.states === 0));
  record("F-worker delayed/reordered source completion never cross-colours", w0.ready && w0.wrongStates === 0 &&
         !wMid.ready && wMid.states === 0 && wMid.wrongStates === 0 &&
         wMs.ready && wMs.src === "ms" && wMs.wrongStates === 0 && wMs.appliedNs === wMs.ns && pendOk &&
         Object.keys(wMs.loadedByNs).every((k) => +k === wMs.ns) &&        // ready only once MS polygons are loaded
         pend.every((c) => !c.ready || Object.keys(c.loadedByNs).every((k) => +k === c.ns)) &&
         wEnd.src === "ms" && wEnd.ready && wEnd.wrongStates === 0 && wEnd.appliedNs === wEnd.ns,
         { w0: [w0.src, w0.ready, w0.states, w0.loaded, w0.wrongStates], mid: [wMid.src, wMid.ready, wMid.states, wMid.wrongStates],
           ms: [wMs.src, wMs.ready, wMs.states, wMs.loaded, wMs.wrongStates, wMs.loadedByNs],
           pending: pend.map((c) => [c.src, c.ready, c.states, c.wrongStates, Object.keys(c.loadedByNs).join("+")]),
           end: [wEnd.src, wEnd.ready, wEnd.states, wEnd.wrongStates, wEnd.loadedByNs] });
  document.querySelector('#floodBld button[data-src="osm"]').click(); await waitBld("osm");
  app.unflood(); await waitBld("osm");

  // F3. interrupted FIRST activation: info response arrives after the scenario was turned off; re-enable -> outline
  app.resetFloodInfo(); infoDelays.push(1500);
  const p3 = app.flood(); await sleep(100); app.unflood(); await p3; await sleep(300);
  const coverAfterInterrupt = app.floodState().coverFeatures;
  await app.flood(8.36); await waitDone();
  record("F3 coverage outline after interrupted first activation", coverAfterInterrupt === 0 && app.floodState().coverFeatures > 0,
         { coverAfterInterrupt, coverAfterReenable: app.floodState().coverFeatures });
  app.unflood(); await waitBld("osm");
  // F4. OSM -> flood -> choose Microsoft -> exit: original source and pin restored
  const b4 = JSON.parse(app.snapshot());
  await app.flood(8.36); await waitDone();
  document.querySelector('#floodBld button[data-src="ms"]').click(); await waitBld("ms");
  const inFlood = app.floodState();
  app.unflood(); await waitBld("osm"); await sleep(300);
  const a4 = JSON.parse(app.snapshot());
  record("F4 exit restores pre-flood footprint source and pin", inFlood.bldSrc === "ms" && a4.bldSrc === b4.bldSrc &&
         a4.bldPinned === b4.bldPinned && a4.bldStates === b4.bldStates, { before: [b4.bldSrc, b4.bldPinned], inFlood: inFlood.bldSrc, after: [a4.bldSrc, a4.bldPinned] });
  // F5a. reset restores the exact baseline (no neighbourhood selected)
  const base0 = app.snapshot();
  await app.flood(8.36); await waitDone();
  const during = app.floodState(), duringSnap = app.snapshot();
  app.unflood(); await waitBld("osm"); await sleep(500);
  record("F5a flood reset restores exact baseline (no selection)", during.cardState === "done" && during.bldStates > 0 &&
         duringSnap !== base0 && app.snapshot() === base0, { during: during.cardText.slice(0, 160) });
  // F5b. same, with a neighbourhood selected before entering the scenario
  app.select(18); await sleep(1500);
  const base1 = app.snapshot();
  await app.flood(6.5); await waitDone();
  app.unflood(); await waitBld(JSON.parse(base1).bldSrc); await sleep(1500);
  record("F5b flood reset restores exact baseline (neighbourhood selected)", app.snapshot() === base1,
         { equal: app.snapshot() === base1 });
  // stale flood response: 9.00 answers late, after a newer 6.50 request
  arrivals.length = 0; floodDelays.push(2500, 0);
  const p1 = app.flood(9.0); await sleep(100); const p2 = app.flood(6.5);
  await Promise.all([p1, p2]); await sleep(500);
  const st = app.floodState();
  record("F-stale late flood response ignored", arrivals.join(",") === "flood 6.50,flood 9.00" &&
         st.cardText.includes("6.50 m (gauge)") && !st.cardText.includes("9.00"), { arrivals: arrivals.slice(), card: st.cardText.slice(0, 80) });
  app.unflood();
  // F7a. mitigation pending when the flood scenario starts: its late response must not appear
  delays.push(2000);
  const pm = app.propose([-66.64, 45.955], [-66.645, 45.958]); await sleep(200);
  await app.flood(8.36); await pm; await waitDone(); await sleep(300);
  const m = app.state(), f = app.floodState();
  record("F7a pending mitigation cannot leak into flood mode", m.cardHidden && m.proposalFeatures === 0 && f.cardState === "done",
         { mitig: m, flood: f.cardState });
  // F7b. the road test is inert during the flood scenario
  document.getElementById("drawBtn").click();
  record("F7b road test disabled in flood mode", document.getElementById("drawBtn").disabled &&
         document.getElementById("hint").classList.contains("hidden"), {});
  // F6. switching area clears the flood scenario - checked while the new area's footprints are still delayed
  bldDelays.push(4000);
  await app.loadArea("tantallon"); await sleep(300);
  const s6 = app.floodState(), snap6 = JSON.parse(app.snapshot());
  record("F6 area switch clears flood state", !s6.on && s6.boxHidden && s6.bldStates === 0 &&
         snap6.vis["fl-cover"] === "none" && ["fl-water", "fl-roads", "fl-cut"].every((l) => off(l)), { s6 });
}

async function fireSuite() {
  const waitDone = async () => { for (let i = 0; i < 150 && app.fireState().cardState !== "done"; i++) await sleep(200); };
  const vis = () => JSON.parse(app.snapshot()).vis;
  const FIRE = ["fi-zone", "fi-zone-line", "fi-cut", "fi-roads"], SCAN = ["choke", "blocked", "blocked-hatch", "blocked-edge", "cut"];
  const C = [-63.854, 44.7052];
  await app.loadArea("fredericton");
  record("X1 Fredericton: hypothetical fire available, mapped 2023 perimeter not offered",
    !app.fireState().boxHidden && app.histHidden(), app.fireState());
  await app.loadArea("tantallon"); app.select(99);
  record("X1b Tantallon: fire available including the mapped 2023 perimeter", !app.fireState().boxHidden && !app.histHidden(), app.fireState());

  // X2 historical: labelled as the mapped 2023 perimeter, entrances outside, no-spread statement, scan overlays hidden
  app.fire("hist"); await waitDone();
  const h = app.fireState(), vh = vis();
  record("X2 historical card", h.on && h.mode === "hist" && h.cardText.includes("Mapped 2023 fire perimeter") &&
         h.cardText.includes("Neither Westwood Hills entrance lies inside the mapped perimeter") && h.cardText.includes("0.96 km and 1.22 km") && h.cardText.includes("This tool does not predict fire spread") &&
         FIRE.every(on) && SCAN.every(off) && app.streetsOpacity() === 0.25, { card: h.cardText.slice(0, 200) });

  // X3 hypothetical: two radii, first answers LAST -> only the newer one is shown
  arrivals.length = 0; fireDelays.push(2500, 0);
  app.fire("hyp", C, 1500); await sleep(100); app.fire("hyp", C, 300);
  await sleep(3200); await waitDone();
  const x3 = app.fireState();
  record("X3 reversed hypothetical responses", arrivals.join(",") === "fire r=300,fire r=1500" &&
         x3.cardText.includes("300 m supplied affected radius") && !x3.cardText.includes("1,500 m") &&
         x3.cardText.includes("not a predicted fire extent"), { arrivals: arrivals.slice(), card: x3.cardText.slice(0, 120) });

  // X4 mode switch while pending: the old hypothetical answer must not overwrite the historical card
  arrivals.length = 0; fireDelays.push(2000, 0);
  app.fire("hyp", C, 800); await sleep(100); app.fire("hist");
  await sleep(2500); await waitDone();
  const x4 = app.fireState();
  record("X4 mode switch while pending", x4.mode === "hist" && x4.cardText.includes("Mapped 2023 fire perimeter") &&
         !x4.cardText.includes("800 m supplied affected radius"), { arrivals: arrivals.slice(), card: x4.cardText.slice(0, 80) });

  // X5 exit restores the vulnerability view and selection exactly
  app.unfire(); await sleep(300);
  const x5 = app.fireState(), v5 = vis(), st5 = JSON.parse(app.snapshot());
  record("X5 exit restores view", !x5.on && x5.cardText === "" && FIRE.every(off) &&
         SCAN.every(on) && app.streetsOpacity() === 1 && st5.selected === 99, { x5, selected: st5.selected });

  // X6 area switch while a fire request is pending clears everything
  fireDelays.push(2000); app.fire("hyp", C, 500); await sleep(200);
  await app.loadArea("fredericton"); await sleep(2300);
  const x6 = app.fireState(), v6 = vis();
  record("X6 area switch clears fire", !x6.on && app.histHidden() && x6.mode === "hyp" && x6.cardText === "" && FIRE.every(off),
         { x6, v6 });
}

async function viewSuite() {
  // 2D and 3D are two views of the same result: toggling must not request, recalculate or change any state
  const W3 = [[-63.87399, 44.72806], [-63.85501, 44.70479]];
  const until = async (ok) => { for (let i = 0; i < 150 && !ok(); i++) await sleep(200); };
  const state = () => {
    const snap = JSON.parse(app.snapshot()), m = app.state(), f = app.fireState(), fl = app.floodState();
    return { selected: snap.selected, panel: snap.panelText, bldSrc: snap.bldSrc, bldPinned: snap.bldPinned,
             mitig: m.cardText, proposal: m.proposalFeatures, fire: f.cardText, fireMode: f.mode, fireOn: f.on,
             flood: fl.cardText, floodOn: fl.on, gauge: app.gaugeValue(), bldStates: snap.bldStates,
             overlays: Object.fromEntries(Object.entries(snap.vis).filter(([k]) => !k.startsWith("bld"))) };
  };
  async function roundTrip(name) {
    const before = state(), calls0 = apiCalls;
    app.view("3d", false); await sleep(600);   // instant: headless Edge does not advance camera animations
    const v3 = app.viewState(), mid = state();
    app.view("2d", false); await sleep(600);
    const v2 = app.viewState(), after = state();
    const same = JSON.stringify(before) === JSON.stringify(mid) && JSON.stringify(before) === JSON.stringify(after);
    record(`V ${name}: 2D -> 3D -> 2D keeps state, no requests`,
      same && apiCalls === calls0 && Math.abs(v3.pitch - 57) < 0.5 && v3.vis3d === "visible" && v3.vis2d === "none" &&
      !v3.noteHidden && v2.pitch === 0 && v2.vis3d === "none" && v2.vis2d === "visible" && v2.noteHidden,
      { requests: apiCalls - calls0, v3, v2, diff: same ? null : { before, mid, after } });
  }
  await app.loadArea("tantallon");
  app.select(99); await sleep(1500);
  await roundTrip("vulnerability (Westwood selected)");
  await app.propose(...W3); await sleep(600);          // let any headline settle (motion on) before the snapshot
  await roundTrip("mitigation (exact Westwood proposal)");
  app.clear();
  app.fire("hist"); await until(() => app.fireState().cardState === "done");
  await roundTrip("historical fire");
  app.unfire();
  await app.loadArea("fredericton");
  await app.flood(8.36); await until(() => app.floodState().cardState === "done");
  await roundTrip("flood 8.36");
  app.unflood();
}

async function demoSuite() {
  // the rehearsed demo flow: Westwood (nid 99) must show the frozen result and keep it through source switch,
  // 2D/3D and Reset view; the exact mitigation proposal must show the audited per-source numbers
  const FROZEN_CHOKE = [-63.878859695, 44.725371840];
  const panelOk = (t) => t.includes("751 mapped buildings in this neighbourhood") && t.includes("OSM 751 · Microsoft 680") &&
    t.includes("234 lose access if the worst sampled blockage occurs") && t.includes("OSM 234 · Microsoft 194") &&
    t.includes("2 connections to major roads");
  const snap = () => JSON.parse(app.snapshot());
  await app.loadArea("tantallon");
  app.select(99); await sleep(1500);
  const s0 = snap(), ch = app.selectedChoke();
  const chokeOk = ch && Math.abs(ch[0] - FROZEN_CHOKE[0]) < 1e-6 && Math.abs(ch[1] - FROZEN_CHOKE[1]) < 1e-6;
  record("D1 Westwood nid 99: 751/680 cohort, 234/194 lose access, 2 connections, frozen choke, disc filtered to 99",
    s0.selected === 99 && panelOk(s0.panelText) && chokeOk && JSON.stringify(app.blockedFilter()) === JSON.stringify(["==", ["get", "nid"], 99]),
    { selected: s0.selected, choke: ch, panel: s0.panelText.slice(0, 260) });
  let calls0 = apiCalls;
  const msBtn = document.querySelector('#bldInfo button[data-src="ms"]');
  msBtn && msBtn.click(); await sleep(1500);
  const s1 = snap();
  record("D2 footprint source OSM -> Microsoft keeps nid 99 and the same headline result",
    !!msBtn && s1.selected === 99 && s1.bldPinned === "ms" && s1.panelText === s0.panelText,
    { pinned: s1.bldPinned, requests: apiCalls - calls0, same: s1.panelText === s0.panelText });
  const osmBtn = document.querySelector('#bldInfo button[data-src="osm"]');
  osmBtn && osmBtn.click(); await sleep(1500);
  calls0 = apiCalls;
  app.view("3d", false); await sleep(500); const s3 = snap();
  app.view("2d", false); await sleep(500); const s2 = snap();
  record("D3 2D -> 3D -> 2D keeps nid 99, the same blockage and analytics, no requests",
    apiCalls === calls0 && [s3, s2].every((s) => s.selected === 99 && s.panelText === s0.panelText &&
      JSON.stringify(s.filters) === JSON.stringify(s0.filters)), { requests: apiCalls - calls0 });
  calls0 = apiCalls;
  document.getElementById("resetView").click(); await sleep(600);
  const s4 = snap();
  record("D4 Reset view changes only the camera: nid 99 and its result stay, no requests",
    apiCalls === calls0 && s4.selected === 99 && s4.panelText === s0.panelText, { requests: apiCalls - calls0 });
  await app.propose([-63.87399, 44.72806], [-63.85501, 44.70479]);
  const m = app.state().cardText;
  record("D5 exact Westwood proposal: 234/194 before, 1/1 same blockage, 233/193 regain, 53/35 residual, 2,992 m",
    m.includes("233 of 234 regain access") && m.includes("OSM 234 · Microsoft 194") && m.includes("OSM 1 · Microsoft 1") &&
    m.includes("OSM 233 · Microsoft 193") && m.includes("OSM 53 · Microsoft 35") && m.includes("2,992 m") &&
    m.includes("Construction feasibility not assessed"), { card: m.slice(0, 400) });
  app.clear();
}

async function probeSuite() {
  // user-placed blockage: same scoring as the scan; state isolation and stale-response handling
  const WORST = [-63.878859695, 44.725371840];            // Westwood's worst sampled centre
  const OTHER = [-63.88573, 44.73359];                     // ~8 m off another Westwood street (snaps onto it)
  const FAR = [-63.80, 44.80];
  const P = () => app.probeInfo(), panel = () => JSON.parse(app.snapshot()).panelText;
  const done = async () => { for (let i = 0; i < 100 && P().state === "pending"; i++) await sleep(100); };
  const scanFilter = JSON.stringify(["==", ["get", "nid"], 99]), off = JSON.stringify(["==", ["get", "nid"], -1]);
  await app.loadArea("tantallon"); app.select(99); await sleep(1500);
  const panel0 = panel();
  const s0 = P();
  record("P0 selected Westwood shows the worst sampled blockage; badge says so",
    !s0.shown && JSON.stringify(s0.blocked) === scanFilter && s0.badge === "Map shows: worst sampled blockage (50 m radius)", s0);

  await app.probeDrop(...WORST); await done();
  const s1 = P();
  record("P1 placing it at the worst sampled centre reproduces 234/194 lose, 0/0 inside, 517/486 retain, labelled 'blockage you placed'",
    s1.shown && s1.cut[0] === 234 && s1.cut[1] === 194 && s1.card.includes("Blockage you placed") &&
    JSON.stringify(s1.counts) === JSON.stringify({ cut: { osm: 234, ms: 194 }, inside: { osm: 0, ms: 0 }, retain: { osm: 517, ms: 486 } }) &&
    s1.badge === "Map shows: blockage you placed" && JSON.stringify(s1.blocked) === off && panel() === panel0, s1);

  await app.probeDrop(...OTHER); await done();
  const s2 = P();
  record("P2 placing it elsewhere gives a different result; the scan panel is unchanged",
    s2.shown && JSON.stringify(s2.centre) !== JSON.stringify(s1.centre) && panel() === panel0 &&
    s2.card.includes("Worst sampled blockage for this neighbourhood (scan finding, 50 m radius): 234"), { centre: s2.centre, cut: s2.cut });

  arrivals.length = 0; probeDelays.push(1500, 0);
  const pA = app.probeDrop(...WORST); await sleep(100); const pB = app.probeDrop(...OTHER);
  await Promise.all([pA, pB]); await done();
  const s3 = P();
  record("P3 rapid repeated drops: the older (slower) answer is discarded, the newest wins",
    arrivals[0] === "probe " + OTHER[0].toFixed(5) && s3.shown &&
    JSON.stringify(s3.centre) === JSON.stringify(s2.centre), { arrivals: arrivals.slice(), centre: s3.centre });

  probeDelays.push(1500);
  const pC = app.probeDrop(...WORST); await sleep(150);
  const dragging = app.probeDragStart(); const mid = P();
  await pC; await sleep(200);
  const s4 = P();
  app.probeDragEnd(true); await sleep(200);
  const s4b = P();
  record("P4 drag started during an in-flight calculation: the answer is discarded; cancelling restores the previous blockage",
    dragging && mid.dragging && mid.badge === "Release to test this blockage" && s4.dragging &&
    JSON.stringify(s4.centre) === JSON.stringify(s2.centre) && !s4b.dragging && s4b.dragPan && s4b.shown &&
    JSON.stringify(s4b.centre) === JSON.stringify(s2.centre), { mid, s4b });

  probeDelays.push(1500);
  const pD = app.probeDrop(...WORST); await sleep(150);
  app.probeReset(); await pD; await sleep(200);
  const s5 = P();
  record("P5 reset mid-calculation: back to the worst sampled blockage, late answer ignored",
    !s5.shown && s5.state === "none" && JSON.stringify(s5.blocked) === scanFilter && s5.probeFeatures === 0 &&
    panel() === panel0 && s5.badge === "Map shows: worst sampled blockage (50 m radius)", s5);

  await app.probeDrop(...FAR); await done();
  const s6 = P();
  record("P6 a release far from any road is rejected and nothing moves", !s6.shown && s6.state === "rejected" &&
    s6.msg.includes("went back") && JSON.stringify(s6.blocked) === scanFilter, s6);

  await app.probeDrop(...OTHER); await done();
  probeDelays.push(1500);
  const pE = app.probeDrop(...WORST); await sleep(150);
  app.probeDragStart();
  await app.loadArea("fredericton"); await pE; await sleep(300);
  const s7 = P();
  record("P7 area switch mid-drag and mid-calculation: drag cancelled, map pan restored, nothing applied",
    !s7.shown && !s7.dragging && s7.dragPan && s7.state === "none" && s7.probeFeatures === 0, s7);

  await app.loadArea("tantallon"); app.select(99); await sleep(1200);
  await app.probeDrop(...OTHER); await done();
  app.fire("hist"); await sleep(300);
  const s8 = P();
  app.unfire(); await sleep(300);
  record("P8 entering a scenario drops the placed blockage (vulnerability-only tool)", !s8.shown && s8.probeFeatures === 0, s8);
  app.probeReset();

  // ---- Codex fix 2: exactly one authoritative snap - the RAW release point is sent, never the preview's snap
  app.select(99); await sleep(1500);
  const RAW_NEAR = [-63.88573, 44.73359];                // ~8 m off a Westwood street
  probeBodies.length = 0;
  app.probeDragStart(); app.probeDragMove(...RAW_NEAR); app.probeDragEnd(false); await done();
  const r1 = P();
  record("S1 release sends the raw cursor; the server's snapped centre is what is shown",
    probeBodies.length === 1 && probeBodies[0].lon === RAW_NEAR[0] && probeBodies[0].lat === RAW_NEAR[1] && r1.shown &&
    JSON.stringify(r1.centre) !== JSON.stringify(RAW_NEAR), { body: probeBodies[0], centre: r1.centre });
  probeBodies.length = 0;
  app.probeDragStart(); app.probeDragMove(...FAR); app.probeDragEnd(false); await done();
  const r2 = P();
  record("S2 raw cursor far from every eligible road: sent as-is, rejected by the server, previous blockage kept",
    probeBodies.length === 1 && probeBodies[0].lon === FAR[0] && r2.msg.includes("went back") && r2.shown &&
    JSON.stringify(r2.centre) === JSON.stringify(r1.centre) && app.previewN() === 0, { body: probeBodies[0], r2 });
  app.probeReset();

  // ---- Codex fix 3: preview geometry cleared unconditionally (asserted on the real preview source)
  const pendingThen = async (name, interrupt) => {
    await app.loadArea("tantallon"); app.select(99); await sleep(1200);
    probeDelays.push(1500);
    const pr = app.probeDrop(...OTHER); await sleep(150);
    const during = await app.previewFeatures();
    await interrupt();
    const now = await app.previewFeatures(), nowN = app.previewN();
    await pr; await sleep(300);
    const after = await app.previewFeatures(), info = P();
    record(`C ${name}: preview cleared immediately and stays cleared after the late answer`,
      during > 0 && now === 0 && nowN === 0 && after === 0 && app.previewN() === 0 && !info.shown && info.probeFeatures === 0,
      { during, now, after, state: info.state });
  };
  await pendingThen("pending -> Reset", async () => app.probeReset());
  await pendingThen("pending -> selection change", async () => app.select(58));
  await pendingThen("pending -> area change", async () => { await app.loadArea("fredericton"); });
  await pendingThen("pending -> fire scenario", async () => { app.fire("hist"); await sleep(100); });
  app.unfire();
  await pendingThen("pending -> mitigation start", async () => document.getElementById("drawBtn").click());
  app.clear();
  // flood: a Fredericton neighbourhood with a pending placed blockage, then the flood scenario
  await app.loadArea("fredericton"); const fnid = app.topNid(); app.select(fnid); await sleep(1500);
  const fc = app.selectedChoke();
  probeDelays.push(1500);
  const pf = app.probeDrop(...fc); await sleep(150);
  const fDuring = await app.previewFeatures();
  await app.flood(8.36);
  const fNow = await app.previewFeatures();
  await pf; await sleep(300);
  const fAfter = await app.previewFeatures();
  record("C pending -> flood scenario: preview cleared immediately and stays cleared",
    fDuring > 0 && fNow === 0 && fAfter === 0 && !P().shown, { fDuring, fNow, fAfter });
  app.unflood();
}

async function motionSuite() {
  // motion is presentation only: state is final before any animation; newer results cancel older counts
  const OTHER = [-63.88573, 44.73359], WORST = [-63.878859695, 44.725371840], W = [[-63.87399, 44.72806], [-63.85501, 44.70479]];
  const P = () => app.probeInfo();
  await app.loadArea("tantallon"); app.select(99); await sleep(1500);
  await app.probeDrop(...OTHER);
  const stateNow = P(), textNow = app.settleText("probe-cut"), ringNow = app.attnRings();
  await sleep(1000);
  const textLater = app.settleText("probe-cut"), final = stateNow.cut && Math.max(...stateNow.cut).toLocaleString();
  record("M1 placed blockage: state is final at once; the headline settles 234 -> final; one ring then none",
    stateNow.shown && textNow === "234" && textLater === final && ringNow === 1 && app.attnRings() === 0,
    { textNow, textLater, final, ringNow, ringsAfter: app.attnRings() });
  const pA = app.probeDrop(...OTHER); const pB = app.probeDrop(...WORST);
  await Promise.all([pA, pB]); await sleep(700);
  record("M2 a newer result cancels the older count: the headline ends on the newest value (234)",
    app.settleText("probe-cut") === "234" && P().cut[0] === 234, { text: app.settleText("probe-cut") });
  app.probeReset();
  await app.propose(...W);
  const mNow = app.state().cardText, afterNow = app.settleText("mit-after");
  await sleep(700);
  record("M3 mitigation: card state final at once (233 of 234); AFTER headline settles 234 -> 1",
    mNow.includes("233 of 234") && afterNow === "234" && app.settleText("mit-after") === "1", { afterNow, after: app.settleText("mit-after") });
  app.clear();
  app.motion(false);
  app.select(99); await sleep(300);
  await app.probeDrop(...OTHER);
  record("M4 motion off: headline shows the final value immediately, no ring",
    app.settleText("probe-cut") === Math.max(...P().cut).toLocaleString() && app.attnRings() === 0, { text: app.settleText("probe-cut") });
  app.probeReset(); app.motion(true);
  const l1 = app.loadArea("fredericton"), l2 = app.loadArea("tantallon"), l3 = app.loadArea("fredericton");
  await Promise.all([l1, l2, l3]); await sleep(1200);
  const snapA = JSON.parse(app.snapshot());
  record("M5 rapid area switching: the last requested area wins, nothing selected, no ring",
    app.state().area === "fredericton" && snapA.selected === null && app.attnRings() === 0 &&
    document.getElementById("ctxArea").textContent === "Fredericton, NB", { area: app.state().area });
  await app.loadArea("tantallon"); app.select(99);
  app.probeReset(); app.clear();                          // during the camera transition
  app.view("3d"); app.view("2d");                          // intentional transitions, immediately superseded
  await sleep(1400);
  const snapB = JSON.parse(app.snapshot()), vs = app.viewState();
  record("M6 Reset / Clear / 2D-3D during transitions: selection and result intact, final view is 2D",
    snapB.selected === 99 && snapB.panelText.includes("234 lose access") && vs.view === "2d" && vs.vis2d === "visible" &&
    vs.vis3d === "none" && !P().shown, { view: vs, selected: snapB.selected });
}

async function xareaSuite() {
  // hypothetical fire on Fredericton: area-aware routing, no historical carry-over, flood <-> fire state hand-over
  const FC = [-66.645, 45.958];
  const done = async () => { for (let i = 0; i < 150 && app.fireState().cardState !== "done"; i++) await sleep(200); };
  // (a) Fredericton hypothetical fire is computed for Fredericton, never Tantallon
  await app.loadArea("fredericton"); await sleep(500);
  urlLog.length = 0;
  app.fire("hyp", FC, 500); await done();
  const reqs = urlLog.filter((u) => u.includes("/fire/"));
  const direct = await (await fetch(`/api/fredericton/fire/hypothetical?lon=${FC[0]}&lat=${FC[1]}&radius=500`)).json();
  const st = app.fireState();
  record("XA Fredericton hypothetical fire requests /api/fredericton/..., response and state are Fredericton's",
    reqs.length === 1 && reqs[0].includes("/api/fredericton/fire/hypothetical") && app.fireDataArea() === "fredericton" &&
    direct.area === "fredericton" && st.cardText.includes(`${direct.roads_affected_km} km`),
    { reqs, area: app.fireDataArea(), km: direct.roads_affected_km });
  app.unfire();
  // (b) historical mode never carries into Fredericton (remembered, button, or explicit request)
  await app.loadArea("tantallon"); await sleep(500);
  app.fire("hist"); await done();
  const histOk = app.fireState().mode === "hist" && app.fireState().cardText.includes("Mapped 2023 fire perimeter");
  await app.loadArea("fredericton"); await sleep(500);
  urlLog.length = 0;
  document.querySelector('#modes [data-mode="fire"]').click(); await sleep(400);
  const b1 = app.fireState();
  app.fire("hist"); await sleep(400);                     // an explicit historical request on Fredericton
  const b2 = app.fireState();
  document.querySelector('#fireModes [data-mode="hist"]').click(); await sleep(400);
  const b3 = app.fireState();
  record("XB historical Tantallon -> Fredericton -> Fire: hypothetical mode, no perimeter request, no Westwood text",
    histOk && [b1, b2, b3].every((s) => s.on && s.mode === "hyp" && !s.cardText.includes("Westwood")) && app.histHidden() &&
    !urlLog.some((u) => u.includes("historical")), { b1: b1.mode, b2: b2.mode, b3: b3.mode, urls: urlLog.slice() });
  app.unfire();
  // (c) flood <-> fire keeps the vulnerability view to restore: selection + footprint source/pin
  await app.loadArea("fredericton"); const nid = app.topNid(); app.select(nid); await sleep(1500);
  const ms = document.querySelector('#bldInfo button[data-src="ms"]'); ms && ms.click(); await sleep(1500);
  const v0 = JSON.parse(app.snapshot());
  const tab = (m) => document.querySelector(`#modes [data-mode="${m}"]`).click();
  tab("flood"); await sleep(300); await app.flood(8.36);
  const osm = document.querySelector('#floodBld button[data-src="osm"]'); osm && osm.click(); await sleep(800);   // change source inside the scenario
  tab("fire"); await sleep(400); app.fire("hyp", FC, 500); await done();
  tab("flood"); await sleep(1500);
  tab("vuln"); await sleep(1800);
  const v1 = JSON.parse(app.snapshot());
  record("XC1 flood -> fire -> flood -> vulnerability restores the original selection and footprint source/pin",
    v0.selected === nid && v1.selected === nid && v1.bldPinned === v0.bldPinned && v1.bldPinned === "ms" &&
    v1.panelText === v0.panelText && app.scenSaved() === null, { v0: [v0.selected, v0.bldPinned], v1: [v1.selected, v1.bldPinned, v1.bldSrc] });
  tab("fire"); await sleep(400); app.fire("hyp", FC, 500); await done();
  tab("flood"); await sleep(300); await app.flood(8.36);
  tab("vuln"); await sleep(1800);
  const v2 = JSON.parse(app.snapshot());
  record("XC2 fire -> flood -> vulnerability restores it too", v2.selected === nid && v2.bldPinned === "ms" && app.scenSaved() === null,
    { v2: [v2.selected, v2.bldPinned] });
  tab("flood"); await sleep(300); await app.flood(8.36);
  await app.loadArea("tantallon"); await sleep(600);
  record("XC3 area switch from a scenario discards the saved view (nothing carries across areas)",
    app.scenSaved() === null && JSON.parse(app.snapshot()).selected === null, {});
}

async function fireDragSuite() {
  // hypothetical fire: drag the centre (free-floating), one calculation on release, same stale-response guards
  const A = [-63.854, 44.7052], B = [-63.8600, 44.7100], C = [-63.8480, 44.7000];
  const I = () => app.fireInfo();
  const fireReqs = () => urlLog.filter((u) => u.includes("/fire/hypothetical"));
  const settle = async () => { for (let i = 0; i < 150; i++) { const s = await I(); if (s.state !== "pending") return s; await sleep(150); } return I(); };
  const near = (c, p) => c && Math.abs(c[0] - p[0]) < 1e-6 && Math.abs(c[1] - p[1]) < 1e-6;
  await app.loadArea("tantallon"); await sleep(400);
  app.fire("hyp", A, 500); await settle();
  // FD1 drag moves only a preview; release -> exactly one request, "Testing...", supplied-area wording intact
  urlLog.length = 0; fireDelays.push(800);
  const started = app.fireDragStart(); app.fireDragMove(...B);
  const mid = await I(); const reqMid = fireReqs().length;
  app.fireDragEnd(false); await sleep(100);
  const pend = await I();
  const fin = await settle();
  record("FD1 drag = preview only; release = one request (Testing...), free-floating centre, supplied-area wording kept",
    started && mid.dragging && mid.badge === "Release to test this area" && mid.previewFeatures === 1 && reqMid === 0 &&
    pend.state === "pending" && pend.badge === "Testing…" && fireReqs().length === 1 && near(fin.centre, B) &&
    fin.state === "done" && fin.previewFeatures === 0 && fin.handle === 1 && fin.card.includes("not a predicted fire extent") &&
    fin.card.includes("This tool does not predict fire spread"), { mid, pend: pend.state, fin, reqs: fireReqs() });
  // FD2 drag started while a calculation is in flight: its answer is discarded; cancelling re-tests the unchanged centre
  arrivals.length = 0; urlLog.length = 0; fireDelays.push(1500);
  app.fireClick(...C); await sleep(150);
  const inflight = (await I()).state;
  app.fireDragStart(); app.fireDragMove(...A); app.fireDragEnd(true);
  const fin2 = await settle(); await sleep(1700);
  const fin2b = await I();
  record("FD2 drag during an in-flight calculation: stale answer discarded; Esc re-tests the unchanged centre",
    inflight === "pending" && near(fin2b.centre, C) && fin2b.state === "done" && fireReqs().length === 2 && fin2b.previewFeatures === 0,
    { inflight, centre: fin2b.centre, reqs: fireReqs().length });
  // FD3 rapid repeated drops: the newest drop wins
  urlLog.length = 0; fireDelays.push(1500, 0);
  app.fireDragStart(); app.fireDragMove(...A); app.fireDragEnd(false); await sleep(100);
  app.fireDragStart(); app.fireDragMove(...B); app.fireDragEnd(false);
  await sleep(1900); const fin3 = await settle();
  record("FD3 rapid repeated drops: the newest centre wins", near(fin3.centre, B) && fin3.state === "done" && fireReqs().length === 2,
    { centre: fin3.centre, reqs: fireReqs().length });
  // FD4 radius slider moved mid-drag: preview resizes, no request; release -> one request with the new radius
  urlLog.length = 0;
  app.fireDragStart(); app.fireDragMove(...A);
  const sl = document.getElementById("fireRadius"); sl.value = 900; sl.dispatchEvent(new Event("input")); sl.dispatchEvent(new Event("change"));
  await sleep(200); const reqSlider = fireReqs().length, dragging4 = (await I()).dragging;
  app.fireDragEnd(false); const fin4 = await settle();
  record("FD4 radius changed mid-drag: no request while dragging; release tests the new radius once",
    reqSlider === 0 && dragging4 && fireReqs().length === 1 && fireReqs()[0].includes("radius=900") && fin4.radius === 900,
    { reqSlider, reqs: fireReqs(), radius: fin4.radius });
  sl.value = 500; sl.dispatchEvent(new Event("input"));
  // FD5 click-to-place still works (and a drag release is not also a click)
  await sleep(200); urlLog.length = 0; app.fireClick(...C); const fin5 = await settle();
  record("FD5 click-to-place unchanged", near(fin5.centre, C) && fireReqs().length === 1 && fin5.state === "done", { centre: fin5.centre });
  // FD6 area switch mid-drag: gesture ended, map pan restored, preview gone, fire off
  app.fireDragStart(); app.fireDragMove(...A);
  await app.loadArea("fredericton"); await sleep(400);
  const fin6 = await I();
  record("FD6 area switch mid-drag: drag ended, pan restored, no preview, fire off",
    !fin6.dragging && fin6.dragPan && fin6.previewFeatures === 0 && fin6.handle === 0 && !app.fireState().on && fin6.badge === "",
    fin6);
  // FD7 scenario switch mid-drag (fire -> flood -> vulnerability) on Fredericton restores the vulnerability view
  const nid = app.topNid(); app.select(nid); await sleep(1500);
  const tab = (m) => document.querySelector(`#modes [data-mode="${m}"]`).click();
  tab("fire"); await sleep(300); app.fire("hyp", [-66.645, 45.958], 500); await settle();
  app.fireDragStart(); app.fireDragMove(-66.640, 45.960);
  tab("flood"); await sleep(300);
  const mid7 = await I();
  await app.flood(8.36); tab("vuln"); await sleep(1500);
  const fin7 = await I(), snap7 = JSON.parse(app.snapshot());
  record("FD7 fire -> flood mid-drag -> vulnerability: drag ended, no preview, original selection restored",
    !mid7.dragging && mid7.dragPan && mid7.previewFeatures === 0 && !fin7.dragging && snap7.selected === nid && app.scenSaved() === null,
    { mid7, selected: snap7.selected });
}

async function transSuite() {
  // scenario transitions: opacity-only MapLibre transitions; state applied synchronously; interruptions land on the
  // latest state; area switches snap; caveats never trail their numbers. Run with &motion=on.
  const SCANL = ["choke", "blocked", "blocked-hatch", "blocked-edge", "cut"], FIREL = ["fi-zone", "fi-zone-line", "fi-cut", "fi-roads"];
  const FLOODL = ["fl-water", "fl-water-line", "fl-cut", "fl-roads"];
  const tab = (m) => document.querySelector(`#modes [data-mode="${m}"]`).click();
  const fireDone = async () => { for (let i = 0; i < 150 && app.fireState().cardState !== "done"; i++) await sleep(150); };
  const floodDone = async () => { for (let i = 0; i < 150 && app.floodState().cardState !== "done"; i++) await sleep(150); };
  const vulnState = () => SCANL.every(on) && FIREL.every(off) && FLOODL.every(off) && app.streetsOpacity() === 1 &&
    !app.fireState().on && !app.floodState().on;
  await app.loadArea("tantallon"); app.select(99); await sleep(1200);
  // T1 entering fire: state changes at once (scan overlays target 0, streets dimmed); the supplied area and its caveat
  //    arrive together with the result
  tab("fire"); const t1a = { scanOff: SCANL.every(off), dim: app.streetsOpacity() === 0.25, fireOff: FIREL.every(off) };
  app.fire("hist"); await fireDone();
  const card = app.fireState().cardText;
  record("T1 fire: state switches at once; area eases in with its result; caveat present with the numbers",
    t1a.scanOff && t1a.dim && t1a.fireOff && FIREL.every(on) && card.includes("This tool does not predict fire spread") &&
    card.includes("817.8 ha"), t1a);
  // T2 interrupted: fire -> vuln -> fire -> vuln within ~100 ms lands exactly on vulnerability (no blend)
  tab("vuln"); await sleep(40); tab("fire"); await sleep(40); tab("vuln"); await sleep(900);
  const s2 = JSON.parse(app.snapshot());
  record("T2 switching again mid-fade lands on the final state (vulnerability), not a blend",
    vulnState() && s2.selected === 99 && !app.bldDipped() && Object.values(app.fadeState("bld-fill"))[0] === 1, { selected: s2.selected, dipped: app.bldDipped() });
  // T3 3D: the same interruption with extruded buildings
  app.view("3d", false); await sleep(300);
  tab("fire"); await sleep(40); tab("vuln"); await sleep(40); tab("fire"); await sleep(40); tab("vuln"); await sleep(900);
  record("T3 3D: interrupted switches land on vulnerability; extrusions back at full opacity",
    vulnState() && !app.bldDipped() && Math.abs(Object.values(app.fadeState("bld-3d"))[0] - 0.92) < 1e-9, app.fadeState("bld-3d"));
  app.view("2d", false);
  // T4 Fredericton flood <-> fire rapid switching ends in the last scenario only
  await app.loadArea("fredericton"); await sleep(600);
  tab("flood"); await sleep(40); tab("fire"); await sleep(40); tab("flood"); await floodDone(); await sleep(700);
  record("T4 flood -> fire -> flood mid-fade: only flood is shown (water on, fire off, scan off)",
    app.floodState().on && !app.fireState().on && FLOODL.every(on) && FIREL.every(off) && SCANL.every(off) &&
    JSON.parse(app.snapshot()).vis["fl-cover"] === "visible", {});
  // T5 area switch mid-transition snaps (duration 0) to the new area's vulnerability view
  tab("vuln"); await sleep(40); tab("flood"); await sleep(40);
  await app.loadArea("tantallon"); await sleep(200);
  const tr = app.map.getPaintProperty("choke", "circle-opacity-transition");
  record("T5 area switch during a transition snaps to the new area's vulnerability view",
    vulnState() && tr && tr.duration === 0 && !app.bldDipped() && JSON.parse(app.snapshot()).vis["fl-cover"] === "none", { tr });
}

async function probeRadiusSuite() {
  // user radius on the placed blockage: never displayed as the scan finding; reset restores radius AND position
  const OTHER = [-63.88573, 44.73359];
  const P = () => app.probeInfo(), panel = () => JSON.parse(app.snapshot()).panelText;
  const done = async () => { for (let i = 0; i < 100 && P().state === "pending"; i++) await sleep(100); };
  const scanFilter = JSON.stringify(["==", ["get", "nid"], 99]);
  await app.loadArea("tantallon"); app.select(99); await sleep(1500);
  const panel0 = panel();
  probeBodies.length = 0;
  app.probeRadius(150); await done();
  const s1 = P();
  record("PR1 radius 150 m: one request at the scan's centre, labelled 'not comparable'; the scan finding stays 50 m",
    probeBodies.length === 1 && probeBodies[0].radius === 150 && s1.shown && s1.radius === 150 && s1.comparable === false &&
    s1.card.includes("not comparable with the scan finding") && s1.card.includes("radius 150 m") &&
    s1.badge.includes("150 m radius (scan uses 50 m)") && panel() === panel0 && panel0.includes("50 m radius") &&
    s1.card.includes("(scan finding, 50 m radius): 234"), { bodies: probeBodies.slice(), s1: { r: s1.radius, badge: s1.badge } });
  app.probeReset(); await sleep(200);
  const s2 = P();
  record("PR2 Reset restores radius AND position: slider 50, scan's own 50 m blockage shown",
    app.probeSlider() === 50 && !s2.shown && JSON.stringify(s2.blocked) === scanFilter && s2.badge === "Map shows: worst sampled blockage (50 m radius)",
    { slider: app.probeSlider(), badge: s2.badge });
  probeBodies.length = 0;
  app.probeDragStart(); app.probeDragMove(...OTHER);
  app.probeRadius(200); await sleep(200);
  const mid = probeBodies.length, dragging = P().dragging;
  app.probeDragEnd(false); await done();
  const s3 = P();
  record("PR3 slider moved mid-drag: preview only; release tests the new radius once",
    mid === 0 && dragging && probeBodies.length === 1 && probeBodies[0].radius === 200 && s3.radius === 200 && s3.comparable === false,
    { mid, bodies: probeBodies.slice() });
  app.select(58); await sleep(800);
  const r4a = app.probeSlider();
  app.select(99); await sleep(800); app.probeRadius(120); await done();
  await app.loadArea("fredericton"); await sleep(300);
  const r4b = app.probeSlider();
  record("PR4 selection change and area switch reset the radius to the scan's 50 m", r4a === 50 && r4b === 50 && !P().shown, { r4a, r4b });
  await app.loadArea("tantallon"); app.select(99); await sleep(1200);
  await app.probeDrop(...OTHER); await done();
  probeDelays.push(1500, 0);
  app.probeRadius(250); await sleep(100); app.probeRadius(80); await sleep(1800); await done();
  const s5 = P();
  record("PR5 radius changed while a calculation is pending: the newest radius wins", s5.shown && s5.radius === 80 && app.probeSlider() === 80,
    { radius: s5.radius, slider: app.probeSlider() });
  app.probeRadius(50); await done();
  const s6 = P();
  record("PR6 radius back to 50 m at a placed position: comparable, no warning", s6.shown && s6.radius === 50 && s6.comparable === true &&
    !s6.card.includes("not comparable"), { radius: s6.radius });
  app.probeReset();
}

async function main() {
  const q = new URLSearchParams(location.search);
  if (q.get("selftest") === "flood") return floodSuite();
  if (q.get("selftest") === "fire") return fireSuite();
  if (q.get("selftest") === "3d") return viewSuite();
  if (q.get("selftest") === "demo") return demoSuite();
  if (q.get("selftest") === "probe") return probeSuite();
  if (q.get("selftest") === "motion") return motionSuite();
  if (q.get("selftest") === "xarea") return xareaSuite();
  if (q.get("selftest") === "firedrag") return fireDragSuite();
  if (q.get("selftest") === "trans") return transSuite();
  if (q.get("selftest") === "proberadius") return probeRadiusSuite();
  if (q.get("road")) {                                               // 5. deep link -> Clear
    for (let i = 0; i < 100 && app.state().cardState !== "done"; i++) await sleep(200);
    const before = app.state();
    document.getElementById("clearBtn").click();
    const after = app.state();
    record("5 deep link -> Clear", before.cardState === "done" && before.clearVisible && after.cardHidden &&
           after.proposalFeatures === 0, { before, after });
    return;
  }
  // 1. exact Westwood request twice
  await app.propose(...W); const s1a = app.state();
  await app.propose(...W); const s1b = app.state();
  record("1 exact Westwood twice", s1a.cardState === "done" && s1a.cardText === s1b.cardText &&
         s1a.cardText.includes("233 of 234") && s1a.cardText.includes("cuts off 53"), { first: s1a.cardText, second: s1b.cardText });

  // 2. Clear while request pending
  delays.push(2000); let p = app.propose(...W); await sleep(300);
  const pending2 = app.state().cardState; app.clear(); await p; await sleep(300);
  const s2 = app.state();
  record("2 Clear while pending", pending2 === "pending" && s2.cardHidden && s2.proposalFeatures === 0 && !s2.clearVisible,
         { pendingState: pending2, after: s2 });

  // 3. area switch while request pending
  delays.push(2000); p = app.propose(...W); await sleep(300);
  const pending3 = app.state().cardState; await app.loadArea("fredericton"); await p; await sleep(300);
  const s3 = app.state();
  record("3 area switch while pending", pending3 === "pending" && s3.area === "fredericton" && s3.cardHidden &&
         s3.proposalFeatures === 0, { pendingState: pending3, after: s3 });
  await app.loadArea("tantallon"); app.select(99);

  // 4. two proposals, responses deliberately reversed (first request answers LAST)
  arrivals.length = 0; delays.push(2500, 0);
  const pA = app.propose(...W); await sleep(100); const pB = app.propose(...ENT);
  await Promise.all([pA, pB]); await sleep(300);
  const s4 = app.state();
  record("4 reversed responses", arrivals.join(",") === "entrance,westwood" && s4.cardText.includes("doesn't start") &&
         !s4.cardText.includes("233") && s4.proposalFeatures === 2, { arrivalOrder: arrivals.slice(), after: s4 });
}

main().catch((e) => record("selftest crashed", false, String(e))).finally(() => {
  if (!new URLSearchParams(location.search).get("selftest")) return;   // results never render in normal mode
  const pre = document.createElement("pre");
  pre.id = "selftest";
  pre.textContent = JSON.stringify({ all_pass: out.length > 0 && out.every((r) => r.pass), results: out }, null, 1);
  document.body.appendChild(pre);
});
