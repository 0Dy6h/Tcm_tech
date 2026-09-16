import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildNetworkTasksUrl,
  getNetworkTaskReadinessLabel,
  getNetworkTaskStatusLabel,
  type NetworkTaskListResponse,
  type NetworkTaskSummary,
} from "../lib/api/network";
import {
  buildNetworkTaskViewHref,
  formatNetworkTaskCreatedAt,
  mapNetworkTasksToRows,
  mapNetworkTaskToRow,
  parseNetworkTaskIdParam,
} from "../lib/network-tasks";

const testFilePath = fileURLToPath(import.meta.url);

function getSource(relativePath: string) {
  return readFileSync(resolve(testFilePath, "..", "..", relativePath), "utf8");
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

// 与展示层同一时区语义：浏览器本地墙钟到分钟。任何时区下都应与实现一致。
function expectedLocalMinutes(iso: string) {
  const parsed = new Date(iso);
  return `${parsed.getFullYear()}-${pad2(parsed.getMonth() + 1)}-${pad2(parsed.getDate())} ${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}`;
}

function buildTask(overrides: Partial<NetworkTaskSummary> = {}): NetworkTaskSummary {
  return {
    task_id: "network-abc123abc123",
    source_task_id: null,
    query: "消风散",
    analysis_type: "formula",
    status: "completed",
    data_mode: "mock",
    formal_network_ready: false,
    created_at: "2026-07-18T09:41:07.123456+00:00",
    ...overrides,
  };
}

test("buildNetworkTasksUrl returns the owner-scoped task list endpoint", () => {
  assert.equal(buildNetworkTasksUrl(), "http://127.0.0.1:8010/api/network/tasks");
});

test("parseNetworkTaskIdParam keeps a real id and rejects blank or missing values", () => {
  assert.equal(parseNetworkTaskIdParam("network-abc123abc123"), "network-abc123abc123");
  assert.equal(parseNetworkTaskIdParam("  network-abc123abc123  "), "network-abc123abc123");
  assert.equal(parseNetworkTaskIdParam(""), null);
  assert.equal(parseNetworkTaskIdParam("   "), null);
  assert.equal(parseNetworkTaskIdParam(null), null);
});

test("formatNetworkTaskCreatedAt renders the local wall clock to minutes and degrades safely", () => {
  const iso = "2026-07-18T09:41:07.123456+00:00";
  assert.equal(formatNetworkTaskCreatedAt(iso), expectedLocalMinutes(iso));
  assert.equal(formatNetworkTaskCreatedAt("   "), "未知时间");
  // non-timestamp strings degrade to the legacy slice instead of leaking "Invalid Date"
  assert.equal(formatNetworkTaskCreatedAt("not-a-timestamp"), "not-a-timestamp");
});

test("buildNetworkTaskViewHref deep links into the network page with an encoded task id", () => {
  assert.equal(
    buildNetworkTaskViewHref("network-abc/123"),
    "/network?task_id=network-abc%2F123",
  );
});

test("task status labels stay distinct so reviewers can tell running from failed", () => {
  assert.equal(getNetworkTaskStatusLabel("completed"), "已完成");
  assert.equal(getNetworkTaskStatusLabel("running"), "运行中");
  assert.equal(getNetworkTaskStatusLabel("failed"), "失败");
  assert.equal(getNetworkTaskStatusLabel("queued"), "排队中");
});

test("readiness label never claims formal research standing for an unready task", () => {
  assert.equal(getNetworkTaskReadinessLabel(true), "达到正式科研标准");
  assert.equal(getNetworkTaskReadinessLabel(false), "未达正式科研标准");
});

test("mapNetworkTaskToRow projects labels, derived flag and view href without exposing owner", () => {
  const row = mapNetworkTaskToRow(
    buildTask({ source_task_id: "network-parent12345", data_mode: "live" }),
  );

  assert.equal(row.taskId, "network-abc123abc123");
  assert.equal(row.sourceTaskId, "network-parent12345");
  assert.equal(row.isDerived, true);
  assert.equal(row.analysisTypeLabel, "复方");
  assert.equal(row.statusLabel, "已完成");
  assert.equal(row.dataModeLabel, "真实数据 opt-in");
  assert.equal(row.readinessLabel, "未达正式科研标准");
  assert.equal(row.formalNetworkReady, false);
  assert.equal(row.createdAtLabel, expectedLocalMinutes("2026-07-18T09:41:07.123456+00:00"));
  assert.equal(row.viewHref, "/network?task_id=network-abc123abc123");
  assert.equal("ownerId" in row, false);
  assert.equal("owner_id" in row, false);
});

test("mapNetworkTaskToRow marks a root task as not derived", () => {
  assert.equal(mapNetworkTaskToRow(buildTask()).isDerived, false);
});

test("mapNetworkTasksToRows preserves the server ordering instead of re-sorting", () => {
  const payload: NetworkTaskListResponse = {
    tasks: [
      buildTask({ task_id: "network-newest000000", created_at: "2026-07-18T10:00:00+00:00" }),
      buildTask({ task_id: "network-oldest000000", created_at: "2026-07-01T10:00:00+00:00" }),
    ],
  };

  assert.deepEqual(
    mapNetworkTasksToRows(payload.tasks).map((row) => row.taskId),
    ["network-newest000000", "network-oldest000000"],
  );
});

test("fetchNetworkTasks throws on a non-ok response instead of rendering an empty list", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => ({ ok: false, status: 401 })) as unknown as typeof fetch;
  try {
    const { fetchNetworkTasks } = await import("../lib/api/network");
    await assert.rejects(fetchNetworkTasks(), /Network tasks request failed/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("task list client surfaces a retry path and never renders a silent empty table on error", () => {
  const source = getSource("components/NetworkTaskListClient.tsx");

  assert.match(source, /"use client"/);
  assert.match(source, /fetchNetworkTasks\(\)/);
  assert.match(source, /setPhase\("error"\)/);
  assert.match(source, /重试加载/);
  // in-flight guard so an unmounted list never sets state
  assert.match(source, /cancelled = true/);
});

test("tasks page wraps the client in Suspense and keeps the non-diagnostic disclaimer", () => {
  const source = getSource("app/tasks/page.tsx");

  assert.match(source, /import \{ Suspense \} from "react"/);
  assert.match(source, /<Suspense[\s\S]*<NetworkTaskListClient \/>/);
  assert.match(source, /不构成诊断或治疗建议/);
});

test("workbench shell exposes 我的研究 in the primary navigation", () => {
  const source = getSource("components/WorkbenchShell.tsx");

  assert.match(source, /\{ href: "\/tasks", label: "我的研究" \}/);
});
