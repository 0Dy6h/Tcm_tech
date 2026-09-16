import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildNetworkAdjudicationsUrl,
  buildNetworkAssemblyPlansUrl,
  sealNetworkAssemblyPlan,
  submitNetworkAdjudication,
  type NetworkAdjudicationRecord,
  type NetworkTargetLineage,
} from "../lib/api/network";
import {
  buildNetworkAdjudicationDecisionMap,
  countNetworkLineageRows,
  getNetworkAdjudicationButtonLabel,
  getNetworkAdjudicationDecisionLabel,
  getNetworkAdjudicationInFlightMessage,
  getNetworkAdjudicationUnavailableReason,
} from "../lib/network-adjudication";

const testFilePath = fileURLToPath(import.meta.url);

function getSource(relativePath: string) {
  return readFileSync(resolve(testFilePath, "..", "..", relativePath), "utf8");
}

function buildRecord(overrides: Partial<NetworkAdjudicationRecord> = {}): NetworkAdjudicationRecord {
  return {
    lineage_row_id: "disease-row-1",
    decision: "included",
    reason: null,
    decided_at: "2026-07-18T09:41:07+00:00",
    ...overrides,
  };
}

test("buildNetworkAdjudicationsUrl targets the task-scoped append-only collection", () => {
  assert.equal(
    buildNetworkAdjudicationsUrl("network-abc123abc123"),
    "http://127.0.0.1:8010/api/network/result/network-abc123abc123/adjudications",
  );
});

test("buildNetworkAdjudicationsUrl encodes a hostile task id instead of splitting the path", () => {
  assert.equal(
    buildNetworkAdjudicationsUrl("../../admin"),
    "http://127.0.0.1:8010/api/network/result/..%2F..%2Fadmin/adjudications",
  );
});

test("assembly plan URL is task-scoped and safely encoded", () => {
  assert.equal(
    buildNetworkAssemblyPlansUrl("network-abc123abc123"),
    "http://127.0.0.1:8010/api/network/result/network-abc123abc123/assembly-plans",
  );
  assert.equal(
    buildNetworkAssemblyPlansUrl("../../admin"),
    "http://127.0.0.1:8010/api/network/result/..%2F..%2Fadmin/assembly-plans",
  );
});

test("sealNetworkAssemblyPlan posts without client-supplied gate fields", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        return {};
      },
    } as Response;
  }) as typeof globalThis.fetch;
  try {
    await sealNetworkAssemblyPlan("network-abc123abc123");
    assert.equal(captured[0]?.url, buildNetworkAssemblyPlansUrl("network-abc123abc123"));
    assert.equal(captured[0]?.init?.method, "POST");
    assert.equal(captured[0]?.init?.body, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("decision labels distinguish the three reviewer outcomes", () => {
  assert.equal(getNetworkAdjudicationDecisionLabel("included"), "已纳入");
  assert.equal(getNetworkAdjudicationDecisionLabel("excluded"), "已排除");
  assert.equal(getNetworkAdjudicationDecisionLabel("needs_review"), "待复核");
  assert.equal(getNetworkAdjudicationButtonLabel("included"), "纳入");
  assert.equal(getNetworkAdjudicationButtonLabel("excluded"), "排除");
  assert.equal(getNetworkAdjudicationButtonLabel("needs_review"), "待复核");
});

test("buildNetworkAdjudicationDecisionMap keys the latest decision by lineage row", () => {
  const map = buildNetworkAdjudicationDecisionMap([
    buildRecord({ lineage_row_id: "disease-row-1", decision: "included" }),
    buildRecord({ lineage_row_id: "compound-row-9", decision: "needs_review", reason: "证据不足" }),
  ]);

  assert.equal(map.size, 2);
  assert.equal(map.get("disease-row-1")?.decision, "included");
  assert.equal(map.get("compound-row-9")?.reason, "证据不足");
  assert.equal(map.get("missing-row"), undefined);
});

test("buildNetworkAdjudicationDecisionMap treats a missing projection as no decisions", () => {
  assert.equal(buildNetworkAdjudicationDecisionMap(null).size, 0);
  assert.equal(buildNetworkAdjudicationDecisionMap(undefined).size, 0);
  assert.equal(buildNetworkAdjudicationDecisionMap([]).size, 0);
});

test("countNetworkLineageRows sums the three adjudicable frozen row sets", () => {
  const lineage = {
    disease_lineage_row_count: 4,
    compound_lineage_row_count: 7,
    intersection_lineage_row_count: 2,
  } as NetworkTargetLineage;

  assert.equal(countNetworkLineageRows(lineage), 13);
});

test("adjudication is unavailable until the task is completed", () => {
  const reason = getNetworkAdjudicationUnavailableReason({
    taskCompleted: false,
    lineageRowCount: 12,
  });

  assert.match(String(reason), /只有 completed 状态/);
});

test("adjudication is unavailable when the frozen lineage has no adjudicable rows", () => {
  const reason = getNetworkAdjudicationUnavailableReason({
    taskCompleted: true,
    lineageRowCount: 0,
  });

  assert.match(String(reason), /没有可判定的靶点 lineage 行/);
});

test("adjudication unlocks only for a completed task with at least one lineage row", () => {
  assert.equal(
    getNetworkAdjudicationUnavailableReason({ taskCompleted: true, lineageRowCount: 1 }),
    null,
  );
});

test("submitNetworkAdjudication posts the row decision and normalizes a blank reason to null", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        return { ...buildRecord(), adjudication_id: "adjudication-abc" };
      },
    };
  }) as unknown as typeof fetch;

  try {
    const accepted = await submitNetworkAdjudication("network-abc123abc123", {
      lineage_row_id: "disease-row-1",
      decision: "included",
      reason: "   ",
    });

    assert.equal(accepted.adjudication_id, "adjudication-abc");
    assert.equal(captured.length, 1);
    assert.equal(captured[0]?.init?.method, "POST");
    assert.deepEqual(JSON.parse(String(captured[0]?.init?.body)), {
      lineage_row_id: "disease-row-1",
      decision: "included",
      reason: null,
    });
    // client never submits reviewer identity, hashes, or readiness fields
    const bodyKeys = Object.keys(JSON.parse(String(captured[0]?.init?.body)));
    assert.deepEqual(bodyKeys.sort(), ["decision", "lineage_row_id", "reason"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitNetworkAdjudication trims a real reason before sending it", async () => {
  const originalFetch = globalThis.fetch;
  let sentReason: unknown = "unset";
  globalThis.fetch = (async (_url: URL | RequestInfo, init?: RequestInit) => {
    sentReason = JSON.parse(String(init?.body)).reason;
    return { ok: true, async json() { return { ...buildRecord(), adjudication_id: "a" }; } };
  }) as unknown as typeof fetch;

  try {
    await submitNetworkAdjudication("network-abc123abc123", {
      lineage_row_id: "disease-row-1",
      decision: "excluded",
      reason: "  与表型无关  ",
    });
    assert.equal(sentReason, "与表型无关");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitNetworkAdjudication rejects a refused decision instead of pretending it landed", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({ ok: false, status: 409 })) as unknown as typeof fetch;

  try {
    await assert.rejects(
      submitNetworkAdjudication("network-abc123abc123", {
        lineage_row_id: "disease-row-1",
        decision: "included",
      }),
      /Network adjudication request failed/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("the adjudication projection lives on the response envelope, not the frozen result snapshot", () => {
  const source = getSource("lib/api/network.ts");
  const resultType = source.slice(
    source.indexOf("export type NetworkAnalysisResult = {"),
    source.indexOf("export type NetworkAnalyzeAccepted"),
  );
  const responseType = source.slice(
    source.indexOf("export type NetworkResultResponse = {"),
    source.indexOf("export function buildNetworkAnalyzeUrl"),
  );

  assert.doesNotMatch(resultType, /adjudication/);
  assert.match(responseType, /adjudication\?: NetworkAdjudicationProjection \| null/);
});

test("network client reads adjudication from the response envelope and clears it per run", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /setAdjudication\(polled\.adjudication \?\? null\)/);
  assert.match(source, /setAdjudication\(refreshed\.adjudication \?\? null\)/);
  // stale decisions from a previous task must not leak into a new run
  assert.match(source, /setResult\(null\);\s*\n\s*setAdjudication\(null\);/);
  assert.doesNotMatch(source, /result\?\.adjudication/);
});

test("in-flight message names how many rows are submitting and is silent when idle", () => {
  assert.equal(getNetworkAdjudicationInFlightMessage(0), null);
  assert.equal(getNetworkAdjudicationInFlightMessage(-1), null);
  assert.match(String(getNetworkAdjudicationInFlightMessage(2)), /正在提交 2 行人工判定/);
});

test("row locking is per row so one submission does not freeze the whole review", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /busyRowIds: ReadonlySet<string>/);
  assert.match(source, /const busy = controls\.busyRowIds\.has\(rowId\)/);
  // a page-wide "any row is busy" lock would read like this — it must not come back
  assert.doesNotMatch(source, /busyRowId !== null/);
});

test("a fast double click cannot slip a duplicate audit event past the disabled state", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /adjudicationBusyRowIdsRef\.current\.has\(rowId\)/);
});

test("a failed refresh after a successful write is never reported as a failed decision", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /人工判定已记录，但刷新判定进度失败/);
  assert.match(source, /setAdjudicationError\(describeApiError\(error, "提交人工判定"\)\)/);
});

test("a superseded task's late response cannot paint over the task being viewed", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /activeTaskIdRef/);
  assert.match(source, /activeTaskIdRef\.current !== taskId/);
  // every new run invalidates whatever poll/refetch is still in flight
  assert.match(source, /function beginRun\(\)[\s\S]{0,200}activeTaskIdRef\.current = null/);
});

test("in-flight submissions are announced in a live region, not just as disabled buttons", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /role="status"[\s\S]{0,80}aria-live="polite"/);
  assert.match(source, /adjudicationInFlightMessage/);
});

test("the draft reason input resets once a decision is recorded for that row", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /key=\{record\?\.decided_at \?\? "undecided"\}/);
});

test("network client offers reviewer controls on all three frozen row sets", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");
  const tableCalls = source.match(/<TargetLineageTable/g) ?? [];
  const cellUses = source.match(/<LineageAdjudicationCell/g) ?? [];

  assert.equal(tableCalls.length, 2, "disease and compound row sets render the lineage table");
  // one cell inside the shared table, one in the derived intersection table
  assert.equal(cellUses.length, 2);
  assert.match(source, /adjudication=\{rowAdjudicationControls\}/);
});

test("network client refuses to submit a row without a stable lineage id", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /无稳定 ID，不可判定/);
});

test("network client states that manual adjudication does not move the readiness gate", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /不会修改快照数据/);
  assert.match(source, /不会单独使网络达到正式科研标准/);
});

test("assembly gate is read from the response envelope and never labeled scientific readiness", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /setAssemblyGate\(polled\.assembly_gate \?\? null\)/);
  assert.match(source, /aria-label="候选装配输入门禁"/);
  assert.match(source, /封存只绑定当前协议/);
  assert.match(source, /不授权后续 writer/);
  assert.match(source, /不翻转 formal_network_ready/);
  assert.doesNotMatch(source, /装配输入已达到科研就绪/);
  assert.doesNotMatch(source, /网络已就绪/);
});

test("network client deep links a task id from 我的研究 exactly once", () => {
  const source = getSource("components/NetworkAnalysisClient.tsx");

  assert.match(source, /parseNetworkTaskIdParam\(searchParams\.get\("task_id"\)\)/);
  assert.match(source, /appliedTaskIdRef\.current === taskIdParam/);
  // a deep-linked task must not be overridden by the focus auto-run path
  assert.match(source, /if \(taskIdParam\) \{\s*\n\s*return;/);
});
