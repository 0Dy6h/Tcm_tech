import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildLiteratureSyncRequest,
  buildLiteratureSyncUrl,
  LITERATURE_SYNC_MAX_RESULTS_CAP,
} from "../lib/api/literature";

test("buildLiteratureSyncUrl points to /api/literature/sync on default backend base URL", () => {
  assert.equal(buildLiteratureSyncUrl(), "http://127.0.0.1:8010/api/literature/sync");
});

test("buildLiteratureSyncRequest trims query and clamps max_results to [1, 50]", () => {
  assert.deepEqual(buildLiteratureSyncRequest("  atopic dermatitis  ", 10), {
    source: "pubmed",
    q: "atopic dermatitis",
    max_results: 10,
  });
  assert.equal(buildLiteratureSyncRequest("ad", 0).max_results, 1);
  assert.equal(buildLiteratureSyncRequest("ad", -3).max_results, 1);
  assert.equal(buildLiteratureSyncRequest("ad", 999).max_results, LITERATURE_SYNC_MAX_RESULTS_CAP);
  assert.equal(buildLiteratureSyncRequest("ad", 7.8).max_results, 7);
});

test("syncLiteratureFromPubmed posts JSON body to sync endpoint and returns response", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        return {
          source: "pubmed",
          query: "atopic dermatitis",
          fetched: 10,
          created: 7,
          updated: 3,
          items: [],
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { syncLiteratureFromPubmed } = await import(`../lib/api/literature?ts=${Date.now()}`);
    const result = await syncLiteratureFromPubmed("atopic dermatitis", 10);

    assert.equal(captured.length, 1);
    assert.equal(captured[0].url, "http://127.0.0.1:8010/api/literature/sync");
    assert.equal(captured[0].init?.method, "POST");
    assert.equal(
      (captured[0].init?.headers as Record<string, string>)["Content-Type"],
      "application/json",
    );
    assert.deepEqual(JSON.parse(String(captured[0].init?.body)), {
      source: "pubmed",
      q: "atopic dermatitis",
      max_results: 10,
    });
    assert.equal(result.fetched, 10);
    assert.equal(result.created, 7);
    assert.equal(result.updated, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("syncLiteratureFromPubmed throws on non-OK response", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    ({
      ok: false,
      async json() {
        return {};
      },
    }) as Response) as typeof globalThis.fetch;
  try {
    const { syncLiteratureFromPubmed } = await import(`../lib/api/literature?ts=${Date.now()}`);
    await assert.rejects(() => syncLiteratureFromPubmed("ad", 10), /Literature sync failed/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
