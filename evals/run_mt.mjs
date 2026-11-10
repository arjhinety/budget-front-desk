#!/usr/bin/env bun
/**
 * Drive a multi-turn script against the published agent and record each reply
 * separately.
 *
 * Provenance-bound (default, fail-closed):
 *   bun evals/run_mt.mjs --arm MT-A5 --phase capture \
 *     --snapshot ../agentplace-private/capture/b1/snapshot.json \
 *     --run-plan ../agentplace-private/capture/b1/run-plan-MT-A5-capture.json \
 *     --url https://<published-agent> --trials 3
 *
 * Offline rehearsal (never evaluates `browser`):
 *   bun evals/run_mt.mjs --dry-run --snapshot <snap> --phase capture --url <url>
 *   bun evals/run_mt.mjs --preflight-only --snapshot <snap> --phase capture
 *
 * Deliberately unverified historical-style run (explicit opt-in):
 *   bun evals/run_mt.mjs --legacy-unverified --arm MT-A5 --url https://...
 *
 * The reply for turn k is the difference between the page text before and after
 * that turn, so the transcript does not have to be parsed to find turn
 * boundaries. That matters because the agent's replies contain the customer's
 * own words.
 */

const RAW = process.argv.slice(2);
const has = (name) => RAW.includes(`--${name}`);
const opt = (name, dflt) => { const i = RAW.indexOf(`--${name}`); return i >= 0 ? RAW[i + 1] : dflt; };

const HELP = `evals/run_mt.mjs — multi-turn capture with provenance

Required for a provenance-bound run:
  --snapshot <file>     verified effective-config snapshot (private)
  --phase <phase>       recorded and resume-checked
  --run-plan <file>     optional plan; --snapshot/--phase/--arm are accepted as the equivalent
  --url <url>           published agent URL (or snapshot.agent.public_url)

Optional:
  --arm MT  --trials 3  --ids MT-C01,...
  --set evals/scenarios-mt.json
  --out <file>          default: private ../agentplace-private/capture/<batch>/runs/<run>/...
  --batch <name>  --tab agent-pub
  --allow-repo-out  --allow-existing-out
  --dry-run | --preflight-only   offline only; no browser, no network
  --legacy-unverified   explicitly allow a historical-style run without provenance
  --json                machine-readable offline report
  --help                print this text; reads and writes nothing

Exit codes: 0 ok, 1 blocked/invalid, 2 usage, 3 quota, 4 resume refused.
`;

if (has("help") || RAW.includes("-h")) {
  console.log(HELP);
  process.exit(0);
}

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

const TAB = opt("tab", "agent-pub");
const URL_ARG = opt("url", "");
const ARM = opt("arm", "MT");
let TRIALS = Number(opt("trials", "3"));
const ONLY = opt("ids", "");
const SET_ARG = opt("set", "evals/scenarios-mt.json");
const SNAPSHOT_ARG = opt("snapshot", null);
const PHASE = opt("phase", null);
const PLAN_ARG = opt("run-plan", opt("run_plan", null));
const LEGACY = has("legacy-unverified");
const OUT_ARG = opt("out", null);
const BATCH = opt("batch", "next");
const ALLOW_REPO_OUT = has("allow-repo-out");
const ALLOW_EXISTING_OUT = has("allow-existing-out");
const AS_JSON = has("json");

const SET_PATH = isAbsolute(SET_ARG)
  ? SET_ARG
  : (SET_ARG.includes("/") || SET_ARG.endsWith(".json")
      ? resolve(REPO, SET_ARG)
      : resolve(REPO, "evals", `${SET_ARG}.json`));

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
const ALL_SCRIPTS = cfg.scripts || cfg.scenarios || [];
if (!Array.isArray(ALL_SCRIPTS) || !ALL_SCRIPTS.length) {
  die(2, "scenario set has no scripts/scenarios array");
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
    if (plan && plan.trials !== undefined && plan.trials !== null && !RAW.includes("--trials")) {
      TRIALS = Number(plan.trials);
    }
    for (const b of planReport.blockers) blockers.push(b);
    for (const w of planReport.warnings) warnings.push(w);
    if (plan) {
      if (plan.arm && plan.arm !== ARM) blockers.push({ code: "plan-arm-mismatch", message: `plan arm ${plan.arm} does not match --arm ${ARM}` });
      if (plan.phase && PHASE && plan.phase !== PHASE) blockers.push({ code: "plan-phase-mismatch", message: `plan phase ${plan.phase} does not match --phase ${PHASE}` });
      if (plan.trials !== undefined && plan.trials !== null && Number(plan.trials) !== TRIALS) {
        blockers.push({ code: "plan-trials-mismatch", message: `plan trials ${plan.trials} does not match --trials ${TRIALS}` });
      }
      if (plan.ids && ONLY) {
        const a = [...plan.ids].sort().join(",");
        const b = [...ONLY.split(",").map((s) => s.trim()).filter(Boolean)].sort().join(",");
        if (a !== b) blockers.push({ code: "plan-ids-mismatch", message: "plan ids do not match --ids" });
      }
    }
  }
}

let picks = ALL_SCRIPTS;
const effectiveIds = ONLY ? ONLY.split(",").map((s) => s.trim()).filter(Boolean) : plan?.ids ?? null;
if (effectiveIds) picks = picks.filter((s) => effectiveIds.includes(s.id));
if (!picks.length) blockers.push({ code: "no-scenarios", message: "no scripts matched --ids/plan" });
if (!Number.isInteger(TRIALS) || TRIALS < 1) blockers.push({ code: "trials", message: "--trials must be a positive integer" });

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
      tool: "evals/run_mt.mjs",
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
  if (!URL_ARG) blockers.push({ code: "url-required", message: "--url is required" });
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

let planned = picks.length * TRIALS;
let skipped = 0;
let retries = 0;
if (store) {
  for (const s of picks) {
    for (let trial = 1; trial <= TRIALS; trial++) {
      const prior = P.nextAttempt(store, s.id, trial);
      if (prior.complete) skipped++;
      else if (prior.attempt > 1) retries++;
    }
  }
}

const offlineReport = {
  schema: "agentplace-run-offline-report-v1",
  tool: "evals/run_mt.mjs",
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

async function reset() {
  try { await tab.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); } catch {}
  for (let i = 0; i < 3; i++) {
    await tab.goto(effectiveUrl);
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

async function checkTarget() {
  const observed = await tab.url();
  const check = P.validateObservedUrl(observed, { expected: effectiveUrl, projectId: snapshot?.project_id });
  if (!check.ok) {
    const err = new Error("target-url: " + check.blockers.map((b) => b.message).join("; "));
    err.blockers = check.blockers;
    throw err;
  }
  return { observed, binding: check.binding };
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

async function recordRaw({ s, trial, attempt, pair, status, reason, observed, binding, turnsCompleted }) {
  if (LEGACY || !sidecarPath) return;
  try {
    await P.appendSidecar(sidecarPath, {
    schema: "agentplace-raw-provenance-v1",
    run_id: runId,
    phase: PHASE,
    arm: ARM,
    project_id: snapshot.project_id,
    scenario_id: s.id,
    trial,
    attempt,
    pair_id: pair,
    tab: TAB,
    observed_url: observed ?? null,
    target_url_binding: binding ?? "declared-unverified",
    at: new Date().toISOString(),
      status,
      invalid_reason: reason ?? null,
      turns_completed: turnsCompleted ?? 0,
    });
  } catch (e) {
    console.error(`sidecar write failed: ${String(e.message || e)}`);
  }
}

const pairOf = (s, trial) => (plan?.schedule ? P.pairId(runId, s.id, trial) : null);
const provenanceFor = (s, trial, pair, observed, binding) => LEGACY
  ? { legacy_unverified: true, captured_at: new Date().toISOString(), arm: ARM }
  : P.makeRecordProvenance({
      runId, phase: PHASE, arm: ARM, scenarioId: s.id, trial, pair,
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

let n = 0;
let invalid = 0;

for (const s of picks) {
  for (let trial = 1; trial <= TRIALS; trial++) {
    const prior = P.nextAttempt(store, s.id, trial);
    if (prior.complete) continue;
    const attempt = prior.attempt;
    const pair = pairOf(s, trial);
    let observed = null;
    let binding = "declared-unverified";
    let replies = [];
    let turnsCompleted = 0;
    try {
      await reset();
      const target = await checkTarget();
      observed = target.observed;
      binding = target.binding;
      console.log(`▶ ${s.id}#${trial}${attempt > 1 ? ` (attempt ${attempt})` : ""} — ${s.family} (${s.turns.length} turns)`);
      for (const turn of s.turns) {
        await send(turn);
        const after = await settle();
        const afterTarget = await checkTarget();
        observed = afterTarget.observed;
        binding = afterTarget.binding;
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
        const health = P.classifyReply(reply);
        replies.push(reply);
        if (!health.valid) {
          const err = new Error(`turn ${turnsCompleted + 1}: ${health.reason}`);
          err.invalidReason = health.reason;
          throw err;
        }
        turnsCompleted++;
      }
      store.records.push({
        id: s.id, family: s.family, trial, attempt, turns: s.turns, replies,
        turns_completed: turnsCompleted, status: "valid",
        at: new Date().toISOString(),
        provenance: provenanceFor(s, trial, pair, observed, binding),
      });
      n++;
      await persist();
      await recordRaw({ s, trial, attempt, pair, status: "valid", observed, binding, turnsCompleted });
      console.log(`  ✓ ${replies.length} replies, ${replies.map((r) => r.length).join("/")} chars`);
    } catch (e) {
      if (e && e.name === "RunnerExit") throw e;
      const msg = String(e.message || e);
      const reason = e.invalidReason || (msg.startsWith("target-url:") ? "target-url" : (/quota/i.test(msg) ? "quota-message" : "harness-error"));
      console.log(`  ✗ ${msg.slice(0, 90)}`);
      store.records.push({
        id: s.id, family: s.family, trial, attempt, turns: s.turns, replies,
        turns_completed: turnsCompleted, status: "invalid", invalid_reason: reason, error: msg,
        at: new Date().toISOString(),
        provenance: provenanceFor(s, trial, pair, observed, binding),
      });
      invalid++;
      await persist();
      await recordRaw({ s, trial, attempt, pair, status: "invalid", reason, observed, binding, turnsCompleted });
      if (reason === "quota-message") { console.log("\nquota hit — stopping"); process.exit(3); }
    }
  }
}
console.log(`\n${n} valid, ${invalid} invalid attempt(s) retained -> ${outPath}`);
