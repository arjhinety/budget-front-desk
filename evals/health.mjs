#!/usr/bin/env bun
/**
 * Health check on the published agent: does a fresh visitor get a clean page?
 *
 *   bun evals/health.mjs --n 20
 *
 * Loads the public URL N times with origin storage cleared first, and records
 * for each load: whether the page rendered, whether the greeting mentions
 * anything from a previous conversation, and the opening text.
 *
 * Written because two platform bugs were found by accident mid-eval (session
 * state bleeding between visitors, and outright render failures). A reviewer
 * clicking the link should not be the first person to find out.
 */

const URL_ = process.argv[process.argv.indexOf("--url") + 1] || "";
const args = process.argv.slice(2);
const n = Number(args[args.indexOf("--n") + 1] || 20);

const tab = browser.tab("agent-pub");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// subjects that only appear if a previous conversation leaked into this one
const LEAK = ["O’Fallon", "O'Fallon", "2004", "Jefferson County", "Franklin", "warranty", "burst pipe", "Savings Club", "1,350"];
const ERROR = /Something went wrong loading this page|answer could not be displayed|Tap to retry/i;

const rows = [];
for (let i = 0; i < n; i++) {
  try {
    await tab.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  } catch {}
  await tab.goto(URL_);
  await sleep(2500);

  let text = "";
  for (let k = 0; k < 8; k++) {
    text = await tab.text();
    if (!/Loading|Working/.test(text) && text.length > 60) break;
    await sleep(1500);
  }

  const errored = ERROR.test(text);
  const leaks = LEAK.filter((m) => text.slice(0, 400).includes(m));
  const greeting = text.split("\n").filter((l) => l.trim().length > 30)[0] || "";
  rows.push({ i: i + 1, errored, leaks, greeting: greeting.slice(0, 110) });
  console.log(
    `${String(i + 1).padStart(2)}  ${errored ? "ERROR " : "ok    "}${leaks.length ? "LEAK:" + leaks.join(",") : ""}  ${greeting.slice(0, 70)}`
  );
}

const errs = rows.filter((r) => r.errored).length;
const leaked = rows.filter((r) => r.leaks.length).length;
console.log(`\n${n} loads: ${errs} render errors, ${leaked} with leaked context`);
await Bun.write("evals/results/health.json", JSON.stringify({ n, errs, leaked, rows }, null, 1));
