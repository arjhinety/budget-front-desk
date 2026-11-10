/**
 * Synthetic tests for the paired executor core. No browser, no runner, no
 * network: the cell function is injected and records are in-memory.
 *
 *   bun test evals/test_run_paired.mjs
 */

import { test, expect } from "bun:test";
import { buildSchedule, buildStoreMeta } from "./provenance.mjs";
import { runPaired } from "./paired_core.mjs";

const RUN = "run-paired";
const T0 = Date.parse("2026-11-11T12:00:00Z");

function metaFor(arm, over = {}) {
  return buildStoreMeta({
    tool: "evals/run_paired.mjs",
    runId: RUN,
    arm,
    phase: "capture",
    projectId: "cgiefgaebmgh",
    configHash: "a".repeat(64),
    snapshotSha256: "b".repeat(64),
    artifactHashes: { instructions: [], knowledge: [], ui_settings: [] },
    setPath: "evals/scenarios.json",
    setSha256: "c".repeat(64),
    scheduleSha256: "d".repeat(64),
    harnessGit: "deadbeef",
    batch: "test",
    ...over,
  });
}

function newStore(arm) {
  return { meta: metaFor(arm), records: [] };
}

function scheduleFor(trials = 2) {
  return buildSchedule({ runId: RUN, scenarioIds: ["S1"], arms: ["A0", "A2"], trials });
}

function recorder(stores, { clock = { value: T0 }, failFirst = 0, quotaFirst = false } = {}) {
  const log = [];
  let calls = 0;
  const invokeCell = async ({ arm, pair, scenario, trial, attempt }) => {
    calls++;
    log.push(`${pair.order}:${arm}:${scenario}#${trial}`);
    clock.value += 60000;
    if (quotaFirst && calls === 1) {
      stores[arm].records.push({
        id: scenario, trial, attempt, status: "invalid", invalid_reason: "quota-message",
        error: "quota", at: new Date(clock.value).toISOString(),
      });
      return { code: 3, message: "quota" };
    }
    if (calls <= failFirst) {
      stores[arm].records.push({
        id: scenario, trial, attempt, status: "invalid", invalid_reason: "empty-reply",
        error: "invalid capture: empty-reply", at: new Date(clock.value).toISOString(),
      });
      return { code: 0, message: "invalid" };
    }
    stores[arm].records.push({
      id: scenario, trial, attempt, status: "valid", thread: "synthetic reply",
      at: new Date(clock.value).toISOString(),
      provenance: { pair_id: pair.pair_id, config_hash: "a".repeat(64) },
    });
    return { code: 0 };
  };
  return { invokeCell, log };
}

async function run(schedule, stores, options = {}) {
  return runPaired({
    schedule,
    scheduleSha: "d".repeat(64),
    phase: "capture",
    armContexts: { A0: { meta: metaFor("A0") }, A2: { meta: metaFor("A2") } },
    loadArmStore: async (arm) => stores[arm],
    invokeCell: options.invokeCell,
    persistState: options.persistState ?? (async () => {}),
    dryRun: options.dryRun ?? false,
    maxCells: options.maxCells ?? Infinity,
    checkSchedule: options.checkSchedule ?? (() => ({ ok: true })),
  });
}

test("alternates the declared AB/BA order and completes every pair", async () => {
  const schedule = scheduleFor(2);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  const { invokeCell, log } = recorder(stores);
  const result = await run(schedule, stores, { invokeCell });
  expect(result.status).toBe("complete");
  expect(result.summary.completed_pairs).toBe(2);
  expect(log).toEqual([
    "AB:A0:S1#1",
    "AB:A2:S1#1",
    "BA:A2:S1#2",
    "BA:A0:S1#2",
  ]);
});

test("skips only valid completed cells and resumes a partial pair", async () => {
  const schedule = scheduleFor(2);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  // S1#1 is complete already; S1#2 has only the first scheduled arm.
  stores.A0.records.push({
    id: "S1", trial: 1, attempt: 1, status: "valid", thread: "a",
    at: new Date(T0).toISOString(), provenance: { pair_id: schedule.pairs[0].pair_id },
  });
  stores.A2.records.push({
    id: "S1", trial: 1, attempt: 1, status: "valid", thread: "b",
    at: new Date(T0 + 60000).toISOString(), provenance: { pair_id: schedule.pairs[0].pair_id },
  });
  // Trial 2 is BA: A2 runs first.
  stores.A2.records.push({
    id: "S1", trial: 2, attempt: 1, status: "valid", thread: "c",
    at: new Date(T0 + 120000).toISOString(), provenance: { pair_id: schedule.pairs[1].pair_id },
  });
  const { invokeCell, log } = recorder(stores, { clock: { value: T0 + 180000 } });
  const result = await run(schedule, stores, { invokeCell });
  expect(log).toEqual(["BA:A0:S1#2"]);
  expect(result.status).toBe("complete");
  expect(result.summary.completed_pairs).toBe(2);
});

test("an invalid first arm leaves the counterpart pending, then a retry appends", async () => {
  const schedule = scheduleFor(1);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  const first = recorder(stores, { failFirst: 1 });
  const stopped = await run(schedule, stores, { invokeCell: first.invokeCell });
  expect(stopped.status).toBe("incomplete");
  expect(first.log).toEqual(["AB:A0:S1#1"]);          // A2 never ran
  expect(stores.A0.records.length).toBe(1);
  expect(stores.A0.records[0].status).toBe("invalid");
  expect(stores.A2.records.length).toBe(0);

  const second = recorder(stores, { clock: { value: T0 + 300000 } });
  const done = await run(schedule, stores, { invokeCell: second.invokeCell });
  expect(second.log).toEqual(["AB:A0:S1#1", "AB:A2:S1#1"]);
  expect(done.status).toBe("complete");
  expect(stores.A0.records.map((r) => r.attempt)).toEqual([1, 2]);
  expect(stores.A0.records[0].status).toBe("invalid"); // retained
  expect(stores.A0.records[1].status).toBe("valid");
});

test("quota stops the run, saves state, and does not consume the counterpart", async () => {
  const schedule = scheduleFor(1);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  const { invokeCell, log } = recorder(stores, { quotaFirst: true });
  const saved = [];
  const result = await run(schedule, stores, {
    invokeCell,
    persistState: async (state) => { saved.push(state); },
  });
  expect(result.status).toBe("stopped");
  expect(result.stop_reason).toBe("quota");
  expect(log).toEqual(["AB:A0:S1#1"]);
  expect(stores.A0.records.length).toBe(1);
  expect(stores.A2.records.length).toBe(0);
  expect(saved.length).toBeGreaterThan(0);
  expect(saved.at(-1).stop_reason).toBe("quota");
  expect(saved.at(-1).pending_pairs).toBe(1);
});

test("a store/config hash mismatch refuses before invoking any cell", async () => {
  const schedule = scheduleFor(1);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  stores.A0.meta = metaFor("A0", { configHash: "e".repeat(64) });
  const { invokeCell, log } = recorder(stores);
  const result = await run(schedule, stores, { invokeCell });
  expect(result.status).toBe("blocked");
  expect(result.stop_reason).toBe("config-mismatch");
  expect(log).toEqual([]);
});

test("a changed schedule hash stops before the next cell", async () => {
  const schedule = scheduleFor(2);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  const { invokeCell, log } = recorder(stores);
  let checks = 0;
  const result = await run(schedule, stores, {
    invokeCell,
    checkSchedule: () => {
      checks++;
      return checks === 1 ? { ok: true } : { ok: false, message: "changed" };
    },
  });
  expect(result.status).toBe("blocked");
  expect(result.stop_reason).toBe("schedule-changed");
  expect(log.length).toBe(1);
});

test("dry-run reports completeness without invoking anything", async () => {
  const schedule = scheduleFor(2);
  const stores = { A0: newStore("A0"), A2: newStore("A2") };
  let called = false;
  const empty = await run(schedule, stores, {
    invokeCell: async () => { called = true; return { code: 0 }; },
    dryRun: true,
  });
  expect(called).toBe(false);
  expect(empty.status).toBe("dry-run");
  expect(empty.cells_planned).toBe(4);
  expect(empty.summary.completed_pairs).toBe(0);

  stores.A0.records.push({ id: "S1", trial: 1, attempt: 1, status: "valid", thread: "a", at: new Date(T0).toISOString() });
  stores.A2.records.push({ id: "S1", trial: 1, attempt: 1, status: "valid", thread: "b", at: new Date(T0 + 1000).toISOString() });
  const partial = await run(schedule, stores, {
    invokeCell: async () => { called = true; return { code: 0 }; },
    dryRun: true,
  });
  expect(partial.cells_planned).toBe(2);
  expect(partial.summary.completed_pairs).toBe(1);
  expect(called).toBe(false);
});
