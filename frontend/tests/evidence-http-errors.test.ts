import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiStatusError } from "../lib/api/client";
import {
  getLiteratureDetail, runFakePdfAutoParse, searchLiterature,
  syncLiteratureFromPubmed, updatePdfParseStatus, uploadLiteraturePdf,
} from "../lib/api/literature";
import { getRagAdEvalReport } from "../lib/api/evals";
import { fetchNetworkEntities, resetNetworkEntitiesCache } from "../lib/api/network-entities";
import { sealNetworkAssemblyPlan } from "../lib/api/network";
import LiteratureDetailPage from "../app/literature/[id]/page";

test("evidence GET and mutation clients preserve HTTP rejection status", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [
    () => searchLiterature("AD"),
    () => getLiteratureDetail("missing"),
    () => uploadLiteraturePdf("id", new File(["%PDF-1.4"], "paper.pdf", { type: "application/pdf" })),
    () => runFakePdfAutoParse("id", "paper.pdf"),
    () => updatePdfParseStatus("id", "failed"),
    () => syncLiteratureFromPubmed("AD", 1),
    () => getRagAdEvalReport(),
    () => { resetNetworkEntitiesCache(); return fetchNetworkEntities(); },
    () => sealNetworkAssemblyPlan("network-example"),
  ];
  try {
    for (const status of [401, 403, 404, 409, 413, 422, 429, 503]) {
      globalThis.fetch = async () => new Response(JSON.stringify({ detail: "rejected" }), { status });
      for (const call of calls) {
        await assert.rejects(call, (error: unknown) => error instanceof ApiStatusError && error.status === status);
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a transient entity lookup failure does not poison all later lookups", async () => {
  resetNetworkEntitiesCache();
  const originalFetch = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts += 1;
    if (attempts === 1) return new Response("unavailable", { status: 503 });
    return Response.json({ herbs: [{ id: "herb:test", name: "Test herb" }], formulas: [], compounds: [], targets: [], pathways: [] });
  };
  try {
    await assert.rejects(fetchNetworkEntities);
    const recovered = await fetchNetworkEntities();
    assert.equal(recovered["herb:test"].name, "Test herb");
    assert.equal(attempts, 2);
  } finally {
    resetNetworkEntitiesCache();
    globalThis.fetch = originalFetch;
  }
});

test("literature detail propagates permission and server errors instead of showing a missing page", async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const status of [401, 403, 503]) {
      globalThis.fetch = async () => new Response("rejected", { status });
      await assert.rejects(
        () => LiteratureDetailPage({ params: Promise.resolve({ id: "paper" }) }),
        (error: unknown) => error instanceof ApiStatusError && error.status === status,
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("evidence clients keep transport failures distinct from HTTP failures", async () => {
  const originalFetch = globalThis.fetch;
  const failure = new TypeError("fetch failed");
  globalThis.fetch = async () => { throw failure; };
  try {
    await assert.rejects(() => searchLiterature("AD"), (error: unknown) => error === failure);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
