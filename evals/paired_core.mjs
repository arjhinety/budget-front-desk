/**
 * Counterbalanced paired executor — offline core.
 *
 * This module is pure orchestration: it reads a prepared immutable schedule and
 * per-arm snapshots/plans, decides which cell is next, invokes a cell function,
 * reloads the arm store, and persists a paired state file. It never touches the
 * browser or the network. The browser entry point is evals/run_paired.mjs; the
 * production cell function evaluates evals/run.mjs in the current runtime.
 *
 * Semantics:
 *   * Only pairs declared in the schedule are executed, in the declared AB/BA
 *     order.
 *   * A cell with a valid record is skipped. An invalid attempt is retained by
 *     the runner and retried with a new attempt number.
 *   * If the first arm of a pair is invalid, the counterpart is left pending,
 *     because running it later would break the declared order.
 *   * Quota, resume/hash refusal, or a missing record stops the run; the state
 *     file records the exact reason and every unstarted counterpart stays
 *     pending.
 *   * No completed pair is ever claimed without both valid records and capture
 *     timestamps that prove the declared order (see summarizePairs).
 */

import { readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import {
  SCHEDULE_SCHEMA,
  assertSafeOutput,
  buildStoreMeta,
  checkResume,
  defaultRecordPath,
  displayPath,
  gitRevision,
  isValidRecord,
  nextAttempt,
  normalizeUrlForCompare,
  privateRoot,
  sha256File,
  summarizePairs,
  validateRunPlan,
  verifySnapshot,
} from "./provenance.mjs";

export const PAIRED_STATE_SCHEMA = "agentplace-paired-state-v1";

function blocker(code, message) {
  return { code, message };
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function latestCell(store, scenario, trial) {
  const records = (store?.records || [])
    .filter((r) => r && r.id === scenario && Number(r.trial) === Number(trial))
    .sort((a, b) => (Number(b.attempt) || 1) - (Number(a.attempt) || 1));
  return records[0] || null;
}

export function cellState(store, scenario, trial) {
  const record = latestCell(store, scenario, trial);
  if (!record) return { status: "pending" };
  return {
    status: isValidRecord(record) ? "valid" : "invalid",
    attempt: Number(record.attempt) || 1,
    reason: record.invalid_reason ?? (record.error ? String(record.error).slice(0, 160) : null),
  };
}

export function buildPairedState({
  schedule, scheduleSha, phase, armContexts, stores, status, stopReason,
  startedAt, cellsInvoked = 0, invalidAttempts = 0,
}) {
  const summary = summarizePairs(schedule, stores);
  return {
    schema: PAIRED_STATE_SCHEMA,
    run_id: schedule.run_id,
    phase,
    schedule_sha256: scheduleSha,
    status,
    stop_reason: stopReason,
    started_at: startedAt,
    updated_at: new Date().toISOString(),
    cells_invoked: cellsInvoked,
    invalid_attempts_retained: invalidAttempts,
    declared_pairs: summary.declared_pairs,
    completed_pairs: summary.completed_pairs,
    pending_pairs: summary.pending_pairs,
    arm_snapshots: Object.fromEntries(
      schedule.arms.map((arm) => [arm, {
        path: armContexts[arm]?.snapshotDisplay ?? null,
        sha256: armContexts[arm]?.snapshot?.snapshot_sha256 ?? null,
        config_hash: armContexts[arm]?.snapshot?.config_hash ?? null,
      }]),
    ),
    arm_plans: Object.fromEntries(
      schedule.arms.map((arm) => [arm, {
        path: armContexts[arm]?.planDisplay ?? null,
        sha256: armContexts[arm]?.planSha ?? null,
        store_path: armContexts[arm]?.storeDisplay ?? null,
      }]),
    ),
    pairs: summary.pairs.map((pair) => ({
      pair_id: pair.pair_id,
      scenario: pair.scenario,
      trial: pair.trial,
      order: pair.order,
      status: pair.status,
      order_evidence: pair.order_evidence,
      arms: Object.fromEntries(
        pair.arms.map((arm) => [arm, cellState(stores[arm], pair.scenario, pair.trial)]),
      ),
    })),
  };
}

/**
 * Validate the immutable inputs. Returns blockers before any invocation.
 * `snapshotsByArm` and `plansByArm` map arm -> path.
 */
export function validatePairedInputs({
  schedulePath, phase, snapshotsByArm = {}, plansByArm = {}, repoRoot,
  batch = "next", outDir = null, allowRepoOut = false, allowExistingOut = false,
  url = "", dryRun = false,
}) {
  const blockers = [];
  const warnings = [];
  const resolvedSchedule = resolve(schedulePath);
  let schedule = null;
  let scheduleSha = null;
  try {
    scheduleSha = sha256File(resolvedSchedule);
    schedule = readJson(resolvedSchedule);
  } catch (e) {
    blockers.push(blocker("paired-schedule-unreadable", `cannot read schedule: ${String(e.message || e)}`));
    return { ok: false, blockers, warnings, schedule: null, scheduleSha: null, arms: {}, outDir: null, statePath: null };
  }
  if (schedule.schema !== SCHEDULE_SCHEMA) {
    blockers.push(blocker("paired-schedule-schema", `schedule schema must be ${SCHEDULE_SCHEMA}`));
  }
  if (typeof schedule.run_id !== "string" || !schedule.run_id.trim()) {
    blockers.push(blocker("paired-run-id", "schedule.run_id is required"));
  }
  const arms = Array.isArray(schedule.arms) ? schedule.arms : [];
  if (arms.length !== 2) {
    blockers.push(blocker("paired-arms", "schedule must declare exactly two arms"));
  }
  if (Number(schedule.reps || 1) !== 1) {
    blockers.push(blocker(
      "paired-reps-unsupported",
      "the runner records 1..N trials without a rep label; a schedule with reps > 1 cannot be executed honestly",
    ));
  }
  if (schedule.pair_execution_implemented === true) {
    blockers.push(blocker("paired-execution-claim", "schedule claims pair execution is already implemented"));
  }
  if (Number(schedule.completed_pairs || 0) > 0) {
    blockers.push(blocker("paired-completed-claim", "schedule claims completed pairs; run accounting instead"));
  }
  const pairs = Array.isArray(schedule.pairs) ? schedule.pairs : [];
  if (!pairs.length) blockers.push(blocker("paired-pairs", "schedule has no pairs"));
  const maxTrial = pairs.reduce((m, p) => Math.max(m, Number(p.trial) || 0), 0);
  const seen = new Set();
  const cellSeen = new Set();
  for (const [index, pair] of pairs.entries()) {
    if (!pair || typeof pair !== "object") {
      blockers.push(blocker("paired-pair-shape", `pair[${index}] is not an object`));
      continue;
    }
    if (!pair.pair_id || seen.has(pair.pair_id)) {
      blockers.push(blocker("paired-pair-id", `pair[${index}] has a missing or duplicate pair_id`));
    } else {
      seen.add(pair.pair_id);
    }
    if (!pair.scenario || !Number.isInteger(Number(pair.trial)) || Number(pair.trial) < 1) {
      blockers.push(blocker("paired-pair-cell", `pair[${index}] has an invalid scenario/trial`));
    } else {
      const cellKey = `${pair.scenario}#${Number(pair.trial)}`;
      if (cellSeen.has(cellKey)) {
        blockers.push(blocker("paired-duplicate-cell", `pair[${index}] repeats ${cellKey}; a record could satisfy two pairs`));
      }
      cellSeen.add(cellKey);
    }
    const expected = pair.order === "AB"
      ? [arms[0], arms[1]]
      : pair.order === "BA"
        ? [arms[1], arms[0]]
        : null;
    if (!expected) {
      blockers.push(blocker("paired-pair-order", `pair[${index}] order must be AB or BA`));
    } else if (JSON.stringify(pair.arms) !== JSON.stringify(expected)) {
      blockers.push(blocker("paired-pair-arms-order", `pair[${index}] arms do not match the declared ${pair.order} order`));
    }
    if (pair.status && pair.status !== "pending") {
      blockers.push(blocker("paired-pair-claim", `pair[${index}] claims status ${pair.status}; schedules are immutable and start pending`));
    }
  }

  const contexts = {};
  const outRoot = outDir
    ? resolve(outDir)
    : join(privateRoot(repoRoot), "capture", batch, "runs", schedule.run_id || "unknown");
  const statePath = join(outRoot, `paired-state-${schedule.run_id || "unknown"}.json`);
  if (!dryRun) {
    const safe = assertSafeOutput({ path: statePath, repoRoot, allowExisting: allowExistingOut, allowRepoOut });
    for (const b of safe.blockers) blockers.push(b);
  }

  for (const arm of arms) {
    const snapshotPath = snapshotsByArm[arm] ? resolve(snapshotsByArm[arm]) : null;
    const planPath = plansByArm[arm] ? resolve(plansByArm[arm]) : null;
    if (!snapshotPath) {
      blockers.push(blocker("paired-snapshot-missing", `no --arm-snapshot ${arm}=<path>`));
      continue;
    }
    if (!planPath) {
      blockers.push(blocker("paired-plan-missing", `no --arm-plan ${arm}=<path>`));
      continue;
    }
    const snapshot = verifySnapshot(snapshotPath);
    for (const b of snapshot.blockers) blockers.push({ ...b, message: `${arm}: ${b.message}` });
    let planRaw = null;
    try {
      planRaw = readJson(planPath);
    } catch (e) {
      blockers.push(blocker("paired-plan-unreadable", `${arm}: cannot read plan: ${String(e.message || e)}`));
      continue;
    }
    const declaredSet = planRaw?.set?.path
      ? (isAbsolute(planRaw.set.path) ? planRaw.set.path : resolve(dirname(planPath), planRaw.set.path))
      : null;
    const planReport = validateRunPlan(planPath, { repoRoot, snapshotReport: snapshot, setPath: declaredSet });
    for (const b of planReport.blockers) blockers.push({ ...b, message: `${arm}: ${b.message}` });
    if (planRaw.run_id !== schedule.run_id) {
      blockers.push(blocker("paired-plan-run-id", `${arm}: plan run_id does not match the schedule`));
    }
    if (planRaw.phase !== phase) {
      blockers.push(blocker("paired-plan-phase", `${arm}: plan phase ${planRaw.phase} does not match --phase ${phase}`));
    }
    if (planRaw.arm !== arm) {
      blockers.push(blocker("paired-plan-arm", `${arm}: plan arm ${planRaw.arm} does not match`));
    }
    if (!planRaw.schedule || String(planRaw.schedule.sha256 || "").toLowerCase() !== scheduleSha) {
      blockers.push(blocker(
        "paired-plan-schedule",
        `${arm}: plan must bind this schedule's sha256 (regenerate with provenance plan --schedule)`,
      ));
    }
    if (Number(planRaw.trials || 0) < maxTrial) {
      blockers.push(blocker("paired-plan-trials", `${arm}: plan trials ${planRaw.trials} does not cover trial ${maxTrial}`));
    }
    if (Array.isArray(planRaw.ids) && planRaw.ids.length) {
      const allowed = new Set(planRaw.ids);
      const missing = [...new Set(pairs.map((p) => p.scenario))].filter((id) => id && !allowed.has(id));
      if (missing.length) {
        blockers.push(blocker("paired-plan-ids", `${arm}: plan omits scheduled scenarios: ${missing.slice(0, 6).join(", ")}`));
      }
    }
    const effectiveUrl = url || snapshot.normalized?.agent?.public_url || "";
    if (!effectiveUrl) {
      blockers.push(blocker("paired-url", `${arm}: snapshot has no agent.public_url; pass --url`));
    } else if (url && snapshot.normalized?.agent?.public_url
        && normalizeUrlForCompare(url) !== normalizeUrlForCompare(snapshot.normalized.agent.public_url)) {
      blockers.push(blocker("paired-url-mismatch", `${arm}: --url does not match snapshot.agent.public_url`));
    }
    const storePath = outDir
      ? resolve(outRoot, `${phase}-${arm}.json`)
      : defaultRecordPath({ repoRoot, batch, runId: schedule.run_id, arm, phase });
    if (!dryRun) {
      const safe = assertSafeOutput({ path: storePath, repoRoot, allowExisting: allowExistingOut, allowRepoOut });
      for (const b of safe.blockers) blockers.push({ ...b, message: `${arm}: ${b.message}` });
    }
    const setSha = planReport.hashes?.set_sha256 ?? planRaw?.set?.sha256 ?? null;
    const meta = buildStoreMeta({
      tool: "evals/run_paired.mjs",
      runId: schedule.run_id,
      arm,
      phase,
      projectId: snapshot.project_id,
      configHash: snapshot.config_hash,
      snapshotSha256: snapshot.snapshot_sha256,
      artifactHashes: snapshot.artifact_hashes,
      setPath: declaredSet ? displayPath(repoRoot, declaredSet) : null,
      setSha256: setSha,
      scheduleSha256: scheduleSha,
      harnessGit: gitRevision(repoRoot),
      batch,
    });
    contexts[arm] = {
      snapshotPath,
      snapshot,
      planPath,
      plan: planRaw,
      planSha: sha256File(planPath),
      meta,
      storePath,
      effectiveUrl,
      snapshotDisplay: displayPath(repoRoot, snapshotPath),
      planDisplay: displayPath(repoRoot, planPath),
      storeDisplay: displayPath(repoRoot, storePath),
    };
  }

  return {
    ok: blockers.length === 0,
    blockers,
    warnings,
    schedule,
    scheduleSha,
    arms: contexts,
    outDir: outRoot,
    statePath,
    maxTrial,
  };
}

/**
 * Execute or rehearse the schedule.
 *
 * `loadArmStore(arm)` returns a parsed store or null.
 * `invokeCell({arm, pair, scenario, trial, attempt, context})` returns
 * `{code, message}`; code 0 means the runner completed its own validation,
 * code 3 means quota, code 4 means resume refused, other nonzero means blocked.
 * `persistState(state)` writes the private state file.
 * `checkSchedule()` re-hashes the schedule and returns `{ok, message}`.
 */
export async function runPaired({
  schedule, scheduleSha, phase, armContexts,
  loadArmStore, invokeCell, persistState = async () => {},
  dryRun = false, maxCells = Infinity, checkSchedule = () => ({ ok: true }),
}) {
  const stores = {};
  for (const arm of schedule.arms) {
    try {
      stores[arm] = await loadArmStore(arm);
    } catch (e) {
      return {
        ok: false,
        status: "blocked",
        stop_reason: "store-unreadable",
        blockers: [blocker("paired-store-unreadable", `${arm}: ${String(e.message || e)}`)],
        summary: summarizePairs(schedule, {}),
        state: null,
      };
    }
  }
  const startedAt = new Date().toISOString();

  if (dryRun) {
    const mismatchBlockers = [];
    for (const arm of schedule.arms) {
      const resume = checkResume(stores[arm], armContexts[arm].meta);
      for (const b of resume.blockers) mismatchBlockers.push({ ...b, message: `${arm}: ${b.message}` });
    }
    if (mismatchBlockers.length) {
      return {
        ok: false,
        status: "blocked",
        stop_reason: "config-mismatch",
        blockers: mismatchBlockers,
        summary: summarizePairs(schedule, stores),
        cells_planned: 0,
        cells_invoked: 0,
        invalid_attempts: 0,
        state: null,
      };
    }
    const summary = summarizePairs(schedule, stores);
    let planned = 0;
    for (const pair of schedule.pairs || []) {
      for (const arm of pair.arms) {
        if (!isValidRecord(latestCell(stores[arm], pair.scenario, pair.trial))) planned++;
      }
    }
    return {
      ok: true,
      status: "dry-run",
      stop_reason: null,
      blockers: [],
      cells_planned: planned,
      cells_invoked: 0,
      invalid_attempts: 0,
      summary,
      state: null,
    };
  }

  const fail = (stopReason, blockers = []) => ({
    ok: false,
    status: "blocked",
    stop_reason: stopReason,
    blockers,
    summary: summarizePairs(schedule, stores),
    state: null,
  });

  let cellsInvoked = 0;
  let invalidAttempts = 0;
  let stopReason = null;
  let status = "running";

  const persist = async () => {
    const state = buildPairedState({
      schedule, scheduleSha, phase, armContexts, stores, status,
      stopReason, startedAt, cellsInvoked, invalidAttempts,
    });
    await persistState(state);
    return state;
  };

  for (const arm of schedule.arms) {
    const resume = checkResume(stores[arm], armContexts[arm].meta);
    if (!resume.ok) {
      status = "stopped";
      stopReason = "config-mismatch";
      await persist();
      return fail("config-mismatch", resume.blockers.map((b) => ({ ...b, message: `${arm}: ${b.message}` })));
    }
  }

  outer: for (const pair of schedule.pairs || []) {
    let pairFailed = false;
    for (const arm of pair.arms) {
      try {
        stores[arm] = await loadArmStore(arm);
      } catch (e) {
        stopReason = "store-unreadable";
        status = "stopped";
        await persist();
        return fail("store-unreadable", [blocker("paired-store-unreadable", `${arm}: ${String(e.message || e)}`)]);
      }
      let latest = latestCell(stores[arm], pair.scenario, pair.trial);
      if (isValidRecord(latest)) continue;
      if (pairFailed) break;

      if (cellsInvoked >= maxCells) {
        stopReason = "max-cells";
        break outer;
      }
      const hash = checkSchedule();
      if (!hash.ok) {
        stopReason = "schedule-changed";
        status = "stopped";
        await persist();
        return fail("schedule-changed", [blocker("paired-schedule-changed", hash.message || "schedule changed during the run")]);
      }
      const resume = checkResume(stores[arm], armContexts[arm].meta);
      if (!resume.ok) {
        stopReason = "config-mismatch";
        status = "stopped";
        await persist();
        return fail("config-mismatch", resume.blockers.map((b) => ({ ...b, message: `${arm}: ${b.message}` })));
      }

      const attempt = nextAttempt(stores[arm], pair.scenario, pair.trial).attempt;
      let result = { code: 0 };
      try {
        result = await invokeCell({
          arm, pair, scenario: pair.scenario, trial: pair.trial, attempt,
          context: armContexts[arm],
        }) || { code: 0 };
      } catch (e) {
        result = { code: 1, message: String(e.message || e) };
      }
      cellsInvoked++;
      try {
        stores[arm] = await loadArmStore(arm);
      } catch (e) {
        pairFailed = true;
        stopReason = "store-unreadable";
        status = "stopped";
        await persist();
        return fail("store-unreadable", [blocker("paired-store-unreadable", `${arm}: ${String(e.message || e)}`)]);
      }
      latest = latestCell(stores[arm], pair.scenario, pair.trial);

      if (!latest) {
        pairFailed = true;
        stopReason = result.code === 3 ? "quota" : "missing-record";
        status = "stopped";
        await persist();
        return fail(stopReason, [blocker(
          "paired-missing-record",
          `${arm}/${pair.pair_id}: runner returned ${result.code} but wrote no attempt record (${result.message || "no message"})`,
        )]);
      }
      if (Number(latest.attempt || 1) < attempt && result.code !== 0) {
        pairFailed = true;
        stopReason = "runner-blocked";
        await persist();
        return fail("runner-blocked", [blocker(
          "paired-runner-blocked",
          `${arm}/${pair.pair_id}: runner exited ${result.code} without appending attempt ${attempt} (${result.message || "no message"})`,
        )]);
      }
      if (!isValidRecord(latest)) {
        invalidAttempts++;
        pairFailed = true;
        const reason = latest.invalid_reason ?? latest.error ?? null;
        if (result.code === 3 || /quota/i.test(String(reason))) {
          stopReason = "quota";
          status = "stopped";
          await persist();
          return {
            ok: false,
            status,
            stop_reason: stopReason,
            blockers: [],
            summary: summarizePairs(schedule, stores),
            cells_invoked: cellsInvoked,
            invalid_attempts: invalidAttempts,
            state: buildPairedState({
              schedule, scheduleSha, phase, armContexts, stores, status,
              stopReason, startedAt, cellsInvoked, invalidAttempts,
            }),
          };
        }
        if (result.code === 4) {
          stopReason = "config-mismatch";
          await persist();
          return fail("config-mismatch", [blocker("paired-resume-refused", `${arm}/${pair.pair_id}: runner refused resume`)]);
        }
      }
      await persist();
    }
    if (stopReason) break;
    await persist();
  }

  const summary = summarizePairs(schedule, stores);
  if (summary.completed_pairs === summary.declared_pairs) {
    status = "complete";
  } else if (stopReason) {
    status = "stopped";
  } else {
    status = "incomplete";
  }
  const state = buildPairedState({
    schedule, scheduleSha, phase, armContexts, stores, status,
    stopReason, startedAt, cellsInvoked, invalidAttempts,
  });
  await persistState(state);
  return {
    ok: status === "complete",
    status,
    stop_reason: stopReason,
    blockers: [],
    summary,
    cells_invoked: cellsInvoked,
    invalid_attempts: invalidAttempts,
    state,
  };
}
