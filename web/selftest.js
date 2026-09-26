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
window.fetch = async (url, opts) => {
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

async function main() {
  const q = new URLSearchParams(location.search);
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
  const pre = document.createElement("pre");
  pre.id = "selftest";
  pre.textContent = JSON.stringify({ all_pass: out.length > 0 && out.every((r) => r.pass), results: out }, null, 1);
  document.body.appendChild(pre);
});
