#!/usr/bin/env bun
/**
 * Send one scenario to the published agent and record the whole thread.
 *
 * Provenance-bound (default, fail-closed):
 *   bun evals/run.mjs --arm A0 --phase capture \
 *     --snapshot ../agentplace-private/capture/b1/snapshot.json \
 *     --run-plan ../agentplace-private/capture/b1/run-plan-A0-capture.json \
 *     --url https://<published-agent> --ids T01,T02 --trials 1
 *
 * Offline rehearsal (never evaluates `browser`):
 *   bun evals/run.mjs --dry-run --snapshot <snap> --phase capture --url <url>
 *   bun evals/run.mjs --preflight-only --snapshot <snap> --phase capture
 *
 * Deliberately unverified historical-style run (explicit opt-in, refused by default):
 *   bun evals/run.mjs --legacy-unverified --arm A0 --ids T01 --trials 1
 *
 * Each trial starts from a clean conversation via "Start over" so a previous
 * scenario cannot leak state into the next one. Records append; invalid attempts
 * are retained with a reason and retried under a new attempt number.
 *
 * Run from the project root, inside the session browser runtime.
 */

const RAW = process.argv.slice(2);
const has = (name) => RAW.includes(`--${name}`);
const opt = (name, dflt) => { const i = RAW.indexOf(`--${name}`); return i >= 0 ? RAW[i + 1] : dflt; };
const flagList = (name) => {
  const out = [];
  for (let i = 0; i < RAW.length; i++) {
    if (RAW[i] === `--${name}` && RAW[i + 1] !== undefined && !RAW[i + 1].startsWith("--")) out.push(RAW[i + 1]);
  }
  return out.flatMap((v) => String(v).split(",")).map((s) => s.trim()).filter(Boolean);
};

const HELP = `evals/run.mjs — single-turn capture with provenance

Required for a provenance-bound run:
  --snapshot <file>     verified effective-config snapshot (private)
  --phase <phase>       capture | validation | ... (recorded and resume-checked)
  --run-plan <file>     optional plan; --snapshot/--phase/--arm are accepted as the equivalent
  --url <url>           published agent URL (or snapshot.agent.public_url)

Optional:
  --arm A0  --trials 1  --trial 1  --ids T01,T02  --split main  --set scenarios
  --trial <n>           first trial number; the paired executor uses one trial per cell
  --out <file>          default: private ../agentplace-private/capture/<batch>/runs/<run>/...
  --batch <name>        private batch label (default "next")
  --tab agent-pub       existing browser tab name
  --allow-repo-out      permit an output path inside this repository
  --allow-existing-out  permit appending to an already-existing output file
  --dry-run             validate and print the plan; never touches the browser or network
  --preflight-only      same offline checks; never touches the browser or network
  --legacy-unverified   explicitly allow a historical-style run without provenance
  --json                machine-readable offline report
  --help                print this text; reads and writes nothing

Exit codes: 0 ok, 1 blocked/invalid, 2 usage, 3 quota, 4 resume refused.
`;

if (has("help") || RAW.includes("-h")) {
  console.log(HELP);
  process.exit(0);
}

/* Resolve the shared module from the real working directory. Static imports
 * cannot be used here: this file is evaluated through new Function(...). */
const { resolve, isAbsolute, dirname, join } = await import("node:path");
const { pathToFileURL } = await import("node:url");
const { existsSync } = await import("node:fs");
const { mkdir } = await import("node:fs/promises");

async function loadProvenance() {
  const starts = [process.cwd()];
  if (process.argv[1]) starts.push(dirname(resolve(process.argv[1])));
  for (const start of starts) {
    let dir = resolve(start);
    for (let i = 0; i < 10; i++) {
      if (existsSync(join(dir, "evals", "provenance.mjs"))) {
        return import(pathToFileURL(join(dir, "evals", "provenance.mjs")).href);
      }
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  throw new Error("evals/provenance.mjs was not found from the working directory; run from the project root");
}

const P = await loadProvenance();
const REPO = P.repoRootFrom(process.cwd());
if (!REPO) {
  console.error("error: cannot locate the project root (evals/provenance.mjs) from the working directory");
  process.exit(2);
}

const MODE = has("preflight-only") ? "preflight" : has("dry-run") ? "dry-run" : "capture";
const OFFLINE = MODE !== "capture";

const SET_ARG = opt("set", "scenarios");
const SET_PATH = (() => {
  if (isAbsolute(SET_ARG)) return SET_ARG;
  if (SET_ARG.includes("/") || SET_ARG.endsWith(".json")) return resolve(REPO, SET_ARG);
  return resolve(REPO, "evals", `${SET_ARG}.json`);
})();

const ARM = opt("arm", "A0");
let TRIALS = Number(opt("trials", "1"));
const TRIAL_BASE = Number(opt("trial", "1"));
const SPLIT = opt("split", null);
const IDS = opt("ids", null);
const TAB = opt("tab", "agent-pub");
const SNAPSHOT_ARG = opt("snapshot", null);
const PHASE = opt("phase", null);
const PLAN_ARG = opt("run-plan", opt("run_plan", null));
const LEGACY = has("legacy-unverified");
const OUT_ARG = opt("out", null);
const BATCH = opt("batch", "next");
const ALLOW_REPO_OUT = has("allow-repo-out");
const ALLOW_EXISTING_OUT = has("allow-existing-out");
const URL_ARG = opt("url", "");
const AS_JSON = has("json");

function die(code, message) {
  console.error(`blocked: ${message}`);
  process.exit(code);
}

function printIssues(blockers, warnings) {
  for (const b of blockers || []) console.error(`  ✗ [${b.code}] ${b.message}`);
  for (const w of warnings || []) console.error(`  ! [${w.code}] ${w.message}`);
}

let cfg;
try {
  cfg = JSON.parse(await Bun.file(SET_PATH).text());
} catch (e) {
  die(2, `cannot read scenario set ${P.displayPath(REPO, SET_PATH)}: ${String(e.message || e)}`);
}
const ALL_SCENARIOS = cfg.scenarios || [];
if (!Array.isArray(ALL_SCENARIOS) || !ALL_SCENARIOS.length) {
  die(2, "scenario set has no scenarios array");
}

/* --------------------------------------------------------- offline plan */

const blockers = [];
const warnings = [];

if (!SNAPSHOT_ARG && !LEGACY) {
  blockers.push({
    code: "provenance-required",
    message: "refusing to collect unbound data: --snapshot and --phase are required for a provenance-bound run; --legacy-unverified is the deliberate opt-out",
  });
}
if (SNAPSHOT_ARG && !PHASE) {
  blockers.push({ code: "phase-required", message: "--phase is required when --snapshot is supplied" });
}
if (!SNAPSHOT_ARG && LEGACY && PHASE) {
  warnings.push({ code: "legacy-phase-ignored", message: "--phase has no meaning in a legacy-unverified run" });
}

let snapshot = null;
let planReport = null;
let plan = null;
if (SNAPSHOT_ARG) {
  snapshot = P.verifySnapshot(SNAPSHOT_ARG);
  for (const b of snapshot.blockers) blockers.push(b);
  for (const w of snapshot.warnings) warnings.push(w);
  if (PLAN_ARG) {
    planReport = P.validateRunPlan(PLAN_ARG, { repoRoot: REPO, snapshotReport: snapshot, setPath: SET_PATH });
    plan = planReport.plan;
    if (plan && plan.trials !== undefined && plan.trials !== null
        && !RAW.includes("--trials") && !RAW.includes("--trial")) {
      TRIALS = Number(plan.trials);
    }
    for (const b of planReport.blockers) blockers.push(b);
    for (const w of planReport.warnings) warnings.push(w);
    if (plan) {
      if (plan.arm && plan.arm !== ARM) blockers.push({ code: "plan-arm-mismatch", message: `plan arm ${plan.arm} does not match --arm ${ARM}` });
      if (plan.phase && PHASE && plan.phase !== PHASE) blockers.push({ code: "plan-phase-mismatch", message: `plan phase ${plan.phase} does not match --phase ${PHASE}` });
      if (plan.trials !== undefined && plan.trials !== null
          && TRIAL_BASE + TRIALS - 1 > Number(plan.trials)) {
        blockers.push({
          code: "plan-trials-range",
          message: `trial range ${TRIAL_BASE}..${TRIAL_BASE + TRIALS - 1} is outside plan trials 1..${plan.trials}`,
        });
      }
      if (plan.ids && IDS) {
        const allowed = new Set(plan.ids);
        const extra = IDS.split(",").map((s) => s.trim()).filter(Boolean).filter((id) => !allowed.has(id));
        if (extra.length) blockers.push({ code: "plan-ids-not-in-plan", message: `ids not in the run plan: ${extra.join(", ")}` });
      }
    }
  }
}

let picks = ALL_SCENARIOS;
const effectiveIds = IDS
  ? IDS.split(",").map((s) => s.trim()).filter(Boolean)
  : plan?.ids ?? null;
if (effectiveIds) picks = picks.filter((s) => effectiveIds.includes(s.id));
if (SPLIT) picks = picks.filter((s) => s.split === SPLIT);
if (!picks.length) blockers.push({ code: "no-scenarios", message: "no scenarios matched --ids/--split/plan" });
if (!Number.isInteger(TRIALS) || TRIALS < 1) blockers.push({ code: "trials", message: "--trials must be a positive integer" });
if (!Number.isInteger(TRIAL_BASE) || TRIAL_BASE < 1) blockers.push({ code: "trial-base", message: "--trial must be a positive integer" });

const effectiveUrl = URL_ARG || snapshot?.normalized?.agent?.public_url || "";

let runId = null;
let outPath = null;
let meta = null;
let store = null;
let sidecarPath = null;
let resume = null;

if (!LEGACY) {
  const setSha = P.sha256File(SET_PATH);
  runId = plan?.run_id || `run-${ARM}-${PHASE}-${(snapshot?.config_hash || "nosnapshot").slice(0, 12)}`;
  outPath = OUT_ARG
    ? resolve(OUT_ARG)
    : P.defaultRecordPath({ repoRoot: REPO, batch: plan?.batch || BATCH, runId, arm: ARM, phase: PHASE });
  const safe = P.assertSafeOutput({
    path: outPath,
    repoRoot: REPO,
    allowExisting: ALLOW_EXISTING_OUT,
    allowRepoOut: ALLOW_REPO_OUT,
  });
  for (const b of safe.blockers) blockers.push(b);
  if (snapshot?.ok) {
    meta = P.buildStoreMeta({
      tool: "evals/run.mjs",
      runId,
      arm: ARM,
      phase: PHASE,
      projectId: snapshot.project_id,
      configHash: snapshot.config_hash,
      snapshotSha256: snapshot.snapshot_sha256,
      artifactHashes: snapshot.artifact_hashes,
      setPath: P.displayPath(REPO, SET_PATH),
      setSha256: setSha,
      scheduleSha256: planReport?.hashes?.schedule_sha256 ?? plan?.schedule?.sha256 ?? null,
      harnessGit: P.gitRevision(REPO),
      batch: plan?.batch || BATCH,
    });
  }
  if (!effectiveUrl) {
    blockers.push({ code: "url-required", message: "a published agent URL is required (--url or snapshot.agent.public_url)" });
  } else {
    if (URL_ARG && snapshot?.normalized?.agent?.public_url
        && P.normalizeUrlForCompare(URL_ARG) !== P.normalizeUrlForCompare(snapshot.normalized.agent.public_url)) {
      blockers.push({ code: "url-snapshot-mismatch", message: "--url does not match snapshot.agent.public_url" });
    }
    const pre = P.validateObservedUrl(effectiveUrl, { expected: effectiveUrl, projectId: snapshot?.project_id });
    for (const b of pre.blockers) blockers.push(b);
  }
  try {
    store = P.loadStore(outPath);
  } catch (e) {
    blockers.push({ code: "store-unreadable", message: String(e.message || e) });
  }
  if (store && meta) {
    resume = P.checkResume(store, meta);
    for (const b of resume.blockers) blockers.push(b);
    for (const w of resume.warnings) warnings.push(w);
  }
  sidecarPath = P.defaultSidecarPath({ repoRoot: REPO, batch: plan?.batch || BATCH, runId });
} else {
  outPath = OUT_ARG ? resolve(OUT_ARG) : resolve(REPO, "evals", "results", `${ARM}.json`);
  if (existsSync(outPath) && !ALLOW_EXISTING_OUT) {
    blockers.push({
      code: "legacy-output-exists",
      message: `legacy run would touch an existing file (${P.displayPath(REPO, outPath)}); add --allow-existing-out to append deliberately`,
    });
  }
  try {
    store = P.loadStore(outPath);
  } catch (e) {
    blockers.push({ code: "store-unreadable", message: String(e.message || e) });
  }
  warnings.push({ code: "legacy-unverified", message: "this run is explicitly unverified: no snapshot, config hash, phase, or target binding will be recorded" });
}

/* Count planned work offline, using the existing store when resuming. */
let planned = picks.length * TRIALS;
let skipped = 0;
let retries = 0;
if (store) {
  for (const sc of picks) {
    for (let trial = TRIAL_BASE; trial < TRIAL_BASE + TRIALS; trial++) {
      const prior = P.nextAttempt(store, sc.id, trial);
      if (prior.complete) skipped++;
      else if (prior.attempt > 1) retries++;
    }
  }
}

const offlineReport = {
  schema: "agentplace-run-offline-report-v1",
  tool: "evals/run.mjs",
  mode: MODE,
  legacy_unverified: LEGACY,
  provenance: !LEGACY,
  arm: ARM,
  phase: PHASE,
  run_id: runId,
  project_id: snapshot?.project_id ?? null,
  config_hash: snapshot?.config_hash ?? null,
  snapshot_path: snapshot ? P.displayPath(REPO, snapshot.path) : null,
  snapshot_sha256: snapshot?.snapshot_sha256 ?? null,
  set_path: P.displayPath(REPO, SET_PATH),
  set_sha256: P.sha256File(SET_PATH),
  out_path: P.displayPath(REPO, outPath),
  sidecar_path: sidecarPath ? P.displayPath(REPO, sidecarPath) : null,
  planned_records: planned,
  already_valid: skipped,
  retry_attempts: retries,
  pending_records: planned - skipped,
  resume: resume ? { ok: resume.ok, blockers: resume.blockers, warnings: resume.warnings } : null,
  harness_git: P.gitRevision(REPO),
  blockers,
  warnings,
};

if (AS_JSON) console.log(JSON.stringify(offlineReport, null, 1));
else {
  console.log(`mode       : ${MODE}${LEGACY ? " (legacy-unverified)" : " (provenance-bound)"}`);
  console.log(`arm        : ${ARM}`);
  console.log(`phase      : ${PHASE ?? "(none)"}`);
  console.log(`run id     : ${runId ?? "(none)"}`);
  console.log(`project    : ${snapshot?.project_id ?? "(none)"}`);
  console.log(`config     : ${snapshot?.config_hash ?? "(none)"}`);
  console.log(`snapshot   : ${snapshot ? P.displayPath(REPO, snapshot.path) : "(none)"}`);
  console.log(`set        : ${P.displayPath(REPO, SET_PATH)} ${offlineReport.set_sha256.slice(0, 12)}`);
  console.log(`out        : ${P.displayPath(REPO, outPath)}`);
  console.log(`sidecar    : ${sidecarPath ? P.displayPath(REPO, sidecarPath) : "(none)"}`);
  console.log(`planned    : ${planned} (${skipped} already valid, ${retries} retries, ${planned - skipped} pending)`);
  console.log(`git        : ${offlineReport.harness_git.slice(0, 12)}`);
  if (warnings.length) { console.error("\nwarnings:"); printIssues([], warnings); }
  if (blockers.length) { console.error("\nblockers:"); printIssues(blockers, []); }
}

if (OFFLINE) process.exit(blockers.length ? 1 : 0);
if (blockers.length) {
  die(blockers.some((b) => /resume/.test(b.code)) ? 4 : 1, "offline validation failed; no browser access was attempted");
}

/* --------------------------------------------------------- browser capture */

const tab = browser.tab(TAB);
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
    }, { args: [effectiveUrl] });
  } catch {}
  for (let i = 0; i < 3; i++) {
    await tab.goto(effectiveUrl);
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

async function checkTarget() {
  const observed = await tab.url();
  const check = P.validateObservedUrl(observed, { expected: effectiveUrl, projectId: snapshot?.project_id });
  if (!check.ok) {
    const err = new Error("target-url: " + check.blockers.map((b) => b.message).join("; "));
    err.blockers = check.blockers;
    throw err;
  }
  return { observed, binding: check.binding, warnings: check.warnings };
}

if (!store) {
  store = LEGACY
    ? { arm: ARM, agent: URL_ARG, records: [] }
    : { arm: ARM, agent: `project:${snapshot.project_id}`, meta, records: [] };
} else if (!LEGACY && !store.meta) {
  store.meta = meta;
}

async function persist() {
  await mkdir(dirname(outPath), { recursive: true });
  await Bun.write(outPath, JSON.stringify(store, null, 1));
}

async function recordRaw({ sc, trial, attempt, pair, status, reason, observed, binding }) {
  if (LEGACY || !sidecarPath) return;
  try {
    await P.appendSidecar(sidecarPath, {
    schema: "agentplace-raw-provenance-v1",
    run_id: runId,
    phase: PHASE,
    arm: ARM,
    project_id: snapshot.project_id,
    scenario_id: sc.id,
    trial,
    attempt,
    pair_id: pair,
    tab: TAB,
    observed_url: observed ?? null,
    target_url_binding: binding ?? "declared-unverified",
    at: new Date().toISOString(),
      status,
      invalid_reason: reason ?? null,
    });
  } catch (e) {
    console.error(`sidecar write failed: ${String(e.message || e)}`);
  }
}

const pairOf = (sc, trial) => (plan?.schedule ? P.pairId(runId, sc.id, trial) : null);

let sent = 0;
let invalid = 0;

for (const sc of picks) {
  for (let trial = TRIAL_BASE; trial < TRIAL_BASE + TRIALS; trial++) {
    const prior = P.nextAttempt(store, sc.id, trial);
    if (prior.complete) continue;
    const attempt = prior.attempt;
    const pair = pairOf(sc, trial);
    let observed = null;
    let binding = "declared-unverified";
    try {
      await reset();
      const target = await checkTarget();
      observed = target.observed;
      binding = target.binding;
      const before = (await tab.text()).length;
      console.log(`▶ ${sc.id}#${trial}${attempt > 1 ? ` (attempt ${attempt})` : ""} — ${sc.customer.slice(0, 60)}`);
      const t0 = Date.now();
      await send(sc.customer);
      const thread = await settle(before);
      const ms = Date.now() - t0;
      const afterTarget = await checkTarget();
      observed = afterTarget.observed;
      binding = afterTarget.binding;
      const health = P.classifyThread(thread, sc.customer);
      const provenance = LEGACY
        ? { legacy_unverified: true, captured_at: new Date().toISOString(), arm: ARM }
        : P.makeRecordProvenance({
            runId, phase: PHASE, arm: ARM, scenarioId: sc.id, trial, pair,
            projectId: snapshot.project_id, configHash: snapshot.config_hash,
            snapshotPath: P.displayPath(REPO, snapshot.path),
            snapshotSha256: snapshot.snapshot_sha256,
            artifactHashes: snapshot.artifact_hashes,
            setId: P.displayPath(REPO, SET_PATH),
            setPath: P.displayPath(REPO, SET_PATH),
            setSha256: offlineReport.set_sha256,
            scheduleSha256: planReport?.hashes?.schedule_sha256 ?? plan?.schedule?.sha256 ?? null,
            harnessGit: P.gitRevision(REPO),
            tab: TAB, observedUrl: observed, binding,
          });
      if (!health.valid) {
        store.records.push({
          id: sc.id, trial, attempt, split: sc.split, lane: sc.lane, customer: sc.customer,
          status: "invalid", invalid_reason: health.reason, chars: thread.length, ms,
          at: new Date().toISOString(), error: `invalid capture: ${health.reason}`, provenance,
        });
        invalid++;
        await persist();
        await recordRaw({ sc, trial, attempt, pair, status: "invalid", reason: health.reason, observed, binding });
        console.log(`  ✗ invalid (${health.reason}) — attempt retained`);
        if (health.reason === "quota-message") { console.log("\nquota hit — stopping"); process.exit(3); }
        continue;
      }
      store.records.push({
        id: sc.id, trial, attempt, split: sc.split, lane: sc.lane,
        customer: sc.customer,
        thread,
        chars: thread.length,
        ms,
        at: new Date().toISOString(),
        status: "valid",
        provenance,
      });
      sent++;
      await persist();
      await recordRaw({ sc, trial, attempt, pair, status: "valid", observed, binding });
      console.log(`  ✓ ${thread.length} chars, ${(ms/1000).toFixed(1)}s, ${store.records.length} total`);
    } catch (e) {
      if (e && e.name === "RunnerExit") throw e;
      const msg = String(e.message || e);
      const reason = msg.startsWith("target-url:") ? "target-url" : (/quota/i.test(msg) ? "quota-message" : "harness-error");
      console.log(`  ✗ ${msg.slice(0, 120)}`);
      const provenance = LEGACY
        ? { legacy_unverified: true, captured_at: new Date().toISOString(), arm: ARM }
        : P.makeRecordProvenance({
            runId, phase: PHASE, arm: ARM, scenarioId: sc.id, trial, pair,
            projectId: snapshot.project_id, configHash: snapshot.config_hash,
            snapshotPath: P.displayPath(REPO, snapshot.path),
            snapshotSha256: snapshot.snapshot_sha256,
            artifactHashes: snapshot.artifact_hashes,
            setId: P.displayPath(REPO, SET_PATH),
            setPath: P.displayPath(REPO, SET_PATH),
            setSha256: offlineReport.set_sha256,
            scheduleSha256: planReport?.hashes?.schedule_sha256 ?? plan?.schedule?.sha256 ?? null,
            harnessGit: P.gitRevision(REPO),
            tab: TAB, observedUrl: observed, binding,
          });
      store.records.push({
        id: sc.id, trial, attempt, split: sc.split, lane: sc.lane, customer: sc.customer,
        status: "invalid", invalid_reason: reason, error: msg,
        at: new Date().toISOString(), provenance,
      });
      invalid++;
      await persist();
      await recordRaw({ sc, trial, attempt, pair, status: "invalid", reason, observed, binding });
      if (reason === "quota-message") { console.log("\nquota hit — stopping"); process.exit(3); }
    }
  }
}

console.log(`\n${sent} valid, ${invalid} invalid attempt(s) retained -> ${outPath}`);
