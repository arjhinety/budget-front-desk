#!/usr/bin/env bun
/**
 * Drive a multi-turn script against the published agent and record each reply
 * separately.
 *
 *   bun evals/run_mt.mjs --arm MT-A5 --url https://... --trials 3
 *
 * The reply for turn k is the difference between the page text before and after
 * that turn, so the transcript does not have to be parsed to find turn
 * boundaries. That matters because the agent's replies contain the customer's
 * own words.
 */

const args0 = process.argv.slice(2);
const opt = (n, d) => { const i = args0.indexOf(`--${n}`); return i >= 0 ? args0[i + 1] : d; };

const TAB = opt("tab", "agent-pub");
const AGENT_URL = opt("url", "");
const ARM = opt("arm", "MT");
const TRIALS = Number(opt("trials", "3"));
const ONLY = opt("ids", "");

if (!AGENT_URL) { console.error("--url is required"); process.exit(2); }

const CFG = JSON.parse(await Bun.file("evals/scenarios-mt.json").text());
let picks = CFG.scripts;
if (ONLY) picks = picks.filter((s) => ONLY.split(",").includes(s.id));

const tab = browser.tab(TAB);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function reset() {
  try { await tab.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); } catch {}
  for (let i = 0; i < 3; i++) {
    await tab.goto(AGENT_URL);
    await sleep(2500);
    const o = await tab.observe({ compact: true });
    if ((o.elements || []).some((e) => e.role === "textbox")) break;
    await sleep(2000);
  }
  const t = await tab.text();
  if (/cannot continue right now/i.test(t)) throw new Error("quota");
  if (/Something went wrong loading this page/i.test(t)) throw new Error("page failed to load");
}

async function send(text) {
  const o = await tab.observe({ compact: true });
  const box = (o.elements || []).find((e) => e.role === "textbox");
  if (!box) throw new Error("no textbox");
  await tab.id(box.id).fill(text);
  await sleep(300);
  const o2 = await tab.observe({ compact: true });
  const btn = (o2.elements || []).find((e) => e.role === "button" && /^Send$/.test((e.name || "").trim()));
  if (!btn) throw new Error("no send button");
  await tab.id(btn.id).click();
}

async function settle(budgetMs = 90000) {
  const start = Date.now();
  let last = -1, stable = 0;
  while (Date.now() - start < budgetMs) {
    await sleep(1500);
    const t = await tab.text();
    if (/Working…|Working\.\.\.|Generating response/.test(t)) { stable = 0; last = -1; continue; }
    if (t.length === last) { stable++; if (stable >= 2) return t; }
    else { stable = 0; last = t.length; }
  }
  return await tab.text();
}

const outPath = `evals/results/${ARM}.json`;
let store = { arm: ARM, agent: AGENT_URL, records: [] };
try { store = JSON.parse(await Bun.file(outPath).text()); } catch {}
const done = new Set(store.records.map((r) => `${r.id}#${r.trial}`));

let n = 0;
for (const s of picks) {
  for (let trial = 1; trial <= TRIALS; trial++) {
    const key = `${s.id}#${trial}`;
    if (done.has(key)) continue;
    console.log(`▶ ${key} — ${s.family} (${s.turns.length} turns)`);
    try {
      await reset();
      const replies = [];
      for (const turn of s.turns) {
        await send(turn);
        const after = await settle();
        // The page re-renders between turns and its total length can shrink, so a
        // character-offset delta returns empty. Take everything after the last
        // occurrence of what the customer just said instead.
        // lastIndexOf finds the message inside other words ("hi" inside "this"), so
        // anchor to a line start. Short customer messages are the case that breaks.
        const marker = "\n" + turn;
        let idx = after.lastIndexOf(marker);
        if (idx < 0) idx = after.lastIndexOf(turn);
        const reply = idx >= 0 ? after.slice(idx + (idx === after.lastIndexOf(marker) ? marker.length : turn.length)).trim() : "";
        if (/cannot continue right now/i.test(reply)) throw new Error("quota");
        replies.push(reply);
      }
      store.records.push({ id: s.id, family: s.family, trial, turns: s.turns, replies,
                           at: new Date().toISOString() });
      n++;
      await Bun.write(outPath, JSON.stringify(store, null, 1));
      console.log(`  ✓ ${replies.length} replies, ${replies.map((r) => r.length).join("/")} chars`);
    } catch (e) {
      const msg = String(e.message || e);
      console.log(`  ✗ ${msg.slice(0, 90)}`);
      if (msg === "quota") { console.log("\nquota hit — stopping"); process.exit(3); }
      store.records.push({ id: s.id, trial, error: msg, at: new Date().toISOString() });
      await Bun.write(outPath, JSON.stringify(store, null, 1));
    }
  }
}
console.log(`\n${n} conversations recorded -> ${outPath}`);
