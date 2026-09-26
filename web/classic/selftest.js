// Self-test for mitigation request handling. Loaded only with ?selftest=1 (never in normal use).
// Delays chosen /mitigate responses AFTER the server replies, so responses genuinely arrive out of order.
// Results are written to <pre id="selftest"> as JSON.
const app = window.__app;
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
window.fetch = async (url, opts) => {
  for (const [needle, q] of [["/flood/info", infoDelays], ["/buildings/", bldDelays]]) {
    if (String(url).includes(needle)) {
      const d = q.length ? q.shift() : 0;
      const resp = await realFetch(url, opts);
      await sleep(d);
      return resp;
    }
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
         ["fl-water", "fl-roads", "fl-cut", "fl-cover"].every((l) => snap6.vis[l] === "none"), { s6 });
}

async function fireSuite() {
  const waitDone = async () => { for (let i = 0; i < 150 && app.fireState().cardState !== "done"; i++) await sleep(200); };
  const vis = () => JSON.parse(app.snapshot()).vis;
  const FIRE = ["fi-zone", "fi-zone-line", "fi-cut", "fi-roads"], SCAN = ["choke", "blocked", "cut"];
  const C = [-63.854, 44.7052];
  await app.loadArea("fredericton");
  record("X1 fire control only on Tantallon", app.fireState().boxHidden, app.fireState());
  await app.loadArea("tantallon"); app.select(99);
  record("X1b fire control shown on Tantallon", !app.fireState().boxHidden, app.fireState());

  // X2 historical: labelled as the mapped 2023 perimeter, entrances outside, no-spread statement, scan overlays hidden
  app.fire("hist"); await waitDone();
  const h = app.fireState(), vh = vis();
  record("X2 historical card", h.on && h.mode === "hist" && h.cardText.includes("Mapped 2023 fire perimeter") &&
         h.cardText.includes("Westwood Hills entrances: outside the perimeter") && h.cardText.includes("0.96 km and 1.22 km") && h.cardText.includes("This tool does not predict fire spread") &&
         FIRE.every((l) => vh[l] === "visible") && SCAN.every((l) => vh[l] === "none"), { card: h.cardText.slice(0, 200), vh });

  // X3 hypothetical: two radii, first answers LAST -> only the newer one is shown
  arrivals.length = 0; fireDelays.push(2500, 0);
  app.fire("hyp", C, 1500); await sleep(100); app.fire("hyp", C, 300);
  await sleep(3200); await waitDone();
  const x3 = app.fireState();
  record("X3 reversed hypothetical responses", arrivals.join(",") === "fire r=300,fire r=1500" &&
         x3.cardText.includes("Radius 300 m") && !x3.cardText.includes("1,500 m") &&
         x3.cardText.includes("not a predicted fire extent"), { arrivals: arrivals.slice(), card: x3.cardText.slice(0, 120) });

  // X4 mode switch while pending: the old hypothetical answer must not overwrite the historical card
  arrivals.length = 0; fireDelays.push(2000, 0);
  app.fire("hyp", C, 800); await sleep(100); app.fire("hist");
  await sleep(2500); await waitDone();
  const x4 = app.fireState();
  record("X4 mode switch while pending", x4.mode === "hist" && x4.cardText.includes("Mapped 2023 fire perimeter") &&
         !x4.cardText.includes("Radius 800"), { arrivals: arrivals.slice(), card: x4.cardText.slice(0, 80) });

  // X5 exit restores the vulnerability view and selection exactly
  app.unfire(); await sleep(300);
  const x5 = app.fireState(), v5 = vis(), st5 = JSON.parse(app.snapshot());
  record("X5 exit restores view", !x5.on && x5.cardText === "" && FIRE.every((l) => v5[l] === "none") &&
         SCAN.every((l) => v5[l] === "visible") && st5.selected === 99, { x5, selected: st5.selected, v5 });

  // X6 area switch while a fire request is pending clears everything
  fireDelays.push(2000); app.fire("hyp", C, 500); await sleep(200);
  await app.loadArea("fredericton"); await sleep(2300);
  const x6 = app.fireState(), v6 = vis();
  record("X6 area switch clears fire", !x6.on && x6.boxHidden && x6.cardText === "" && FIRE.every((l) => v6[l] === "none"),
         { x6, v6 });
}

async function main() {
  const q = new URLSearchParams(location.search);
  if (q.get("selftest") === "flood") return floodSuite();
  if (q.get("selftest") === "fire") return fireSuite();
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
