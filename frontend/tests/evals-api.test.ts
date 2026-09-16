import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildRagAdEvalReportUrl,
  formatEvalPassRate,
  getEvalItemStatusLabel,
  getRagEvalCorpusLabel,
} from "../lib/api/evals";

test("buildRagAdEvalReportUrl returns rag eval report endpoint", () => {
  assert.equal(buildRagAdEvalReportUrl(), "http://127.0.0.1:8010/api/evals/rag-ad/report");
});

test("formatEvalPassRate formats ratio as percentage", () => {
  assert.equal(formatEvalPassRate(0), "0%");
  assert.equal(formatEvalPassRate(0.625), "63%");
  assert.equal(formatEvalPassRate(1), "100%");
});

test("getEvalItemStatusLabel returns compact result labels", () => {
  assert.equal(getEvalItemStatusLabel(true), "通过");
  assert.equal(getEvalItemStatusLabel(false), "需复核");
});

test("getRagEvalCorpusLabel returns explicit corpus scope labels", () => {
  assert.equal(getRagEvalCorpusLabel("seed"), "Seed 基线语料");
  assert.equal(getRagEvalCorpusLabel("runtime"), "Runtime 本地状态");
});

test("getRagAdEvalReport fetches report payload", async () => {
  process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN = "dev-token";
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        return {
          summary: {
            total_questions: 50,
            corpus: "seed",
            passed_questions: 14,
            pass_rate: 0.7,
            citation_hit_count: 18,
            chunk_hit_count: 6,
            disclaimer_coverage_count: 50,
            must_not_violation_count: 0,
            grounding_blocked_count: 0,
          },
          items: [
            {
              id: "rag-eval-001",
              question: "question",
              source_preference: "all",
              difficulty: "easy",
              expected_literature_ids: [],
              expected_literature_hits: [],
              expected_chunk_ids: [],
              expected_chunk_hits: [],
              missing_must_include: [],
              violated_must_not_include: [],
              disclaimer_present: true,
              citation_count: 2,
              provider_name: "deterministic",
              grounding_status: "skipped",
              passed: true,
            },
          ],
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { getRagAdEvalReport } = await import(`../lib/api/evals?ts=${Date.now()}`);
    const report = await getRagAdEvalReport();

    assert.equal(captured[0].url, "http://127.0.0.1:8010/api/evals/rag-ad/report");
    const headers = captured[0].init?.headers as Record<string, string>;
    assert.equal("X-Access-Token" in headers, false);
    assert.equal(report.summary.total_questions, 50);
    assert.equal(report.summary.corpus, "seed");
    assert.equal(report.summary.pass_rate, 0.7);
    assert.equal(report.summary.grounding_blocked_count, 0);
    assert.equal(report.items[0].grounding_status, "skipped");
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN;
  }
});
