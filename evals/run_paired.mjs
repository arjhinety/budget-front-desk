#!/usr/bin/env bun
/**
 * Counterbalanced paired executor — browser entry.
 *
 * Prepared immutable inputs only:
 *   bun evals/run_paired.mjs --schedule <schedule.json> --phase capture \
 *     --arm-snapshot A0=<snap0.json> --arm-plan A0=<plan0.json> \
 *     --arm-snapshot A2=<snap2.json> --arm-plan A2=<plan2.json> \
 *     [--url <published-agent>] [--batch b1] [--dry-run] [--json]
 *
 * Each cell is executed by evaluating evals/run.mjs in this same runtime, with
 * a synthetic argv and a process.exit that is caught instead of terminating the
 * executor. The runner's own gates (snapshot/phase/plan, URL, resume, attempt
 * retention, private sidecar) remain in force. This entry never writes a record
 * itself.
 *
 * --dry-run validates the immutable inputs, reads the arm stores, and reports
 * paired completeness without invoking the runner, the browser, or the network.
 *
 * A schedule with reps > 1, a plan without a schedule binding, a changed
 * schedule hash, a snapshot that is not current-effective, or an unreadable
 * store is refused before any cell runs.
 *
 * Exit codes: 0 complete/ready, 1 blocked/incomplete, 2 usage, 3 quota stopped.
 */

const RAW = process.argv.slice(2);
const has = (name) => RAW.includes(`--${name}`);
const opt = (name, dflt) => { const i = RAW.indexOf(`--${name}`); return i >= 0 ? RAW[i + 1] : dflt; };

const HELP = `evals/run_paired.mjs — counterbalanced paired executor

Required:
  --schedule <file>          immutable agentplace-pair-schedule-v1
  --phase <phase>            must match every arm plan
  --arm-snapshot ARM=path    one verified snapshot per scheduled arm
  --arm-plan ARM=path        one run plan per arm, bound to the schedule sha256

Optional:
  --url <url>                published agent URL for every arm (or snapshot.agent.public_url)
  --batch <name>             private batch label (default "next")
  --out-dir <dir>            private output directory (default under agentplace-private)
  --max-cells <n>            stop after n invocations
  --allow-existing-out       permit resuming existing private stores/state
  --allow-repo-out           permit an output directory inside this repository
  --tab agent-pub            existing browser tab name
  --dry-run | --preflight-only
                             no runner/browser/network; validation and completeness only
  --json                     machine-readable report
  --help                     print this text; reads and writes nothing

The executor alternates the declared AB/BA order, skips only valid cells, leaves
the counterpart pending when the first cell fails, retains invalid attempts, and
writes a private paired-state JSON. It never claims a pair without both valid
records and ordered capture timestamps.
`;

if (has("help") || RAW.includes("-h")) {
  console.log(HELP);
  process.exit(0);
}

const { resolve, dirname, join, isAbsolute } = await import("node:path");
const { pathToFileURL } = await import("node:url");
const { existsSync } = await import("node:fs");
const { mkdir, writeFile } = await import("node:fs/promises");

function loadRepoRoot() {
  const starts = [process.cwd()];
  if (process.argv[1]) starts.push(dirname(resolve(process.argv[1])));
  for (const start of starts) {
    let dir = resolve(start);
    for (let i = 0; i < 10; i++) {
      if (existsSync(join(dir, "evals", "provenance.mjs"))) return dir;
      const parent = dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return null;
}

const REPO = loadRepoRoot();
if (!REPO) {
  console.error("error: cannot locate the project root (evals/provenance.mjs) from the working directory");
  process.exit(2);
}
const P = await import(pathToFileURL(join(REPO, "evals", "provenance.mjs")).href);
const CORE = await import(pathToFileURL(join(REPO, "evals", "paired_core.mjs")).href);

const { flags } = P.parseFlags(RAW);
const scheduleArg = flags.schedule;
const phase = flags.phase;
if (typeof scheduleArg !== "string") {
  console.error("error: --schedule is required");
  process.exit(2);
}
if (typeof phase !== "string" || !phase.trim()) {
  console.error("error: --phase is required");
  process.exit(2);
}

function pairMap(name) {
  const out = {};
  for (const spec of P.flagList(flags[name])) {
    const idx = spec.indexOf("=");
    if (idx < 1) {
      console.error(`error: --${name} must be ARM=path (got ${spec})`);
      process.exit(2);
    }
    out[spec.slice(0, idx)] = spec.slice(idx + 1);
  }
  return out;
}

const snapshots = pairMap("arm-snapshot");
const plans = pairMap("arm-plan");
const dryRun = has("dry-run") || has("preflight-only");
const batch = opt("batch", "next");
const url = opt("url", "");
const tab = opt("tab", "agent-pub");
const allowRepoOut = has("allow-repo-out");
const allowExistingOut = has("allow-existing-out");
const maxCells = opt("max-cells", null);
const maxCellsNum = maxCells === null ? Infinity : Number(maxCells);
if (!(maxCellsNum === Infinity || (Number.isInteger(maxCellsNum) && maxCellsNum > 0))) {
  console.error("error: --max-cells must be a positive integer");
  process.exit(2);
}
const asJson = has("json");

const validation = CORE.validatePairedInputs({
  schedulePath: scheduleArg,
  phase,
  snapshotsByArm: snapshots,
  plansByArm: plans,
  repoRoot: REPO,
  batch,
  outDir: opt("out-dir", null),
  allowRepoOut,
  allowExistingOut,
  url,
  dryRun,
});

function printValidation() {
  console.log(`schedule : ${validation.scheduleSha ? validation.scheduleSha.slice(0, 16) : "(unread)"}`);
  console.log(`run id   : ${validation.schedule?.run_id ?? "(none)"}`);
  console.log(`phase    : ${phase}`);
  console.log(`pairs    : ${validation.schedule?.pairs?.length ?? 0}`);
  console.log(`state    : ${validation.statePath ? P.displayPath(REPO, validation.statePath) : "(none)"}`);
  for (const arm of validation.schedule?.arms || []) {
    const context = validation.arms[arm];
    console.log(`arm ${arm}  : snapshot ${context?.snapshotDisplay ?? "(missing)"} config ${context?.snapshot?.config_hash?.slice(0, 12) ?? "(none)"}`);
    console.log(`          plan ${context?.planDisplay ?? "(missing)"} store ${context?.storeDisplay ?? "(none)"}`);
  }
  for (const warning of validation.warnings) console.error(`  ! [${warning.code}] ${warning.message}`);
  for (const b of validation.blockers) console.error(`  ✗ [${b.code}] ${b.message}`);
}

if (!validation.ok) {
  if (asJson) console.log(JSON.stringify({ schema: "agentplace-paired-report-v1", dry_run: dryRun, validation }, null, 1));
  else printValidation();
  console.error("\nblocked before any cell; no browser access was attempted");
  process.exit(1);
}

async function loadArmStore(arm) {
  return P.loadStore(validation.arms[arm].storePath);
}

if (dryRun) {
  const rehearsal = await CORE.runPaired({
    schedule: validation.schedule,
    scheduleSha: validation.scheduleSha,
    phase,
    armContexts: validation.arms,
    loadArmStore,
    invokeCell: async () => ({ code: 0 }),
    dryRun: true,
    maxCells: 0,
  });
  const report = {
    schema: "agentplace-paired-report-v1",
    dry_run: true,
    validation,
    rehearsal: {
      status: rehearsal.status,
      cells_planned: rehearsal.cells_planned,
      declared_pairs: rehearsal.summary.declared_pairs,
      completed_pairs: rehearsal.summary.completed_pairs,
      pending_pairs: rehearsal.summary.pending_pairs,
    },
  };
  if (asJson) console.log(JSON.stringify(report, null, 1));
  else {
    printValidation();
    if (rehearsal.status === "blocked") {
      console.log(`\nDRY RUN — blocked: ${rehearsal.stop_reason}`);
      for (const b of rehearsal.blockers || []) console.error(`  ✗ [${b.code}] ${b.message}`);
      process.exit(1);
    }
    console.log(`\nDRY RUN — no browser, no runner, no network`);
    console.log(`pairs     : ${rehearsal.summary.completed_pairs}/${rehearsal.summary.declared_pairs} complete, ${rehearsal.summary.pending_pairs} pending`);
    console.log(`cells     : ${rehearsal.cells_planned} would be invoked`);
    for (const pair of rehearsal.summary.pairs) {
      const arms = Object.entries(pair.records).map(([arm, value]) => `${arm}:${value ?? "pending"}`).join(" ");
      console.log(`  ${pair.order} ${pair.scenario}#${pair.trial} ${pair.status} (${arms})`);
    }
  }
  if (rehearsal.status === "blocked") process.exit(1);
  process.exit(0);
}

const browserGlobal = typeof browser !== "undefined" ? browser : globalThis.browser;
if (!browserGlobal) {
  console.error("blocked: no browser runtime is available; run this entry inside the session browser runtime");
  process.exit(2);
}

const runSource = join(REPO, "evals", "run.mjs");
const source = (await Bun.file(runSource).text()).replace(/^#!.*\r?\n/, "");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const cellFunction = new AsyncFunction("browser", "Bun", "process", source);

class RunnerExit extends Error {
  constructor(code) {
    super(`runner exited ${code}`);
    this.name = "RunnerExit";
    this.code = code;
  }
}

const statePath = validation.statePath;
async function persistState(state) {
  await mkdir(dirname(statePath), { recursive: true });
  await writeFile(statePath, JSON.stringify(state, null, 1) + "\n", "utf8");
}

function invokeRunner({ arm, scenario, trial, context }) {
  const planSet = context.plan?.set?.path;
  const setPath = planSet
    ? (isAbsolute(planSet) ? planSet : resolve(dirname(context.planPath), planSet))
    : null;
  const argv = [
    "bun", runSource,
    "--arm", arm,
    "--snapshot", context.snapshotPath,
    "--phase", phase,
    "--run-plan", context.planPath,
    "--ids", scenario,
    "--trials", "1",
    "--trial", String(trial),
    "--out", context.storePath,
    "--batch", batch,
    "--tab", tab,
    "--allow-existing-out",
  ];
  if (setPath) argv.push("--set", setPath);
  if (url) argv.push("--url", url);
  if (allowRepoOut) argv.push("--allow-repo-out");
  const fakeProcess = {
    argv,
    cwd: () => process.cwd(),
    env: process.env,
    exit: (code) => { throw new RunnerExit(Number(code) || 0); },
  };
  return cellFunction(browserGlobal, Bun, fakeProcess)
    .then(() => ({ code: 0 }))
    .catch((e) => {
      if (e instanceof RunnerExit) return { code: e.code, message: e.message };
      return { code: 1, message: String(e.message || e) };
    });
}

const checkSchedule = () => {
  try {
    const now = P.sha256File(resolve(scheduleArg));
    return now === validation.scheduleSha
      ? { ok: true }
      : { ok: false, message: "schedule bytes changed during the run" };
  } catch (e) {
    return { ok: false, message: `cannot re-read schedule: ${String(e.message || e)}` };
  }
};

const result = await CORE.runPaired({
  schedule: validation.schedule,
  scheduleSha: validation.scheduleSha,
  phase,
  armContexts: validation.arms,
  loadArmStore,
  invokeCell: invokeRunner,
  persistState,
  dryRun: false,
  maxCells: maxCellsNum,
  checkSchedule,
});

const report = {
  schema: "agentplace-paired-report-v1",
  dry_run: false,
  run_id: validation.schedule.run_id,
  phase,
  status: result.status,
  stop_reason: result.stop_reason,
  cells_invoked: result.cells_invoked ?? 0,
  invalid_attempts_retained: result.invalid_attempts ?? 0,
  declared_pairs: result.summary.declared_pairs,
  completed_pairs: result.summary.completed_pairs,
  pending_pairs: result.summary.pending_pairs,
  state_path: P.displayPath(REPO, statePath),
  blockers: result.blockers,
};
if (asJson) console.log(JSON.stringify(report, null, 1));
else {
  console.log(`\npaired run: ${result.status}${result.stop_reason ? ` (${result.stop_reason})` : ""}`);
  console.log(`pairs     : ${result.summary.completed_pairs}/${result.summary.declared_pairs} complete, ${result.summary.pending_pairs} pending`);
  console.log(`cells     : ${result.cells_invoked ?? 0} invoked, ${result.invalid_attempts ?? 0} invalid attempt(s) retained`);
  console.log(`state     : ${P.displayPath(REPO, statePath)}`);
  for (const b of result.blockers || []) console.error(`  ✗ [${b.code}] ${b.message}`);
}
if (result.status === "complete") process.exit(0);
if (result.stop_reason === "quota") process.exit(3);
process.exit(1);
