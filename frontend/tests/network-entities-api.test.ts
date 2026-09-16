import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildNetworkEntitiesUrl,
  resetNetworkEntitiesCache,
} from "../lib/api/network-entities";

test("buildNetworkEntitiesUrl returns entities endpoint with default backend base URL", () => {
  assert.equal(buildNetworkEntitiesUrl(), "http://127.0.0.1:8010/api/network/entities");
});

test("fetchNetworkEntities flattens the grouped backend payload into an id-keyed lookup", async () => {
  process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN = "dev-token";
  resetNetworkEntitiesCache();
  const originalFetch = globalThis.fetch;
  const captured: { init?: RequestInit }[] = [];
  globalThis.fetch = (async (_url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ init });
    return {
      ok: true,
      async json() {
        return {
          herbs: [{ id: "herb-jingjie", name: "荆芥", pinyin: "jingjie" }],
          formulas: [
            { id: "formula-xiaofengsan", name: "消风散", pinyin: "xiaofengsan", herb_ids: [] },
          ],
          compounds: [{ id: "compound-quercetin", name: "槲皮素", herb_ids: [] }],
          targets: [
            { id: "target-stat3", symbol: "STAT3", name: "Signal Transducer And Activator Of Transcription 3" },
          ],
          pathways: [{ id: "pathway-jak-stat", name: "JAK-STAT signaling pathway", target_ids: [] }],
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkEntities } = await import(
      `../lib/api/network-entities?ts=${Date.now()}`
    );
    resetNetworkEntitiesCache();
    const lookup = await fetchNetworkEntities();

    assert.equal(captured.length, 1);
    const headers = captured[0].init?.headers as Record<string, string>;
    assert.equal("X-Access-Token" in headers, false);
    assert.equal(lookup["herb-jingjie"].name, "荆芥");
    assert.equal(lookup["herb-jingjie"].kind, "herb");
    assert.equal(lookup["formula-xiaofengsan"].kind, "formula");
    assert.equal(lookup["compound-quercetin"].kind, "compound");
    // target chip should prefer symbol over long protein name
    assert.equal(lookup["target-stat3"].name, "STAT3");
    assert.equal(lookup["target-stat3"].kind, "target");
    assert.equal(lookup["pathway-jak-stat"].kind, "pathway");
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN;
    resetNetworkEntitiesCache();
  }
});

test("fetchNetworkEntities memoizes the network call across repeated invocations", async () => {
  resetNetworkEntitiesCache();
  const originalFetch = globalThis.fetch;
  let fetchCount = 0;
  globalThis.fetch = (async () => {
    fetchCount += 1;
    return {
      ok: true,
      async json() {
        return {
          herbs: [],
          formulas: [],
          compounds: [],
          targets: [],
          pathways: [],
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkEntities } = await import(
      `../lib/api/network-entities?ts=${Date.now()}`
    );
    resetNetworkEntitiesCache();
    await fetchNetworkEntities();
    await fetchNetworkEntities();
    await fetchNetworkEntities();
    assert.equal(fetchCount, 1);
  } finally {
    globalThis.fetch = originalFetch;
    resetNetworkEntitiesCache();
  }
});

test("lookupEntity returns the entity record for known ids and undefined for unknown ids", async () => {
  const { lookupEntity } = await import("../lib/api/network-entities");

  const lookup = {
    "herb-fangfeng": { id: "herb-fangfeng", name: "防风", kind: "herb" as const },
  };
  assert.equal(lookupEntity(lookup, "herb-fangfeng")?.name, "防风");
  assert.equal(lookupEntity(lookup, "herb-missing"), undefined);
});

test("buildNetworkFocusHref encodes the entity id into the /network focus query param", async () => {
  const { buildNetworkFocusHref } = await import("../lib/api/network-entities");

  assert.equal(buildNetworkFocusHref("formula-xiaofengsan"), "/network?focus=formula-xiaofengsan");
  assert.equal(
    buildNetworkFocusHref("herb with space"),
    "/network?focus=herb%20with%20space",
  );
});
