#!/usr/bin/env bun
/**
 * Send one scenario to the published agent and record the whole thread.
 *
 *   bun run.mjs --arm A0 --ids T01,T02 --trials 1
 *   bun run.mjs --arm A0 --split main --trials 3
 *
 * Each trial starts from a clean conversation via "Start over" so a previous
 * scenario cannot leak state into the next one. Writes evals/results/<arm>.json,
 * appending rather than overwriting, so a crashed batch loses nothing.
 *
 * Run from the project root, inside the session browser runtime.
 */

const args0 = process.argv.slice(2);
const SET = (() => { const i = args0.indexOf("--set"); return i >= 0 ? args0[i + 1] : "scenarios"; })();
const CFG = JSON.parse(await Bun.file(`evals/${SET}.json`).text());
const opt0 = (name, dflt) => { const i = args0.indexOf(`--${name}`); return i >= 0 ? args0[i + 1] : dflt; };
const TAB = opt0("tab", "agent-pub");
const AGENT_URL = opt0("url", "");   // pass --url with the published agent for the run

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : dflt;
};

const arm = opt("arm", "A0");
const trials = Number(opt("trials", "1"));
const split = opt("split", null);
const ids = opt("ids", null);

let picks = CFG.scenarios;
if (ids) picks = picks.filter((s) => ids.split(",").includes(s.id));
if (split) picks = picks.filter((s) => s.split === split);
if (!picks.length) { console.error("no scenarios matched"); process.exit(2); }

const tab = browser.tab(TAB);
await tab.url();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function send(text) {
  const obs = await tab.observe({ compact: true });
  const box = (obs.elements || []).find((e) => e.role === "textbox");
  if (!box) throw new Error("no textbox");
  await tab.id(box.id).fill(text);
  await sleep(300);
  const o2 = await tab.observe({ compact: true });
  const sendBtn = (o2.elements || []).find((e) => e.role === "button" && /^Send$/.test((e.name || "").trim()));
  if (!sendBtn) throw new Error("no send button");
  await tab.id(sendBtn.id).click();
}

async function expand() {
  for (let i = 0; i < 6; i++) {
    const obs = await tab.observe({ compact: true });
    const more = (obs.elements || []).filter((e) => /^Show more$/i.test((e.name || "").trim()));
    if (!more.length) return;
    for (const m of more) { try { await tab.id(m.id).click(); } catch {} }
    await sleep(700);
  }
}

async function settle(before, budgetMs = 90000) {
  const start = Date.now();
  let last = before, stable = 0;
  while (Date.now() - start < budgetMs) {
    await sleep(1500);
    const t = await tab.text();
    if (/Working…|Working\.\.\.|Generating response/.test(t)) { stable = 0; last = -1; continue; }
    if (t.length === last) {
      stable++;
      if (stable >= 2) { await expand(); return await tab.text(); }
    } else { stable = 0; last = t.length; }
  }
  return await tab.text();
}

async function reset() {
  // Reload the document. "Start over" clears the visible UI but the transcript
  // can still carry earlier turns, and a scenario graded against leftovers from
  // another scenario is not an independent trial.
  // The published agent can carry the previous session into the opening turn
  // (7 of 39 trials showed another scenario's subject in the greeting), so the
  // origin's storage and cookies are cleared before the reload.
  // Scoped to the agent's own origin. tab.clearStorage() with no argument wipes
  // every origin in the profile and logged the builder session out twice.
  try {
    await tab.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  } catch {}
  // Scope cookie deletion to the agent's own origin. clearCookies() clears the
  // whole browser context and logged the *builder* session out mid-run.
  try {
    await tab.run(async ({ page }, url) => {
      const host = new URL(url).hostname;
      const cookies = await page.cookies(url);
      const client = await page.target().createCDPSession();
      for (const c of cookies) {
        // page.cookies(url) also returns parent-domain cookies (.agentplace.io),
        // and deleting those logs the builder session out. Only the agent's own
        // host is cleared.
        if (c.domain.replace(/^\./, "") !== host) continue;
        await client.send("Network.deleteCookies", { name: c.name, domain: c.domain, path: c.path });
      }
      return cookies.length;
    }, { args: [AGENT_URL] });
  } catch {}
  for (let i = 0; i < 3; i++) {
    await tab.goto(AGENT_URL);
    await sleep(2500);
    const obs = await tab.observe({ compact: true });
    if ((obs.elements || []).some((e) => e.role === "textbox")) break;
    await sleep(2000);
  }
  const t = await tab.text();
  if (/my ac stopped cooling|i smell gas near the water heater/i.test(t)) {
    throw new Error("reset failed: previous scenario still in transcript");
  }
  if (/Something went wrong loading this page/i.test(t)) {
    throw new Error("page failed to load (platform error)");
  }
}

const outPath = `evals/results/${arm}.json`;
let store = { arm, agent: AGENT_URL, records: [] };
try { store = JSON.parse(await Bun.file(outPath).text()); } catch {}

const already = new Set(store.records.map((r) => `${r.id}#${r.trial}`));
let sent = 0;

for (const sc of picks) {
  for (let trial = 1; trial <= trials; trial++) {
    const key = `${sc.id}#${trial}`;
    if (already.has(key)) continue;
    await reset();
    const before = (await tab.text()).length;
    console.log(`▶ ${key} — ${sc.customer.slice(0, 60)}`);
    try {
      const t0 = Date.now();
      await send(sc.customer);
      const thread = await settle(before);
      const ms = Date.now() - t0;
      store.records.push({
        id: sc.id, trial, split: sc.split, lane: sc.lane,
        customer: sc.customer,
        thread,
        chars: thread.length,
        ms,
        at: new Date().toISOString(),
      });
      sent++;
      await Bun.write(outPath, JSON.stringify(store, null, 1));
      console.log(`  ✓ ${thread.length} chars, ${(ms/1000).toFixed(1)}s, ${store.records.length} total`);
    } catch (e) {
      console.log(`  ✗ ${String(e.message || e).slice(0, 120)}`);
      store.records.push({ id: sc.id, trial, split: sc.split, error: String(e.message || e), at: new Date().toISOString() });
      await Bun.write(outPath, JSON.stringify(store, null, 1));
    }
  }
}

console.log(`\n${sent} conversations recorded -> ${outPath}`);
