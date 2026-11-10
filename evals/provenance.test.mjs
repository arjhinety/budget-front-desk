/**
 * Synthetic tests for evals/provenance.mjs. Offline only: temp directories,
 * fabricated artifacts, no browser and no network.
 *
 *   bun test evals/test_provenance.mjs
 */

import { test, expect, afterAll } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  SNAPSHOT_SCHEMA,
  RUN_PLAN_SCHEMA,
  SCHEDULE_SCHEMA,
  RECORD_PROVENANCE_SCHEMA,
  validateSnapshotObject,
  verifySnapshot,
  buildRunPlan,
  validateRunPlan,
  evaluateResume,
  checkResume,
  buildStoreMeta,
  classifyReply,
  classifyThread,
  nextAttempt,
  isValidRecord,
  buildSchedule,
  summarizePairs,
  pairId,
  assertSafeOutput,
  validateObservedUrl,
  sha256File,
  sha256Text,
  isPlaceholderHash,
  normalizeArtifactPath,
  makeRecordProvenance,
} from "./provenance.mjs";

const DIRS = [];
afterAll(() => {
  for (const dir of DIRS) {
    try { rmSync(dir, { recursive: true, force: true }); } catch {}
  }
});

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), "agentplace-prov-"));
  DIRS.push(dir);
  return dir;
}

function write(path, text) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, "utf8");
}

function fixture({ method = "platform-export", mutate = (snap) => snap, artifact = {} } = {}) {
  const dir = tempDir();
  write(join(dir, "instructions.txt"), artifact.instructions ?? "Answer as Budget Heating. Never invent a price. ".repeat(2));
  write(join(dir, "knowledge.txt"), artifact.knowledge ?? "Hours: Mon-Fri 8-7; closed Sunday. ".repeat(2));
  write(join(dir, "ui.json"), artifact.ui ?? JSON.stringify({ greeting: "Hi", temperature: 0 }));
  const snap = mutate({
    schema: SNAPSHOT_SCHEMA,
    project_id: "cgiefgaebmgh",
    model: "Luna",
    agent: { public_url: "https://agentplace.io/agents/cgiefgaebmgh" },
    capture: {
      method,
      captured_at: "2026-11-11T12:00:00Z",
      export_scope: "partial",
      current_effective_config_verified: true,
      publication: { surface: "published-agent", revision: "2026-11-11" },
      revision: "rev-7",
    },
    artifacts: {
      instructions: [{ path: "instructions.txt", sha256: sha256File(join(dir, "instructions.txt")) }],
      knowledge: [{ path: "knowledge.txt", sha256: sha256File(join(dir, "knowledge.txt")) }],
      ui_settings: [{ path: "ui.json", sha256: sha256File(join(dir, "ui.json")) }],
    },
    unknowns: ["knowledge retrieval order is not exposed by the platform"],
    limitations: ["the UI capture shows rendered settings, not the stored JSON"],
  });
  const path = join(dir, "snapshot.json");
  writeFileSync(path, JSON.stringify(snap, null, 1), "utf8");
  return { dir, path, snap };
}

test("a fully populated platform-export snapshot verifies", () => {
  const { path } = fixture();
  const report = verifySnapshot(path);
  expect(report.ok).toBe(true);
  expect(report.status).toBe("verified-effective");
  expect(report.project_id).toBe("cgiefgaebmgh");
  expect(report.model).toBe("Luna");
  expect(report.config_hash).toMatch(/^[0-9a-f]{64}$/);
  expect(report.artifact_hashes.instructions.length).toBe(1);
});

test("intended-only manifests never verify", () => {
  const { path } = fixture({ method: "intended-only" });
  const report = verifySnapshot(path);
  expect(report.ok).toBe(false);
  expect(report.blockers.map((b) => b.code)).toContain("intended-only-not-effective");
});

test("a historical read-back or an unstated current verification never verifies", () => {
  const historical = fixture({
    mutate: (s) => ({ ...s, capture: { ...s.capture, current_effective_config_verified: false } }),
  });
  expect(verifySnapshot(historical.path).blockers.map((b) => b.code)).toContain("current-config-not-verified");

  const unstated = fixture({
    mutate: (s) => {
      const capture = { ...s.capture };
      delete capture.current_effective_config_verified;
      return { ...s, capture };
    },
  });
  expect(verifySnapshot(unstated.path).blockers.map((b) => b.code)).toContain("current-config-verification-missing");
});

test("the model must be Luna and the project id must be real", () => {
  const badModel = fixture({ mutate: (s) => ({ ...s, model: "Terra" }) });
  expect(verifySnapshot(badModel.path).blockers.map((b) => b.code)).toContain("model-not-luna");
  const badProject = fixture({ mutate: (s) => ({ ...s, project_id: "TODO" }) });
  expect(verifySnapshot(badProject.path).blockers.map((b) => b.code)).toContain("project-id-placeholder");
});

test("a placeholder hash is rejected even when the file exists", () => {
  const { dir, snap } = fixture();
  snap.artifacts.instructions[0].sha256 = "0".repeat(64);
  const path = join(dir, "placeholder.json");
  writeFileSync(path, JSON.stringify(snap), "utf8");
  const report = verifySnapshot(path);
  expect(report.ok).toBe(false);
  expect(report.blockers.map((b) => b.code)).toContain("artifact-instructions-sha-placeholder");
});

test("a tampered artifact and a traversal path are both refused", () => {
  const { dir, snap } = fixture();
  write(join(dir, "instructions.txt"), "different bytes now");
  const tampered = join(dir, "tampered.json");
  writeFileSync(tampered, JSON.stringify(snap), "utf8");
  expect(verifySnapshot(tampered).blockers.map((b) => b.code)).toContain("artifact-instructions-sha-mismatch");

  snap.artifacts.knowledge[0].path = "../outside.txt";
  const traversal = join(dir, "traversal.json");
  writeFileSync(traversal, JSON.stringify(snap), "utf8");
  expect(verifySnapshot(traversal).blockers.map((b) => b.code)).toContain("artifact-knowledge-path");
});

test("unknowns and limitations must be declared", () => {
  const { dir, snap } = fixture();
  delete snap.unknowns;
  const path = join(dir, "no-unknowns.json");
  writeFileSync(path, JSON.stringify(snap), "utf8");
  expect(verifySnapshot(path).blockers.map((b) => b.code)).toContain("unknowns-missing");
});

test("artifact path normalization is strict", () => {
  expect(normalizeArtifactPath("a/b.txt").ok).toBe(true);
  expect(normalizeArtifactPath("C:/x.txt").ok).toBe(false);
  expect(normalizeArtifactPath("../x.txt").ok).toBe(false);
  expect(normalizeArtifactPath("/x.txt").ok).toBe(false);
  expect(isPlaceholderHash("a".repeat(64))).toBe(true);
  expect(isPlaceholderHash(sha256Text("real"))).toBe(false);
});

test("reply health keeps genuinely short replies and rejects artefacts", () => {
  expect(classifyReply("$99.").valid).toBe(true);
  expect(classifyReply("Yes.").valid).toBe(true);
  expect(classifyReply("   ").valid).toBe(false);
  expect(classifyReply("This agent cannot continue right now.").reason).toBe("quota-message");
  expect(classifyReply("Working…").reason).toBe("render-or-partial-text");
  expect(classifyReply("The answer could not be displayed").reason).toBe("render-or-partial-text");
  expect(classifyThread("hi\n$99.", "hi").valid).toBe(true);
  expect(classifyThread("hi", "hi").reason).toBe("no-reply-after-customer");
  expect(classifyThread("Welcome to the business. How can I help?", "hi").reason).toBe("customer-marker-absent");
  expect(classifyThread("this is an agent reply", "hi").reason).toBe("customer-marker-absent");
  expect(classifyThread("hi\nSend", "hi").reason).toBe("no-reply-after-customer");
  expect(classifyThread("\u201CMy AC stopped cooling,\u201D they said\nCall (636) 887-2800.", "\u201CMy AC stopped cooling,\u201D they said").valid).toBe(true);
  expect(classifyThread("  My   AC stopped cooling  \n  $99.  ", "My AC stopped cooling").valid).toBe(true);
});

test("resume refuses changed project, config, phase, scenario set, or arm", () => {
  const meta = buildStoreMeta({
    tool: "test", runId: "run-1", arm: "A0", phase: "capture",
    projectId: "cgiefgaebmgh", configHash: "a".repeat(64), snapshotSha256: "b".repeat(64),
    artifactHashes: {}, setPath: "evals/scenarios.json", setSha256: "c".repeat(64),
    scheduleSha256: null, harnessGit: "deadbeef", batch: "b1",
  });
  const store = { meta, records: [] };
  expect(checkResume(null, meta).ok).toBe(true);
  expect(checkResume(store, meta).ok).toBe(true);
  expect(checkResume(store, { ...meta, config_hash: "d".repeat(64) }).ok).toBe(false);
  expect(checkResume(store, { ...meta, phase: "validation" }).ok).toBe(false);
  expect(checkResume(store, { ...meta, set_sha256: "e".repeat(64) }).ok).toBe(false);
  expect(checkResume(store, { ...meta, arm: "A2" }).ok).toBe(false);
  expect(checkResume({ records: [] }, meta).blockers[0].code).toBe("store-meta-missing");
  expect(checkResume(store, { ...meta, config_hash: undefined }).ok).toBe(false);
});

test("invalid attempts are retained and retried under a new attempt number", () => {
  const store = { records: [
    { id: "T01", trial: 1, attempt: 1, status: "invalid", error: "no textbox" },
    { id: "T01", trial: 1, attempt: 2, thread: "ok", status: "valid" },
    { id: "T02", trial: 1, attempt: 1, thread: "", status: "invalid", invalid_reason: "empty-reply" },
  ] };
  expect(nextAttempt(store, "T01", 1).complete).toBe(true);
  expect(nextAttempt(store, "T01", 1).attempt).toBe(3);
  expect(nextAttempt(store, "T02", 1).attempt).toBe(2);
  expect(isValidRecord({ thread: "" })).toBe(false);
  expect(isValidRecord({ replies: ["a", ""] })).toBe(false);
  expect(isValidRecord({ replies: ["$99."] })).toBe(true);
});

test("run plan validation binds snapshot, set, phase, and refuses pairs", () => {
  const { dir, path } = fixture();
  const snapshot = verifySnapshot(path);
  const setPath = join(dir, "scenarios.json");
  write(setPath, JSON.stringify({ scenarios: [{ id: "T01", customer: "hello" }] }));
  const plan = buildRunPlan({
    runId: "run-test-1", arm: "A0", phase: "capture",
    snapshotPath: path, snapshotReport: snapshot, setPath,
  });
  const planPath = join(dir, "run-plan.json");
  writeFileSync(planPath, JSON.stringify(plan), "utf8");
  const ok = validateRunPlan(planPath, { repoRoot: dir, snapshotReport: snapshot, setPath });
  expect(ok.ok).toBe(true);
  expect(ok.plan.schema).toBe(RUN_PLAN_SCHEMA);

  write(setPath, JSON.stringify({ scenarios: [{ id: "T02", customer: "changed" }] }));
  expect(validateRunPlan(planPath, { repoRoot: dir, snapshotReport: snapshot, setPath }).ok).toBe(false);

  const pairPlan = { ...plan, pair_execution: true };
  const pairPath = join(dir, "pair-plan.json");
  writeFileSync(pairPath, JSON.stringify(pairPlan), "utf8");
  expect(validateRunPlan(pairPath, { repoRoot: dir, snapshotReport: snapshot, setPath }).blockers.map((b) => b.code))
    .toContain("pair-execution-unimplemented");
});

test("resume revalidates the plan and refuses a changed scenario set or snapshot", () => {
  const { dir, path } = fixture();
  const snapshot = verifySnapshot(path);
  const setPath = join(dir, "scenarios.json");
  write(setPath, JSON.stringify({ scenarios: [{ id: "T01", customer: "hello" }] }));
  const plan = buildRunPlan({
    runId: "run-resume-1", arm: "A0", phase: "capture",
    snapshotPath: path, snapshotReport: snapshot, setPath,
  });
  const planPath = join(dir, "run-plan.json");
  writeFileSync(planPath, JSON.stringify(plan), "utf8");
  const storePath = join(dir, "store.json");
  const baseline = evaluateResume({ planPath, storePath, repoRoot: dir });
  expect(baseline.ok).toBe(true);

  write(setPath, JSON.stringify({ scenarios: [{ id: "T02", customer: "changed" }] }));
  const driftedSet = evaluateResume({ planPath, storePath, repoRoot: dir });
  expect(driftedSet.ok).toBe(false);
  expect(driftedSet.blockers.map((b) => b.code)).toContain("run-plan-set-sha");

  const second = fixture();
  const secondSnapshot = verifySnapshot(second.path);
  const secondSet = join(second.dir, "scenarios.json");
  write(secondSet, JSON.stringify({ scenarios: [{ id: "T01", customer: "hello" }] }));
  const secondPlan = buildRunPlan({
    runId: "run-resume-2", arm: "A0", phase: "capture",
    snapshotPath: second.path, snapshotReport: secondSnapshot, setPath: secondSet,
  });
  const secondPlanPath = join(second.dir, "run-plan.json");
  writeFileSync(secondPlanPath, JSON.stringify(secondPlan), "utf8");
  writeFileSync(second.path, JSON.stringify({ ...second.snap, unknowns: ["changed"] }), "utf8");
  const driftedSnapshot = evaluateResume({
    planPath: secondPlanPath, storePath: join(second.dir, "store.json"), repoRoot: second.dir,
  });
  expect(driftedSnapshot.ok).toBe(false);
  expect(driftedSnapshot.blockers.some((b) => /snapshot/.test(b.code))).toBe(true);
});

test("counterbalanced schedule is stable, balanced, and never claims pairs", () => {
  const ids = ["S3", "S1", "S2"];
  const schedule = buildSchedule({ runId: "run-sched", scenarioIds: ids, arms: ["A0", "A2"], trials: 2 });
  expect(schedule.schema).toBe(SCHEDULE_SCHEMA);
  expect(schedule.pairs.length).toBe(6);
  expect(schedule.pair_execution_implemented).toBe(false);
  expect(schedule.completed_pairs).toBe(0);
  for (const id of ids.sort()) {
    const orders = schedule.pairs.filter((p) => p.scenario === id).map((p) => p.order);
    expect(orders.filter((o) => o === "AB").length).toBe(1);
    expect(orders.filter((o) => o === "BA").length).toBe(1);
  }
  const again = buildSchedule({ runId: "run-sched", scenarioIds: ids, arms: ["A0", "A2"], trials: 2 });
  expect(again.pairs.map((p) => p.pair_id)).toEqual(schedule.pairs.map((p) => p.pair_id));
  expect(pairId("run-sched", "S1", 1)).toBe(again.pairs.find((p) => p.scenario === "S1" && p.trial === 1).pair_id);

  const none = summarizePairs(schedule, {});
  expect(none.completed_pairs).toBe(0);
  expect(none.pending_pairs).toBe(6);
  expect(none.pair_execution_implemented).toBe(false);

  const pair = schedule.pairs.find((p) => p.scenario === "S1" && p.trial === 1);
  const records = (arm, at) => ({ records: [{
    id: "S1", trial: 1, thread: "reply", status: "valid", at,
    provenance: { pair_id: pair.pair_id, config_hash: "a".repeat(64) },
  }] });
  const done = summarizePairs(schedule, {
    [pair.arms[0]]: records(pair.arms[0], "2026-11-11T12:00:00Z"),
    [pair.arms[1]]: records(pair.arms[1], "2026-11-11T12:05:00Z"),
  });
  expect(done.completed_pairs).toBe(1);
  expect(done.pairs.find((p) => p.pair_id === pair.pair_id).status).toBe("complete");
  expect(done.pairs.find((p) => p.pair_id === pair.pair_id).order_evidence).toBe("capture-timestamps");

  const reversed = summarizePairs(schedule, {
    [pair.arms[0]]: records(pair.arms[0], "2026-11-11T12:05:00Z"),
    [pair.arms[1]]: records(pair.arms[1], "2026-11-11T12:00:00Z"),
  });
  expect(reversed.completed_pairs).toBe(0);
  expect(reversed.warnings.length).toBeGreaterThan(0);
});

test("one record cannot complete two pairs with the same scenario#trial", () => {
  const schedule = buildSchedule({ runId: "run-reps", scenarioIds: ["S1"], arms: ["A0", "A2"], trials: 1, reps: 2 });
  expect(schedule.pairs.length).toBe(2);
  expect(schedule.pairs[0].pair_id).not.toBe(schedule.pairs[1].pair_id);
  const first = schedule.pairs[0];
  const second = schedule.pairs[1];
  const record = (arm, pairId, at) => ({
    id: "S1", trial: 1, attempt: 1, status: "valid", thread: "reply", at,
    provenance: pairId ? { pair_id: pairId } : {},
  });
  const stores = {
    A0: { records: [record("A0", first.pair_id, "2026-11-11T12:00:00Z")] },
    A2: { records: [record("A2", first.pair_id, "2026-11-11T12:01:00Z")] },
  };
  const one = summarizePairs(schedule, stores);
  expect(one.completed_pairs).toBe(1);
  expect(one.pairs.find((p) => p.pair_id === first.pair_id).status).toBe("complete");
  expect(one.pairs.find((p) => p.pair_id === second.pair_id).status).toBe("pending");

  const unbound = summarizePairs(schedule, {
    A0: { records: [record("A0", null, "2026-11-11T12:00:00Z")] },
    A2: { records: [record("A2", null, "2026-11-11T12:01:00Z")] },
  });
  expect(unbound.completed_pairs).toBe(0);

  const both = summarizePairs(schedule, {
    A0: { records: [
      record("A0", first.pair_id, "2026-11-11T12:00:00Z"),
      record("A0", second.pair_id, "2026-11-11T12:03:00Z"),
    ] },
    A2: { records: [
      record("A2", first.pair_id, "2026-11-11T12:01:00Z"),
      record("A2", second.pair_id, "2026-11-11T12:02:00Z"),
    ] },
  });
  expect(both.completed_pairs).toBe(2);
});

test("record provenance never contains a raw URL", () => {
  const url = "https://agentplace.io/agents/cgiefgaebmgh";
  const provenance = makeRecordProvenance({
    runId: "run-1", phase: "capture", arm: "A0", scenarioId: "T01", trial: 1,
    projectId: "cgiefgaebmgh", configHash: "a".repeat(64), observedUrl: url,
    binding: "observed-in-url",
  });
  expect(provenance.schema).toBe(RECORD_PROVENANCE_SCHEMA);
  expect(JSON.stringify(provenance)).not.toContain(url);
  expect(provenance.observed_url_sha256).toBe(sha256Text(url));
});

test("target URL validation rejects builder surfaces and host drift", () => {
  expect(validateObservedUrl("https://agentplace.io/agents/cgiefgaebmgh", {
    expected: "https://agentplace.io/agents/cgiefgaebmgh", projectId: "cgiefgaebmgh",
  }).ok).toBe(true);
  expect(validateObservedUrl("https://agentplace.io/admin/dashboard", {
    expected: "https://agentplace.io/agents/cgiefgaebmgh",
  }).blockers.map((b) => b.code)).toContain("url-builder-surface");
  expect(validateObservedUrl("https://example.test/agents/x", {
    expected: "https://agentplace.io/agents/x",
  }).blockers.map((b) => b.code)).toContain("url-host-mismatch");
  expect(validateObservedUrl("about:blank", {}).ok).toBe(false);
});

test("output safety refuses repo paths and existing files without opt-in", () => {
  const dir = tempDir();
  const repo = join(dir, "repo");
  mkdirSync(join(repo, "evals", "results"), { recursive: true });
  expect(assertSafeOutput({ path: join(dir, "private", "a.json"), repoRoot: repo }).ok).toBe(true);
  expect(assertSafeOutput({ path: join(repo, "evals", "results", "A0.json"), repoRoot: repo }).blockers[0].code)
    .toBe("output-inside-repo");
  expect(assertSafeOutput({ path: join(repo, "evals", "results", "A0.json"), repoRoot: repo, allowRepoOut: true }).ok).toBe(true);
  write(join(dir, "private", "exists.json"), "{}");
  expect(assertSafeOutput({ path: join(dir, "private", "exists.json"), repoRoot: repo }).blockers[0].code).toBe("output-exists");
  expect(assertSafeOutput({ path: join(dir, "private", "exists.json"), repoRoot: repo, allowExisting: true }).ok).toBe(true);
});

test("a config hash ignores capture time but changes with artifact bytes", () => {
  const first = fixture();
  const a = verifySnapshot(first.path);
  const second = fixture({ mutate: (s) => ({ ...s, capture: { ...s.capture, captured_at: "2026-11-12T09:00:00Z" } }) });
  const b = verifySnapshot(second.path);
  expect(a.config_hash).toBe(b.config_hash);
  const third = fixture({ artifact: { knowledge: "different knowledge bytes entirely" } });
  const c = verifySnapshot(third.path);
  expect(a.config_hash).not.toBe(c.config_hash);
});

test("validateSnapshotObject does not mutate and reports artifact bytes", () => {
  const { snap, dir } = fixture();
  const before = JSON.stringify(snap);
  const report = validateSnapshotObject(snap, { snapshotDir: dir });
  expect(report.ok).toBe(true);
  expect(report.normalized.artifacts.ui_settings[0].bytes).toBeGreaterThan(0);
  expect(JSON.stringify(snap)).toBe(before);
});
