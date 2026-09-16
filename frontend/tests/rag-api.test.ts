import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildRagAnswerExportUrl,
  buildRagAnswerRequest,
  buildRagAnswerUrl,
  getRagSourceLabel,
  type RagAnswerResponse,
} from "../lib/api/rag";

test("buildRagAnswerUrl returns rag endpoint with default backend base URL", () => {
  assert.equal(buildRagAnswerUrl(), "http://127.0.0.1:8010/api/rag/answer");
});

test("buildRagAnswerExportUrl returns rag export endpoint with default backend base URL", () => {
  assert.equal(buildRagAnswerExportUrl(), "http://127.0.0.1:8010/api/rag/answer/export");
});

test("buildRagAnswerRequest trims question and preserves source/top_k", () => {
  assert.deepEqual(buildRagAnswerRequest("  特应性皮炎和肠-脑-皮肤轴有什么关系？  ", "pubmed", 3), {
    question: "特应性皮炎和肠-脑-皮肤轴有什么关系？",
    source: "pubmed",
    top_k: 3,
  });
});

test("getRagSourceLabel returns display text", () => {
  assert.equal(getRagSourceLabel("all"), "全部文献");
  assert.equal(getRagSourceLabel("cn_literature"), "中文文献");
  assert.equal(getRagSourceLabel("pubmed"), "PubMed");
});

test("RagAnswerResponse type carries provider, retrieval strategy, and token usage", () => {
  const payload: RagAnswerResponse = {
    question: "特应性皮炎和肠-脑-皮肤轴有什么关系？",
    answer: "answer",
    disclaimer: "非诊断结论、需结合临床。",
    answered_at: "2026-05-27T00:00:00+00:00",
    provider_name: "opencode_go",
    input_tokens: 128,
    output_tokens: 64,
    integrity_token: "signed-answer-token",
    grounding: {
      status: "passed",
      policy: "opencode_go_tool_use_v1",
      checked: true,
      blocked_reason: null,
      allowed_evidence_refs: ["chunk-cn-ad-gbs-001-abstract"],
      matched_evidence_refs: ["chunk-cn-ad-gbs-001-abstract"],
      unsupported_evidence_refs: [],
      claim_count: 2,
      cited_claim_count: 2,
      structured_claims: [
        {
          text: "证据提示肠道菌群与皮肤屏障异常之间存在关联",
          evidence_refs: ["chunk-cn-ad-gbs-001-abstract"],
          semantic_score: 0.76,
          entailment_score: 0.99,
        },
      ],
      provider_native_grounding: true,
      tool_name: "record_grounded_claims",
      tool_call_count: 1,
      semantic_threshold: 0.3,
      min_semantic_score: 0.76,
      nli_threshold: 0.5,
      min_entailment_score: 0.99,
    },
    retrieval: {
      applied_source: "all",
      applied_top_k: 2,
      available_citation_count: 16,
      strategy: "hybrid",
    },
    citations: [],
  };

  assert.equal(payload.provider_name, "opencode_go");
  assert.equal(payload.retrieval.strategy, "hybrid");
  assert.equal(payload.grounding.status, "passed");
  assert.equal(payload.grounding.policy, "opencode_go_tool_use_v1");
  assert.equal(payload.grounding.provider_native_grounding, true);
  assert.equal(payload.grounding.tool_name, "record_grounded_claims");
  assert.equal(payload.grounding.tool_call_count, 1);
  assert.equal(payload.grounding.semantic_threshold, 0.3);
  assert.equal(payload.grounding.min_semantic_score, 0.76);
  assert.equal(payload.grounding.nli_threshold, 0.5);
  assert.equal(payload.grounding.min_entailment_score, 0.99);
  assert.equal(payload.grounding.claim_count, 2);
  assert.equal(payload.grounding.cited_claim_count, 2);
  assert.equal(payload.grounding.structured_claims[0].text, "证据提示肠道菌群与皮肤屏障异常之间存在关联");
  assert.equal(payload.grounding.structured_claims[0].entailment_score, 0.99);
  assert.equal(payload.input_tokens, 128);
  assert.equal(payload.output_tokens, 64);
  assert.equal(payload.integrity_token, "signed-answer-token");
});

const _EXPORT_SAMPLE: RagAnswerResponse = {
  question: "特应性皮炎和肠-脑-皮肤轴有什么关系？",
  answer: "answer",
  disclaimer: "非诊断结论、需结合临床。",
  answered_at: "2026-06-04T07:42:11.123456+00:00",
  provider_name: "deterministic",
  input_tokens: null,
  output_tokens: null,
  integrity_token: "signed-export-token",
  grounding: {
    status: "skipped",
    policy: "structured_claim_refs_v3",
    checked: false,
    blocked_reason: null,
    allowed_evidence_refs: [],
    matched_evidence_refs: [],
    unsupported_evidence_refs: [],
    claim_count: 0,
    cited_claim_count: 0,
    structured_claims: [],
    provider_native_grounding: false,
    tool_name: null,
    tool_call_count: 0,
  },
  retrieval: {
    applied_source: "all",
    applied_top_k: 2,
    available_citation_count: 0,
    strategy: "keyword",
  },
  citations: [],
};

test("fetchRagAnswerMarkdown posts answer payload and returns markdown text", async () => {
  process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN = "dev-token";
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async text() {
        return "# Qiyan Nexus RAG 答案导出\n\n- 导出时间（UTC）：2026-06-04T07:42:11.123456+00:00\n";
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchRagAnswerMarkdown } = await import(`../lib/api/rag?ts=${Date.now()}`);
    const markdown = await fetchRagAnswerMarkdown(_EXPORT_SAMPLE);

    assert.equal(captured.length, 1);
    assert.equal(captured[0].url, "http://127.0.0.1:8010/api/rag/answer/export");
    assert.equal(captured[0].init?.method, "POST");
    const headers = captured[0].init?.headers as Record<string, string>;
    assert.equal(headers["Content-Type"], "application/json");
    assert.equal("X-Access-Token" in headers, false);
    const body = JSON.parse(String(captured[0].init?.body ?? "{}"));
    assert.equal(body.question, "特应性皮炎和肠-脑-皮肤轴有什么关系？");
    assert.equal(body.provider_name, "deterministic");
    assert.ok(markdown.startsWith("# Qiyan Nexus"));
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN;
  }
});

test("fetchRagAnswerMarkdown throws when the response is not ok", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    return {
      ok: false,
      async text() {
        return "boom";
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchRagAnswerMarkdown } = await import(`../lib/api/rag?ts=${Date.now()}`);
    await assert.rejects(
      fetchRagAnswerMarkdown(_EXPORT_SAMPLE),
      /RAG answer export request failed/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
