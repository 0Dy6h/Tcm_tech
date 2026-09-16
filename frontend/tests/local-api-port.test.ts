import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { getBackendBaseUrl as literatureBase } from "../lib/api/literature";
import { getBackendBaseUrl as ragBase } from "../lib/api/rag";
import { buildNetworkAnalyzeUrl } from "../lib/api/network";
import { buildRagAdEvalReportUrl } from "../lib/api/evals";

test("local dev command and every browser API default share the unreserved 8010 backend", () => {
  const oldPublic = process.env.NEXT_PUBLIC_API_BASE_URL;
  const oldInternal = process.env.QIYAN_INTERNAL_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
  delete process.env.QIYAN_INTERNAL_API_BASE_URL;
  try {
    for (const url of [literatureBase(), ragBase(), buildNetworkAnalyzeUrl(), buildRagAdEvalReportUrl()]) {
      assert.equal(new URL(url).origin, "http://127.0.0.1:8010");
    }
    const scripts = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")).scripts;
    assert.match(scripts["dev:backend"], /--port 8010(?:\s|$)/);
    const e2e = readFileSync(new URL("../e2e/start-frontend.mjs", import.meta.url), "utf8");
    assert.match(e2e, /QIYAN_E2E_BACKEND_PORT \?\? "8010"/);
  } finally {
    if (oldPublic === undefined) delete process.env.NEXT_PUBLIC_API_BASE_URL;
    else process.env.NEXT_PUBLIC_API_BASE_URL = oldPublic;
    if (oldInternal === undefined) delete process.env.QIYAN_INTERNAL_API_BASE_URL;
    else process.env.QIYAN_INTERNAL_API_BASE_URL = oldInternal;
  }
});
