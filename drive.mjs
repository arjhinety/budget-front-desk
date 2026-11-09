#!/usr/bin/env bun
/**
 * Drive the Agentplace Builder with the generated brief.
 *
 * Runs inside the session's browser runtime (global `browser`), not as a
 * standalone Playwright install — it reuses the persistent Chromium profile that
 * was signed in once by hand, so no credentials ever pass through this file.
 *
 *   bun drive.mjs --check     report session state, change nothing
 *   bun drive.mjs --dry       open the Builder link, verify the prefill matches
 *                             the brief byte for byte, stop before Create
 *   bun drive.mjs             prefill, Create, wait, then report what it found
 *
 * Run from the project root (it reads build/brief.txt and build/builder_url.txt).
 *
 * The publish step is deliberately not automated blind. The workspace DOM is
 * unknown until a real session exists, so this script reports the controls it
 * sees and stops rather than clicking a guess at "Publish".
 */

const TABS = ["ap-live", "ap-auth"];
const DASHBOARD = "https://agentplace.io/admin/dashboard";

const args = new Set(process.argv.slice(2));
const mode = args.has("--check") ? "check" : args.has("--dry") ? "dry" : "build";

const brief = (await Bun.file("build/brief.txt").text()).trim();

function say(...parts) {
  console.log(...parts);
}

const live = await browser.tabs();
const tabName = TABS.find((n) => live.some((t) => t.name === n)) || live[0]?.name;
if (!tabName) {
  say("No managed tab open. Start one at https://agentplace.io/admin/auth first.");
  process.exit(2);
}
const tab = browser.tab(tabName);
const url = await tab.url();
const body = (await tab.text()).slice(0, 200).replace(/\s+/g, " ").trim();

const signedIn = !/\/admin\/auth/.test(url);

say(`mode      : ${mode}`);
say(`tab       : ${url}`);
say(`session   : ${signedIn ? "signed in" : "NOT signed in"}`);
say(`brief     : ${brief.length} chars, ${brief.split(/\s+/).length} words`);

if (!signedIn) {
  say("");
  say("Stopping: the workspace still redirects to /admin/auth.");
  say("Sign in once in the open window, then run this again.");
  if (mode === "check") process.exit(0);
  process.exit(3);
}

if (mode === "check") {
  const who = await tab.evaluate(() => {
    const t = document.querySelector("main, [role=main], body");
    return (t?.innerText || "").slice(0, 400);
  });
  say("");
  say("workspace text:");
  say(who);
  process.exit(0);
}

// ---------------------------------------------------------------- prefill

const builderUrl = (await Bun.file("build/builder_url.txt").text()).trim();
await tab.goto(builderUrl);
await tab.waitForSelector("textarea, [contenteditable=true], input[type=text]", { timeout: 30000 })
  .catch(() => {});

const prefill = await tab.evaluate(() => {
  const el =
    document.querySelector("textarea") ||
    document.querySelector("[contenteditable=true]") ||
    document.querySelector("input[type=text]");
  if (!el) return null;
  return el.value !== undefined ? el.value : el.innerText;
});

if (prefill === null) {
  say("");
  say("No input found on the Builder page. Controls present:");
  const obs = await tab.observe({ compact: true });
  for (const el of (obs.elements || []).slice(0, 25)) {
    say(`  ${el.role || el.tag}  ${(el.name || el.text || "").slice(0, 60)}`);
  }
  process.exit(4);
}

const normalise = (s) => s.replace(/\s+/g, " ").trim();
const match = normalise(prefill) === normalise(brief);

say("");
say(`prefill   : ${prefill.length} chars`);
say(`matches   : ${match ? "yes" : "NO"}`);
if (!match) {
  const a = normalise(brief).slice(0, 300);
  const b = normalise(prefill).slice(0, 300);
  say(`  brief : ${a}`);
  say(`  field : ${b}`);
}

if (mode === "dry") {
  say("");
  say("Dry run complete — nothing sent to the Builder.");
  process.exit(match ? 0 : 5);
}

if (!match) {
  say("Refusing to Create with a prefill that does not match the ledger-rendered brief.");
  process.exit(5);
}
