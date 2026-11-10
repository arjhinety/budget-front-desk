#!/usr/bin/env bun
/**
 * Offline provenance, snapshot validation, run planning, and pair scheduling
 * for Agentplace captures.
 *
 * This module is imported dynamically by evals/run.mjs and evals/run_mt.mjs.
 * Those runners are evaluated inside `new Function(browser, Bun, process, ...)`,
 * where static imports are unavailable, so they resolve this file from the real
 * working directory and call `import(...)`.
 *
 * Nothing in this module touches the browser, the network, or any existing
 * file under evals/results or evals/blind. Every write goes to an explicit path
 * (private by default) and refuses to overwrite unless `--force` is given.
 *
 * CLI:
 *   bun evals/provenance.mjs --help
 *   bun evals/provenance.mjs hash <file...>
 *   bun evals/provenance.mjs verify --snapshot <snapshot.json> [--json]
 *   bun evals/provenance.mjs snapshot --project-id <id> --method platform-export \
 *       --captured-at <iso> --instructions <rel> --knowledge <rel> \
 *       --ui-settings <rel> [--out <private>/snapshot.json]
 *   bun evals/provenance.mjs plan --snapshot <snapshot.json> --arm A0 \
 *       --phase capture [--scenarios evals/scenarios.json] [--run-id <id>]
 *   bun evals/provenance.mjs schedule --scenarios evals/scenarios.json \
 *       --arms A0,A2 --trials 3 [--out <private>/schedule.json]
 *   bun evals/provenance.mjs pairs --schedule <schedule.json> \
 *       [--arm-file A0=evals/results/A0.json --arm-file A2=...]
 *   bun evals/provenance.mjs resume --store <out.json> --plan <run-plan.json>
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { appendFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

export const SNAPSHOT_SCHEMA = "agentplace-snapshot-v1";
export const RUN_PLAN_SCHEMA = "agentplace-run-plan-v1";
export const SCHEDULE_SCHEMA = "agentplace-pair-schedule-v1";
export const RECORD_PROVENANCE_SCHEMA = "agentplace-record-provenance-v1";
export const STORE_META_SCHEMA = "agentplace-store-meta-v1";
export const PREFLIGHT_EXPECT_SCHEMA = "agentplace-preflight-expect-v1";
export const CAPTURE_METHODS = ["platform-export", "verbatim-ui", "intended-only"];
export const EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

const PLACEHOLDER_WORDS = new Set([
  "", "0", "todo", "tbd", "pending", "unknown", "placeholder", "none", "null",
  "fixme", "example", "sample", "<sha256>", "sha256", "hash", "redacted",
]);

/* ------------------------------------------------------------------ hashing */

export function sha256Bytes(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

export function sha256Text(text) {
  return sha256Bytes(Buffer.from(String(text), "utf8"));
}

export function sha256File(path) {
  return sha256Bytes(readFileSync(path));
}

/** Stable JSON used for config and plan hashes. Undefined values are omitted. */
export function canonicalJson(value) {
  if (value === undefined) return "null";
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map((v) => canonicalJson(v)).join(",") + "]";
  const keys = Object.keys(value).filter((k) => value[k] !== undefined).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalJson(value[k])).join(",") + "}";
}

export function hashJson(value) {
  return sha256Text(canonicalJson(value));
}

export function isPlaceholderHash(value) {
  if (typeof value !== "string") return true;
  const v = value.trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(v)) return true;
  if (PLACEHOLDER_WORDS.has(v)) return true;
  if (v === EMPTY_SHA256) return true;
  if (new Set(v).size <= 2) return true;
  return false;
}

export function isIsoTimestamp(value) {
  if (typeof value !== "string" || !value.trim()) return false;
  const s = value.trim();
  if (!/([zZ]|[+-]\d\d:?\d\d)$/.test(s)) return false;
  return !Number.isNaN(Date.parse(s));
}

/* ------------------------------------------------------------------- paths */

export function repoRootFrom(start = process.cwd()) {
  let dir = resolve(start);
  for (let i = 0; i < 10; i++) {
    if (existsSync(join(dir, "evals", "provenance.mjs"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

export function privateRoot(root) {
  const fromEnv = process.env.AGENTPLACE_PRIVATE;
  if (fromEnv && fromEnv.trim()) return resolve(fromEnv.trim());
  return resolve(root, "..", "agentplace-private");
}

export function displayPath(root, path) {
  const rel = relative(resolve(root), resolve(path));
  if (rel && !rel.startsWith("..") && !isAbsolute(rel)) return rel.split(sep).join("/");
  return `<external>/${basename(path)}`;
}

export function isInside(root, path) {
  const rel = relative(resolve(root), resolve(path));
  return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
}

/** Reject absolute paths, drive letters, `..`, and empty segments. */
export function normalizeArtifactPath(input) {
  if (typeof input !== "string" || !input.trim()) {
    return { ok: false, reason: "artifact path is empty" };
  }
  const raw = input.trim().replace(/\\/g, "/");
  if (raw.startsWith("/") || /^[A-Za-z]:\//.test(raw)) {
    return { ok: false, reason: "artifact path must be relative, not absolute" };
  }
  const segments = raw.split("/");
  if (segments.some((s) => s === "..")) {
    return { ok: false, reason: "artifact path may not escape the snapshot directory" };
  }
  if (segments.some((s) => s === "" || s === ".")) {
    return { ok: false, reason: "artifact path has an empty or '.' segment" };
  }
  return { ok: true, path: segments.join("/") };
}

/* --------------------------------------------------------------------- git */

export function gitRevision(root) {
  try {
    let gitDir = join(root, ".git");
    const st = statSync(gitDir);
    if (st.isFile()) {
      const m = readFileSync(gitDir, "utf8").match(/^gitdir:\s*(.+)$/m);
      if (!m) return "unknown";
      gitDir = resolve(root, m[1].trim());
    }
    const head = readFileSync(join(gitDir, "HEAD"), "utf8").trim();
    if (head.startsWith("ref:")) {
      const ref = head.slice(4).trim();
      const direct = join(gitDir, ref);
      if (existsSync(direct)) return readFileSync(direct, "utf8").trim();
      const packed = join(gitDir, "packed-refs");
      if (existsSync(packed)) {
        for (const line of readFileSync(packed, "utf8").split("\n")) {
          const parts = line.trim().split(/\s+/);
          if (parts.length === 2 && parts[1] === ref) return parts[0];
        }
      }
      return `unresolved:${ref}`;
    }
    return head;
  } catch {
    return "unknown";
  }
}

/* ------------------------------------------------------------------ snapshot */

function stringField(value) {
  return typeof value === "string" ? value.trim() : "";
}

function modelName(value) {
  if (typeof value === "string") return value.trim();
  if (value && typeof value === "object") return stringField(value.name ?? value.id);
  return "";
}

function normalizeMethod(value) {
  const raw = stringField(value).toLowerCase().replace(/[_\s]+/g, "-");
  if (raw === "platform-export" || raw === "platformexport" || raw === "export") return "platform-export";
  if (raw === "verbatim-ui" || raw === "verbatim" || raw === "ui") return "verbatim-ui";
  if (raw === "intended-only" || raw === "intended" || raw === "planned") return "intended-only";
  return raw;
}

function isPlaceholderValue(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") {
    const v = value.trim().toLowerCase();
    return !v || PLACEHOLDER_WORDS.has(v) || /^<.*>$/.test(v);
  }
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

function collectArtifactEntries(value, label, blockers) {
  const out = [];
  const add = (entry) => {
    if (typeof entry === "string") {
      out.push({ path: entry });
      return;
    }
    if (entry && typeof entry === "object" && !Array.isArray(entry)) {
      if (entry.path) {
        out.push(entry);
        return;
      }
      if (Array.isArray(entry.artifacts)) {
        entry.artifacts.forEach(add);
        return;
      }
    }
    blockers.push({
      code: `artifact-${label}-malformed`,
      message: `${label} artifact entry is not {path, sha256}: ${JSON.stringify(entry)?.slice(0, 90)}`,
    });
  };
  if (Array.isArray(value)) value.forEach(add);
  else if (value !== undefined && value !== null) add(value);
  return out;
}

function normalizeStringList(value, field, blockers) {
  if (value === undefined || value === null) {
    blockers.push({
      code: `${field}-missing`,
      message: `snapshot must declare \`${field}\` as an array (empty is allowed, but the key is required)`,
    });
    return [];
  }
  if (!Array.isArray(value)) {
    blockers.push({ code: `${field}-not-array`, message: `snapshot.${field} must be an array of strings` });
    return [];
  }
  const out = [];
  value.forEach((entry, i) => {
    if (typeof entry !== "string" || !entry.trim()) {
      blockers.push({ code: `${field}-entry-${i}`, message: `snapshot.${field}[${i}] must be a non-empty string` });
    } else out.push(entry.trim());
  });
  return out;
}

/**
 * Validate a parsed snapshot object. The snapshot directory is the base for
 * every artifact path. Returns the normalized object and every blocker; a
 * snapshot is only `verified-effective` when `ok` is true.
 */
export function validateSnapshotObject(snap, { snapshotDir } = {}) {
  const blockers = [];
  const warnings = [];
  const dir = snapshotDir ? resolve(snapshotDir) : null;

  if (!snap || typeof snap !== "object" || Array.isArray(snap)) {
    return {
      ok: false,
      blockers: [{ code: "snapshot-not-object", message: "snapshot is not a JSON object" }],
      warnings,
      normalized: null,
    };
  }
  if (snap.schema !== SNAPSHOT_SCHEMA) {
    blockers.push({
      code: "snapshot-schema",
      message: `snapshot.schema must be "${SNAPSHOT_SCHEMA}" (got ${JSON.stringify(snap.schema)})`,
    });
  }

  const projectId = stringField(snap.project_id);
  if (!projectId) {
    blockers.push({ code: "project-id-missing", message: "snapshot.project_id is required" });
  } else if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(projectId)) {
    blockers.push({ code: "project-id-shape", message: `snapshot.project_id is not a platform id: ${projectId}` });
  } else if (/^(project|unknown|todo|tbd|none|example|sample)$/i.test(projectId)) {
    blockers.push({ code: "project-id-placeholder", message: `snapshot.project_id is a placeholder: ${projectId}` });
  }

  const model = modelName(snap.model);
  if (!model) {
    blockers.push({ code: "model-missing", message: "snapshot.model is required (expected \"Luna\")" });
  } else if (model.toLowerCase() !== "luna") {
    blockers.push({ code: "model-not-luna", message: `snapshot.model must be Luna (got ${model})` });
  }

  const capture = snap.capture && typeof snap.capture === "object" ? snap.capture : {};
  if (!snap.capture || typeof snap.capture !== "object" || Array.isArray(snap.capture)) {
    blockers.push({ code: "capture-missing", message: "snapshot.capture object is required" });
  }
  const method = normalizeMethod(capture.method ?? snap.method);
  if (!CAPTURE_METHODS.includes(method)) {
    blockers.push({
      code: "capture-method",
      message: `snapshot.capture.method must be one of ${CAPTURE_METHODS.join(", ")} (got ${JSON.stringify(capture.method ?? snap.method)})`,
    });
  }
  if (method === "intended-only") {
    blockers.push({
      code: "intended-only-not-effective",
      message: "intended-only manifests describe what was intended; they are never evidence of the effective published configuration",
    });
  }
  const capturedAt = stringField(capture.captured_at ?? snap.captured_at);
  if (!isIsoTimestamp(capturedAt)) {
    blockers.push({
      code: "captured-at-invalid",
      message: "snapshot.capture.captured_at must be an ISO-8601 timestamp with an offset or Z",
    });
  }
  const exportScope = stringField(capture.export_scope).toLowerCase();
  if (["full", "complete", "effective-complete", "all"].includes(exportScope)) {
    blockers.push({
      code: "export-scope-overclaimed",
      message: "the platform does not expose a complete effective configuration; export_scope cannot be full/complete",
    });
  } else if (!exportScope) {
    warnings.push({
      code: "export-scope-unstated",
      message: "capture.export_scope is unstated; hidden platform configuration remains unknown",
    });
  }
  const currentVerified = capture.current_effective_config_verified;
  if (currentVerified === false) {
    blockers.push({
      code: "current-config-not-verified",
      message: "capture states the current effective configuration was not verified; a historical read-back is not a current publication snapshot",
    });
  } else if (currentVerified !== true) {
    blockers.push({
      code: "current-config-verification-missing",
      message: "capture.current_effective_config_verified must be true to treat this snapshot as evidence of the current publication",
    });
  }

  const publication = capture.publication ?? snap.publication ?? null;
  const revision = capture.revision ?? snap.revision ?? null;
  if (publication !== null && isPlaceholderValue(publication)) {
    blockers.push({ code: "publication-placeholder", message: "snapshot publication is present but empty/placeholder" });
  }
  if (revision !== null && isPlaceholderValue(revision)) {
    blockers.push({ code: "revision-placeholder", message: "snapshot revision is present but empty/placeholder" });
  }
  if (publication === null) {
    warnings.push({ code: "publication-not-exposed", message: "publication metadata is absent; record it under unknowns" });
  }
  if (revision === null) {
    warnings.push({ code: "revision-not-exposed", message: "revision metadata is absent; record it under unknowns" });
  }

  const unknowns = normalizeStringList(snap.unknowns, "unknowns", blockers);
  const limitations = normalizeStringList(snap.limitations, "limitations", blockers);

  const artifactsRaw = snap.artifacts;
  if (!artifactsRaw || typeof artifactsRaw !== "object" || Array.isArray(artifactsRaw)) {
    blockers.push({ code: "artifacts-missing", message: "snapshot.artifacts object is required" });
  }
  const artifacts = { instructions: [], knowledge: [], ui_settings: [] };
  for (const [category, minBytes] of [["instructions", 16], ["knowledge", 1], ["ui_settings", 1]]) {
    const entries = artifactsRaw && typeof artifactsRaw === "object"
      ? collectArtifactEntries(artifactsRaw[category], category, blockers)
      : [];
    if (!entries.length) {
      blockers.push({
        code: `artifact-${category}-missing`,
        message: `snapshot.artifacts.${category} must name at least one captured, hashed artifact`,
      });
      continue;
    }
    for (const entry of entries) {
      const normalizedPath = normalizeArtifactPath(entry.path);
      if (!normalizedPath.ok) {
        blockers.push({ code: `artifact-${category}-path`, message: normalizedPath.reason });
        continue;
      }
      if (!dir) {
        blockers.push({ code: `artifact-${category}-no-dir`, message: "snapshot directory is unknown; cannot hash artifacts" });
        continue;
      }
      const abs = resolve(dir, normalizedPath.path);
      if (!isInside(dir, abs)) {
        blockers.push({ code: `artifact-${category}-escape`, message: `${entry.path} resolves outside the snapshot directory` });
        continue;
      }
      if (!existsSync(abs) || !statSync(abs).isFile()) {
        blockers.push({ code: `artifact-${category}-absent`, message: `${normalizedPath.path} does not exist beside the snapshot` });
        continue;
      }
      const bytes = readFileSync(abs);
      const actual = sha256Bytes(bytes);
      if (bytes.length === 0) {
        blockers.push({ code: `artifact-${category}-empty`, message: `${normalizedPath.path} is empty` });
      } else if (!bytes.toString("utf8").trim()) {
        blockers.push({ code: `artifact-${category}-blank`, message: `${normalizedPath.path} contains only whitespace` });
      } else if (bytes.length < minBytes) {
        blockers.push({ code: `artifact-${category}-too-small`, message: `${normalizedPath.path} is smaller than ${minBytes} bytes` });
      }
      if (entry.sha256 === undefined || entry.sha256 === null) {
        blockers.push({ code: `artifact-${category}-sha-missing`, message: `${normalizedPath.path} has no recorded sha256` });
      } else if (isPlaceholderHash(entry.sha256)) {
        blockers.push({ code: `artifact-${category}-sha-placeholder`, message: `${normalizedPath.path} has a placeholder/invalid sha256` });
      } else if (String(entry.sha256).toLowerCase() !== actual) {
        blockers.push({
          code: `artifact-${category}-sha-mismatch`,
          message: `${normalizedPath.path} recorded sha256 does not match the bytes on disk`,
        });
      }
      if (entry.bytes !== undefined && Number(entry.bytes) !== bytes.length) {
        blockers.push({ code: `artifact-${category}-bytes-mismatch`, message: `${normalizedPath.path} recorded byte count does not match` });
      }
      artifacts[category].push({ path: normalizedPath.path, sha256: actual, bytes: bytes.length });
    }
  }

  const agent = snap.agent && typeof snap.agent === "object" ? snap.agent : {};
  let publicUrl = null;
  if (agent.public_url !== undefined) {
    try {
      const u = new URL(String(agent.public_url));
      if (!/^https?:$/.test(u.protocol)) throw new Error("not http(s)");
      publicUrl = u.href;
    } catch {
      blockers.push({ code: "agent-public-url-invalid", message: "snapshot.agent.public_url is not an http(s) URL" });
    }
  }
  if (agent.project_id !== undefined && stringField(agent.project_id) !== projectId) {
    blockers.push({ code: "agent-project-mismatch", message: "snapshot.agent.project_id does not match snapshot.project_id" });
  }

  const configMaterial = {
    project_id: projectId,
    model: "Luna",
    capture_method: method,
    current_effective_config_verified: currentVerified === true,
    publication,
    revision,
    public_url: publicUrl,
    artifacts: {
      instructions: artifacts.instructions.map(({ path, sha256 }) => ({ path, sha256 })),
      knowledge: artifacts.knowledge.map(({ path, sha256 }) => ({ path, sha256 })),
      ui_settings: artifacts.ui_settings.map(({ path, sha256 }) => ({ path, sha256 })),
    },
    unknowns,
    limitations,
  };
  const configHash = hashJson(configMaterial);

  return {
    ok: blockers.length === 0,
    blockers,
    warnings,
    normalized: {
      schema: SNAPSHOT_SCHEMA,
      project_id: projectId,
      model: "Luna",
      capture: { method, captured_at: capturedAt, publication, revision, export_scope: exportScope || null, current_effective_config_verified: currentVerified === true },
      agent: { public_url: publicUrl },
      artifacts,
      unknowns,
      limitations,
      config_hash: configHash,
    },
  };
}

/** Verify a snapshot file on disk. Pure read; never writes. */
export function verifySnapshot(snapshotPath) {
  const abs = resolve(snapshotPath);
  const base = {
    schema: SNAPSHOT_SCHEMA,
    path: abs,
    snapshot_sha256: null,
    status: "invalid",
    project_id: null,
    model: null,
    captured_at: null,
    method: null,
    current_effective_config_verified: null,
    config_hash: null,
    artifact_hashes: { instructions: [], knowledge: [], ui_settings: [] },
    normalized: null,
  };
  if (!existsSync(abs)) {
    return { ...base, ok: false, blockers: [{ code: "snapshot-absent", message: `snapshot does not exist: ${abs}` }], warnings: [] };
  }
  let raw;
  try {
    raw = readFileSync(abs);
  } catch (e) {
    return { ...base, ok: false, blockers: [{ code: "snapshot-unreadable", message: String(e.message || e) }], warnings: [] };
  }
  let snap;
  try {
    snap = JSON.parse(raw.toString("utf8"));
  } catch (e) {
    return {
      ...base,
      snapshot_sha256: sha256Bytes(raw),
      ok: false,
      blockers: [{ code: "snapshot-json", message: `snapshot is not valid JSON: ${String(e.message || e)}` }],
      warnings: [],
    };
  }
  const report = validateSnapshotObject(snap, { snapshotDir: dirname(abs) });
  const n = report.normalized;
  return {
    ...base,
    snapshot_sha256: sha256Bytes(raw),
    status: report.ok ? "verified-effective" : "invalid",
    ok: report.ok,
    project_id: n?.project_id ?? null,
    model: n?.model ?? null,
    captured_at: n?.capture.captured_at ?? null,
    method: n?.capture.method ?? null,
    current_effective_config_verified: n?.capture.current_effective_config_verified ?? null,
    config_hash: n?.config_hash ?? null,
    artifact_hashes: n?.artifacts ?? base.artifact_hashes,
    normalized: n,
    blockers: report.blockers,
    warnings: report.warnings,
  };
}

/** A canonical hash of the effective configuration, independent of capture time. */
export function effectiveConfigHash(snapshotReport) {
  return snapshotReport?.config_hash ?? null;
}

/* -------------------------------------------------------------- run plans */

function readJson(path, code, blockers) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    blockers.push({ code, message: `${path}: ${String(e.message || e)}` });
    return null;
  }
}

function resolveDeclaredPath(value, baseDir, repoRoot) {
  if (typeof value !== "string" || !value.trim()) return null;
  const raw = value.trim();
  if (isAbsolute(raw)) return resolve(raw);
  const besidePlan = resolve(baseDir, raw);
  if (existsSync(besidePlan)) return besidePlan;
  return resolve(repoRoot ?? baseDir, raw);
}

/**
 * Validate a run plan against a verified snapshot, scenario set, and optional
 * pair schedule. Pair execution is not implemented; a plan that asks for it is
 * refused rather than silently downgraded.
 */
export function validateRunPlan(planPath, { repoRoot, snapshotReport, setPath = null } = {}) {
  const blockers = [];
  const warnings = [];
  const abs = resolve(planPath);
  const plan = readJson(abs, "run-plan-json", blockers);
  if (!plan) return { ok: false, blockers, warnings, plan: null, path: abs, hashes: {} };
  if (plan.schema !== RUN_PLAN_SCHEMA) {
    blockers.push({ code: "run-plan-schema", message: `run plan schema must be ${RUN_PLAN_SCHEMA}` });
  }
  for (const field of ["run_id", "phase", "arm"]) {
    if (typeof plan[field] !== "string" || !plan[field].trim()) {
      blockers.push({ code: `run-plan-${field}`, message: `run plan requires a non-empty ${field}` });
    }
  }
  if (plan.run_id && !/^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$/.test(plan.run_id)) {
    blockers.push({ code: "run-plan-run-id-shape", message: "run plan run_id has unsupported characters" });
  }
  if (Array.isArray(plan.allowed_phases) && plan.phase && !plan.allowed_phases.includes(plan.phase)) {
    blockers.push({ code: "run-plan-phase", message: `phase ${plan.phase} is not in allowed_phases` });
  }
  if (!snapshotReport || !snapshotReport.ok) {
    blockers.push({ code: "run-plan-snapshot-unverified", message: "run plan cannot bind to an unverified snapshot" });
  }
  if (snapshotReport?.ok && plan.project_id !== snapshotReport.project_id) {
    blockers.push({ code: "run-plan-project-mismatch", message: "run plan project_id does not match the snapshot" });
  }
  if (plan.pair_execution === true) {
    blockers.push({
      code: "pair-execution-unimplemented",
      message: "run_paired.mjs consumes per-arm plans and the schedule; a plan must not request pair_execution",
    });
  }
  if (plan.collection_authorized === false) {
    blockers.push({
      code: "collection-not-authorized",
      message: "run plan explicitly marks collection_authorized=false",
    });
  } else if (plan.collection_authorized === undefined || plan.collection_authorized === null) {
    warnings.push({
      code: "collection-authorization-unstated",
      message: "run plan does not record collection_authorized; capture requires an explicit authorization record",
    });
  }
  if (["preparation_only", "preparation-only", "blocked", "draft", "not_ready", "not-ready"].includes(String(plan.status || "").toLowerCase())) {
    blockers.push({ code: "plan-not-ready", message: `run plan status ${plan.status} is not a ready collection state` });
  }

  const hashes = {};
  const baseDir = dirname(abs);
  if (plan.snapshot && typeof plan.snapshot === "object") {
    const snapPath = resolveDeclaredPath(plan.snapshot.path, baseDir, repoRoot);
    if (!snapPath) {
      blockers.push({ code: "run-plan-snapshot-path", message: "run plan snapshot.path is missing" });
    } else {
      if (!existsSync(snapPath)) {
        blockers.push({ code: "run-plan-snapshot-absent", message: `run plan snapshot is absent: ${snapPath}` });
      } else {
        const actual = sha256File(snapPath);
        hashes.snapshot_sha256 = actual;
        if (plan.snapshot.sha256 && String(plan.snapshot.sha256).toLowerCase() !== actual) {
          blockers.push({ code: "run-plan-snapshot-sha", message: "run plan snapshot sha256 does not match the file" });
        }
        if (snapshotReport?.path && resolve(snapshotReport.path) !== snapPath) {
          blockers.push({ code: "run-plan-snapshot-different", message: "run plan names a different snapshot than the one verified" });
        }
      }
      if (!plan.snapshot.sha256) {
        blockers.push({ code: "run-plan-snapshot-sha-missing", message: "run plan snapshot.sha256 is required" });
      }
      if (!plan.snapshot.config_hash) {
        blockers.push({ code: "run-plan-config-hash-missing", message: "run plan snapshot.config_hash is required" });
      } else if (snapshotReport?.config_hash && plan.snapshot.config_hash !== snapshotReport.config_hash) {
        blockers.push({ code: "run-plan-config-hash", message: "run plan config_hash does not match the verified snapshot" });
      }
    }
  } else {
    blockers.push({ code: "run-plan-snapshot-missing", message: "run plan requires a snapshot object with path and sha256" });
  }

  if (plan.set && typeof plan.set === "object") {
    const declared = resolveDeclaredPath(plan.set.path, baseDir, repoRoot);
    if (!declared || !existsSync(declared)) {
      blockers.push({ code: "run-plan-set-absent", message: "run plan scenario set is absent" });
    } else {
      const actual = sha256File(declared);
      hashes.set_sha256 = actual;
      if (!plan.set.sha256) {
        blockers.push({ code: "run-plan-set-sha-missing", message: "run plan set.sha256 is required" });
      } else if (String(plan.set.sha256).toLowerCase() !== actual) {
        blockers.push({ code: "run-plan-set-sha", message: "scenario set changed since the plan was written" });
      }
      if (setPath && resolve(setPath) !== declared) {
        blockers.push({ code: "run-plan-set-different", message: "run plan names a different scenario set than --set" });
      }
    }
  } else {
    blockers.push({ code: "run-plan-set-missing", message: "run plan requires a set object with path and sha256" });
  }

  if (plan.schedule && typeof plan.schedule === "object") {
    const declared = resolveDeclaredPath(plan.schedule.path, baseDir, repoRoot);
    if (!declared || !existsSync(declared)) {
      blockers.push({ code: "run-plan-schedule-absent", message: "run plan schedule is absent" });
    } else {
      const actual = sha256File(declared);
      hashes.schedule_sha256 = actual;
      if (!plan.schedule.sha256) {
        blockers.push({ code: "run-plan-schedule-sha-missing", message: "run plan schedule.sha256 is required" });
      } else if (String(plan.schedule.sha256).toLowerCase() !== actual) {
        blockers.push({ code: "run-plan-schedule-sha", message: "pair schedule changed since the plan was written" });
      }
      const sched = readJson(declared, "run-plan-schedule-json", blockers);
      if (sched) {
        if (sched.schema !== SCHEDULE_SCHEMA) {
          blockers.push({ code: "run-plan-schedule-schema", message: `schedule schema must be ${SCHEDULE_SCHEMA}` });
        }
        if (Array.isArray(sched.arms) && plan.arm && !sched.arms.includes(plan.arm)) {
          blockers.push({ code: "run-plan-arm-not-scheduled", message: `arm ${plan.arm} is not in the pair schedule` });
        }
        if (sched.run_id && plan.run_id && sched.run_id !== plan.run_id) {
          blockers.push({ code: "run-plan-run-id-mismatch", message: "run plan run_id does not match the schedule" });
        }
      }
    }
  } else if (plan.schedule !== undefined && plan.schedule !== null) {
    blockers.push({ code: "run-plan-schedule-shape", message: "run plan schedule must be an object {path, sha256}" });
  }

  if (plan.trials !== undefined && plan.trials !== null) {
    const t = Number(plan.trials);
    if (!Number.isInteger(t) || t < 1) {
      blockers.push({ code: "run-plan-trials", message: "run plan trials must be a positive integer" });
    }
  }
  if (plan.ids !== undefined && plan.ids !== null && (!Array.isArray(plan.ids) || plan.ids.some((x) => typeof x !== "string"))) {
    blockers.push({ code: "run-plan-ids", message: "run plan ids must be an array of strings" });
  }

  return { ok: blockers.length === 0, blockers, warnings, plan, path: abs, hashes };
}

export function buildRunPlan({
  runId, arm, phase, snapshotPath, snapshotReport, setPath, setSha256 = null,
  schedulePath = null, scheduleSha256 = null, trials = null, ids = null, pairExecution = false,
  collectionAuthorized = null, status = null,
}) {
  return {
    schema: RUN_PLAN_SCHEMA,
    run_id: runId,
    arm,
    phase,
    project_id: snapshotReport?.project_id ?? null,
    snapshot: {
      path: snapshotPath,
      sha256: existsSync(snapshotPath) ? sha256File(snapshotPath) : null,
      config_hash: snapshotReport?.config_hash ?? null,
    },
    set: {
      path: setPath,
      sha256: setSha256 ?? (existsSync(setPath) ? sha256File(setPath) : null),
    },
    schedule: schedulePath ? {
      path: schedulePath,
      sha256: scheduleSha256 ?? (existsSync(schedulePath) ? sha256File(schedulePath) : null),
    } : null,
    trials,
    ids,
    pair_execution: !!pairExecution,
    collection_authorized: collectionAuthorized,
    status,
    created_at: new Date().toISOString(),
  };
}

/* ----------------------------------------------------------------- stores */

export function loadStore(path) {
  if (!existsSync(path)) return null;
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch (e) {
    throw new Error(`existing output is unreadable: ${String(e.message || e)}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("existing output is not valid JSON; refusing to overwrite it");
  }
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.records)) {
    throw new Error("existing output has no records array; refusing to overwrite it");
  }
  return parsed;
}

/**
 * Revalidate a run plan from disk before any resume decision. Every binding is
 * recomputed from the actual snapshot and scenario-set bytes; a plan's declared
 * hashes are never trusted on their own. Any unresolved plan blocker refuses
 * the resume, including a changed set, snapshot, project, phase, or schedule.
 */
export function evaluateResume({ planPath, storePath, repoRoot }) {
  const planAbs = resolve(planPath);
  const blockers = [];
  const warnings = [];
  let raw;
  try {
    raw = JSON.parse(readFileSync(planAbs, "utf8"));
  } catch (e) {
    return {
      ok: false,
      blockers: [{ code: "resume-plan-unreadable", message: `cannot read plan: ${String(e.message || e)}` }],
      warnings,
      plan: null,
      snapshot: null,
      meta: null,
    };
  }
  const planDir = dirname(planAbs);
  const snapshotPath = raw.snapshot?.path
    ? (isAbsolute(raw.snapshot.path) ? raw.snapshot.path : resolve(planDir, raw.snapshot.path))
    : null;
  if (!snapshotPath) {
    blockers.push({ code: "resume-snapshot-missing", message: "plan has no snapshot.path" });
  }
  const snapshot = snapshotPath ? verifySnapshot(snapshotPath) : null;
  if (snapshot) {
    for (const b of snapshot.blockers) blockers.push({ ...b, message: `snapshot: ${b.message}` });
  }
  const declaredSet = raw.set?.path
    ? (isAbsolute(raw.set.path) ? raw.set.path : resolve(planDir, raw.set.path))
    : null;
  if (!declaredSet) {
    blockers.push({ code: "resume-set-missing", message: "plan has no set.path" });
  } else if (!existsSync(declaredSet)) {
    blockers.push({ code: "resume-set-absent", message: `plan scenario set is absent: ${declaredSet}` });
  }
  const planReport = validateRunPlan(planAbs, {
    repoRoot,
    snapshotReport: snapshot,
    setPath: declaredSet,
  });
  for (const b of planReport.blockers) blockers.push(b);
  for (const w of planReport.warnings) warnings.push(w);
  if (blockers.length) {
    return { ok: false, blockers, warnings, plan: raw, snapshot, meta: null, setPath: declaredSet };
  }
  const setSha = sha256File(declaredSet);
  if (raw.set?.sha256 && String(raw.set.sha256).toLowerCase() !== setSha) {
    blockers.push({ code: "resume-set-sha", message: "scenario set changed since the plan was written" });
  }
  const schedulePath = raw.schedule?.path
    ? (isAbsolute(raw.schedule.path) ? raw.schedule.path : resolve(planDir, raw.schedule.path))
    : null;
  const scheduleSha = schedulePath ? sha256File(schedulePath) : null;
  const meta = buildStoreMeta({
    tool: "resume-check",
    runId: raw.run_id,
    arm: raw.arm,
    phase: raw.phase,
    projectId: snapshot?.project_id ?? null,
    configHash: snapshot?.config_hash ?? null,
    snapshotSha256: snapshot?.snapshot_sha256 ?? null,
    artifactHashes: snapshot?.artifact_hashes ?? null,
    setPath: displayPath(repoRoot, declaredSet),
    setSha256: setSha,
    scheduleSha256: scheduleSha,
    harnessGit: gitRevision(repoRoot),
    batch: raw.batch ?? null,
  });
  let store = null;
  try {
    store = loadStore(resolve(storePath));
  } catch (e) {
    blockers.push({ code: "resume-store-unreadable", message: String(e.message || e) });
  }
  const check = checkResume(store, meta);
  for (const b of check.blockers) blockers.push(b);
  for (const w of check.warnings) warnings.push(w);
  return {
    ok: blockers.length === 0,
    blockers,
    warnings,
    plan: raw,
    snapshot,
    meta,
    setPath: declaredSet,
    setSha,
    scheduleSha,
  };
}

export function buildStoreMeta({
  tool, runId, arm, phase, projectId, configHash, snapshotSha256, artifactHashes,
  setPath, setSha256, scheduleSha256 = null, harnessGit, batch = null, legacyUnverified = false,
}) {
  return {
    schema: STORE_META_SCHEMA,
    tool,
    run_id: runId,
    arm,
    phase,
    project_id: projectId,
    config_hash: configHash,
    snapshot_sha256: snapshotSha256,
    artifact_hashes: artifactHashes,
    set_path: setPath,
    set_sha256: setSha256,
    schedule_sha256: scheduleSha256,
    harness_git: harnessGit,
    batch,
    observed_platform_config: "unknown-not-observable-at-runtime",
    intended_inputs_sha256: hashJson({
      snapshot_sha256: snapshotSha256,
      config_hash: configHash,
      set_sha256: setSha256,
      schedule_sha256: scheduleSha256,
    }),
    legacy_unverified: !!legacyUnverified,
    created_at: new Date().toISOString(),
  };
}

const RESUME_KEYS = ["schema", "run_id", "project_id", "config_hash", "phase", "set_sha256", "arm"];

/**
 * Refuse to append when the project, effective config, phase, scenario set, or
 * arm has changed. Records that predate provenance are retained and warned
 * about; they are never silently relabelled.
 */
export function checkResume(store, meta) {
  const blockers = [];
  const warnings = [];
  if (!store) return { ok: true, fresh: true, blockers, warnings };
  if (!Array.isArray(store.records)) {
    return {
      ok: false,
      fresh: false,
      blockers: [{ code: "store-records-missing", message: "existing output has no records array" }],
      warnings,
    };
  }
  if (!store.meta) {
    return {
      ok: false,
      fresh: false,
      blockers: [{
        code: "store-meta-missing",
        message: "existing output has no provenance meta; refusing to append without --allow-legacy-store (not provided)",
      }],
      warnings,
    };
  }
  for (const key of RESUME_KEYS) {
    if (!(key in store.meta) || !(key in meta)) {
      blockers.push({
        code: `resume-${key.replace(/_/g, "-")}-missing`,
        message: `cannot compare ${key}: existing meta has it=${key in store.meta}, this run has it=${key in meta}`,
      });
      continue;
    }
    const have = store.meta[key] ?? null;
    const want = meta[key] ?? null;
    if (have !== want) {
      blockers.push({
        code: `resume-${key.replace(/_/g, "-")}-mismatch`,
        message: `existing output ${key}=${JSON.stringify(have)} does not match this run ${JSON.stringify(want)}`,
      });
    }
  }
  if (meta.schedule_sha256 && (store.meta.schedule_sha256 ?? null) !== meta.schedule_sha256) {
    blockers.push({ code: "resume-schedule-mismatch", message: "pair schedule changed since this output was started" });
  }
  const stale = (store.records || []).filter((r) => {
    const p = r?.provenance;
    if (!p || p.legacy_unverified) return false;
    return (p.config_hash && p.config_hash !== meta.config_hash) || (p.phase && p.phase !== meta.phase);
  });
  if (stale.length) {
    blockers.push({
      code: "resume-record-config-mismatch",
      message: `${stale.length} existing record(s) were captured under a different config/phase; refusing to mix them`,
    });
  }
  const legacy = (store.records || []).filter((r) => r?.provenance?.legacy_unverified || !r?.provenance);
  if (legacy.length) {
    warnings.push({ code: "resume-legacy-records", message: `${legacy.length} record(s) have no provenance and are retained unmodified` });
  }
  return { ok: blockers.length === 0, fresh: false, blockers, warnings };
}

/** Historical records with an `error` field or status invalid are attempts, not results. */
export function isValidRecord(record) {
  if (!record || typeof record !== "object") return false;
  if (record.error) return false;
  if (record.status === "invalid") return false;
  if (Array.isArray(record.replies)) {
    if (!record.replies.length) return false;
    if (record.turns && record.replies.length !== record.turns.length) return false;
    return record.replies.every((r) => typeof r === "string" && r.trim());
  }
  return typeof record.thread === "string" && record.thread.trim().length > 0;
}

/**
 * The next attempt number for a scenario/trial, and whether a valid result
 * already exists. Invalid attempts are never overwritten; a retry appends.
 */
export function nextAttempt(store, scenarioId, trial) {
  let max = 0;
  let valid = null;
  for (const record of store?.records || []) {
    if (record.id !== scenarioId || Number(record.trial) !== Number(trial)) continue;
    max = Math.max(max, Number(record.attempt) || 1);
    if (isValidRecord(record)) valid = record;
  }
  return { attempt: max + 1, complete: Boolean(valid), validRecord: valid };
}

/* ------------------------------------------------------------ reply health */

const QUOTA_RE = /cannot continue right now/i;
const RENDER_RE = /Something went wrong loading this page|The answer could not be displayed|Tap to retry|Generating response|Working…|Working\.\.\./i;

/**
 * Empty replies, quota messages, and render/partial text are invalid attempts.
 * A genuinely short reply ("$99.") is valid: there is no minimum length.
 */
export function classifyReply(text) {
  if (typeof text !== "string" || !text.trim()) return { valid: false, reason: "empty-reply" };
  if (QUOTA_RE.test(text)) return { valid: false, reason: "quota-message" };
  if (RENDER_RE.test(text)) return { valid: false, reason: "render-or-partial-text" };
  return { valid: true, reason: "ok" };
}

/** Normalize smart quotes, dashes, whitespace, and case for marker matching. */
export function normalizeThreadText(text) {
  return String(text ?? "")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2013\u2014]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function customerMarkerIndex(lines, customer) {
  const target = normalizeThreadText(customer);
  if (!target) return -1;
  let exact = -1;
  let phrase = -1;
  for (let i = 0; i < lines.length; i++) {
    let line = normalizeThreadText(lines[i]);
    line = line.replace(/^(?:you(?: said)?|customer|user|visitor)\s*:\s*/, "").replace(/^>\s*/, "");
    if (line === target) exact = i;
    else if (target.length >= 12 && phrase < 0) {
      const boundary = new RegExp(`(^|[^a-z0-9])${escapeRegExp(target)}([^a-z0-9]|$)`);
      if (boundary.test(line)) phrase = i;
    }
  }
  return exact >= 0 ? exact : phrase;
}

const UI_ONLY = /^(home|start over|speak|send|attach files|retry)$/i;

/**
 * Whole-page capture validity. A greeting-only page is not a reply: the
 * customer's message must appear as a whole normalized line (or as a
 * word-bounded phrase for a long message), and at least one non-UI line must
 * follow it. Short answers such as "$99." remain valid.
 */
export function classifyThread(thread, customer) {
  const base = classifyReply(thread);
  if (!base.valid) return base;
  if (typeof customer !== "string" || !customer.trim()) {
    return { valid: false, reason: "customer-marker-missing" };
  }
  const lines = String(thread).split(/\r?\n/);
  const index = customerMarkerIndex(lines, customer);
  if (index < 0) return { valid: false, reason: "customer-marker-absent" };
  const tailLines = lines.slice(index + 1)
    .map((line) => line.trim())
    .filter((line) => line && !UI_ONLY.test(line));
  if (!tailLines.length) return { valid: false, reason: "no-reply-after-customer" };
  const health = classifyReply(tailLines.join("\n"));
  if (!health.valid) return health;
  return { valid: true, reason: "ok" };
}

/* ------------------------------------------------------------- target URLs */

export function normalizeUrlForCompare(input) {
  const u = new URL(String(input));
  const defaultPort = (u.protocol === "https:" && u.port === "443") || (u.protocol === "http:" && u.port === "80");
  let path = u.pathname || "/";
  if (path.length > 1 && path.endsWith("/")) path = path.slice(0, -1);
  return `${u.protocol}//${u.hostname.toLowerCase()}${defaultPort || !u.port ? "" : `:${u.port}`}${path}`;
}

export function validateObservedUrl(observed, { expected = null, projectId = null } = {}) {
  const blockers = [];
  const warnings = [];
  let u;
  try {
    u = new URL(String(observed || ""));
  } catch {
    return {
      ok: false,
      binding: "none",
      blockers: [{ code: "url-invalid", message: `observed tab URL is not a URL: ${JSON.stringify(observed)}` }],
      warnings,
      normalized_observed: null,
      observed_url_sha256: null,
    };
  }
  if (!/^https?:$/.test(u.protocol)) {
    blockers.push({ code: "url-not-http", message: `observed tab URL is not http(s): ${u.href}` });
  }
  if (/^\/(admin|dashboard|builder|login|auth|signin|settings)(\/|$)/i.test(u.pathname)) {
    blockers.push({ code: "url-builder-surface", message: `observed tab is a builder/admin surface, not the published agent: ${u.pathname}` });
  }
  let binding = "declared-unverified";
  const normalizedObserved = u.protocol.startsWith("http") ? normalizeUrlForCompare(u.href) : u.href;
  if (expected) {
    let e;
    try {
      e = new URL(String(expected));
    } catch {
      blockers.push({ code: "expected-url-invalid", message: "expected agent URL is not a URL" });
      e = null;
    }
    if (e) {
      if (e.hostname.toLowerCase() !== u.hostname.toLowerCase()) {
        blockers.push({ code: "url-host-mismatch", message: `observed host ${u.hostname} does not match expected ${e.hostname}` });
      } else if (normalizeUrlForCompare(e.href) !== normalizedObserved) {
        blockers.push({ code: "url-path-mismatch", message: "observed agent path does not match the expected published URL" });
      }
    }
  } else {
    warnings.push({ code: "url-not-bound", message: "no expected agent URL was supplied; target binding is declaration-only" });
  }
  if (projectId && !u.href.toLowerCase().includes(String(projectId).toLowerCase())) {
    warnings.push({
      code: "url-project-not-visible",
      message: "project id does not appear in the observed URL; project binding is declared, not observed",
    });
  } else if (projectId) {
    binding = "observed-in-url";
  }
  return {
    ok: blockers.length === 0,
    binding,
    blockers,
    warnings,
    normalized_observed: normalizedObserved,
    observed_url_sha256: sha256Text(normalizedObserved),
  };
}

/* -------------------------------------------------------------- scheduling */

export function pairId(runId, scenarioId, trial, rep = 1) {
  return "pair-" + sha256Text(`${runId}|${scenarioId}|${Number(trial)}|${Number(rep)}`).slice(0, 12);
}

/**
 * Counterbalanced AB/BA schedule. Stable ids are derived only from run id,
 * scenario id, and trial, so regenerating the same schedule reproduces them.
 * Order alternates within each scenario by trial; an extra rep shifts parity
 * only when trials is odd, so complete blocks stay balanced.
 */
export function buildSchedule({ runId, scenarioIds, arms, trials = 1, reps = 1 }) {
  if (!Array.isArray(arms) || arms.length !== 2) throw new Error("a pair schedule needs exactly two arms");
  if (!Number.isInteger(trials) || trials < 1) throw new Error("trials must be a positive integer");
  if (!Number.isInteger(reps) || reps < 1) throw new Error("reps must be a positive integer");
  const ids = [...scenarioIds].sort();
  const pairs = [];
  ids.forEach((scenario, si) => {
    for (let rep = 1; rep <= reps; rep++) {
      for (let trial = 1; trial <= trials; trial++) {
        const ab = ((si + trial - 1 + (rep - 1) * trials) % 2) === 0;
        pairs.push({
          pair_id: pairId(runId, scenario, trial, rep),
          scenario,
          trial,
          rep,
          order: ab ? "AB" : "BA",
          arms: ab ? [arms[0], arms[1]] : [arms[1], arms[0]],
          status: "pending",
          attempts: [],
        });
      }
    }
  });
  return {
    schema: SCHEDULE_SCHEMA,
    run_id: runId,
    arms,
    trials,
    reps,
    scenarios: ids,
    pair_execution_implemented: false,
    completed_pairs: 0,
    pairs,
    created_at: new Date().toISOString(),
    note: "Ordered pairs only. No pair runner exists; run.mjs/run_mt.mjs record one arm per invocation and never claim a completed pair.",
  };
}

/**
 * Account for pairs from recorded arm stores. A pair is complete only when both
 * arms have a valid record for the scenario/trial. With no stores every pair is
 * pending; this function never invents collected data.
 */
export function summarizePairs(schedule, stores = {}) {
  const byArm = {};
  for (const arm of schedule.arms || []) {
    const store = stores[arm];
    byArm[arm] = Array.isArray(store?.records) ? store.records.length : 0;
  }

  // A scenario#trial key can appear in more than one pair when a schedule has
  // reps or duplicated cells. In that case a record is only evidence for the
  // pair whose pair_id it carries; one record may never satisfy two pairs.
  const cellCounts = new Map();
  for (const pair of schedule.pairs || []) {
    const key = `${pair.scenario}#${pair.trial}`;
    cellCounts.set(key, (cellCounts.get(key) || 0) + 1);
  }
  const requiresPairId = Number(schedule.reps || 1) > 1;

  const pick = (arm, pair) => {
    const key = `${pair.scenario}#${pair.trial}`;
    const all = (stores[arm]?.records || []).filter(
      (r) => r && r.id === pair.scenario && Number(r.trial) === Number(pair.trial) && isValidRecord(r),
    );
    const needsId = requiresPairId || (cellCounts.get(key) || 1) > 1;
    const candidates = needsId
      ? all.filter((r) => r.provenance?.pair_id === pair.pair_id)
      : all;
    candidates.sort((a, b) => (Number(b.attempt) || 1) - (Number(a.attempt) || 1));
    return candidates[0] || null;
  };

  let completed = 0;
  let invalidAttempts = 0;
  const warnings = [];
  const pairs = (schedule.pairs || []).map((pair) => {
    const found = {};
    const attempts = [];
    for (const arm of pair.arms) {
      const matching = (stores[arm]?.records || []).filter(
        (r) => r && r.id === pair.scenario && Number(r.trial) === Number(pair.trial),
      );
      for (const r of matching) {
        attempts.push({
          arm,
          attempt: r.attempt ?? 1,
          status: isValidRecord(r) ? "valid" : "invalid",
          reason: r.invalid_reason ?? r.error ?? null,
        });
        if (!isValidRecord(r)) invalidAttempts++;
      }
      found[arm] = pick(arm, pair);
    }
    const haveBoth = pair.arms.every((arm) => Boolean(found[arm]));
    let orderEvidence = "missing";
    let orderOk = false;
    if (haveBoth) {
      const first = found[pair.arms[0]];
      const second = found[pair.arms[1]];
      const tFirst = Date.parse(first?.at ?? "");
      const tSecond = Date.parse(second?.at ?? "");
      if (Number.isFinite(tFirst) && Number.isFinite(tSecond) && tFirst !== tSecond) {
        orderEvidence = "capture-timestamps";
        // pair.arms is already ordered [first executed, second executed];
        // the AB/BA label describes which arm is first, not a second flip.
        orderOk = tFirst < tSecond;
      }
    }
    const complete = haveBoth && orderOk;
    if (haveBoth && !orderOk) {
      warnings.push({
        code: `pair-order-unverified:${pair.pair_id}`,
        message: `${pair.pair_id} has both records but no capture timestamps proving ${pair.order} order`,
      });
    }
    if (complete) completed++;
    return {
      ...pair,
      status: complete ? "complete" : "pending",
      order_evidence: orderEvidence,
      completed_at: complete
        ? (found[pair.arms[1]]?.at ?? null)
        : null,
      attempts,
      records: Object.fromEntries(pair.arms.map((arm) => [arm, found[arm] ? `recorded:${found[arm].attempt ?? 1}` : null])),
    };
  });
  return {
    schema: "agentplace-pair-accounting-v1",
    run_id: schedule.run_id,
    pair_execution_implemented: false,
    declared_pairs: pairs.length,
    completed_pairs: completed,
    pending_pairs: pairs.length - completed,
    invalid_attempts_retained: invalidAttempts,
    warnings,
    records_by_arm: byArm,
    pairs,
  };
}

/* --------------------------------------------------------------- output IO */

export function assertSafeOutput({ path, repoRoot, allowExisting = false, allowRepoOut = false }) {
  const abs = resolve(path);
  const blockers = [];
  if (repoRoot && isInside(repoRoot, abs) && !allowRepoOut) {
    blockers.push({
      code: "output-inside-repo",
      message: `refusing to write inside the repository (${displayPath(repoRoot, abs)}); pass --allow-repo-out for a deliberate historical destination`,
    });
  }
  if (existsSync(abs) && !allowExisting) {
    blockers.push({
      code: "output-exists",
      message: `refusing to touch an existing file (${abs}); pass --allow-existing-out to resume/append`,
    });
  }
  return { ok: blockers.length === 0, blockers, path: abs };
}

export function defaultRecordPath({ repoRoot, batch = "next", runId, arm, phase = "capture" }) {
  return join(privateRoot(repoRoot), "capture", batch, "runs", runId, `${phase}-${arm}.json`);
}

export function defaultSidecarPath({ repoRoot, batch = "next", runId }) {
  return join(privateRoot(repoRoot), "capture", batch, "provenance", `${runId}.jsonl`);
}

export async function appendSidecar(path, entry) {
  await mkdir(dirname(path), { recursive: true });
  await appendFile(path, JSON.stringify(entry) + "\n", "utf8");
}

export function makeRecordProvenance({
  runId, phase, arm, scenarioId, trial, pair = null, projectId, configHash,
  snapshotPath = null, snapshotSha256 = null, artifactHashes = null,
  setId = null, setPath = null, setSha256 = null, scheduleSha256 = null,
  harnessGit = "unknown", tab = null, observedUrl = null, binding = "declared-unverified",
  legacyUnverified = false,
}) {
  return {
    schema: RECORD_PROVENANCE_SCHEMA,
    run_id: runId,
    phase,
    arm,
    scenario_id: scenarioId,
    trial,
    pair_id: pair,
    project_id: projectId,
    config_hash: configHash,
    snapshot_path: snapshotPath,
    snapshot_sha256: snapshotSha256,
    artifact_hashes: artifactHashes,
    set_id: setId,
    set_path: setPath,
    set_sha256: setSha256,
    schedule_sha256: scheduleSha256,
    harness_git: harnessGit,
    tab,
    target_url_binding: binding,
    observed_url_sha256: observedUrl ? sha256Text(normalizeUrlForCompare(observedUrl)) : null,
    observed_platform_config: "unknown-not-observable-at-runtime",
    intended_inputs_sha256: hashJson({
      snapshot_sha256: snapshotSha256,
      config_hash: configHash,
      set_sha256: setSha256,
      schedule_sha256: scheduleSha256,
    }),
    legacy_unverified: !!legacyUnverified,
    captured_at: new Date().toISOString(),
  };
}

/* --------------------------------------------------------------------- CLI */

const HELP = `evals/provenance.mjs — offline provenance for Agentplace captures

Read-only commands:
  hash <file...>                       sha256 + byte count for each file
  verify --snapshot <file> [--json]    validate a snapshot and every artifact hash
  pairs --schedule <file> [--arm-file ARM=path ...] [--json]
                                       completed-pair accounting; never invents pairs

Writer commands (private paths by default; refuse to overwrite without --force):
  snapshot --project-id <id> [--model Luna] --method <platform-export|verbatim-ui|intended-only>
           --captured-at <iso> --instructions <rel> [--knowledge <rel> ...]
           --ui-settings <rel> [--publication <json-or-string>] [--revision <str>]
           [--public-url <url>] [--unknown <str> ...] [--limitation <str> ...]
           [--captured-by <str>] [--export-scope partial] [--out <dir>/snapshot.json]
           [--current-verified | --historical-readback]
                                  assert whether the current publication was verified;
                                  omitted means missing and refuses to verify
           [--allow-incomplete]   write blockers as an explicitly invalid audit snapshot
  plan     --snapshot <file> --arm <arm> --phase <phase>
           [--scenarios <file>] [--schedule <file>] [--run-id <id>]
           [--manifest <manifest.json>]   copy collection_authorized/status; refuses false
           [--trials N] [--ids a,b] [--out <file>]
  schedule --scenarios <file> --arms A0,A2 --trials N [--reps N]
           [--run-id <id>] [--out <file>]
  resume   --store <records.json> --plan <run-plan.json> [--json]

Snapshot artifacts must already exist beside the snapshot file; this tool hashes
what is on disk and never fabricates an export. Paths are relative to the
snapshot directory. "intended-only" can be recorded but never verifies.

Writer commands refuse to overwrite without --force and refuse to write raw
capture material inside the repository unless --allow-in-repo is supplied.
Pair execution is not implemented; a plan that requests it is never written.

Exit codes: 0 ok, 1 invalid/blocked, 2 usage.
`;

function fail(message) {
  console.error(`error: ${message}`);
  return 2;
}

function printBlockers(blockers) {
  for (const b of blockers) console.error(`  ✗ [${b.code}] ${b.message}`);
}

function printWarnings(warnings) {
  for (const w of warnings || []) console.error(`  ! [${w.code}] ${w.message}`);
}

async function writeJsonFile(path, value, { force = false } = {}) {
  if (existsSync(path) && !force) throw new Error(`refusing to overwrite ${path}; pass --force`);
  await mkdir(dirname(resolve(path)), { recursive: true });
  await writeFile(resolve(path), JSON.stringify(value, null, 1) + "\n", "utf8");
}

function guardPrivate(repoRoot, path, flags) {
  if (!repoRoot) return;
  const abs = resolve(path);
  if (isInside(repoRoot, abs) && !flags["allow-in-repo"]) {
    throw new Error(
      `refusing to write raw capture material inside the repository (${displayPath(repoRoot, abs)}); pass --allow-in-repo only for deliberate public evidence`,
    );
  }
}

async function cmdHash(argv) {
  if (!argv.length) return fail("hash needs at least one file");
  let code = 0;
  for (const path of argv) {
    if (!existsSync(path)) {
      console.error(`${path}: missing`);
      code = 1;
      continue;
    }
    const bytes = readFileSync(path);
    console.log(`${sha256Bytes(bytes)}  ${bytes.length}  ${path}`);
  }
  return code;
}

async function cmdVerify(flags) {
  const snapshot = flags.snapshot;
  if (typeof snapshot !== "string") return fail("--snapshot is required");
  const report = verifySnapshot(snapshot);
  if (flags.json) {
    console.log(JSON.stringify(report, null, 1));
  } else {
    console.log(`snapshot : ${report.path}`);
    console.log(`sha256   : ${report.snapshot_sha256 ?? "(unread)"}`);
    console.log(`status   : ${report.status}`);
    console.log(`project  : ${report.project_id ?? "(none)"}`);
    console.log(`model    : ${report.model ?? "(none)"}`);
    console.log(`method   : ${report.method ?? "(none)"}`);
    console.log(`captured : ${report.captured_at ?? "(none)"}`);
    console.log(`config   : ${report.config_hash ?? "(none)"}`);
    if (report.blockers.length) {
      console.error("\nblockers:");
      printBlockers(report.blockers);
    }
    if (report.warnings.length) {
      console.error("\nwarnings:");
      printWarnings(report.warnings);
    }
  }
  return report.ok ? 0 : 1;
}

async function cmdSnapshot(flags) {
  const projectId = flags["project-id"];
  if (typeof projectId !== "string") return fail("--project-id is required");
  if (typeof flags.method !== "string") return fail("--method is required");
  const captureRoot = flags.out
    ? resolve(String(flags.out))
    : join(privateRoot(repoRootFrom(process.cwd()) || process.cwd()), "capture", String(flags.batch || "next"), "snapshot.json");
  guardPrivate(repoRootFrom(process.cwd()), captureRoot, flags);
  const snapshotDir = dirname(captureRoot);
  const artifactBase = snapshotDir;
  guardPrivate(repoRootFrom(process.cwd()), artifactBase, flags);
  const relOf = (p) => {
    if (typeof p !== "string" || !p.trim()) return null;
    const abs = isAbsolute(p) ? resolve(p) : resolve(artifactBase, p);
    if (!isInside(artifactBase, abs)) throw new Error(`artifact ${p} is outside --artifacts-dir`);
    const rel = relative(artifactBase, abs).split(sep).join("/");
    return rel;
  };
  const one = (v) => {
    const rel = relOf(String(v));
    if (!rel) return null;
    const abs = resolve(artifactBase, rel);
    if (!existsSync(abs)) throw new Error(`artifact does not exist: ${rel}`);
    const bytes = readFileSync(abs);
    return { path: rel, sha256: sha256Bytes(bytes), bytes: bytes.length };
  };
  const knowledge = flagList(flags.knowledge).map(one).filter(Boolean);
  const instructions = flags.instructions ? one(flags.instructions) : null;
  const uiSettings = flags["ui-settings"] ? one(flags["ui-settings"]) : null;

  const snap = {
    schema: SNAPSHOT_SCHEMA,
    project_id: projectId,
    model: String(flags.model || "Luna"),
    agent: flags["public-url"] ? { public_url: String(flags["public-url"]) } : {},
    capture: {
      method: String(flags.method),
      captured_at: String(flags["captured-at"] || new Date().toISOString()),
      captured_by: flags["captured-by"] ?? null,
      export_scope: flags["export-scope"] ?? "partial",
      current_effective_config_verified: flags["current-verified"] ? true : flags["historical-readback"] ? false : null,
      publication: flags.publication !== undefined ? flags.publication : null,
      revision: flags.revision !== undefined ? flags.revision : null,
    },
    artifacts: {
      instructions,
      knowledge,
      ui_settings: uiSettings,
    },
    unknowns: flagList(flags.unknown),
    limitations: flagList(flags.limitation),
  };
  const report = validateSnapshotObject(snap, { snapshotDir });
  const incomplete = !report.ok;
  if (incomplete && !flags["allow-incomplete"]) {
    console.error("refusing to write an invalid snapshot:");
    printBlockers(report.blockers);
    console.error("  (--allow-incomplete records it as explicitly invalid for audit; it will never verify)");
    return 1;
  }
  const payload = incomplete
    ? {
        ...snap,
        verification: {
          status: "invalid",
          verified_at: new Date().toISOString(),
          blockers: report.blockers,
          warnings: report.warnings,
        },
      }
    : snap;
  await writeJsonFile(captureRoot, payload, { force: Boolean(flags.force) });
  console.log(`wrote ${captureRoot}`);
  if (incomplete) {
    console.error("status: INVALID — recorded for audit only; preflight will refuse it");
    printBlockers(report.blockers);
    return 1;
  }
  console.log(`config_hash ${report.normalized.config_hash}`);
  printWarnings(report.warnings);
  return 0;
}

async function cmdPlan(flags) {
  const repoRoot = repoRootFrom(process.cwd()) || process.cwd();
  const snapshotPath = flags.snapshot;
  if (typeof snapshotPath !== "string") return fail("--snapshot is required");
  if (typeof flags.arm !== "string") return fail("--arm is required");
  if (typeof flags.phase !== "string") return fail("--phase is required");
  const snapshot = verifySnapshot(snapshotPath);
  if (!snapshot.ok) {
    console.error("cannot plan against an unverified snapshot:");
    printBlockers(snapshot.blockers);
    return 1;
  }
  const setPath = flags.scenarios ? resolve(String(flags.scenarios)) : join(repoRoot, "datasets", "next-run", "scenarios.json");
  if (!existsSync(setPath)) return fail(`scenario set missing: ${setPath}`);
  let collectionAuthorized = null;
  let planStatus = null;
  if (flags.manifest) {
    const manifestPath = resolve(String(flags.manifest));
    let manifest;
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    } catch (e) {
      console.error(`error: cannot read manifest ${manifestPath}: ${String(e.message || e)}`);
      return 2;
    }
    collectionAuthorized = manifest.collection_authorized;
    planStatus = manifest.status ?? null;
    if (collectionAuthorized !== true) {
      console.error("refusing to plan: manifest does not explicitly set collection_authorized=true");
      return 1;
    }
    if (["preparation_only", "preparation-only", "blocked", "draft", "not_ready", "not-ready"].includes(String(planStatus || "").toLowerCase())) {
      console.error(`refusing to plan: manifest status ${planStatus} is not ready`);
      return 1;
    }
  }
  const runId = typeof flags["run-id"] === "string"
    ? flags["run-id"]
    : `run-${String(flags.arm)}-${String(flags.phase)}-${snapshot.config_hash.slice(0, 12)}`;
  let schedulePath = null;
  let scheduleSha = null;
  if (flags.schedule) {
    schedulePath = resolve(String(flags.schedule));
    if (!existsSync(schedulePath)) return fail(`schedule missing: ${schedulePath}`);
    scheduleSha = sha256File(schedulePath);
    const sched = JSON.parse(readFileSync(schedulePath, "utf8"));
    if (sched.schema !== SCHEDULE_SCHEMA) return fail("schedule schema mismatch");
    if (!Array.isArray(sched.arms) || !sched.arms.includes(flags.arm)) return fail("arm is not in the schedule");
    if (sched.run_id !== runId) return fail(`run id ${runId} does not match schedule ${sched.run_id}`);
  }
  const plan = buildRunPlan({
    runId,
    arm: flags.arm,
    phase: flags.phase,
    snapshotPath: resolve(snapshotPath),
    snapshotReport: snapshot,
    setPath,
    schedulePath,
    scheduleSha256: scheduleSha,
    trials: flags.trials !== undefined ? Number(flags.trials) : null,
    ids: flags.ids ? flagList(flags.ids) : null,
    pairExecution: Boolean(flags["pair-execution"]),
    collectionAuthorized,
    status: planStatus,
  });
  const out = flags.out
    ? resolve(String(flags.out))
    : join(dirname(resolve(snapshotPath)), `run-plan-${flags.arm}-${flags.phase}.json`);
  guardPrivate(repoRoot, out, flags);
  // Validate what we are about to write by writing it first only when it is sane.
  if (plan.pair_execution) {
    console.error("pair execution is not implemented; refusing to write a runnable plan that asks for it");
    return 1;
  }
  await writeJsonFile(out, plan, { force: Boolean(flags.force) });
  const after = validateRunPlan(out, { repoRoot, snapshotReport: snapshot, setPath });
  console.log(`wrote ${out}`);
  console.log(`run_id ${runId}`);
  if (after.blockers.length) {
    printBlockers(after.blockers);
    return 1;
  }
  printWarnings(after.warnings);
  return 0;
}

async function cmdSchedule(flags) {
  const repoRoot = repoRootFrom(process.cwd()) || process.cwd();
  const setPath = flags.scenarios ? resolve(String(flags.scenarios)) : join(repoRoot, "datasets", "next-run", "scenarios.json");
  if (!existsSync(setPath)) return fail(`scenario set missing: ${setPath}`);
  const arms = flagList(flags.arms);
  if (arms.length !== 2) return fail("--arms needs exactly two arm ids, e.g. --arms A0,A2");
  const cfg = JSON.parse(readFileSync(setPath, "utf8"));
  const items = cfg.scenarios || cfg.scripts || [];
  const scenarioIds = items.map((s) => s.id).filter(Boolean);
  if (!scenarioIds.length) return fail("scenario set has no ids");
  const trials = flags.trials !== undefined ? Number(flags.trials) : 1;
  const reps = flags.reps !== undefined ? Number(flags.reps) : 1;
  const runId = typeof flags["run-id"] === "string"
    ? flags["run-id"]
    : `sched-${sha256File(setPath).slice(0, 8)}-${arms.join("-")}`;
  const schedule = buildSchedule({ runId, scenarioIds, arms, trials, reps });
  const out = flags.out
    ? resolve(String(flags.out))
    : join(privateRoot(repoRoot), "capture", String(flags.batch || "next"), `schedule-${runId}.json`);
  guardPrivate(repoRoot, out, flags);
  await writeJsonFile(out, schedule, { force: Boolean(flags.force) });
  const counts = { AB: 0, BA: 0 };
  for (const p of schedule.pairs) counts[p.order]++;
  console.log(`wrote ${out}`);
  console.log(`${schedule.pairs.length} pairs (${counts.AB} AB, ${counts.BA} BA), ${scenarioIds.length} scenarios, ${trials} trial(s) x ${reps} rep(s)`);
  if (reps > 1) {
    console.log("note: run.mjs/run_mt.mjs record trial 1..N without a rep label, so only rep 1 can be accounted; reps > 1 stays pending");
  }
  console.log("pair execution: not implemented — all pairs are pending");
  return 0;
}

async function cmdPairs(flags) {
  if (typeof flags.schedule !== "string") return fail("--schedule is required");
  const path = resolve(flags.schedule);
  if (!existsSync(path)) return fail(`schedule missing: ${path}`);
  const schedule = JSON.parse(readFileSync(path, "utf8"));
  if (schedule.schema !== SCHEDULE_SCHEMA) return fail("schedule schema mismatch");
  const stores = {};
  for (const spec of flagList(flags["arm-file"])) {
    const idx = spec.indexOf("=");
    if (idx < 1) return fail("--arm-file must be ARM=path");
    const arm = spec.slice(0, idx);
    const file = resolve(spec.slice(idx + 1));
    if (!existsSync(file)) return fail(`arm file does not exist: ${file}`);
    stores[arm] = loadStore(file);
  }
  const accounting = summarizePairs(schedule, stores);
  if (flags.json) {
    console.log(JSON.stringify(accounting, null, 1));
  } else {
    console.log(`run_id          : ${accounting.run_id}`);
    console.log(`declared pairs  : ${accounting.declared_pairs}`);
    console.log(`completed pairs : ${accounting.completed_pairs}`);
    console.log(`pending pairs   : ${accounting.pending_pairs}`);
    console.log(`invalid attempts: ${accounting.invalid_attempts_retained}`);
    for (const warning of accounting.warnings || []) console.error(`  ! [${warning.code}] ${warning.message}`);
    console.log("pair execution  : not implemented (no pair is claimed without both valid records)");
  }
  return 0;
}

async function cmdResume(flags) {
  if (typeof flags.store !== "string") return fail("--store is required");
  if (typeof flags.plan !== "string") return fail("--plan is required");
  const repoRoot = repoRootFrom(process.cwd()) || process.cwd();
  const result = evaluateResume({
    planPath: resolve(flags.plan),
    storePath: resolve(flags.store),
    repoRoot,
  });
  if (flags.json) console.log(JSON.stringify(result, null, 1));
  else {
    console.log(result.ok ? "resume allowed" : "resume refused");
    printBlockers(result.blockers);
    printWarnings(result.warnings);
  }
  return result.ok ? 0 : 1;
}


export async function cli(argv = process.argv.slice(2)) {
  if (!argv.length || argv.includes("--help") || argv.includes("-h")) {
    console.log(HELP);
    return 0;
  }
  const command = argv[0];
  const rest = argv.slice(1);
  try {
    if (command === "hash") return cmdHash(rest);
    const { flags } = parseFlags(rest);
    if (command === "verify") return cmdVerify(flags);
    if (command === "snapshot") return cmdSnapshot(flags);
    if (command === "plan") return cmdPlan(flags);
    if (command === "schedule") return cmdSchedule(flags);
    if (command === "pairs") return cmdPairs(flags);
    if (command === "resume") return cmdResume(flags);
    return fail(`unknown command ${command} (try --help)`);
  } catch (e) {
    console.error(`error: ${String(e.message || e)}`);
    return 1;
  }
}

export function parseFlags(argv) {
  const flags = Object.create(null);
  const positionals = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    let key = arg.slice(2);
    let value;
    const eq = key.indexOf("=");
    if (eq >= 0) {
      value = key.slice(eq + 1);
      key = key.slice(0, eq);
    } else {
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        value = next;
        i++;
      } else {
        value = true;
      }
    }
    if (Object.prototype.hasOwnProperty.call(flags, key)) {
      flags[key] = Array.isArray(flags[key]) ? [...flags[key], value] : [flags[key], value];
    } else {
      flags[key] = value;
    }
  }
  return { flags, positionals };
}

export function flagList(value) {
  if (value === undefined || value === null || value === false) return [];
  return (Array.isArray(value) ? value : [value])
    .flatMap((v) => String(v).split(","))
    .map((s) => s.trim())
    .filter(Boolean);
}

if (import.meta.main) {
  const code = await cli();
  process.exit(code);
}
